"""
PiClaw OS – SmartRouter
Manages automatic switching between local (Gemma 4 E2B) and API backends.

State machine:
  BOOTING   → checks API connectivity in parallel while local model loads
  LOCAL     → running on Gemma 4 E2B (no API key / offline / API down)
  API       → running on cloud API (Anthropic / OpenAI)
  SWITCHING → transitioning between backends (brief window)

Transitions:
  BOOTING → API    : API key present + connectivity confirmed
  BOOTING → LOCAL  : no API key, or connectivity check failed
  API → LOCAL      : API request fails (timeout / 5xx / network error)
  LOCAL → API      : API connectivity restored (background re-check every 60s)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import AsyncIterator

from piclaw.config import PiClawConfig
from piclaw.llm.base import LLMBackend, Message, ToolDefinition, LLMResponse
from piclaw.llm.api import AnthropicBackend, OpenAIBackend
from piclaw.llm.local import LocalBackend, DEFAULT_MODEL_PATH

log = logging.getLogger("piclaw.llm.router")


class BackendState(StrEnum):
    BOOTING = "booting"
    LOCAL = "local"
    API = "api"
    SWITCHING = "switching"


@dataclass
class RouterStatus:
    state: BackendState = BackendState.BOOTING
    active_backend: str = "none"
    local_loaded: bool = False
    api_reachable: bool = False
    last_api_check: float = 0.0
    last_api_error: str = ""
    switch_count: int = 0
    uptime_local_s: float = 0.0
    uptime_api_s: float = 0.0
    _state_since: float = field(default_factory=time.time)

    def summary(self) -> str:
        mode = {
            BackendState.LOCAL: "🟡 Offline / Local (Gemma 4 E2B)",
            BackendState.API: "🟢 Online / Cloud API",
            BackendState.BOOTING: "⚪ Booting…",
            BackendState.SWITCHING: "🔄 Switching…",
        }[self.state]
        age = int(time.time() - self._state_since)
        return (
            f"Mode        : {mode}\n"
            f"In this mode: {age}s\n"
            f"API reachable: {self.api_reachable}\n"
            f"Local loaded : {self.local_loaded}\n"
            f"Switches     : {self.switch_count}"
        )


# How long to wait for API connectivity check on boot
API_CHECK_TIMEOUT = 8  # seconds
# How often to re-check API when in LOCAL mode
API_RECHECK_INTERVAL = 60  # seconds
# How many consecutive API failures before falling back
API_FAILURE_THRESHOLD = 2


class SmartRouter(LLMBackend):
    """
    Drop-in LLMBackend replacement that routes between
    LocalBackend and API backend automatically.
    """

    def __init__(self, cfg: PiClawConfig):
        self.cfg = cfg
        self.status = RouterStatus()

        # Instantiate backends
        self._local = LocalBackend(
            model_path=DEFAULT_MODEL_PATH,
            n_ctx=12288,
            n_threads=4,
            max_tokens=1024,
            temperature=cfg.llm.temperature,
        )
        self._api: LLMBackend | None = self._build_api_backend()
        self._active: LLMBackend = self._local  # start with local

        self._api_failures = 0
        self._boot_complete = asyncio.Event()
        self._recheck_task: asyncio.Task | None = None

    def _build_api_backend(self) -> LLMBackend | None:
        cfg = self.cfg.llm
        if not cfg.api_key:
            return None
        kw = dict(
            api_key=cfg.api_key,
            model=cfg.model,
            base_url=cfg.base_url,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
        )
        if cfg.backend == "anthropic":
            return AnthropicBackend(**kw)
        if cfg.backend == "openai":
            return OpenAIBackend(**kw)
        return None

    # ── Boot sequence ────────────────────────────────────────────

    async def boot(self):
        """
        Called once at startup. Runs two tasks in parallel:
          1. Pre-load the local model (so it's ready as fallback)
          2. Check API connectivity
        Switches to API if available, stays local otherwise.
        """
        log.info(
            "SmartRouter booting – checking API and loading local model in parallel…"
        )
        self.status.state = BackendState.BOOTING

        api_task = asyncio.create_task(self._check_api_connectivity())
        local_task = asyncio.create_task(self._preload_local())

        # We don't wait for both to finish before proceeding –
        # API check is fast, local load may take 10-30s on Pi.
        # We wait for the API check first (with timeout).
        try:
            api_ok = await asyncio.wait_for(api_task, timeout=API_CHECK_TIMEOUT)
        except TimeoutError:
            log.warning("API connectivity check timed out.")
            api_ok = False

        self.status.api_reachable = api_ok
        self.status.last_api_check = time.time()

        if api_ok and self._api:
            log.info("API reachable → switching to API mode.")
            await self._switch_to_api(unload_local=False)  # keep local as warm fallback
        else:
            reason = "no API key" if not self._api else "API unreachable"
            log.info("API not available (%s) → LOCAL mode.", reason)
            self._set_state(BackendState.LOCAL, "local (Gemma 4 E2B)")
            # Make sure local model finishes loading
            await local_task

        self._boot_complete.set()

        # Start background re-checker if in local mode
        if self.status.state == BackendState.LOCAL:
            self._start_recheck()

        log.info("SmartRouter boot complete: %s", self.status.state.value)

    async def _preload_local(self):
        """Load Gemma 4 E2B into RAM in the background."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._local._load)
            self.status.local_loaded = True
            log.info("Local model pre-loaded.")
        except Exception as e:
            log.error("Local model pre-load failed: %s", e)

    async def _check_api_connectivity(self) -> bool:
        """Quick connectivity check – sends a minimal test request."""
        if not self._api:
            return False
        try:
            # Minimal test message
            test = [Message(role="user", content="ping")]
            resp = await asyncio.wait_for(
                self._api.chat(test), timeout=API_CHECK_TIMEOUT
            )
            return bool(resp.content or resp.tool_calls)
        except TimeoutError:
            log.warning("API check timeout (>%ss)", API_CHECK_TIMEOUT)
            self.status.last_api_error = "timeout"
            return False
        except Exception as e:
            log.warning("API check failed: %s", e)
            self.status.last_api_error = str(e)
            return False

    # ── State transitions ─────────────────────────────────────────

    def _set_state(self, state: BackendState, backend_name: str):
        self.status.state = state
        self.status.active_backend = backend_name
        self.status._state_since = time.time()
        if state == BackendState.API:
            self._active = self._api
        else:
            self._active = self._local

    async def _switch_to_api(self, unload_local: bool = False):
        self.status.state = BackendState.SWITCHING
        self._api_failures = 0
        if unload_local and self.status.local_loaded:
            log.info("Unloading local model to free RAM…")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._local.unload)
            self.status.local_loaded = False
        self._set_state(
            BackendState.API, f"api ({self.cfg.llm.backend}/{self.cfg.llm.model})"
        )
        self.status.switch_count += 1
        log.info("Switched to API mode.")

    async def _switch_to_local(self, reason: str = ""):
        self.status.state = BackendState.SWITCHING
        if not self.status.local_loaded:
            log.info("Loading local model for fallback…")
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._local._load)
                self.status.local_loaded = True
            except Exception as e:
                log.error("Failed to load local model: %s", e)
                self._set_state(BackendState.LOCAL, "local (unavailable)")
                return
        self._set_state(BackendState.LOCAL, "local (Gemma 4 E2B)")
        self.status.switch_count += 1
        log.warning("Switched to LOCAL mode. Reason: %s", reason or "API failure")
        self._start_recheck()

    # ── Background API re-checker ─────────────────────────────────

    def _start_recheck(self):
        if self._recheck_task and not self._recheck_task.done():
            return
        self._recheck_task = asyncio.create_task(
            self._api_recheck_loop(), name="api-recheck"
        )

    async def _api_recheck_loop(self):
        """Periodically try to restore API when in local mode."""
        while self.status.state == BackendState.LOCAL:
            await asyncio.sleep(API_RECHECK_INTERVAL)
            if not self._api:
                # Re-build API backend in case key was added since boot
                self._api = self._build_api_backend()
            if not self._api:
                continue
            log.info("Re-checking API connectivity…")
            ok = await self._check_api_connectivity()
            self.status.api_reachable = ok
            self.status.last_api_check = time.time()
            if ok:
                log.info("API restored! Switching back to API mode.")
                await self._switch_to_api(unload_local=True)
                break

    # ── LLMBackend interface ──────────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        await self._boot_complete.wait()

        # In LOCAL mode: inject offline notice if API was expected
        if self.status.state == BackendState.LOCAL and self._api:
            messages = self._inject_offline_notice(messages)

        try:
            resp = await self._active.chat(messages, tools=tools, stream=stream)
            if self.status.state == BackendState.API:
                self._api_failures = 0
            return resp

        except Exception as e:
            log.error("Backend error (%s): %s", self.status.active_backend, e)
            self.status.last_api_error = str(e)

            if self.status.state == BackendState.API:
                self._api_failures += 1
                if self._api_failures >= API_FAILURE_THRESHOLD:
                    await self._switch_to_local(reason=str(e))
                    # Retry with local
                    messages = self._inject_offline_notice(messages)
                    return await self._local.chat(messages, tools=tools)
            raise

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[str]:
        await self._boot_complete.wait()
        if self.status.state == BackendState.LOCAL and self._api:
            messages = self._inject_offline_notice(messages)
        try:
            async for token in self._active.stream_chat(messages, tools=tools):
                yield token
        except Exception as e:
            log.error("Stream error: %s", e)
            if self.status.state == BackendState.API:
                await self._switch_to_local(reason=str(e))
                yield "\n\n⚠️ API connection lost – switched to offline mode.\n\n"
                async for token in self._local.stream_chat(messages):
                    yield token

    async def health_check(self) -> bool:
        return self.status.local_loaded or (
            self._api is not None and self.status.api_reachable
        )

    # ── Helpers ───────────────────────────────────────────────────

    def _inject_offline_notice(self, messages: list[Message]) -> list[Message]:
        """Prepend offline notice to system prompt."""
        new = list(messages)
        notice = (
            "⚠️  OFFLINE MODE: You are running as a local Gemma 4 E2B model. "
            "Cloud API is unavailable. Be concise and honest about limitations. "
            "For complex tasks, ask the user to check their internet connection "
            "or API key with: piclaw config set llm.api_key <key>"
        )
        if new and new[0].role == "system":
            new[0] = Message(role="system", content=notice + "\n\n" + new[0].content)
        else:
            new.insert(0, Message(role="system", content=notice))
        return new

    def get_status(self) -> RouterStatus:
        return self.status

    def get_status_dict(self) -> dict:
        s = self.status
        return {
            "mode": s.state.value,
            "backend": s.active_backend,
            "local_loaded": s.local_loaded,
            "api_reachable": s.api_reachable,
            "last_api_error": s.last_api_error,
            "switch_count": s.switch_count,
        }

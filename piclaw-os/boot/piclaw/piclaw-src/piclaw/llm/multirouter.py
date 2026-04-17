"""
PiClaw OS – Multi-LLM Router
Selects the best LLM backend for each request based on:
  1. Task classification (tags from classifier)
  2. Backend tag overlap (from registry)
  3. Availability (API reachable, not in error state)
  4. Priority tiebreaking

Falls back to:
  - Next best backend if primary fails
  - Local Phi-3 Mini if all APIs fail / offline

Wraps existing SmartRouter for local/API switching.

Selection logic:
  request → classifier → [tag1, tag2, ...] → registry.find_by_tags()
      → sorted candidates → pick best available → call LLM

Override:
  The user can force a specific backend per-message:
    "@claude-sonnet how do I reverse a linked list?"
    "@local what services are running?"
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from dataclasses import dataclass
from collections.abc import AsyncIterator

from piclaw.llm.base import LLMBackend, Message, ToolDefinition, LLMResponse
from piclaw.llm.registry import LLMRegistry, BackendConfig
from piclaw.llm.classifier import TaskClassifier, ClassificationResult
from piclaw.llm.api import AnthropicBackend, OpenAIBackend
from piclaw.llm.local import LocalBackend, DEFAULT_MODEL_PATH
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.llm.multirouter")

# Regex to detect explicit backend override: "@name message"
OVERRIDE_RE = re.compile(r"^@(\S+)\s+(.*)", re.DOTALL)

# After this many consecutive failures, mark a backend as degraded
FAILURE_THRESHOLD = 3
# Degraded backends are retried after this many seconds
DEGRADED_RETRY_S = 120


@dataclass
class BackendHealth:
    name: str
    consecutive_failures: int = 0
    last_failure: float = 0.0
    last_success: float = 0.0
    total_calls: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0

    @property
    def is_degraded(self) -> bool:
        if self.consecutive_failures < FAILURE_THRESHOLD:
            return False
        return (time.time() - self.last_failure) < DEGRADED_RETRY_S

    def record_success(self, latency_ms: float):
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.total_calls += 1
        # Rolling average
        self.avg_latency_ms = self.avg_latency_ms * 0.8 + latency_ms * 0.2

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure = time.time()
        self.total_errors += 1
        self.total_calls += 1


class MultiLLMRouter(LLMBackend):
    """
    Drop-in LLMBackend that intelligently routes to the best available backend.
    Replaces SmartRouter when the registry has multiple entries.
    """

    def __init__(self, registry: LLMRegistry, global_cfg):
        self.registry = registry
        self.global_cfg = global_cfg

        # Instantiated backends cache (lazy)
        self._instances: dict[str, LLMBackend] = {}
        self._health: dict[str, BackendHealth] = {}

        # Local fallback – prefer cfg.llm.model if it looks like a path
        _model_path = DEFAULT_MODEL_PATH
        if global_cfg and global_cfg.llm.backend == "local" and global_cfg.llm.model:
            _candidate = Path(global_cfg.llm.model)
            if _candidate.suffix in (".gguf", ".bin") or _candidate.is_absolute():
                _model_path = _candidate
        self._local = LocalBackend(
            model_path=_model_path,
            n_ctx=4096,
            n_threads=4,
        )
        self._local_loaded = False

        # Classifier uses the fastest available backend
        self._classifier: TaskClassifier | None = None

        self._boot_complete = asyncio.Event()

    # ── Boot ──────────────────────────────────────────────────────

    async def boot(self):
        """Initialize backends and classifier."""
        log.info("MultiLLMRouter booting…")

        # Wenn das konfigurierte Backend nicht mit dem gespeicherten übereinstimmt
        # (z.B. nach piclaw setup von openai → ollama), Registry zurücksetzen
        if self.registry._backends:
            configured_backend = self.global_cfg.llm.backend if self.global_cfg else None
            registered_providers = {b.provider for b in self.registry.list_all()}
            if configured_backend and configured_backend not in registered_providers:
                log.info(
                    "Backend-Wechsel erkannt (%s → %s) – Registry wird zurückgesetzt",
                    registered_providers, configured_backend,
                )
                self.registry.clear()

        # Bootstrap registry from global config if empty
        self.registry.bootstrap_from_config(self.global_cfg)
        # Note: ensure_nvidia_backend() wird nicht automatisch aufgerufen.
        # Users add additional backends via 'piclaw setup' or 'piclaw llm add'.

        # Build health trackers
        for b in self.registry.list_enabled():
            self._health[b.name] = BackendHealth(name=b.name)

        # Classifier mit Pattern-only initialisieren.
        # LLM-Stage (Stage 2) würde das primäre Backend für Klassifikation nutzen,
        # was eine zirkuläre Abhängigkeit erzeugt: das Backend, das wir auswählen wollen,
        # wird zur Auswahl dieses Backends genutzt. Bei hoher Last verstärkt sich das.
        # Pattern-Matching reicht für >95% aller Anfragen aus (HA, Marketplace, allgemein).
        self._classifier = TaskClassifier(llm_for_classification=None)

        # Pre-warm local model im Hintergrund für schnellen Fallback
        # (RAM ist auf Pi 5 ausreichend; Modell ist dann sofort bereit)
        create_background_task(self._preload_local(), name="local-preload")

        self._boot_complete.set()
        backends = [b.name for b in self.registry.list_enabled()]
        log.info("MultiLLMRouter ready. Backends: %s", backends)

    async def _preload_local(self):
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._local._load)
            self._local_loaded = True
            log.info("Local fallback model loaded.")
        except Exception as e:
            log.warning("Local model preload failed: %s", e)

    # ── Instance factory ──────────────────────────────────────────

    def _get_instance(self, cfg: BackendConfig) -> LLMBackend:
        """Get or create a backend instance. Invalidates cache if registry changed."""
        # Wenn Backend nicht mehr in Registry (gelöscht) → Cache bereinigen, kein rekursiver Aufruf
        if cfg.name not in self.registry._backends:
            self._instances.pop(cfg.name, None)
            # Kein rekursiver Aufruf – cfg ist veraltet, Caller muss neues cfg holen
            raise ValueError(f"Backend '{cfg.name}' ist nicht mehr in der Registry")
        if cfg.name in self._instances:
            # Prüfen ob Config noch aktuell ist (Priorität/Model könnte sich geändert haben)
            cached_cfg = self.registry._backends.get(cfg.name)
            if cached_cfg and (cached_cfg.model != cfg.model or cached_cfg.priority != cfg.priority):
                log.info("Backend '%s' config changed – invalidating cache", cfg.name)
                del self._instances[cfg.name]
            else:
                return self._instances[cfg.name]

        # Resolve API key: use backend-specific or fall back to global
        api_key = cfg.api_key or self.global_cfg.llm.api_key
        base_url = cfg.base_url

        kw = dict(
            api_key=api_key,
            model=cfg.model,
            base_url=base_url,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
        )

        if cfg.provider == "anthropic":
            instance = AnthropicBackend(**kw)
        elif cfg.provider in ("openai", "ollama"):
            # Ollama is OpenAI-compatible
            if cfg.provider == "ollama" and not base_url:
                kw["base_url"] = "http://localhost:11434/v1"
                kw["api_key"] = kw["api_key"] or "ollama"
            # Ollama auf Pi 5 (CPU-only) braucht bei 3B Modellen 2-4 Minuten
            # → Timeout großzügig auf 300s setzen
            if cfg.provider == "ollama":
                kw["timeout"] = max(kw.get("timeout", 60), 300)
            instance = OpenAIBackend(**kw)
        elif cfg.provider == "local":
            instance = self._local
        else:
            raise ValueError(f"Unknown provider: {cfg.provider}")

        self._instances[cfg.name] = instance
        return instance

    def _get_fastest_instance(self) -> LLMBackend | None:
        """Return the highest-priority enabled backend for quick classification calls."""
        backends = self.registry.list_enabled()
        if not backends:
            return None
        return self._get_instance(backends[0])

    # ── Routing logic ─────────────────────────────────────────────

    def _check_override(
        self, messages: list[Message]
    ) -> tuple[str | None, list[Message]]:
        """
        Check if the last user message starts with @backend-name.
        Returns (backend_name_or_None, messages_without_prefix).
        """
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user":
                m = OVERRIDE_RE.match(messages[i].content)
                if m:
                    name, rest = m.group(1), m.group(2)
                    new_messages = list(messages)
                    new_messages[i] = Message(
                        role="user",
                        content=rest,
                        tool_call_id=messages[i].tool_call_id,
                        tool_name=messages[i].tool_name,
                    )
                    return name, new_messages
                break
        return None, messages

    async def _select_backend(
        self, messages: list[Message]
    ) -> tuple[BackendConfig, ClassificationResult]:
        """Select the best backend for the given messages."""
        # Find last user message
        user_text = ""
        for m in reversed(messages):
            if m.role == "user":
                user_text = m.content
                break

        # Classify the task
        classification = await self._classifier.classify(user_text)
        log.info(
            f"Task classified as {classification.tags} "
            f"(confidence={classification.confidence:.2f}, method={classification.method})"
        )

        # Find matching backends
        candidates = self.registry.find_by_tags(classification.tags, min_overlap=1)

        # ── Thermal routing: if Pi is hot, deprioritise local backends ──────
        try:
            from piclaw.hardware.thermal import (
                local_inference_allowed,
                get_thermal_state,
            )

            _thermal_ok = local_inference_allowed()
            _thermal_state = get_thermal_state()
            if not _thermal_ok:
                log.info(
                    "Thermal routing: local disabled "
                    f"({_thermal_state.temp_c:.1f}°C), forcing cloud backends"
                )
                # Exclude local provider candidates
                cloud_candidates = [b for b in candidates if b.provider != "local"]
                if cloud_candidates:
                    candidates = cloud_candidates
            elif _thermal_state and _thermal_state.cloud_pref:
                log.debug(
                    f"Thermal routing: {_thermal_state.temp_c:.1f}°C "
                    "– preferring cloud backends"
                )
                cloud_first = sorted(
                    candidates, key=lambda b: (b.provider == "local", -b.priority)
                )
                candidates = cloud_first
        except Exception as _e:
            log.debug(
                "thermal routing check: %s", _e
            )  # thermal module not available – proceed normally
        # ────────────────────────────────────────────────────────────────────

        # Filter out degraded backends (unless they're all degraded)
        available = [
            b
            for b in candidates
            if not self._health.get(b.name, BackendHealth(b.name)).is_degraded
        ]
        if not available:
            available = candidates  # try degraded ones as last resort before local

        # Pick first available
        if available:
            return available[0], classification

        # No match: use highest-priority general backend
        general = self.registry.find_by_tags(["general"])
        if general:
            return general[0], classification

        # Absolute fallback: first enabled backend
        all_enabled = self.registry.list_enabled()
        if all_enabled:
            return all_enabled[0], classification

        # Kein Backend in Registry → lokales Modell nur wenn explizit konfiguriert
        if self.global_cfg and self.global_cfg.llm.backend == "local":
            if self._local.model_path.exists():
                log.warning("Keine Backends konfiguriert – nutze lokales Modell direkt")
                local_cfg = BackendConfig(
                    name="local-fallback",
                    provider="local",
                    model=str(self._local.model_path),
                    api_key="",
                    tags=["general"],
                    priority=1,
                )
                return local_cfg, classification

        raise RuntimeError("No LLM backends configured or available.")

    # ── LLMBackend interface ──────────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        await self._boot_complete.wait()

        # Check for explicit @backend override
        override_name, messages = self._check_override(messages)

        if override_name:
            cfg = self.registry.get(override_name)
            if not cfg:
                # Try partial match
                matches = [
                    b
                    for b in self.registry.list_enabled()
                    if override_name.lower() in b.name.lower()
                ]
                cfg = matches[0] if matches else None
            if not cfg:
                return LLMResponse(
                    content=f"❌ Unknown backend: '{override_name}'. "
                    f"Available: {[b.name for b in self.registry.list_enabled()]}",
                    tool_calls=[],
                    finish_reason="error",
                )
            classification = ClassificationResult(
                tags=cfg.tags, confidence=1.0, method="override"
            )
        else:
            cfg, classification = await self._select_backend(messages)

        # Add routing note to system context (debug mode)
        messages = self._inject_routing_note(messages, cfg, classification)

        # Try selected backend, fall back on failure
        return await self._call_with_fallback(cfg, messages, tools, classification)

    async def _call_with_fallback(
        self,
        primary: BackendConfig,
        messages: list[Message],
        tools,
        classification: ClassificationResult,
        tried: set | None = None,
    ) -> LLMResponse:
        """Try primary backend, then iterate through fallbacks – no recursion."""
        if tried is None:
            tried = set()

        # Build ordered candidate list: primary first, then remaining by tag match
        candidates_by_tag = self.registry.find_by_tags(classification.tags)
        # Deduplicate, primary first
        ordered = [primary] + [b for b in candidates_by_tag if b.name != primary.name]

        last_exc: Exception | None = None
        for cfg in ordered:
            if cfg.name in tried:
                continue
            # Skip rate-limited backends
            _monitor_health = self._get_monitor_health(cfg.name)
            if _monitor_health and _monitor_health.get("rate_limited"):
                log.debug("Skipping rate-limited backend '%s'", cfg.name)
                tried.add(cfg.name)
                continue

            tried.add(cfg.name)
            t_start = time.time()
            try:
                instance = self._get_instance(cfg)
            except ValueError as e:
                log.warning("Backend '%s' not available: %s", cfg.name, e)
                last_exc = e
                continue

            try:
                resp = await instance.chat(messages, tools=tools)
                self._health.setdefault(cfg.name, BackendHealth(cfg.name)).record_success(
                    (time.time() - t_start) * 1000
                )
                log.info("Response from '%s' (%sms)", cfg.name, int((time.time() - t_start) * 1000))
                self._report_to_monitor("success", cfg.name)
                return resp
            except Exception as e:
                self._health.setdefault(cfg.name, BackendHealth(cfg.name)).record_failure()
                log.warning("Backend '%s' failed: %s", cfg.name, e)
                self._report_to_monitor("error", cfg.name, self._extract_error_code(e), str(e))
                last_exc = e

        # All API backends exhausted → local fallback
        if primary.provider != "local":
            log.warning("All API backends failed, using local model.")
            return await self._local.chat(messages, tools=tools)

        if last_exc:
            raise last_exc
        raise RuntimeError("No LLM backends available.")

    def _extract_error_code(self, error: Exception) -> int:
        """Extrahiert HTTP Status-Code aus Exception."""
        err_str = str(error)
        if "429" in err_str:
            return 429
        if "404" in err_str:
            return 404
        if "401" in err_str or "403" in err_str:
            return 401
        if "timeout" in err_str.lower():
            return 408
        return 500

    def _report_to_monitor(self, event: str, backend_name: str,
                           error_code: int = 0, error_msg: str = ""):
        """Meldet Ereignisse an den Health Monitor (wenn vorhanden)."""
        try:
            from piclaw.llm.health_monitor import get_monitor
            monitor = get_monitor()
            if monitor:
                if event == "success":
                    monitor.report_success(backend_name)
                elif event == "error":
                    monitor.report_error(backend_name, error_code, error_msg)
        except Exception as _e:
            log.debug("Health monitor report: %s", _e)

    def _get_monitor_health(self, backend_name: str) -> dict | None:
        """Fragt den Health Monitor nach dem Status eines Backends."""
        try:
            from piclaw.llm.health_monitor import get_monitor
            monitor = get_monitor()
            if monitor:
                status = monitor.status_dict()
                return status.get(backend_name)
        except Exception:
            pass
        return None

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[str]:
        await self._boot_complete.wait()
        override_name, messages = self._check_override(messages)

        if override_name:
            cfg = self.registry.get(override_name)
            if not cfg:
                yield f"❌ Unknown backend: '{override_name}'"
                return
            classification = ClassificationResult(
                tags=cfg.tags, confidence=1.0, method="override"
            )
        else:
            cfg, classification = await self._select_backend(messages)

        messages = self._inject_routing_note(messages, cfg, classification)
        instance = self._get_instance(cfg)

        tokens_yielded = 0
        try:
            it = instance.stream_chat(messages, tools=tools)
            while True:
                try:
                    token = await anext(it)
                except StopAsyncIteration:
                    break
                tokens_yielded += 1
                yield token
        except Exception as e:
            log.warning(
                "Stream from '%s' failed after %d tokens: %r",
                cfg.name,
                tokens_yielded,
                e,
            )
            # Only show warning and fall back if we got NO tokens yet
            # (if tokens came through, the response was already delivered to the user)
            if (
                tokens_yielded == 0
                and cfg.provider != "local"
                and cfg.name != "local-fallback"
            ):
                log.warning("Switching to local fallback after stream failure")
                # Try next API backend first before going local
                candidates = self.registry.list_enabled()
                next_api = next(
                    (
                        b
                        for b in candidates
                        if b.name != cfg.name
                        and b.provider != "local"
                        and not self._health.get(
                            b.name, BackendHealth(b.name)
                        ).is_degraded
                    ),
                    None,
                )
                if next_api:
                    log.info("Trying next API backend: %s", next_api.name)
                    try:
                        instance2 = self._get_instance(next_api)
                        async for token in instance2.stream_chat(messages, tools=tools):
                            yield token
                        return
                    except Exception as _e2:
                        log.warning("Next API backend also failed: %r", _e2)
                # All APIs failed → lokaler Fallback nur wenn explizit konfiguriert
                _primary_provider = cfg.provider if hasattr(cfg, "provider") else "api"
                _local_configured = (
                    self.global_cfg and
                    self.global_cfg.llm.backend in ("local", "ollama")
                )
                if not _local_configured:
                    yield "\n\n⚠️ Cloud-APIs nicht erreichbar. Bitte API-Key prüfen: piclaw setup\n\n"
                    return
                if _primary_provider == "ollama":
                    yield "\n\n⚠️ Ollama antwortet nicht – Gemma 2B übernimmt (Ollama lädt noch?)\n\n"
                else:
                    yield "\n\n⚠️ Cloud-APIs nicht erreichbar – lokales Modell übernimmt…\n\n"
                try:
                    async for token in self._local.stream_chat(messages):
                        yield token
                except Exception as _le:
                    log.error("Local fallback stream failed: %r", _le)
                    yield f"\n\n❌ Lokales Modell nicht verfügbar: {str(_le)}\nBitte herunterladen: piclaw model download"
            elif tokens_yielded == 0:
                yield f"\n\n❌ LLM Fehler: {str(e)}"
            # If tokens_yielded > 0: response already delivered, suppress the error silently

    async def health_check(self) -> bool:
        # Für lokales Backend: Datei vorhanden?
        if self.global_cfg and self.global_cfg.llm.backend == "local":
            return self._local.model_path.exists()
        # Für Ollama: Service erreichbar?
        if self.global_cfg and self.global_cfg.llm.backend == "ollama":
            try:
                import aiohttp
                base = (self.global_cfg.llm.base_url or "http://localhost:11434").rstrip("/")
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"{base}/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as r:
                        return r.status == 200
            except Exception:
                return False
        return bool(self.registry.list_enabled()) or self._local_loaded

    # ── Helper ────────────────────────────────────────────────────

    def _inject_routing_note(
        self,
        messages: list[Message],
        cfg: BackendConfig,
        classification: ClassificationResult,
    ) -> list[Message]:
        """Routing-Notiz in den System-Prompt injizieren (nur bei mehreren Backends)."""
        if len(self.registry.list_enabled()) <= 1:
            return messages  # kein Copy wenn nichts zu tun
        if not messages or messages[0].role != "system":
            return messages  # kein System-Prompt – nichts zu modifizieren
        note = (
            f"[Routing: backend={cfg.name}, "
            f"task={','.join(classification.tags)}, "
            f"method={classification.method}]"
        )
        # Nur ersten Message ersetzen – minimale Kopie statt list(messages)
        return [
            Message(role="system", content=messages[0].content + f"\n{note}")
        ] + messages[1:]

    # ── Status ────────────────────────────────────────────────────

    def get_status_dict(self) -> dict:
        backends = []
        for b in self.registry.list_all():
            h = self._health.get(b.name, BackendHealth(b.name))
            backends.append(
                {
                    "name": b.name,
                    "provider": b.provider,
                    "model": b.model,
                    "tags": b.tags,
                    "priority": b.priority,
                    "enabled": b.enabled,
                    "degraded": h.is_degraded,
                    "errors": h.total_errors,
                    "calls": h.total_calls,
                    "avg_ms": round(h.avg_latency_ms),
                }
            )
        return {
            "mode": "multi-llm",
            "backends": backends,
            "local_loaded": self._local_loaded,
            "all_tags": self.registry.all_tags(),
        }

    # ── SmartRouter compatibility (for Watchdog + existing code) ──

    def get_status(self):
        return self.get_status_dict()

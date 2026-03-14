"""
PiClaw OS – Local LLM Backend
Runs local GGUF models via llama-cpp-python.
Default: Gemma 2B Q4 – schneller und effizienter auf dem Pi 5.
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import AsyncIterator, Optional

from piclaw.llm.base import LLMBackend, Message, ToolDefinition, ToolCall, LLMResponse

log = logging.getLogger("piclaw.llm.local")

# Default model path – can be overridden in config
DEFAULT_MODEL_PATH = Path("/etc/piclaw/models/gemma-2b-q4.gguf")
# Standard-Modell: Gemma 2B Q4 – schnell, effizient, gute Qualität
MODEL_URL = (
    "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF"
    "/resolve/main/gemma-2-2b-it-Q4_K_M.gguf"
)

# System prompt tuned for the offline/setup context
OFFLINE_SYSTEM = """You are PiClaw in offline mode. You are a helpful AI assistant
running locally on a Raspberry Pi 5. You have limited capabilities compared to the
cloud API mode. Be concise and honest about your limitations.

You can help with:
- Basic system setup and configuration
- Simple questions about the Raspberry Pi
- Guiding users to configure WiFi and API keys
- Basic GPIO and service management

For complex tasks, coding, or detailed analysis, suggest the user connect to
the internet and configure an API key."""


def _detect_format(model_path: Path) -> str:
    """Erkennt das Chat-Format anhand des Dateinamens."""
    name = model_path.name.lower()
    if "gemma" in name:
        return "gemma"
    if "tinyllama" in name or "llama" in name:
        return "tinyllama"
    return "phi3"  # default


def _build_prompt(messages: list[Message], model_path: Path) -> str:
    """Universeller Prompt-Builder für verschiedene Modell-Formate."""
    fmt = _detect_format(model_path)
    if fmt == "gemma":
        return _build_gemma_prompt(messages)
    if fmt == "tinyllama":
        return _build_tinyllama_prompt(messages)
    return _build_phi3_prompt(messages)


def _build_gemma_prompt(messages: list[Message]) -> str:
    """
    Gemma 2 Chat-Format:
    <start_of_turn>user\n...<end_of_turn>\n<start_of_turn>model\n
    """
    parts = []
    system_text = ""
    for m in messages:
        if m.role == "system":
            system_text = m.content
        elif m.role == "user":
            content = f"{system_text}\n\n{m.content}" if system_text else m.content
            parts.append(f"<start_of_turn>user\n{content}<end_of_turn>")
            system_text = ""  # nur beim ersten user-turn
        elif m.role == "assistant":
            parts.append(f"<start_of_turn>model\n{m.content}<end_of_turn>")
        elif m.role == "tool":
            parts.append(f"<start_of_turn>user\nTool result: {m.content}<end_of_turn>")
    parts.append("<start_of_turn>model")
    return "\n".join(parts)


def _build_tinyllama_prompt(messages: list[Message]) -> str:
    """
    TinyLlama / ChatML Format:
    <|system|>\n...<|user|>\n...<|assistant|>\n
    """
    parts = []
    system_added = False
    for m in messages:
        if m.role == "system":
            parts.append(f"<|system|>\n{m.content}")
            system_added = True
        elif m.role == "user":
            if not system_added:
                parts.append(f"<|system|>\n{OFFLINE_SYSTEM}")
                system_added = True
            parts.append(f"<|user|>\n{m.content}")
        elif m.role == "assistant":
            parts.append(f"<|assistant|>\n{m.content}")
    parts.append("<|assistant|>")
    return "\n".join(parts)


def _build_phi3_prompt(messages: list[Message]) -> str:
    """
    Phi-3 Chat-Format:
    <|system|>\n...<|end|>\n<|user|>\n...<|end|>\n<|assistant|>\n
    """
    parts = []
    system_added = False

    for m in messages:
        if m.role == "system":
            parts.append(f"<|system|>\n{m.content}<|end|>")
            system_added = True
        elif m.role == "user":
            if not system_added:
                parts.append(f"<|system|>\n{OFFLINE_SYSTEM}<|end|>")
                system_added = True
            parts.append(f"<|user|>\n{m.content}<|end|>")
        elif m.role == "assistant":
            parts.append(f"<|assistant|>\n{m.content}<|end|>")
        elif m.role == "tool":
            parts.append(f"<|system|>\nTool result: {m.content}<|end|>")

    parts.append("<|assistant|>")
    return "\n".join(parts)


def _simple_tool_parse(text: str, tools: list[ToolDefinition]) -> list[ToolCall]:
    """
    Phi-3 Mini doesn't natively support tool calling.
    We use a lightweight prompt trick and parse JSON blocks.
    """
    import re
    calls = []
    # Look for ```json blocks containing tool calls
    pattern = r'```json\s*(\{.*?\})\s*```'
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            obj = json.loads(match.group(1))
            if "tool" in obj and "arguments" in obj:
                name = obj["tool"]
                if any(t.name == name for t in (tools or [])):
                    calls.append(ToolCall(
                        id=f"local_{len(calls)}",
                        name=name,
                        arguments=obj["arguments"],
                    ))
        except Exception:
            continue
    return calls


def _stop_tokens(model_path: Path) -> list[str]:
    """Stop-Tokens je nach Modell-Format."""
    fmt = _detect_format(model_path)
    if fmt == "gemma":
        return ["<end_of_turn>", "<start_of_turn>"]
    if fmt == "tinyllama":
        return ["<|user|>", "<|system|>", "</s>"]
    return ["<|end|>", "<|user|>", "<|system|>"]  # phi3


class LocalBackend(LLMBackend):
    """
    Phi-3 Mini Q4 via llama-cpp-python.
    Loads lazily on first use, unloads via .unload().
    """

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH,
                 n_ctx: int = 4096, n_threads: int = 4,
                 max_tokens: int = 1024, temperature: float = 0.7):
        self.model_path  = Path(model_path)
        self.n_ctx       = n_ctx
        self.n_threads   = n_threads
        self.max_tokens  = max_tokens
        self.temperature = temperature
        self._llm        = None
        self._lock       = threading.Lock()
        self._loaded     = False

    # ── Load / Unload ────────────────────────────────────────────

    def _load(self):
        """Load model into RAM (blocking, call from thread)."""
        if self._loaded:
            return
        try:
            from llama_cpp import Llama
        except ImportError:
            raise RuntimeError(
                "llama-cpp-python not installed. "
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cpu"
            )

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Local model not found: {self.model_path}\n"
                "Download with: piclaw model download"
            )

        log.info("Loading local model: %s " "(n_ctx=%s, threads=%s)", self.model_path, self.n_ctx, self.n_threads)

        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_gpu_layers=0,       # CPU-only on Pi
            verbose=False,
            use_mmap=True,        # memory-map for faster load
            use_mlock=False,      # don't lock RAM pages
        )
        self._loaded = True
        log.info("Local model loaded ✅")

    def unload(self):
        """Release model from RAM."""
        with self._lock:
            if self._llm is not None:
                del self._llm
                self._llm    = None
                self._loaded = False
                import gc; gc.collect()
                log.info("Local model unloaded – RAM freed.")

    def is_loaded(self) -> bool:
        return self._loaded

    # ── LLMBackend interface ─────────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Load model if not yet loaded (in executor to avoid blocking event loop)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load)

        prompt = _build_prompt(messages, self.model_path)

        # Inject tool-calling instructions if tools provided
        if tools:
            tool_desc = "\n".join(
                f"- {t.name}: {t.description}" for t in tools
            )
            prompt = prompt.replace(
                "<|assistant|>",
                f"<|system|>\nAvailable tools (respond with ```json {{\"tool\": \"name\", "
                f"\"arguments\": {{...}}}}``` to call one):\n{tool_desc}<|end|>\n<|assistant|>",
                1,
            )

        def _infer():
            with self._lock:
                result = self._llm(
                    prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stop=["<|end|>", "<|user|>", "<|system|>"],
                    echo=False,
                )
                choices = result.get("choices") or []
                if not choices:
                    raise ValueError(f"llama.cpp returned no choices: {result}")
                return (choices[0].get("text") or "").strip()

        text       = await loop.run_in_executor(None, _infer)
        tool_calls = _simple_tool_parse(text, tools) if tools else []

        # Strip JSON tool call blocks from visible text
        if tool_calls:
            import re
            text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL).strip()

        finish = "tool_calls" if tool_calls else "stop"
        return LLMResponse(content=text, tool_calls=tool_calls, finish_reason=finish)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[str]:
        loop   = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load)
        prompt = _build_prompt(messages, self.model_path)

        def _stream_infer():
            with self._lock:
                for chunk in self._llm(
                    prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stop=_stop_tokens(self.model_path),
                    stream=True,
                    echo=False,
                ):
                    yield (chunk.get("choices") or [{}])[0].get("text") or ""

        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _run():
            try:
                for token in _stream_infer():
                    asyncio.run_coroutine_threadsafe(queue.put(token), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        threading.Thread(target=_run, daemon=True).start()

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    async def health_check(self) -> bool:
        return self.model_path.exists()

"""
PiClaw OS – Local LLM Backend
Runs local GGUF models via llama-cpp-python.
Default: Gemma 2B Q4 – schneller und effizienter auf dem Pi 5.
"""

import asyncio
import json
import logging
import threading
import os
from contextlib import contextmanager
from pathlib import Path
from collections.abc import AsyncIterator

# Set C-level log suppressors BEFORE llama_cpp is imported anywhere.
# This silences GGML/GGUF progress output from llama.cpp's internal threads,
# which bypass Python-level fd redirects applied later.
os.environ.setdefault("LLAMA_CPP_LOG_LEVEL", "0")   # llama-cpp-python wrapper
os.environ.setdefault("GGML_LOG_LEVEL", "0")          # ggml C backend
os.environ.setdefault("LLAMA_LOG_LEVEL", "4")          # llama.cpp core (4 = ERROR only)

from piclaw.llm.base import LLMBackend, Message, ToolDefinition, ToolCall, LLMResponse

log = logging.getLogger("piclaw.llm.local")

# Global lock to prevent race conditions when multiple threads
# manipulate file descriptors 1 (stdout) and 2 (stderr).
_output_lock = threading.Lock()


@contextmanager
def _suppress_output():
    """Suppress C-level stdout AND stderr from llama.cpp.

    llama.cpp writes verbose progress to both fd 1 and fd 2.
    We redirect both to /dev/null at the file-descriptor level so that
    even C threads spawned inside the Llama() call stay silent.
    The global lock ensures only one thread manipulates the fds at a time.
    """
    with _output_lock:
        null_fd = os.open(os.devnull, os.O_RDWR)
        save_stdout = os.dup(1)
        save_stderr = os.dup(2)
        try:
            os.dup2(null_fd, 1)
            os.dup2(null_fd, 2)
            yield
        finally:
            os.dup2(save_stdout, 1)
            os.dup2(save_stderr, 2)
            os.close(null_fd)
            os.close(save_stdout)
            os.close(save_stderr)


# Default model path – can be overridden in config
DEFAULT_MODEL_PATH = Path("/etc/piclaw/models/qwen3-1.7b-q4_k_m.gguf")
# Standard-Modell: Qwen3 1.7B Q4_K_M – native Tool Calling, agentic, Agent Score 0.96
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF"
    "/resolve/main/qwen3-1.7b-q4_k_m.gguf"
)
# Legacy Fallback (falls Qwen3 nicht geladen werden kann)
LEGACY_MODEL_PATH = Path("/etc/piclaw/models/gemma-2b-q4.gguf")

# System prompt tuned for the offline/setup context
OFFLINE_SYSTEM = """Du bist Dameon im Offline-Modus, ein KI-Agent auf einem Raspberry Pi 5.
Du läufst lokal ohne Cloud-APIs. Du kannst Tool-Calls ausführen.

Deine Hauptaufgabe im Offline-Modus:
1. System-Monitoring und -Diagnose
2. Neue LLM-API-Backends suchen und konfigurieren (self-healing)
3. Services verwalten
4. Einfache Aufgaben erledigen bis Cloud-APIs wieder verfügbar sind

Für die Selbstheilung: Suche aktive LLM-Anbieter (Groq, NVIDIA NIM, Together AI,
Fireworks, Cerebras) und registriere funktionierende Backends automatisch.
Antworte auf Deutsch, präzise und handlungsorientiert."""


def _detect_format(model_path: Path) -> str:
    """Erkennt das Chat-Format anhand des Dateinamens."""
    name = model_path.name.lower()
    if "qwen" in name:
        return "qwen3"   # ChatML + natives Tool Calling
    if "gemma" in name:
        return "gemma"
    if "tinyllama" in name or "llama" in name:
        return "tinyllama"
    return "phi3"  # default


def _build_prompt(messages: list[Message], model_path: Path) -> str:
    """Universeller Prompt-Builder für verschiedene Modell-Formate."""
    fmt = _detect_format(model_path)
    if fmt == "qwen3":
        return _build_chatml_prompt(messages)
    if fmt == "gemma":
        return _build_gemma_prompt(messages)
    if fmt == "tinyllama":
        return _build_tinyllama_prompt(messages)
    return _build_phi3_prompt(messages)


def _build_chatml_prompt(messages: list[Message]) -> str:
    """
    ChatML Format (Qwen3, Mistral, LFM2 etc.):
    <|im_start|>system
...<|im_end|>
    <|im_start|>user
...<|im_end|>
    <|im_start|>assistant


    Qwen3 unterstützt natives Tool Calling über dieses Format.
    Tool-Definitionen werden im System-Prompt übergeben.
    """
    parts = []
    system_added = False
    for m in messages:
        if m.role == "system":
            parts.append(f"<|im_start|>system
{m.content}<|im_end|>")
            system_added = True
        elif m.role == "user":
            if not system_added:
                parts.append(f"<|im_start|>system
{OFFLINE_SYSTEM}<|im_end|>")
                system_added = True
            parts.append(f"<|im_start|>user
{m.content}<|im_end|>")
        elif m.role == "assistant":
            parts.append(f"<|im_start|>assistant
{m.content}<|im_end|>")
        elif m.role == "tool":
            # Tool-Ergebnisse als user-Nachricht (Qwen3-Konvention)
            parts.append(f"<|im_start|>user
Tool-Ergebnis: {m.content}<|im_end|>")
    parts.append("<|im_start|>assistant")
    return "
".join(parts)


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
    pattern = r"```json\s*(\{.*?\})\s*```"
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            obj = json.loads(match.group(1))
            if "tool" in obj and "arguments" in obj:
                name = obj["tool"]
                if any(t.name == name for t in (tools or [])):
                    calls.append(
                        ToolCall(
                            id=f"local_{len(calls)}",
                            name=name,
                            arguments=obj["arguments"],
                        )
                    )
        except Exception:
            continue
    return calls


def _stop_tokens(model_path: Path) -> list[str]:
    """Stop-Tokens je nach Modell-Format."""
    fmt = _detect_format(model_path)
    if fmt == "qwen3":
        return ["<|im_end|>", "<|endoftext|>", "<|im_start|>"]
    if fmt == "gemma":
        return ["<end_of_turn>", "<start_of_turn>"]
    if fmt == "tinyllama":
        return ["<|user|>", "<|system|>", "</s>"]
    return ["<|end|>", "<|user|>", "<|system|>"]  # phi3


class LocalBackend(LLMBackend):
    """
    Qwen3-1.7B Q4_K_M via llama-cpp-python.
    Natives Tool Calling via ChatML-Format, Agent Score 0.96 auf CPU.
    Lädt lazy beim ersten Aufruf, entlädt via .unload().
    Fallback: gemma-2b-q4.gguf falls Qwen3 nicht vorhanden.
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        n_ctx: int = 4096,
        n_threads: int = 4,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ):
        # Qwen3 bevorzugen, auf Legacy-Gemma zurückfallen falls nicht vorhanden
        requested = Path(model_path)
        if not requested.exists() and model_path == DEFAULT_MODEL_PATH:
            if LEGACY_MODEL_PATH.exists():
                log.warning(
                    "Qwen3 Modell nicht gefunden (%s), nutze Legacy-Fallback: %s",
                    requested, LEGACY_MODEL_PATH
                )
                requested = LEGACY_MODEL_PATH
        self.model_path = requested
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._llm = None
        self._lock = threading.Lock()
        self._loaded = False

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
                f"Lokales KI-Modell nicht gefunden unter: {self.model_path}\n"
                "Bitte lade das Standard-Modell herunter mit: piclaw model download"
            )

        log.info(
            "Loading local model: %s (n_ctx=%s, threads=%s)",
            self.model_path,
            self.n_ctx,
            self.n_threads,
        )

        with _suppress_output():
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=0,  # CPU-only on Pi
                verbose=False,
                use_mmap=True,  # memory-map for faster load
                use_mlock=False,  # don't lock RAM pages
            )
        self._loaded = True
        log.info("Local model loaded ✅")

    def unload(self):
        """Release model from RAM."""
        with self._lock:
            if self._llm is not None:
                del self._llm
                self._llm = None
                self._loaded = False
                import gc

                gc.collect()
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
            tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools)
            prompt = prompt.replace(
                "<|assistant|>",
                f'<|system|>\nAvailable tools (respond with ```json {{"tool": "name", '
                f'"arguments": {{...}}}}``` to call one):\n{tool_desc}<|end|>\n<|assistant|>',
                1,
            )

        def _infer():
            with self._lock, _suppress_output():
                result = self._llm(
                    prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stop=_stop_tokens(self.model_path),
                    echo=False,
                )
                choices = result.get("choices") or []
                if not choices:
                    raise ValueError(f"llama.cpp returned no choices: {result}")
                return (choices[0].get("text") or "").strip()

        text = await loop.run_in_executor(None, _infer)
        tool_calls = _simple_tool_parse(text, tools) if tools else []

        # Strip JSON tool call blocks from visible text
        if tool_calls:
            import re

            text = re.sub(r"```json.*?```", "", text, flags=re.DOTALL).strip()

        finish = "tool_calls" if tool_calls else "stop"
        return LLMResponse(content=text, tool_calls=tool_calls, finish_reason=finish)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load)
        prompt = _build_prompt(messages, self.model_path)

        def _stream_infer():
            with self._lock, _suppress_output():
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

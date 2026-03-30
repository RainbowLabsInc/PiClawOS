"""PiClaw OS – API LLM backends (Anthropic & OpenAI)"""

import json
import aiohttp
from collections.abc import AsyncIterator
from .base import LLMBackend, ToolCall, LLMResponse


# ── Bekannte Provider ──────────────────────────────────────────────
# Format: key_prefix → (provider, base_url, default_model)
# NIM: kein hardcodiertes Modell – wird live via /v1/models abgefragt
_KNOWN_PROVIDERS_BY_PREFIX = {
    "sk-ant-": ("anthropic", "https://api.anthropic.com", "claude-sonnet-4-20250514"),
    "nvapi-": (
        "openai",
        "https://integrate.api.nvidia.com/v1",
        None,  # wird live abgefragt
    ),
    "AIza": (
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.0-flash",
    ),
    "fw-": (
        "openai",
        "https://api.fireworks.ai/inference/v1",
        "accounts/fireworks/models/llama-v3p1-70b-instruct",
    ),
    "gsk_": (
        "openai",
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
    ),
    "csk-": (
        "openai",
        "https://api.cerebras.ai/v1",
        "llama-3.3-70b",
    ),
}

# Bevorzugte NIM-Modelle (in dieser Reihenfolge, erstes verfügbares wird genutzt)
_NIM_PREFERRED_MODELS = [
    "meta/llama-3.3-70b-instruct",          # bestes Tool Calling auf NIM
    "mistralai/mistral-large-2-instruct",    # sehr gut, Tool Calling
    "mistralai/mistral-large-3-675b-instruct-2512",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "meta/llama-3.1-70b-instruct",
    "qwen/qwen2.5-7b-instruct",
    "meta/llama-3.1-8b-instruct",           # kleinstes Fallback
]


async def _detect_nim_model(api_key: str, base_url: str) -> str:
    """Fragt NVIDIA NIM /v1/models ab und wählt das beste verfügbare Modell."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return _NIM_PREFERRED_MODELS[0]
                data = await r.json()
                available = {m["id"] for m in data.get("data", [])}
                # Bevorzugtes Modell wählen
                for model in _NIM_PREFERRED_MODELS:
                    if model in available:
                        return model
                # Fallback: erstes verfügbares Chat-Modell
                chat_models = [
                    m["id"] for m in data.get("data", [])
                    if "instruct" in m["id"].lower() or "chat" in m["id"].lower()
                ]
                if chat_models:
                    return chat_models[0]
    except Exception:
        pass
    return _NIM_PREFERRED_MODELS[0]

# Provider die /v1/models unterstützen (OpenAI-kompatibel)
_PROBE_ENDPOINTS = [
    (
        "https://api.openai.com/v1/models",
        "openai",
        "https://api.openai.com/v1",
        "gpt-4o",
    ),
    (
        "https://api.mistral.ai/v1/models",
        "openai",
        "https://api.mistral.ai/v1",
        "mistral-large-latest",
    ),
    (
        "https://api.fireworks.ai/inference/v1/models",
        "openai",
        "https://api.fireworks.ai/inference/v1",
        "accounts/fireworks/models/llama-v3p1-70b-instruct",
    ),
]


async def detect_provider_and_model(api_key: str) -> tuple[str, str, str]:
    """
    Auto-erkennt Provider, Base-URL und Standardmodell anhand des API-Keys.
    Unterstützt: Anthropic, OpenAI, NVIDIA NIM, Google Gemini, Mistral, Fireworks AI.

    Returns:
        tuple: (provider, base_url, model)
    """
    api_key = api_key.strip()

    # 1. Prefix-Erkennung (sofort, kein API-Call nötig)
    for prefix, (provider, base_url, model) in _KNOWN_PROVIDERS_BY_PREFIX.items():
        if api_key.startswith(prefix):
            # NIM: Modell live abfragen statt hardcodiert
            if model is None:
                model = await _detect_nim_model(api_key, base_url)
            return provider, base_url, model

    # 2. API-Probe: /v1/models abfragen
    timeout = aiohttp.ClientTimeout(total=5)
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for endpoint, provider, base_url, default_model in _PROBE_ENDPOINTS:
                try:
                    async with session.get(endpoint, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            models = [m["id"] for m in data.get("data", [])]
                            # Bestes verfügbares Modell wählen
                            preferred = {
                                "openai": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
                                "mistral": ["mistral-large-latest", "mistral-medium"],
                                "fireworks": [
                                    "accounts/fireworks/models/llama-v3p1-70b-instruct"
                                ],
                            }
                            for m in preferred.get(provider, []):
                                if m in models:
                                    return provider, base_url, m
                            # Fallback: erstes verfügbares Modell
                            if models:
                                return provider, base_url, models[0]
                            return provider, base_url, default_model
                except Exception:
                    continue
    except Exception:
        pass

    # 3. Anthropic-Test (kein /v1/models Endpoint)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers_ant = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            payload = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            }
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers_ant,
                json=payload,
            ) as resp:
                if resp.status == 200:
                    return (
                        "anthropic",
                        "https://api.anthropic.com",
                        "claude-sonnet-4-20250514",
                    )
    except Exception:
        pass

    # 4. Fallback
    return "openai", "https://api.openai.com/v1", "gpt-4o"



def _extract_text_tool_calls(text: str, tools) -> list:
    """
    Fallback-Parser für Modelle (z.B. Groq llama-3.3) die Tool-Calls als
    JSON-Text zurückgeben statt über die native tool_calls API.

    Erkannte Formate:
      {"name": "tool_name", "parameters": {...}}
      {"type": "function", "name": "tool_name", "parameters": {...}}
      {"function": {"name": "tool_name", "arguments": {...}}}
    """
    if not text or not tools:
        return []

    known_names = {t.name for t in tools} if hasattr(tools[0], "name") else set()
    results = []

    # Alle JSON-Objekte im Text suchen (auch verschachtelt)
    depth = 0
    start = None
    candidates = []
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
                start = None

    # Auch Markdown-Code-Blöcke durchsuchen: ```json {...} ``` oder ``` {...} ```
    import re as _re
    code_blocks = _re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    for cb in code_blocks:
        if cb not in candidates:
            candidates.append(cb)

    for blob in candidates:
        try:
            obj = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue

        # Format A: {"name": ..., "parameters": {...}}
        name = obj.get("name")
        args = obj.get("parameters") or obj.get("arguments") or {}

        # Format B: {"type": "function", "name": ..., "parameters": {...}}
        if not name and obj.get("type") == "function":
            name = obj.get("name")
            args = obj.get("parameters") or obj.get("arguments") or {}

        # Format C: {"function": {"name": ..., "arguments": {...}}}
        if not name and "function" in obj:
            func = obj["function"]
            name = func.get("name")
            args = func.get("arguments") or func.get("parameters") or {}

        if not name or name not in known_names:
            continue

        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                args = {}

        import uuid
        results.append(ToolCall(id=f"txt-{uuid.uuid4().hex[:8]}", name=name, arguments=args))

    return results


class AnthropicBackend(LLMBackend):
    def __init__(self, api_key, model, temperature, max_tokens, timeout, **_):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.base_url = "https://api.anthropic.com"

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _split(self, messages):
        system, conv = "", []
        for m in messages:
            if m.role == "system":
                system += m.content + "\n"
            elif m.role == "tool":
                conv.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content,
                            }
                        ],
                    }
                )
            else:
                conv.append({"role": m.role, "content": m.content})
        return system.strip(), conv

    async def chat(self, messages, tools=None, stream=False) -> LLMResponse:
        system, conv = self._split(messages)
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": conv,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]
        async with aiohttp.ClientSession(timeout=self.timeout) as s:
            async with s.post(
                f"{self.base_url}/v1/messages", headers=self._headers(), json=payload
            ) as r:
                if r.status >= 400:
                    body = await r.text()
                    raise RuntimeError(f"Anthropic API error {r.status}: {body}")
                data = await r.json()
        content, tool_calls = "", []
        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block.get("input", {}),
                    )
                )
        finish = "tool_calls" if tool_calls else data.get("stop_reason", "end_turn")
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish)

    async def stream_chat(self, messages, tools=None) -> AsyncIterator[str]:
        system, conv = self._split(messages)
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": conv,
            "stream": True,
        }
        if system:
            payload["system"] = system
        async with aiohttp.ClientSession(timeout=self.timeout) as s:
            async with s.post(
                f"{self.base_url}/v1/messages", headers=self._headers(), json=payload
            ) as r:
                r.raise_for_status()
                async for raw in r.content:
                    line = raw.strip().decode()
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                            token = chunk.get("delta", {}).get("text", "")
                            if token:
                                yield token
                        except (json.JSONDecodeError, KeyError):
                            continue

    async def health_check(self) -> bool:
        return bool(self.api_key)


class OpenAIBackend(LLMBackend):
    # NVIDIA NIM braucht parallel_tool_calls=False, aber kein tool_choice
    _NIM_HOST = "integrate.api.nvidia.com"
    _GEMINI_HOST = "generativelanguage.googleapis.com"
    _MISTRAL_HOST = "api.mistral.ai"
    _FW_HOST = "api.fireworks.ai"
    # Hosts die kein tool_choice vertragen
    _NO_TOOL_CHOICE_HOSTS = frozenset(
        [
            "integrate.api.nvidia.com",
        ]
    )

    def __init__(self, api_key, model, base_url, temperature, max_tokens, timeout, **_):
        self.api_key = api_key
        self.model = model
        # Normalize base_url und Chat-Endpoint bestimmen
        _url = base_url.rstrip("/")
        # Providers mit eigenem Pfad-Präfix (z.B. Gemini /v1beta/openai)
        # bekommen kein /v1 vorangestellt
        _FULL_PATH_HOSTS = ("generativelanguage.googleapis.com",)
        if any(h in _url for h in _FULL_PATH_HOSTS):
            self.base_url = _url
            self._chat_endpoint = f"{_url}/chat/completions"
        else:
            if _url.endswith("/v1"):
                _url = _url[:-3]
            self.base_url = _url
            self._chat_endpoint = f"{_url}/v1/chat/completions"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._is_nim = self._NIM_HOST in self.base_url
        self._no_tool_choice = any(
            h in self.base_url for h in self._NO_TOOL_CHOICE_HOSTS
        )

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(self, messages) -> list[dict]:
        """Konvertiert Message-Objekte in OpenAI-Format inkl. tool_results."""
        out = []
        for m in messages:
            if m.role == "tool":
                # Tool-Results müssen als eigene Nachricht im OpenAI-Format übergeben werden
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    async def chat(self, messages, tools=None, stream=False) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._build_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            # NVIDIA NIM Tool-Calling (INV_024):
            # tool_choice NICHT setzen – verursacht HTTP 400 oder
            # unzuverlässiges Verhalten auf allen NIM-Modellen.
            # parallel_tool_calls=False ist der einzige sichere Parameter.
            if self._no_tool_choice:
                payload["parallel_tool_calls"] = False
                # tool_choice wird BEWUSST NICHT gesetzt (INV_024)
            else:
                payload["tool_choice"] = "auto"
        async with aiohttp.ClientSession(timeout=self.timeout) as s:
            async with s.post(
                f"{self._chat_endpoint}",
                headers=self._headers(),
                json=payload,
            ) as r:
                if r.status >= 400:
                    body = await r.text()
                    raise RuntimeError(f"OpenAI/NIM API error {r.status}: {body}")
                data = await r.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"OpenAI response hat keine choices: {data}")
        choice = choices[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            func = tc.get("function") or {}
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    args = {}
            tc_id = tc.get("id", "")
            tc_name = func.get("name", "")
            if tc_name:  # Nur gültige Tool-Calls übernehmen
                tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=args))
        finish = choice.get("finish_reason", "stop")

        # ── Fallback: Text-basierte Tool-Calls erkennen ───────────────────────
        # Manche Modelle (z.B. Groq llama-3.3) geben Tool-Calls als JSON-Text
        # zurück statt über die native tool_calls API (finish_reason="stop").
        if not tool_calls and content and tools:
            _fallback = _extract_text_tool_calls(content, tools)
            if _fallback:
                tool_calls = _fallback
                content = ""
                finish = "tool_calls"
        # ─────────────────────────────────────────────────────────────────────

        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish)

    async def stream_chat(self, messages, tools=None) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self.temperature,
            "stream": True,
        }
        async with aiohttp.ClientSession(timeout=self.timeout) as s:
            async with s.post(
                f"{self._chat_endpoint}",
                headers=self._headers(),
                json=payload,
            ) as r:
                r.raise_for_status()
                async for raw in r.content:
                    line = raw.strip().decode()
                    if line.startswith("data: "):
                        line = line[6:]
                    if line in ("[DONE]", ""):
                        continue
                    try:
                        token = (
                            json.loads(line)["choices"][0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if token:
                            yield token
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as s:
                async with s.get(
                    f"{self.base_url}/v1/models", headers=self._headers()
                ) as r:
                    return r.status == 200
        except Exception:
            return False

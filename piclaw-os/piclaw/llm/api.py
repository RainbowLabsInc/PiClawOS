"""PiClaw OS – API LLM backends (Anthropic & OpenAI)"""

import json
import aiohttp
import asyncio
from typing import AsyncIterator
from .base import LLMBackend, ToolCall, LLMResponse


async def detect_provider_and_model(api_key: str) -> tuple[str, str, str]:
    """
    Auto-detects the provider, base URL, and a suitable default model based on the given API key.

    Returns:
        tuple: (provider, base_url, model)
    """
    api_key = api_key.strip()

    # 1. Check Anthropic by prefix
    if api_key.startswith("sk-ant-"):
        # We assume if it's Anthropic, the key is likely valid.
        return "anthropic", "https://api.anthropic.com", "claude-3-5-sonnet-20241022"

    # 2. Check NVIDIA NIM by prefix
    if api_key.startswith("nvapi-"):
        return "openai", "https://integrate.api.nvidia.com/v1", "nvidia/llama-3.1-nemotron-70b-instruct"

    # 3. Fallback logic: check OpenAI vs Anthropic by trying the API endpoints
    # Anthropic models don't have a standard format other than the sk-ant- prefix,
    # but OpenAI models often start with 'sk-proj-' or just 'sk-'.

    # Let's verify OpenAI first, as it's the most common
    timeout = aiohttp.ClientTimeout(total=5)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Try OpenAI /v1/models endpoint
            headers = {"Authorization": f"Bearer {api_key}"}
            async with session.get("https://api.openai.com/v1/models", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["id"] for m in data.get("data", [])]
                    if "gpt-4o" in models:
                        return "openai", "https://api.openai.com/v1", "gpt-4o"
                    elif "gpt-4-turbo" in models:
                        return "openai", "https://api.openai.com/v1", "gpt-4-turbo"
                    else:
                        return "openai", "https://api.openai.com/v1", "gpt-3.5-turbo"
    except Exception:
        pass

    # Try Anthropic anyway if OpenAI failed (in case prefix changed)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
            # Send a minimal request to check validity
            payload = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}]
            }
            async with session.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return "anthropic", "https://api.anthropic.com", "claude-3-5-sonnet-20241022"
    except Exception:
        pass

    # If all else fails, assume standard OpenAI with GPT-4o
    return "openai", "https://api.openai.com/v1", "gpt-4o"


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

    def __init__(self, api_key, model, base_url, temperature, max_tokens, timeout, **_):
        self.api_key = api_key
        self.model = model
        # Normalize base_url: strip trailing slash and trailing /v1
        # so that base_url='https://integrate.api.nvidia.com/v1' and
        # base_url='https://api.openai.com' both work correctly
        _url = base_url.rstrip("/")
        if _url.endswith("/v1"):
            _url = _url[:-3]
        self.base_url = _url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._is_nim = self._NIM_HOST in self.base_url

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
            # NVIDIA NIM / Kimi K2:
            # 'required' fuehrt bei Llama 3.1 NIM zu Error 400
            # 'auto' fuehrt in neueren Versionen auch zu Fehler 400 (requires --enable-auto-tool-choice and --tool-call-parser)
            # Daher: komplett weglassen fuer NIM.
            if self._is_nim:
                payload["parallel_tool_calls"] = False
            else:
                payload["tool_choice"] = "auto"
        async with aiohttp.ClientSession(timeout=self.timeout) as s:
            async with s.post(
                f"{self.base_url}/v1/chat/completions",
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
                f"{self.base_url}/v1/chat/completions",
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

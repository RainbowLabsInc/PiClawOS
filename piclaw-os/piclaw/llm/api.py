"""PiClaw OS – API LLM backends (Anthropic & OpenAI)"""

import json
import aiohttp
from typing import AsyncIterator
from .base import LLMBackend, ToolCall, LLMResponse


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
    # NVIDIA NIM braucht explizites tool_choice und parallel_tool_calls=False
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
            # NVIDIA NIM / Kimi K2: tool_choice=required erzwingt Tool-Aufruf
            # "auto" reicht nicht -- Kimi K2 beschreibt Tools statt sie aufzurufen
            if self._is_nim:
                payload["tool_choice"] = "required"
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

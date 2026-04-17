"""PiClaw OS – LLM abstraction layer"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import AsyncIterator


@dataclass
class Message:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str
    tool_calls: list
    finish_reason: str


class LLMBackend(ABC):
    @abstractmethod
    async def chat(self, messages, tools=None, stream=False) -> LLMResponse: ...
    @abstractmethod
    async def stream_chat(self, messages, tools=None) -> AsyncIterator[str]: ...
    @abstractmethod
    async def health_check(self) -> bool: ...

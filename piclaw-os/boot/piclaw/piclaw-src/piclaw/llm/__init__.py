"""PiClaw OS – LLM package"""

from piclaw.config         import PiClawConfig
from .base                 import LLMBackend, Message, ToolDefinition, ToolCall, LLMResponse
from .api                  import AnthropicBackend, OpenAIBackend
from .local                import LocalBackend
from .registry             import LLMRegistry, BackendConfig
from .classifier           import TaskClassifier
from .multirouter          import MultiLLMRouter
from .router               import SmartRouter, BackendState, RouterStatus


def create_backend(cfg: PiClawConfig) -> MultiLLMRouter:
    """
    Returns a MultiLLMRouter that:
      - manages multiple named backends from the registry
      - classifies tasks and routes to the best backend
      - falls back to local Phi-3 Mini when all APIs fail
    """
    registry = LLMRegistry()
    return MultiLLMRouter(registry, cfg)


__all__ = [
    "create_backend",
    "MultiLLMRouter", "LLMRegistry", "BackendConfig",
    "TaskClassifier",
    "SmartRouter", "BackendState", "RouterStatus",
    "LLMBackend", "Message", "ToolDefinition", "ToolCall", "LLMResponse",
    "AnthropicBackend", "OpenAIBackend", "LocalBackend",
]

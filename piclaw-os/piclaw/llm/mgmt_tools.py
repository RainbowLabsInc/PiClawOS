"""
PiClaw OS – LLM Management Tools
Agent-callable tools for managing the LLM registry at runtime.
"""

from piclaw.llm.base import ToolDefinition
from piclaw.llm.registry import LLMRegistry, BackendConfig

TOOL_DEFS = [
    ToolDefinition(
        name="llm_list",
        description="Show all configured LLM backends with their tags, priority and health status.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="llm_add",
        description=(
            "Add a new LLM backend to the registry. "
            "Tags define what kinds of tasks this backend is good at. "
            "Example tags: coding, debugging, creative, writing, german, reasoning, math, fast."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name, e.g. 'gpt4o-coding'",
                },
                "provider": {
                    "type": "string",
                    "enum": ["anthropic", "openai", "ollama", "local"],
                },
                "model": {
                    "type": "string",
                    "description": "Model string, e.g. 'gpt-4o'",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Capability tags this backend is best at",
                },
                "priority": {
                    "type": "integer",
                    "description": "1–10, higher = preferred when tied",
                    "default": 5,
                },
                "api_key": {
                    "type": "string",
                    "description": "API key (leave empty to use global key)",
                },
                "base_url": {
                    "type": "string",
                    "description": "Override API endpoint URL",
                },
                "temperature": {"type": "number", "default": 0.7},
                "max_tokens": {"type": "integer", "default": 4096},
                "notes": {
                    "type": "string",
                    "description": "Human-readable description",
                },
            },
            "required": ["name", "provider", "model", "tags"],
        },
    ),
    ToolDefinition(
        name="llm_update",
        description="Update tags, priority, or other settings of an existing LLM backend.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "integer"},
                "enabled": {"type": "boolean"},
                "notes": {"type": "string"},
                "temperature": {"type": "number"},
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="llm_remove",
        description="Remove an LLM backend from the registry.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="llm_test",
        description="Send a test message to a specific backend to verify it works.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Backend name to test"},
                "prompt": {
                    "type": "string",
                    "description": "Test prompt",
                    "default": "Reply with OK.",
                },
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="llm_classify",
        description="Show how PiClaw would classify a given message and which backend would handle it.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to classify"},
            },
            "required": ["message"],
        },
    ),
]


def build_handlers(registry: LLMRegistry, router) -> dict:

    async def llm_list() -> str:
        status = router.get_status_dict()
        backends = status.get("backends", [])
        if not backends:
            return "No backends configured. Use llm_add to add one."
        lines = [f"LLM Backends ({len(backends)}):\n"]
        for b in backends:
            icons = []
            if b["enabled"]:
                icons.append("✅")
            else:
                icons.append("⏸")
            if b["degraded"]:
                icons.append("⚠️")
            lines.append(
                f"  {''.join(icons)} [{b['priority']:2}] {b['name']}\n"
                f"       {b['provider']}/{b['model']}\n"
                f"       tags: {', '.join(b['tags']) or '(none)'}\n"
                f"       calls: {b['calls']}  errors: {b['errors']}  avg: {b['avg_ms']}ms"
            )
        lines.append(f"\nAll tags in use: {', '.join(status.get('all_tags', []))}")
        return "\n\n".join(lines)

    async def llm_add(
        name: str,
        provider: str,
        model: str,
        tags: list,
        priority: int = 5,
        api_key: str = "",
        base_url: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        notes: str = "",
    ) -> str:
        cfg = BackendConfig(
            name=name,
            provider=provider,
            model=model,
            tags=tags,
            priority=priority,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            notes=notes,
        )
        result = registry.add(cfg)
        # Register health tracker
        from piclaw.llm.multirouter import BackendHealth

        router._health[name] = BackendHealth(name=name)
        return result + f"\nTags assigned: {', '.join(tags)}"

    async def llm_update(name: str, **kwargs) -> str:
        return registry.update(
            name, **{k: v for k, v in kwargs.items() if v is not None}
        )

    async def llm_remove(name: str) -> str:
        result = registry.remove(name)
        router._instances.pop(name, None)
        router._health.pop(name, None)
        return result

    async def llm_test(name: str, prompt: str = "Reply with OK.") -> str:
        import time

        cfg = registry.get(name)
        if not cfg:
            return f"Backend '{name}' not found."
        try:
            from piclaw.llm.base import Message

            instance = router._get_instance(cfg)
            t = time.time()
            resp = await instance.chat([Message(role="user", content=prompt)])
            ms = int((time.time() - t) * 1000)
            return f"✅ Backend '{name}' responded in {ms}ms:\n{resp.content[:500]}"
        except Exception as e:
            return f"❌ Backend '{name}' failed: {e}"

    async def llm_classify(message: str) -> str:
        result = await router._classifier.classify(message)
        matches = registry.find_by_tags(result.tags, min_overlap=1)
        lines = [
            f'Message: "{message[:80]}"',
            f"Detected tags: {', '.join(result.tags)}",
            f"Confidence: {result.confidence:.0%} (method: {result.method})",
            "",
            "Backend selection:",
        ]
        if matches:
            for i, b in enumerate(matches[:3]):
                marker = "→ SELECTED" if i == 0 else f"  fallback {i}"
                overlap = b.tag_overlap(result.tags)
                lines.append(
                    f"  {marker}: {b.name} "
                    f"(overlap={overlap}/{len(result.tags)}, priority={b.priority})"
                )
        else:
            lines.append("  No matching backends – would use highest-priority backend.")
        return "\n".join(lines)

    return {
        "llm_list": lambda **_: llm_list(),
        "llm_add": lambda **kw: llm_add(**kw),
        "llm_update": lambda **kw: llm_update(**kw),
        "llm_remove": lambda **kw: llm_remove(**kw),
        "llm_test": lambda **kw: llm_test(**kw),
        "llm_classify": lambda **kw: llm_classify(**kw),
    }

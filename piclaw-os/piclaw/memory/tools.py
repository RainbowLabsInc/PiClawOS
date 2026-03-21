"""
PiClaw OS – Memory Tools
Agent-callable tools for searching, reading, and writing memory.
"""

from piclaw.llm.base import ToolDefinition
from piclaw.memory import store, qmd as qmd_module

TOOL_DEFS = [
    ToolDefinition(
        name="memory_search",
        description=(
            "Search PiClaw's persistent memory for relevant facts, decisions, "
            "past conversations, preferences or configuration. "
            "Use before answering questions about prior work or decisions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "collection": {
                    "type": "string",
                    "enum": ["memory", "daily", "sessions", "workspace", "all"],
                    "description": "Which collection to search (default: all)",
                    "default": "all",
                },
                "mode": {
                    "type": "string",
                    "enum": ["query", "vsearch", "search"],
                    "description": "query=hybrid+rerank (best), vsearch=semantic, search=keyword",
                    "default": "query",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="memory_write",
        description=(
            "Save an important fact, decision, preference or note to persistent memory. "
            "Use when the user says 'remember this' or when something important is decided."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact or note to save",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "fact",
                        "decision",
                        "preference",
                        "config",
                        "error",
                        "skill",
                        "note",
                    ],
                    "default": "fact",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for easier retrieval",
                },
            },
            "required": ["content"],
        },
    ),
    ToolDefinition(
        name="memory_log",
        description="Append a note to today's daily log.",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note to log"},
            },
            "required": ["content"],
        },
    ),
    ToolDefinition(
        name="memory_stats",
        description="Show memory storage statistics and QMD index status.",
        parameters={"type": "object", "properties": {}},
    ),
]


def build_handlers(qmd: qmd_module.QMDBackend) -> dict:

    async def memory_search(
        query: str, collection: str = "all", mode: str = "query"
    ) -> str:
        col = None if collection == "all" else collection
        results = await qmd.search(query, top_k=6, collection=col, mode=mode)
        if not results:
            return f"No memories found for: '{query}'"
        lines = [f"Found {len(results)} result(s) for '{query}':\n"]
        for i, r in enumerate(results, 1):
            src = r.source.split("/")[-1] if r.source else "?"
            score = f"{r.score:.2f}" if r.score else "?"
            lines.append(f"[{i}] ({src}, score={score})\n{r.text[:400]}")
        return "\n\n".join(lines)

    async def memory_write(
        content: str, category: str = "fact", tags: list | None = None
    ) -> str:
        result = store.write_fact(content, category=category, tags=tags or [])
        await qmd.update()
        return result

    async def memory_log(content: str) -> str:
        result = store.write_daily_note(content)
        await qmd.update()
        return result

    async def memory_stats() -> str:
        s = store.memory_stats()
        status = await qmd.status()
        return (
            f"Memory files : {s['files']}\n"
            f"Total size   : {s['total_bytes'] // 1024} KB "
            f"(~{s['est_tokens']:,} tokens)\n"
            f"Daily logs   : {s['daily_count']}\n"
            f"Sessions     : {s['sessions']}\n"
            f"QMD available: {status.get('qmd_available', False)}\n"
            f"Collections  : {'ready' if status.get('collections_ready') else 'initializing'}"
        )

    return {
        "memory_search": lambda **kw: memory_search(**kw),
        "memory_write": lambda **kw: memory_write(**kw),
        "memory_log": lambda **kw: memory_log(**kw),
        "memory_stats": lambda **_: memory_stats(),
    }

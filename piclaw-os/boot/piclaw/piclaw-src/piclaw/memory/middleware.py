"""
PiClaw OS – Memory Middleware
Two jobs:
  1. RECALL  – before each agent.run(), search QMD and inject relevant
               memories into the system prompt.
  2. EXTRACT – after each turn, extract new facts and save them to disk,
               then trigger qmd update so the index stays fresh.

This runs identically regardless of whether the active LLM backend is
local (Phi-3) or a cloud API – the injection happens at the prompt level.
"""

import logging
import re
from datetime import datetime

from piclaw.llm.base import Message, LLMBackend
from piclaw.memory.store import write_fact, save_session
from piclaw.memory.qmd import QMDBackend, MemoryResult
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.memory.middleware")

# Max tokens to spend on injected memories (~4 chars per token)
MAX_MEMORY_CHARS = 2000
# Min relevance score to inject a result
MIN_SCORE = 0.15
# How many results to fetch before trimming to char budget
FETCH_TOP_K = 8
# After this many turns, save the session and extract facts
EXTRACT_EVERY_N = 4


class MemoryMiddleware:
    """
    Wrap an agent's message list with memory recall before LLM calls,
    and trigger background extraction after responses.
    """

    def __init__(self, qmd: QMDBackend, llm: LLMBackend):
        self.qmd = qmd
        self.llm = llm  # the SmartRouter – used for extraction LLM calls
        self._turn_count = 0
        self._session_msgs: list[dict] = []

    # ── Public entry point ────────────────────────────────────────

    async def enrich(self, messages: list[Message]) -> list[Message]:
        """
        Given the current message list, inject relevant memories
        into the system prompt. Returns enriched messages.
        """
        # Find the last user message as the query
        query = ""
        for m in reversed(messages):
            if m.role == "user":
                query = m.content
                break
        if not query:
            return messages

        results = await self.qmd.search(query, top_k=FETCH_TOP_K)
        if not results:
            return messages

        # Filter by score and fit within char budget
        good = [r for r in results if r.score >= MIN_SCORE]
        memory_block = self._format_memories(good)
        if not memory_block:
            return messages

        log.debug(
            "Injecting %s memory results (%s chars)", len(good), len(memory_block)
        )
        return self._inject_into_system(messages, memory_block)

    async def after_turn(self, user_text: str, assistant_text: str):
        """
        Called after each agent response.
        Accumulates session turns and periodically extracts + saves facts.
        """
        self._turn_count += 1
        self._session_msgs.append(
            {"role": "user", "content": user_text, "ts": datetime.now().isoformat()}
        )
        self._session_msgs.append(
            {
                "role": "assistant",
                "content": assistant_text,
                "ts": datetime.now().isoformat(),
            }
        )

        if self._turn_count % EXTRACT_EVERY_N == 0:
            create_background_task(self._extract_and_index())

    async def flush(self, session_id: str = "manual"):
        """Save the current session and run extraction immediately."""
        if self._session_msgs:
            save_session(session_id, self._session_msgs)
        await self._extract_and_index()

    # ── Memory injection ─────────────────────────────────────────

    def _format_memories(self, results: list[MemoryResult]) -> str:
        if not results:
            return ""
        parts = []
        total = 0
        for r in results:
            src = r.source.split("/")[-1] if r.source else "memory"
            chunk = f"[{src}]\n{r.text.strip()}"
            if total + len(chunk) > MAX_MEMORY_CHARS:
                break
            parts.append(chunk)
            total += len(chunk)
        return "\n\n---\n\n".join(parts)

    def _inject_into_system(self, messages: list[Message], block: str) -> list[Message]:
        header = (
            "## Relevant memories from past conversations and notes\n"
            "(Use this context to answer more accurately. "
            "Do not mention that you looked up memories unless asked.)\n\n"
            f"{block}\n\n---"
        )
        new = list(messages)
        if new and new[0].role == "system":
            new[0] = Message(
                role="system",
                content=new[0].content + "\n\n" + header,
            )
        else:
            new.insert(0, Message(role="system", content=header))
        return new

    # ── Extraction ────────────────────────────────────────────────

    async def _extract_and_index(self):
        """
        Use the LLM to extract memorable facts from recent conversation,
        then write them to disk and re-index with QMD.
        """
        if not self._session_msgs:
            return

        recent = self._session_msgs[-EXTRACT_EVERY_N * 2 :]
        "\n".join(f"{m['role'].upper()}: {m['content'][:300]}" for m in recent)

        extract_prompt = """You are a memory extraction system for an AI agent running on a Raspberry Pi.
Read the following conversation and extract ONLY facts, decisions, preferences, or important information
that should be remembered for future conversations.

Return a JSON array of objects with keys:
  "category": one of fact|decision|preference|config|error|skill
  "content":  the fact to remember (1-2 sentences, specific and concrete)
  "tags":     list of relevant tags

Skip trivial exchanges. Return [] if nothing important to remember.
Return ONLY valid JSON, no explanation.

Conversation:
{conversation}"""

        try:
            resp = await self.llm.chat(
                [Message(role="user", content=extract_prompt)],
                tools=None,
            )
            raw = resp.content.strip()

            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            facts = []
            try:
                facts = json_safe_parse(raw)
            except Exception:
                log.debug("Memory extraction parse failed: %.100s", raw)

            for fact in facts:
                if isinstance(fact, dict) and "content" in fact:
                    write_fact(
                        content=fact["content"],
                        category=fact.get("category", "fact"),
                        tags=fact.get("tags", []),
                    )
                    log.info(
                        "Memory extracted: [%s] %.60s",
                        fact.get("category"),
                        fact["content"],
                    )

            if facts:
                # QMD-Re-index läuft nicht mehr nach jedem Turn (zu CPU-intensiv auf Pi)
                # Stattdessen: stündlicher Cron-Job via piclaw-qmd-update.service
                log.debug(
                    "Memory extracted %d facts – QMD update deferred to cron",
                    len(facts),
                )

        except Exception as e:
            log.error("Memory extraction failed: %s", e)


def json_safe_parse(text: str):
    """Tolerant JSON parse – handles single quotes, trailing commas."""
    import json

    try:
        return json.loads(text)
    except Exception:
        # Try to extract a JSON array
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError) as _e:
                log.debug("fact JSON parse: %s", _e)
        return []

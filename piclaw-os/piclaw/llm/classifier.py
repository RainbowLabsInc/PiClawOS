"""
PiClaw OS – Task Classifier
Determines which capability tags best describe an incoming user request.

Two-stage approach:
  Stage 1 – Pattern matching (instant, no LLM required)
             Covers the most common/obvious cases.
  Stage 2 – LLM classification (used when Stage 1 is inconclusive)
             Calls the fastest available backend for a single-token response.

Output: a list of tags like ["coding", "python"] or ["german", "creative"]
These tags are then matched against the registry to select a backend.
"""

import asyncio
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("piclaw.llm.classifier")


@dataclass
class ClassificationResult:
    tags:       list[str]
    confidence: float        # 0.0–1.0
    method:     str          # "pattern" | "llm" | "default"
    reasoning:  str = ""


# ── Pattern rules ─────────────────────────────────────────────────
# Each rule: (regex_pattern, tags_to_assign, confidence)
# Patterns are checked in order; first match wins for Stage 1.
# Multiple patterns can match to build up a tag set.

PATTERN_RULES: list[tuple[str, list[str], float]] = [

    # ── Coding & technical ────────────────────────────────────────
    (r'\b(write|create|build|implement|code|program)\b.{0,40}\b(function|class|script|module|api|endpoint)\b',
     ["coding"], 0.90),
    (r'\b(debug|fix|error|exception|traceback|bug|crash|broken)\b',
     ["debugging"], 0.85),
    (r'\b(python|javascript|typescript|rust|go|java|c\+\+|bash|sql)\b',
     ["coding"], 0.80),
    (r'\b(refactor|optimize|clean up|improve).{0,30}\b(code|function|script)\b',
     ["coding", "analysis"], 0.80),
    (r'\b(regex|algorithm|data structure|complexity|big.?o)\b',
     ["coding", "reasoning"], 0.80),
    (r'\b(dockerfile|kubernetes|docker|k8s|terraform|ansible|ci/cd|github actions)\b',
     ["coding", "technical"], 0.80),
    (r'\b(api|rest|graphql|endpoint|http|curl|request|response)\b',
     ["coding", "technical"], 0.70),

    # ── Math & science ────────────────────────────────────────────
    (r'\b(berechne|calculate|solve|equation|integral|derivative|matrix|vector)\b',
     ["math", "reasoning"], 0.85),
    (r'\b(statistik|statistics|probability|regression|correlation)\b',
     ["math", "analysis"], 0.80),

    # ── Analysis & reasoning ──────────────────────────────────────
    (r'\b(analyze|analyse|vergleiche|compare|evaluate|bewerte|assess)\b',
     ["analysis", "reasoning"], 0.75),
    (r'\b(pros and cons|vor.? und nachteile|trade.?offs?|decision)\b',
     ["analysis", "reasoning"], 0.75),
    (r'\b(summarize|zusammenfass|tldr|key points|highlights)\b',
     ["summarization"], 0.80),

    # ── Creative & writing ────────────────────────────────────────
    (r'\b(write|schreibe|verfasse).{0,40}\b(story|poem|gedicht|essay|artikel|blog|email|brief)\b',
     ["creative", "writing"], 0.85),
    (r'\b(brainstorm|ideas|ideen|kreativ|creative)\b',
     ["creative"], 0.75),
    (r'\b(marketing|advertisement|slogan|pitch|sales)\b',
     ["creative", "writing"], 0.70),

    # ── Translation & language ────────────────────────────────────
    (r'\b(translate|übersetze|übersetz|translation|übersetzen)\b',
     ["translation"], 0.90),
    (r'\b(auf deutsch|in german|ins deutsche|auf englisch|in english)\b',
     ["translation"], 0.85),
    (r'\b(grammar|grammatik|spell.?check|rechtschreibung|korrigiere)\b',
     ["writing", "translation"], 0.80),

    # ── Language detection ────────────────────────────────────────
    (r'\b(ich|du|bitte|danke|kannst|möchte|würde|habe|sein|nicht|auch|wenn|dass)\b',
     ["german"], 0.70),
    (r'\b(je|tu|vous|merci|bonjour|s\'il vous plaît|est-ce que)\b',
     ["french"], 0.70),
    (r'\b(hola|gracias|por favor|cómo|qué|está|también)\b',
     ["spanish"], 0.70),

    # ── Research & information ────────────────────────────────────
    (r'\b(research|recherche|find out|what is|what are|how does|erkläre|explain)\b',
     ["research", "general"], 0.65),

    # ── System / Pi specific ──────────────────────────────────────
    (r'\b(raspberry|gpio|sensor|i2c|spi|uart|pwm|pin)\b',
     ["coding", "technical"], 0.80),
    (r'\b(systemd|service|daemon|process|cron|schedule)\b',
     ["technical"], 0.70),
]

# Tags that indicate "general" if nothing else matches
DEFAULT_TAGS = ["general"]


class TaskClassifier:
    """
    Classifies a user message into capability tags.
    The tags are then used by the MultiLLMRouter to select a backend.
    """

    def __init__(self, llm_for_classification=None):
        """
        llm_for_classification: optional fast LLM backend to use for Stage 2.
        If None, only pattern matching is used.
        """
        self._llm = llm_for_classification
        self._compiled = [
            (re.compile(pattern, re.IGNORECASE), tags, conf)
            for pattern, tags, conf in PATTERN_RULES
        ]

    async def classify(self, text: str) -> ClassificationResult:
        """Main entry point. Returns tags for the given user message."""

        # Stage 1: Pattern matching
        result = self._pattern_classify(text)

        # Stage 2: LLM fallback if confidence is low and LLM available
        if result.confidence < 0.65 and self._llm:
            try:
                llm_result = await asyncio.wait_for(
                    self._llm_classify(text), timeout=8.0
                )
                if llm_result.confidence > result.confidence:
                    return llm_result
            except asyncio.TimeoutError:
                log.debug("LLM classification timed out, using pattern result.")
            except Exception as e:
                log.debug("LLM classification failed: %s", e)

        return result

    def classify_sync(self, text: str) -> ClassificationResult:
        """Pattern-only classification (synchronous, no LLM)."""
        return self._pattern_classify(text)

    # ── Stage 1: Patterns ─────────────────────────────────────────

    def _pattern_classify(self, text: str) -> ClassificationResult:
        matched_tags: dict[str, float] = {}  # tag → max confidence

        for pattern, tags, conf in self._compiled:
            if pattern.search(text):
                for tag in tags:
                    matched_tags[tag] = max(matched_tags.get(tag, 0), conf)

        if not matched_tags:
            return ClassificationResult(
                tags=DEFAULT_TAGS,
                confidence=0.3,
                method="default",
                reasoning="No patterns matched.",
            )

        # Sort tags by confidence, take top ones
        sorted_tags = sorted(matched_tags.items(), key=lambda x: x[1], reverse=True)
        top_tags    = [t for t, _ in sorted_tags[:4]]
        confidence  = sorted_tags[0][1]

        return ClassificationResult(
            tags=top_tags,
            confidence=confidence,
            method="pattern",
            reasoning=f"Pattern matched: {top_tags}",
        )

    # ── Stage 2: LLM classification ───────────────────────────────

    async def _llm_classify(self, text: str) -> ClassificationResult:
        from piclaw.llm.base import Message

        all_tags = [
            "coding", "debugging", "analysis", "reasoning",
            "creative", "writing", "summarization", "translation",
            "math", "research", "technical", "general",
            "german", "english", "french", "spanish",
        ]

        prompt = (
            "Classify this user request into 1-3 tags from this list:\n"
            f"{', '.join(all_tags)}\n\n"
            f"Request: \"{text[:300]}\"\n\n"
            "Reply with ONLY a comma-separated list of tags, nothing else.\n"
            "Example: coding, debugging"
        )

        resp = await self._llm.chat(
            [Message(role="user", content=prompt)],
            tools=None,
        )

        raw   = resp.content.strip().lower()
        tags  = [t.strip() for t in raw.split(",") if t.strip() in all_tags]
        if not tags:
            tags = DEFAULT_TAGS

        return ClassificationResult(
            tags=tags,
            confidence=0.80,
            method="llm",
            reasoning=f"LLM returned: {raw}",
        )

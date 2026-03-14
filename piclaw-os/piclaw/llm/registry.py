"""
PiClaw OS – LLM Registry
Stores multiple LLM backend configurations with user-defined capability tags.

Each backend has:
  name        – unique identifier (e.g. "claude-sonnet", "gpt-4o", "local")
  provider    – anthropic | openai | ollama | local
  model       – model string (e.g. "claude-sonnet-4-20250514")
  tags        – user-defined capability labels (e.g. ["coding", "german"])
  priority    – tiebreaker when multiple backends match (higher = preferred)
  api_key     – can be empty if shared from global config
  base_url    – override endpoint
  enabled     – soft-disable without deleting
  max_tokens  – per-backend limit
  temperature – per-backend temperature

Tags are free-form strings. Built-in tag categories (used by the classifier):
  Task tags:   coding, debugging, analysis, reasoning, creative, writing,
               summarization, translation, math, research, general
  Language:    german, english, french, spanish, …
  Style:       fast, detailed, concise, step-by-step
  Domain:      medical, legal, finance, science, …
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.llm.registry")

REGISTRY_FILE = CONFIG_DIR / "llm_registry.json"


@dataclass
class BackendConfig:
    name:        str         # unique identifier
    provider:    str         # anthropic | openai | ollama | local
    model:       str
    tags:        list[str]   = field(default_factory=list)
    priority:    int         = 5       # 1–10, higher = preferred
    api_key:     str         = ""      # empty = use global config key
    base_url:    str         = ""      # empty = provider default
    enabled:     bool        = True
    max_tokens:  int         = 4096
    temperature: float       = 0.7
    timeout:     int         = 60
    notes:       str         = ""      # user-visible description

    def has_tag(self, tag: str) -> bool:
        return tag.lower() in [t.lower() for t in self.tags]

    def tag_overlap(self, tags: list[str]) -> int:
        """How many of the given tags does this backend cover?"""
        my_tags = {t.lower() for t in self.tags}
        return sum(1 for t in tags if t.lower() in my_tags)


class LLMRegistry:
    """
    Persistent store for all LLM backend configurations.
    CRUD operations + tag-based lookup.
    """

    def __init__(self):
        self._backends: dict[str, BackendConfig] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        if not REGISTRY_FILE.exists():
            self._backends = {}
            return
        try:
            data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            self._backends = {
                k: BackendConfig(**v) for k, v in data.items()
            }
            log.info("LLM registry loaded: %s backends", len(self._backends))
        except Exception as e:
            log.error("Registry load error: %s", e)
            self._backends = {}

    def _save(self):
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in self._backends.items()}
        from piclaw.fileutils import safe_write_json
        safe_write_json(REGISTRY_FILE, data, label="llm_registry")

    # ── CRUD ──────────────────────────────────────────────────────

    def add(self, cfg: BackendConfig) -> str:
        self._backends[cfg.name] = cfg
        self._save()
        log.info("Registry: added backend '%s' tags=%s", cfg.name, cfg.tags)
        return f"Backend '{cfg.name}' added."

    def update(self, name: str, **kwargs) -> str:
        if name not in self._backends:
            return f"Backend '{name}' not found."
        for k, v in kwargs.items():
            if hasattr(self._backends[name], k):
                setattr(self._backends[name], k, v)
        self._save()
        return f"Backend '{name}' updated."

    def remove(self, name: str) -> str:
        if name not in self._backends:
            return f"Backend '{name}' not found."
        del self._backends[name]
        self._save()
        return f"Backend '{name}' removed."

    def get(self, name: str) -> Optional[BackendConfig]:
        return self._backends.get(name)

    def list_all(self) -> list[BackendConfig]:
        return sorted(
            self._backends.values(),
            key=lambda b: (-b.priority, b.name)
        )

    def list_enabled(self) -> list[BackendConfig]:
        return [b for b in self.list_all() if b.enabled]

    # ── Tag-based lookup ──────────────────────────────────────────

    def find_by_tags(self, tags: list[str],
                     min_overlap: int = 1) -> list[BackendConfig]:
        """
        Return enabled backends sorted by tag overlap (descending),
        then priority (descending).
        """
        results = []
        for b in self.list_enabled():
            overlap = b.tag_overlap(tags)
            if overlap >= min_overlap:
                results.append((overlap, b.priority, b))
        results.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [b for _, _, b in results]

    def best_for_tags(self, tags: list[str]) -> Optional[BackendConfig]:
        """Return the single best backend for the given tags."""
        matches = self.find_by_tags(tags, min_overlap=1)
        return matches[0] if matches else None

    def all_tags(self) -> list[str]:
        """All unique tags across all registered backends."""
        tags = set()
        for b in self._backends.values():
            tags.update(t.lower() for t in b.tags)
        return sorted(tags)

    # ── Bootstrap from global config ─────────────────────────────

    def bootstrap_from_config(self, cfg) -> bool:
        """
        Auto-populate registry from PiClawConfig on first boot.
        Only runs if registry is empty.
        Returns True if backends were added.
        """
        if self._backends:
            return False

        llm = cfg.llm
        # Lokales Backend hat keinen API-Key – trotzdem registrieren
        if not llm.api_key and llm.backend not in ("local", "ollama"):
            return False

        name = f"{llm.backend}-default"
        default = BackendConfig(
            name=name,
            provider=llm.backend,
            model=llm.model,
            api_key=llm.api_key,
            base_url=llm.base_url,
            tags=["general", "reasoning", "analysis"],
            priority=5,
            notes="Auto-imported from config.toml",
        )
        self.add(default)
        log.info("Registry bootstrapped from config: %s", name)
        return True

    # ── Status summary ────────────────────────────────────────────

    def summary(self) -> str:
        backends = self.list_all()
        if not backends:
            return "No backends registered. Run: piclaw llm add"
        lines = [f"LLM Backends ({len(backends)} registered):\n"]
        for b in backends:
            status = "✅" if b.enabled else "⏸"
            key    = "🔑" if b.api_key else "  "
            lines.append(
                f"  {status} {key} [{b.priority:2}] {b.name}\n"
                f"        {b.provider}/{b.model}\n"
                f"        tags: {', '.join(b.tags) or '(none)'}\n"
                f"        {b.notes or ''}"
            )
        return "\n".join(lines)

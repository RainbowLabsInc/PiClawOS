"""
PiClaw OS – QMD Search Backend
Wraps the `qmd` CLI (BM25 + vector + LLM reranking).

QMD is installed via: npm install -g @tobilu/qmd
Collections managed here:
  memory    → MEMORY.md + daily logs (facts, decisions, preferences)
  sessions  → conversation JSONL history
  workspace → skills, notes, project docs
"""

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass

from piclaw.memory.store import (
    MEMORY_ROOT,
    MEMORY_MAIN,
    DAILY_DIR,
    SESSIONS_DIR,
    WORKSPACE_DIR,
    ensure_dirs,
)

log = logging.getLogger("piclaw.memory.qmd")

# QMD XDG dirs – isolated per agent to avoid conflicts
QMD_XDG_CONFIG = MEMORY_ROOT / "qmd" / "xdg-config"
QMD_XDG_CACHE = MEMORY_ROOT / "qmd" / "xdg-cache"

QMD_ENV = {
    **os.environ,
    "XDG_CONFIG_HOME": str(QMD_XDG_CONFIG),
    "XDG_CACHE_HOME": str(QMD_XDG_CACHE),
}

# How many memory snippets to inject per query
DEFAULT_TOP_K = 5
# Search timeout (vector search can be slow on Pi)
SEARCH_TIMEOUT = 6  # kurz halten: Agent-Timeout ist 8s
# Embed timeout (model loading takes time on first run)
EMBED_TIMEOUT = 180


@dataclass
class MemoryResult:
    text: str
    source: str
    score: float
    collection: str


class QMDBackend:
    """
    Manages QMD collections and provides hybrid search.
    Falls back to simple keyword grep if QMD is not installed.
    """

    def __init__(self):
        self._qmd_available: bool | None = None
        self._collections_ready = False
        self._embed_task = None

    # ── Installation check ───────────────────────────────────────

    def _qmd_bin(self) -> str | None:
        return shutil.which("qmd")

    def is_available(self) -> bool:
        if self._qmd_available is None:
            self._qmd_available = self._qmd_bin() is not None
            if not self._qmd_available:
                log.warning(
                    "QMD not found. Falling back to grep search. "
                    "Install with: npm install -g @tobilu/qmd"
                )
        return self._qmd_available

    # ── QMD command runner ───────────────────────────────────────

    async def _qmd(self, args: list[str], timeout: int = SEARCH_TIMEOUT) -> str:
        qmd = self._qmd_bin()
        if not qmd:
            return ""
        cmd = [qmd] + args
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=QMD_ENV,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                log.debug("qmd %s: %.200s", " ".join(args[:2]), err.decode())
            return out.decode(errors="replace")
        except TimeoutError:
            log.debug("qmd timeout – args: %s", " ".join(args))
            return ""
        except Exception as e:
            log.error("qmd error: %s", e)
            return ""

    # ── Collection setup ─────────────────────────────────────────

    async def setup_collections(self):
        """
        Create/update QMD collections on first boot and after index changes.
        Safe to call multiple times (qmd collection add is idempotent).
        """
        if not self.is_available():
            return

        ensure_dirs()
        QMD_XDG_CONFIG.mkdir(parents=True, exist_ok=True)
        QMD_XDG_CACHE.mkdir(parents=True, exist_ok=True)

        log.info("Setting up QMD collections…")

        # SOUL.md aus dem Memory-Index ausschliessen:
        # Die Soul-Datei enthaelt die Agenten-Persoenlichkeit, keine Fakten.
        # Wenn sie indiziert wird, injiziert QMD sie als "Erinnerung" und
        # verwirrt das Modell bei unverwandten Anfragen (z.B. Marktplatz-Suche).
        # Loesung: memory-Collection nur auf MEMORY.md + memory/ beschraenken,
        # SOUL.md liegt im MEMORY_ROOT aber wird nicht mehr erfasst.

        # Register collections
        # memory-Collection: nur daily-Logs und MEMORY.md, NICHT SOUL.md
        await self._qmd(
            ["collection", "add", str(DAILY_DIR), "--name", "memory", "--mask", "*.md"]
        )
        # MEMORY.md explizit als einzelne Datei hinzufuegen
        if (MEMORY_MAIN).exists():
            await self._qmd(["collection", "add", str(MEMORY_MAIN), "--name", "memory"])
        await self._qmd(
            [
                "collection",
                "add",
                str(SESSIONS_DIR),
                "--name",
                "sessions",
                "--mask",
                "*.jsonl",
            ]
        )
        await self._qmd(
            [
                "collection",
                "add",
                str(WORKSPACE_DIR),
                "--name",
                "workspace",
                "--mask",
                "**/*.md",
            ]
        )

        # Add context descriptions (helps QMD understand what's what)
        await self._qmd(
            [
                "context",
                "add",
                str(DAILY_DIR),
                "PiClaw agent memory: facts, decisions, preferences, "
                "hardware config, installed skills, scheduled tasks, "
                "daily activity logs (SOUL.md is excluded)",
            ]
        )
        await self._qmd(
            [
                "context",
                "add",
                str(SESSIONS_DIR),
                "Conversation session history in JSONL format",
            ]
        )
        await self._qmd(
            [
                "context",
                "add",
                str(WORKSPACE_DIR),
                "Workspace documents, project notes, skill definitions",
            ]
        )

        # Initial index
        log.info("Running qmd update (indexing)…")
        await self._qmd(["update"], timeout=60)

        self._collections_ready = True
        log.info("QMD collections ready.")

    async def embed(self):
        """
        Build/update vector embeddings (downloads GGUF models on first run ~2 GB).
        Runs in background – agent works without it using BM25 only.
        """
        if not self.is_available():
            return
        log.info(
            "Building QMD vector embeddings (may take several minutes on first run)…"
        )
        await self._qmd(["embed"], timeout=EMBED_TIMEOUT)
        log.info("QMD embeddings ready.")

    async def update(self):
        """Re-index changed files (call after writing new memories)."""
        if not self.is_available() or not self._collections_ready:
            return
        await self._qmd(["update"], timeout=60)

    # ── Search ────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        collection: str | None = None,
        mode: str = "query",  # query=hybrid+rerank | vsearch=semantic | search=BM25
    ) -> list[MemoryResult]:
        """
        Hybrid search across all collections (or a specific one).
        mode: 'query' = best quality (BM25+vector+rerank), slower
              'vsearch' = semantic only
              'search'  = BM25 only, fastest
        """
        if not self.is_available():
            return await self._grep_fallback(query, top_k)

        args = [mode, query, "--json", f"--limit={top_k}"]
        if collection:
            args += ["-c", collection]

        raw = await self._qmd(args)
        if not raw.strip():
            # Try BM25 fallback if hybrid fails (embeddings may not be ready)
            if mode == "query":
                raw = await self._qmd(
                    ["search", query, "--json", f"--limit={top_k}"]
                    + (["-c", collection] if collection else [])
                )

        return self._parse_results(raw)

    def _parse_results(self, raw: str) -> list[MemoryResult]:
        results = []
        try:
            data = json.loads(raw)
            items = data if isinstance(data, list) else data.get("results", [])
            for item in items:
                text = (
                    item.get("content") or item.get("text") or item.get("snippet") or ""
                ).strip()
                if not text:
                    continue
                results.append(
                    MemoryResult(
                        text=text,
                        source=item.get("path", item.get("file", "")),
                        score=float(item.get("score", 0.0)),
                        collection=item.get("collection", ""),
                    )
                )
        except Exception as e:
            log.debug("QMD result parse error: %s. Raw: %.200s", e, raw)
        return results

    # ── Grep fallback (when QMD not installed) ────────────────────

    async def _grep_fallback(self, query: str, top_k: int) -> list[MemoryResult]:
        """Simple grep across markdown files as fallback."""
        results = []
        terms = query.lower().split()
        # SOUL.md explizit ausschliessen – sie gehoert nicht ins Memory-Recall
        _soul_name = "SOUL.md"
        files = ([MEMORY_MAIN] if MEMORY_MAIN.exists() else []) + [
            f for f in DAILY_DIR.glob("*.md") if f.name != _soul_name
        ]

        for f in files:
            if not f.exists():
                continue
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue  # unlesbare Datei – überspringen
            for i, line in enumerate(lines):
                ll = line.lower()
                if any(t in ll for t in terms):
                    # Include surrounding context (2 lines before/after)
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "\n".join(lines[start:end]).strip()
                    results.append(
                        MemoryResult(
                            text=snippet,
                            source=str(f),
                            score=sum(1 for t in terms if t in ll) / len(terms),
                            collection="memory",
                        )
                    )
                    if len(results) >= top_k * 3:
                        break

        # Sort by score, deduplicate, take top_k
        results.sort(key=lambda r: r.score, reverse=True)
        seen, deduped = set(), []
        for r in results:
            key = r.text[:80]
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped[:top_k]

    # ── Status ────────────────────────────────────────────────────

    async def status(self) -> dict:
        raw = await self._qmd(["status", "--json"])
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            data = {"raw": raw.strip()}
        return {
            "qmd_available": self.is_available(),
            "collections_ready": self._collections_ready,
            **data,
        }

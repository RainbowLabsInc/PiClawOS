"""
PiClaw OS – Memory Store
Plain markdown files on disk.
Layout:
  /etc/piclaw/memory/
    MEMORY.md           – durable facts, decisions, preferences
    memory/YYYY-MM-DD.md – daily logs
    sessions/           – conversation session JSONL files
    workspace/          – notes, skills, project docs
    context.md          – agent self-description (used by QMD context)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.memory.store")

MEMORY_ROOT = CONFIG_DIR / "memory"
MEMORY_MAIN = MEMORY_ROOT / "MEMORY.md"
DAILY_DIR = MEMORY_ROOT / "memory"
SESSIONS_DIR = MEMORY_ROOT / "sessions"
WORKSPACE_DIR = MEMORY_ROOT / "workspace"   # WORKSPACE bleibt global (geteilt)
CONTEXT_FILE = MEMORY_ROOT / "context.md"


def _resolve_user_id(user_id: str | None) -> str | None:
    """Wenn user_id explizit None ist, ContextVar nachschlagen.
    Bleibt None: globale Pfade (Legacy/System)."""
    if user_id is not None:
        return user_id
    try:
        from piclaw.agent_context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return None


def _paths_for(user_id: str | None) -> tuple[Path, Path, Path, Path]:
    """Liefert (root, MEMORY.md, daily_dir, sessions_dir) — pro User oder global."""
    if user_id is None:
        return MEMORY_ROOT, MEMORY_MAIN, DAILY_DIR, SESSIONS_DIR
    from piclaw.users import user_path
    base = user_path(user_id, "memory")
    return base, base / "MEMORY.md", base / "memory", base / "sessions"


def ensure_dirs(user_id: str | None = None):
    """Stellt Verzeichnisse + MEMORY.md sicher (pro User wenn user_id)."""
    user_id = _resolve_user_id(user_id)
    root, main, daily, sessions = _paths_for(user_id)
    for d in [root, daily, sessions]:
        d.mkdir(parents=True, exist_ok=True)
    if not main.exists():
        main.write_text(
            "# PiClaw Memory\n\n"
            "> Persistent facts, decisions and preferences.\n\n"
        )

    # WORKSPACE und CONTEXT bleiben global (geteilt)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONTEXT_FILE.exists():
        CONTEXT_FILE.write_text(
            "# PiClaw Agent Context\n\n"
            "This is the PiClaw AI operating system running on a Raspberry Pi 5.\n"
            "Memory files contain: facts about the hardware setup, user preferences,\n"
            "decisions made, installed skills, scheduled tasks, and conversation history.\n"
        )


# ── Write helpers ────────────────────────────────────────────────


def write_fact(
    content: str,
    category: str = "fact",
    tags: list[str] | None = None,
    user_id: str | None = None,
) -> str:
    """Append a structured fact to MEMORY.md (pro User wenn user_id)."""
    user_id = _resolve_user_id(user_id)
    ensure_dirs(user_id)
    _, main, _, _ = _paths_for(user_id)
    ts = datetime.now().isoformat(timespec="seconds")
    tag_s = ", ".join(tags) if tags else ""
    block = (
        f"\n## [{category.upper()}] {ts}\n"
        f"{f'**Tags:** {tag_s}  ' if tag_s else ''}\n"
        f"{content.strip()}\n"
    )
    with open(main, "a", encoding="utf-8") as f:
        f.write(block)
    log.info("Wrote memory fact (%s, user=%s): %.60s…", category, user_id or "-", content)
    return f"Memory saved: {content[:80]}"


def write_daily_note(
    content: str,
    date: str | None = None,
    user_id: str | None = None,
) -> str:
    """Append to today's daily log."""
    user_id = _resolve_user_id(user_id)
    ensure_dirs(user_id)
    _, _, daily, _ = _paths_for(user_id)
    day = date or datetime.now().strftime("%Y-%m-%d")
    path = daily / f"{day}.md"
    ts = datetime.now().strftime("%H:%M:%S")
    if not path.exists():
        path.write_text(f"# Daily Log – {day}\n\n", encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n### {ts}\n{content.strip()}\n")
    return f"Daily note saved ({day})."


def save_session(
    session_id: str,
    messages: list[dict],
    user_id: str | None = None,
) -> Path:
    """Persist a conversation session as JSONL for QMD indexing."""
    user_id = _resolve_user_id(user_id)
    ensure_dirs(user_id)
    _, _, _, sessions = _paths_for(user_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = sessions / f"{ts}_{session_id[:8]}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


def write_workspace_file(filename: str, content: str) -> str:
    """Write an arbitrary file to the workspace collection."""
    ensure_dirs()
    path = (WORKSPACE_DIR / filename).resolve()
    if not path.is_relative_to(WORKSPACE_DIR.resolve()):
        raise ValueError("Invalid path: Workspace path must be within WORKSPACE_DIR")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Workspace file saved: {path}"


# ── Read helpers ─────────────────────────────────────────────────


def read_memory_main(user_id: str | None = None) -> str:
    user_id = _resolve_user_id(user_id)
    ensure_dirs(user_id)
    _, main, _, _ = _paths_for(user_id)
    return main.read_text(encoding="utf-8") if main.exists() else ""


def read_today(user_id: str | None = None) -> str:
    user_id = _resolve_user_id(user_id)
    ensure_dirs(user_id)
    _, _, daily, _ = _paths_for(user_id)
    day = datetime.now().strftime("%Y-%m-%d")
    path = daily / f"{day}.md"
    return (
        path.read_text(encoding="utf-8")
        if path.exists()
        else f"No daily log yet for {day}."
    )


def list_memory_files() -> list[Path]:
    ensure_dirs()
    return (
        list(MEMORY_ROOT.glob("*.md"))
        + list(DAILY_DIR.glob("*.md"))
        + list(WORKSPACE_DIR.rglob("*.md"))
    )


def memory_stats() -> dict:
    ensure_dirs()
    files = list_memory_files()
    total = sum(f.stat().st_size for f in files)
    tokens = total // 4  # rough estimate
    return {
        "files": len(files),
        "total_bytes": total,
        "est_tokens": tokens,
        "main_size": MEMORY_MAIN.stat().st_size if MEMORY_MAIN.exists() else 0,
        "daily_count": len(list(DAILY_DIR.glob("*.md"))),
        "sessions": len(list(SESSIONS_DIR.glob("*.jsonl"))),
    }

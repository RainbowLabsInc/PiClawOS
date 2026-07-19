"""
PiClaw OS – Sub-Agent Run-Historie

Ring-Puffer-Store für die Ergebnisse abgeschlossener Sub-Agent-Läufe,
bewusst getrennt von subagents.json: Die SubAgentRegistry lädt nur beim
Prozessstart und merged beim Schreiben ihren In-Memory-Stand zurück –
Laufergebnisse dort abzulegen würde veraltete Kopien des jeweils anderen
Prozesses (api ↔ agent) zurückschreiben. Diese Datei wird von beiden
Prozessen nur unter File-Lock append-und-trimmend geschrieben und von
der API bei jedem Request frisch von Platte gelesen.

Format: {agent_id: [entry, ...]} – Einträge chronologisch, ältester zuerst.
Entry: {ts, name, status, duration_s, result, owner_id}
"""

import json
import logging
from datetime import datetime

from piclaw.config import CONFIG_DIR
from piclaw.fileutils import safe_write_json, with_file_lock

log = logging.getLogger("piclaw.agents.sa_history")

HISTORY_FILE = CONFIG_DIR / "sa_history.json"

# Ring-Puffer-Grenzen: bounded file size auf der SD-Karte.
MAX_ENTRIES_PER_AGENT = 20
# Einmalige Agenten (once/SearchAssistant) werden nach dem Lauf aus der
# Registry entfernt, ihre Historie bliebe sonst ewig liegen – deshalb
# zusätzlich ein globales Limit über die Agenten-Anzahl (älteste zuerst raus).
MAX_AGENTS = 50
MAX_RESULT_CHARS = 600


def _read() -> dict[str, list[dict]]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError) as e:
        log.warning("sa_history load error: %s", e)
    return {}


def _latest_ts(entries: list[dict]) -> str:
    return entries[-1].get("ts", "") if entries else ""


def record_run(
    agent_id: str,
    name: str,
    status: str,
    duration_s: float,
    result: str,
    owner_id: str | None = None,
) -> bool:
    """Hängt einen abgeschlossenen Lauf an die Historie des Agenten an.

    Nur Terminal-Status (ok/error/timeout) aufzeichnen – transiente
    'running'-Zustände gehören nicht hierher.
    """
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "name": name,
        "status": status,
        "duration_s": round(float(duration_s), 1),
        "result": (result or "")[:MAX_RESULT_CHARS],
        "owner_id": owner_id,
    }
    try:
        with with_file_lock(HISTORY_FILE):
            data = _read()
            entries = data.setdefault(agent_id, [])
            entries.append(entry)
            del entries[:-MAX_ENTRIES_PER_AGENT]
            if len(data) > MAX_AGENTS:
                for stale_id in sorted(data, key=lambda k: _latest_ts(data[k]))[
                    : len(data) - MAX_AGENTS
                ]:
                    del data[stale_id]
            return safe_write_json(HISTORY_FILE, data, label="sa_history")
    except TimeoutError as e:
        log.warning("sa_history: Lock nicht bekommen, Eintrag verworfen: %s", e)
        return False


def history_for(agent_id: str, limit: int = MAX_ENTRIES_PER_AGENT) -> list[dict]:
    """Läufe eines Agenten, neuester zuerst."""
    return list(reversed(_read().get(agent_id, [])))[:limit]


def latest_per_agent() -> dict[str, dict]:
    """Jüngster Eintrag pro Agent (für das Status-Overlay der API)."""
    return {aid: entries[-1] for aid, entries in _read().items() if entries}

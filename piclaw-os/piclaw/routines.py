"""
PiClaw OS – Routinen-System
============================

Nutzer-definierte Routinen: Was soll PiClaw wann automatisch tun?

Eingebaute Routinen (konfigurierbar):
  morning_briefing  – täglich um 7:00 Uhr Morgen-Briefing per Telegram
  evening_check     – täglich um 22:00 Abend-Check (Lichter, Türen)
  weekly_report     – Montags um 8:00 Wochenbericht

Eigene Routinen:
  Jede Routine ist ein cron-gesteuerter Task mit:
  - Aktion: briefing | ha_scene | agent_prompt | notify
  - Empfänger: all | telegram | discord | whatsapp
  - Bedingungen: nur wenn (Wochentag, HA-Zustand, etc.)

Persistenz: /etc/piclaw/routines.json
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from piclaw.proactive import ProactiveRunner

log = logging.getLogger("piclaw.routines")


# ── Datenmodell ───────────────────────────────────────────────────


@dataclass
class Routine:
    id: str
    name: str
    enabled: bool
    cron: str  # cron expression
    action: str  # "briefing" | "ha_scene" | "agent_prompt" | "notify"
    params: dict  # action-specific params
    channel: str = "all"  # "all" | "telegram" | "discord" | "whatsapp"
    conditions: dict = field(default_factory=dict)  # optional conditions
    last_run: str = ""
    run_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Routine:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def describe(self) -> str:
        status = "✓" if self.enabled else "✗"
        last = f"  (zuletzt: {self.last_run[:16]})" if self.last_run else ""
        return f"[{status}] {self.name}  [{self.cron}]  → {self.action}{last}"


# ── Standard-Routinen ─────────────────────────────────────────────

DEFAULT_ROUTINES: list[dict] = [
    {
        "id": "morning_briefing",
        "name": "Morgen-Briefing",
        "enabled": False,  # deaktiviert bis Nutzer es anschaltet
        "cron": "0 7 * * *",  # täglich 07:00
        "action": "briefing",
        "params": {"type": "morning"},
        "channel": "all",
        "conditions": {},
        "last_run": "",
        "run_count": 0,
    },
    {
        "id": "evening_check",
        "name": "Abend-Check",
        "enabled": False,
        "cron": "0 22 * * *",  # täglich 22:00
        "action": "briefing",
        "params": {"type": "evening"},
        "channel": "all",
        "conditions": {},
        "last_run": "",
        "run_count": 0,
    },
    {
        "id": "weekly_report",
        "name": "Wochenbericht",
        "enabled": False,
        "cron": "0 8 * * 1",  # Montags 08:00
        "action": "briefing",
        "params": {"type": "weekly"},
        "channel": "all",
        "conditions": {},
        "last_run": "",
        "run_count": 0,
    },
    {
        "id": "temp_check",
        "name": "Temperatur-Check",
        "enabled": False,
        "cron": "*/30 * * * *",  # alle 30 Minuten
        "action": "agent_prompt",
        "params": {
            "prompt": (
                "Prüfe die CPU-Temperatur des Pi. "
                "Falls sie über 80°C liegt, sende eine Warnung. "
                "Falls alles normal ist, schweige (keine Nachricht senden)."
            ),
            "silent_on_ok": True,
        },
        "channel": "all",
        "conditions": {},
        "last_run": "",
        "run_count": 0,
    },
    {
        "id": "network_check",
        "name": "Netzwerk-Überwachung",
        "enabled": False,
        "cron": "*/15 * * * *",  # alle 15 Minuten
        "action": "agent_prompt",
        "params": {
            "prompt": (
                "Prüfe das Netzwerk auf neue Geräte (check_new_devices). "
                "Falls neue Geräte gefunden wurden, liste sie auf und melde sie. "
                "Falls keine neuen Geräte da sind, schweige."
            ),
            "silent_on_ok": True,
        },
        "channel": "all",
        "conditions": {},
        "last_run": "",
        "run_count": 0,
    },
]


# ── Routinen-Registry ─────────────────────────────────────────────


class RoutineRegistry:
    def __init__(self, path: Path):
        self._path = path
        self._routines: dict[str, Routine] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._routines = {
                    d["id"]: Routine.from_dict(d) for d in data if "id" in d
                }
                log.info("Routinen geladen: %d", len(self._routines))
                return
            except Exception as e:
                log.warning("Routinen-Datei fehlerhaft: %s", e)

        # Erste Einrichtung: Default-Routinen anlegen
        for d in DEFAULT_ROUTINES:
            r = Routine.from_dict(d)
            self._routines[r.id] = r
        self._save()
        log.info("Standard-Routinen angelegt: %d", len(self._routines))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        from piclaw.fileutils import safe_write_json

        safe_write_json(
            self._path, [r.to_dict() for r in self._routines.values()], label="routines"
        )

    def all(self) -> list[Routine]:
        return list(self._routines.values())

    def enabled(self) -> list[Routine]:
        return [r for r in self._routines.values() if r.enabled]

    def get(self, id_or_name: str) -> Routine | None:
        if id_or_name in self._routines:
            return self._routines[id_or_name]
        for r in self._routines.values():
            if r.name.lower() == id_or_name.lower():
                return r
        return None

    def add(self, routine: Routine) -> None:
        self._routines[routine.id] = routine
        self._save()

    def update(self, routine: Routine) -> None:
        self._routines[routine.id] = routine
        self._save()

    def remove(self, id_or_name: str) -> bool:
        r = self.get(id_or_name)
        if r and r.id not in {d["id"] for d in DEFAULT_ROUTINES}:
            del self._routines[r.id]
            self._save()
            return True
        return False

    def enable(self, id_or_name: str) -> bool:
        r = self.get(id_or_name)
        if r:
            r.enabled = True
            self._save()
            return True
        return False

    def disable(self, id_or_name: str) -> bool:
        r = self.get(id_or_name)
        if r:
            r.enabled = False
            self._save()
            return True
        return False

    def mark_ran(self, routine_id: str) -> None:
        r = self._routines.get(routine_id)
        if r:
            r.last_run = datetime.now().isoformat()
            r.run_count += 1
            self._save()

    def create_custom(
        self,
        name: str,
        cron: str,
        action: str,
        params: dict,
        channel: str = "all",
    ) -> Routine:
        r = Routine(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            cron=cron,
            action=action,
            params=params,
            channel=channel,
        )
        self.add(r)
        return r


# ── Agent-Tools für Routinen ──────────────────────────────────────

from piclaw.llm.base import ToolDefinition

TOOL_DEFS = [
    ToolDefinition(
        name="routine_list",
        description=(
            "Zeigt alle konfigurierten Routinen – automatische Aufgaben die PiClaw "
            "zu festgelegten Zeiten ausführt (Morgen-Briefing, Abend-Check, etc.)."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="routine_enable",
        description="Aktiviert eine Routine. Nutze dies wenn jemand sagt 'aktiviere das Morgen-Briefing'.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name oder ID der Routine"}
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="routine_disable",
        description="Deaktiviert eine Routine.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name oder ID der Routine"}
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="routine_create",
        description=(
            "Erstellt eine neue benutzerdefinierte Routine. "
            "Beispiele: 'Erinnere mich jeden Freitag um 17 Uhr die Pflanzen zu gießen', "
            "'Prüfe jeden Morgen um 6 Uhr den Wetterbericht und sende ihn mir'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name der Routine"},
                "cron": {
                    "type": "string",
                    "description": "Cron-Ausdruck, z.B. '0 7 * * *' für täglich 7 Uhr",
                },
                "action": {
                    "type": "string",
                    "description": "briefing | agent_prompt | notify | ha_scene",
                },
                "prompt": {
                    "type": "string",
                    "description": "Was der Agent tun soll (für action=agent_prompt)",
                },
                "message": {
                    "type": "string",
                    "description": "Feste Nachricht (für action=notify)",
                },
                "channel": {
                    "type": "string",
                    "description": "Empfänger: all | telegram | discord | whatsapp",
                    "default": "all",
                },
            },
            "required": ["name", "cron", "action"],
        },
    ),
    ToolDefinition(
        name="routine_run_now",
        description="Führt eine Routine sofort aus (unabhängig vom Zeitplan). Nützlich zum Testen.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name oder ID der Routine"}
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="briefing_now",
        description=(
            "Erstellt sofort ein Briefing und sendet es. "
            "Typen: morning (Morgen), evening (Abend), weekly (Woche), status (Kurzstatus)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "morning | evening | weekly | status",
                    "default": "status",
                }
            },
        },
    ),
]


def build_handlers(registry: RoutineRegistry, runner: ProactiveRunner) -> dict:
    """Baut die Tool-Handler für den Agent."""

    async def routine_list(**_) -> str:
        routines = registry.all()
        if not routines:
            return "Keine Routinen definiert."
        lines = ["Routinen:\n"]
        for r in routines:
            lines.append(f"  {r.describe()}")
            if r.params:
                for k, v in r.params.items():
                    if k != "silent_on_ok":
                        lines.append(f"    {k}: {str(v)[:60]}")
        return "\n".join(lines)

    async def routine_enable(name: str, **_) -> str:
        if registry.enable(name):
            r = registry.get(name)
            return f"✓ Routine '{r.name}' aktiviert. Nächster Lauf: {r.cron}"
        return f"Routine '{name}' nicht gefunden."

    async def routine_disable(name: str, **_) -> str:
        if registry.disable(name):
            return f"✓ Routine '{name}' deaktiviert."
        return f"Routine '{name}' nicht gefunden."

    async def routine_create(
        name: str,
        cron: str,
        action: str,
        prompt: str = "",
        message: str = "",
        channel: str = "all",
        **_,
    ) -> str:
        params: dict[str, Any] = {}
        if action == "agent_prompt":
            if not prompt:
                return "Für action=agent_prompt muss ein 'prompt' angegeben werden."
            params["prompt"] = prompt
        elif action == "notify":
            if not message:
                return "Für action=notify muss eine 'message' angegeben werden."
            params["message"] = message
        elif action == "briefing":
            params["type"] = "status"

        r = registry.create_custom(name, cron, action, params, channel)
        return f"✓ Routine '{name}' erstellt (ID: {r.id}). Läuft: {cron}"

    async def routine_run_now(name: str, **_) -> str:
        r = registry.get(name)
        if not r:
            return f"Routine '{name}' nicht gefunden."
        result = await runner.execute_routine(r)
        return f"✓ Routine '{r.name}' ausgeführt:\n{result[:200]}"

    async def briefing_now(briefing_type: str = "status", **_) -> str:
        from piclaw.briefing import generate_briefing

        msg = await generate_briefing(briefing_type, runner.cfg, runner.llm)
        if runner.hub:
            await runner.hub.send_all(msg)
            return f"Briefing gesendet:\n{msg[:300]}"
        return msg

    return {
        "routine_list": routine_list,
        "routine_enable": routine_enable,
        "routine_disable": routine_disable,
        "routine_create": routine_create,
        "routine_run_now": routine_run_now,
        "briefing_now": briefing_now,
    }

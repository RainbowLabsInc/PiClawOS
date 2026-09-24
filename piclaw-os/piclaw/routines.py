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
import os
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
    action: str  # "briefing" | "ha_scene" | "agent_prompt" | "notify" | "direct_check"
    params: dict  # action-specific params
    channel: str = "all"  # "all" | "telegram" | "discord" | "whatsapp"
    conditions: dict = field(default_factory=dict)  # optional conditions
    last_run: str = ""
    run_count: int = 0
    # Multi-User: None = System-/geteilte Routine (z.B. temp_check),
    # sonst Owner-User-ID. Filterung via RoutineRegistry.enabled(user_id=...).
    owner_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Routine:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def describe(self) -> str:
        status = "✓" if self.enabled else "✗"
        last = f"  (zuletzt: {self.last_run[:16]})" if self.last_run else ""
        return f"[{status}] {self.name}  [{self.cron}]  → {self.action}{last}"

    def visible_to(self, user_id: str | None) -> bool:
        """True wenn der User die Routine sehen darf.
        - System-Routinen (owner_id=None) sind global sichtbar (read-only).
        - Aufruf mit user_id=None (Scheduler/Admin) sieht alle Routinen.
        - Sonst nur eigene + System.
        """
        if user_id is None:
            return True
        if self.owner_id is None:
            return True
        return self.owner_id == user_id

    @property
    def is_system(self) -> bool:
        return self.owner_id is None


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
        "enabled": False,  # Deaktiviert: _threshold_loop in proactive.py übernimmt das bereits tokenlos
        "cron": "*/30 * * * *",  # alle 30 Minuten
        "action": "direct_check",  # Kein LLM – direkte vcgencmd-Abfrage
        "params": {
            "check_type": "cpu_temp",
            "threshold": 80,  # °C
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
        "action": "direct_check",  # Kein LLM – direkte nmap-Abfrage
        "params": {
            "check_type": "new_devices",
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
        log.info("Routinen geladen: %d", len(self._routines))

    def _load(self) -> None:
        """Liest die Datei in den In-Memory-Cache (ohne Lock – nur Read).

        Schreibt NIE: Eine defekte Datei wird in Quarantäne verschoben
        (nie überschrieben), Defaults leben dann zunächst nur im Speicher
        und werden mit der nächsten Mutation persistiert.
        """
        if not self._path.exists():
            self._routines = {
                r.id: r for r in (Routine.from_dict(d) for d in DEFAULT_ROUTINES)
            }
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._routines = {
                d["id"]: Routine.from_dict(d) for d in data if "id" in d
            }
        except Exception as e:
            quarantine = self._path.with_name(
                self._path.name + datetime.now().strftime(".corrupt-%Y%m%d-%H%M%S")
            )
            try:
                os.replace(self._path, quarantine)
                log.error(
                    "Routinen-Datei fehlerhaft (%s) – Original nach '%s' "
                    "verschoben, Standard-Routinen aktiv", e, quarantine.name,
                )
            except OSError as move_err:
                log.error(
                    "Routinen-Datei fehlerhaft (%s), Quarantäne fehlgeschlagen "
                    "(%s) – Standard-Routinen nur im Speicher, Datei bleibt "
                    "unangetastet", e, move_err,
                )
            self._routines = {
                r.id: r for r in (Routine.from_dict(d) for d in DEFAULT_ROUTINES)
            }

    def _atomic_modify(self, mutate) -> bool:
        """Read-Merge-Write unter File-Lock (Muster: ReminderStore).

        `mutate(routines_dict)` arbeitet auf dem frisch von Platte gelesenen
        Stand und gibt True zurück, wenn geschrieben werden soll. So können
        parallele Writer (API-Routine-Tools ↔ Daemon mark_ran) einander
        keine Einträge mehr verlieren – der alte Code schrieb den ggf.
        veralteten In-Memory-Stand komplett zurück.
        """
        from piclaw.fileutils import safe_write_json, with_file_lock

        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with with_file_lock(self._path):
                self._load()
                changed = bool(mutate(self._routines))
                if changed:
                    safe_write_json(
                        self._path,
                        [r.to_dict() for r in self._routines.values()],
                        label="routines",
                    )
                return changed
        except TimeoutError as e:
            log.error("Routines registry: %s", e)
            return False

    @staticmethod
    def _resolve(routines: dict[str, Routine], id_or_name: str) -> Routine | None:
        r = routines.get(id_or_name)
        if r is None:
            for cand in routines.values():
                if cand.name.lower() == id_or_name.lower():
                    return cand
        return r

    def all(self, user_id: str | None = None) -> list[Routine]:
        """Alle Routinen. Mit user_id: nur eigene + System-Routinen."""
        return [r for r in self._routines.values() if r.visible_to(user_id)]

    def enabled(self, user_id: str | None = None) -> list[Routine]:
        """Alle aktivierten Routinen. Mit user_id: nur eigene + System-Routinen.
        Scheduler ruft typischerweise mit user_id=None auf (sieht alle Owner)
        und nutzt routine.owner_id für den Kontext-Wechsel beim Trigger."""
        return [r for r in self._routines.values()
                if r.enabled and r.visible_to(user_id)]

    def get(self, id_or_name: str, user_id: str | None = None) -> Routine | None:
        """Routine per ID oder Name suchen. Wenn user_id gesetzt, nur eigene + System."""
        r = self._routines.get(id_or_name)
        if r is None:
            for cand in self._routines.values():
                if cand.name.lower() == id_or_name.lower():
                    r = cand
                    break
        if r is None or not r.visible_to(user_id):
            return None
        return r

    def add(self, routine: Routine) -> None:
        def _mut(d: dict[str, Routine]) -> bool:
            d[routine.id] = routine
            return True

        self._atomic_modify(_mut)

    def update(self, routine: Routine) -> None:
        self.add(routine)

    def remove(self, id_or_name: str) -> bool:
        default_ids = {d["id"] for d in DEFAULT_ROUTINES}

        def _mut(d: dict[str, Routine]) -> bool:
            r = self._resolve(d, id_or_name)
            if r and r.id not in default_ids:
                del d[r.id]
                return True
            return False

        return self._atomic_modify(_mut)

    def _set_enabled(self, id_or_name: str, enabled: bool) -> bool:
        def _mut(d: dict[str, Routine]) -> bool:
            r = self._resolve(d, id_or_name)
            if r:
                r.enabled = enabled
                return True
            return False

        return self._atomic_modify(_mut)

    def enable(self, id_or_name: str) -> bool:
        return self._set_enabled(id_or_name, True)

    def disable(self, id_or_name: str) -> bool:
        return self._set_enabled(id_or_name, False)

    def mark_ran(self, routine_id: str) -> None:
        def _mut(d: dict[str, Routine]) -> bool:
            r = d.get(routine_id)
            if r is None:
                return False  # parallel gelöscht – nicht wiederbeleben
            r.last_run = datetime.now().isoformat()
            r.run_count += 1
            return True

        self._atomic_modify(_mut)

    def create_custom(
        self,
        name: str,
        cron: str,
        action: str,
        params: dict,
        channel: str = "all",
        owner_id: str | None = None,
    ) -> Routine:
        r = Routine(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            cron=cron,
            action=action,
            params=params,
            channel=channel,
            owner_id=owner_id,
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
                    "description": "briefing | agent_prompt | notify | ha_scene | direct_check",
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
    """Baut die Tool-Handler für den Agent.
    Multi-User: liest user_id aus agent_context.ContextVar — Tools filtern + setzen
    owner_id beim Anlegen automatisch.
    """
    from piclaw.agent_context import get_current_user_id

    async def routine_list(**_) -> str:
        user_id = get_current_user_id()
        routines = registry.all(user_id)
        if not routines:
            return "Keine Routinen definiert."
        lines = ["Routinen:\n"]
        for r in routines:
            scope = "[system]" if r.is_system else ""
            lines.append(f"  {r.describe()} {scope}".rstrip())
            if r.params:
                for k, v in r.params.items():
                    if k != "silent_on_ok":
                        lines.append(f"    {k}: {str(v)[:60]}")
        return "\n".join(lines)

    async def routine_enable(name: str, **_) -> str:
        user_id = get_current_user_id()
        r = registry.get(name, user_id)
        if r is None:
            return f"Routine '{name}' nicht gefunden."
        if r.is_system and user_id is not None:
            return f"Routine '{r.name}' ist eine System-Routine und kann nicht pro User aktiviert werden."
        registry.enable(r.id)
        return f"✓ Routine '{r.name}' aktiviert. Nächster Lauf: {r.cron}"

    async def routine_disable(name: str, **_) -> str:
        user_id = get_current_user_id()
        r = registry.get(name, user_id)
        if r is None:
            return f"Routine '{name}' nicht gefunden."
        if r.is_system and user_id is not None:
            return f"Routine '{r.name}' ist eine System-Routine und kann nicht pro User deaktiviert werden."
        registry.disable(r.id)
        return f"✓ Routine '{r.name}' deaktiviert."

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

        owner_id = get_current_user_id()  # User-Kontext → eigene Routine
        r = registry.create_custom(name, cron, action, params, channel, owner_id=owner_id)
        return f"✓ Routine '{name}' erstellt (ID: {r.id}). Läuft: {cron}"

    async def routine_run_now(name: str, **_) -> str:
        r = registry.get(name)
        if not r:
            return f"Routine '{name}' nicht gefunden."
        result = await runner.execute_routine(r)
        return f"✓ Routine '{r.name}' ausgeführt:\n{result[:200]}"

    # Der Parameter MUSS "type" heißen: der Agent ruft Handler mit
    # handler(**call.arguments) auf, und das Tool-Schema oben definiert die
    # Property "type". Ein anders benannter Parameter (früher: briefing_type)
    # fiel still in **_ – jedes "briefing_now type=morning" lieferte nur das
    # Status-Briefing.
    async def briefing_now(type: str = "status", **_) -> str:  # noqa: A002
        from piclaw.briefing import generate_briefing

        msg = await generate_briefing(type or "status", runner.cfg, runner.llm)
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

"""
PiClaw OS – Reminder Tool
=========================

Einmalige oder wiederkehrende Reminder, die der Nutzer per Telegram (oder
einem anderen Messaging-Kanal) anlegt:

    "erinnere mich morgen 17 Uhr an Milch"
        → reminder_create(text="Milch", when="2026-05-24T17:00:00",
                          channel="telegram")

Persistenz: /etc/piclaw/reminders.json  (bzw. ~/.piclaw/reminders.json im
Dev-Modus – siehe piclaw.config.CONFIG_DIR).

Der ReminderRunner läuft als Background-Task vom Daemon und prüft alle 30s,
ob ein Eintrag fällig ist; bei Treffer wird via MessagingHub.send_to() die
Nachricht zugestellt. One-Shot-Einträge werden danach gelöscht, wiederkehrende
auf den nächsten Cron-Termin gerollt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import TYPE_CHECKING

from piclaw.config import REMINDERS_DB
from piclaw.llm.base import ToolDefinition

if TYPE_CHECKING:
    from piclaw.messaging.hub import MessagingHub

log = logging.getLogger("piclaw.reminders")


# ── Datenmodell ───────────────────────────────────────────────────


@dataclass
class Reminder:
    id: str
    text: str
    due_at: str               # ISO-Datetime, lokale Zeitzone
    recurrence: str | None    # None = One-Shot; "daily" | "weekly" | Cron-String
    channel: str              # "telegram" | "discord" | "whatsapp" | "all"
    created_at: str
    fired_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Reminder:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Persistenz ────────────────────────────────────────────────────


_RECURRENCE_TO_CRON = {
    "daily":   "{m} {h} * * *",
    "weekly":  "{m} {h} * * {dow}",
    "monthly": "{m} {h} {dom} * *",
}


def _next_due(current_iso: str, recurrence: str) -> str | None:
    """Berechne den nächsten Termin nach `current_iso` für eine Recurrence.

    Akzeptiert sowohl die Kurzformen ("daily"/"weekly"/"monthly") als auch
    direkte Cron-Strings ("0 8 * * 1"). Gibt None zurück, wenn croniter
    nicht verfügbar oder das Pattern ungültig ist.
    """
    try:
        from croniter import croniter
    except ImportError:
        log.error("croniter not installed – recurring reminders disabled")
        return None

    try:
        base = datetime.fromisoformat(current_iso)
    except ValueError:
        log.warning("Invalid due_at iso '%s' – cannot compute next", current_iso)
        return None

    if recurrence in _RECURRENCE_TO_CRON:
        # Cron zählt Wochentage ab Sonntag (0=So … 6=Sa), Python ab Montag
        # (0=Mo … 6=So). base.weekday() direkt einzusetzen verschob jeden
        # wöchentlichen Reminder um einen Tag nach vorn (Mi-Reminder → Di).
        cron_dow = (base.weekday() + 1) % 7
        pattern = _RECURRENCE_TO_CRON[recurrence].format(
            m=base.minute, h=base.hour, dow=cron_dow, dom=base.day
        )
    else:
        pattern = recurrence

    try:
        return croniter(pattern, base).get_next(datetime).isoformat()
    except Exception as e:
        log.warning("Invalid cron '%s' for recurrence: %s", pattern, e)
        return None


class ReminderStore:
    """Read-modify-write Store für /etc/piclaw/reminders.json."""

    def __init__(self, path=None):
        self._path = path or REMINDERS_DB
        self._reminders: dict[str, Reminder] = {}
        self._load()

    def _load(self) -> None:
        """Liest die Datei in den In-Memory-Cache (ohne Lock – nur Read)."""
        if not self._path.exists():
            self._reminders = {}
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._reminders = {
                d["id"]: Reminder.from_dict(d) for d in data if "id" in d
            }
        except Exception as e:
            log.warning("Reminder-Datei fehlerhaft: %s", e)

    def _atomic_modify(self, mutate) -> None:
        """Read-Merge-Write unter File-Lock.

        `mutate(reminders_dict)` darf das Dict in-place verändern; danach wird
        es atomar zurückgeschrieben. So bleiben parallele Writer (API ↔ Daemon)
        konsistent – beide arbeiten auf demselben Stand zum Lock-Zeitpunkt.
        """
        from piclaw.fileutils import safe_write_json, with_file_lock

        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with with_file_lock(self._path):
                self._load()
                mutate(self._reminders)
                safe_write_json(
                    self._path,
                    [r.to_dict() for r in self._reminders.values()],
                    label="reminders",
                )
        except TimeoutError as e:
            log.error("Reminder store: %s", e)

    # ── Public API ─────────────────────────────────────────────────

    def add(
        self,
        text: str,
        due_at: str,
        recurrence: str | None = None,
        channel: str = "telegram",
    ) -> Reminder:
        r = Reminder(
            id=str(uuid.uuid4())[:8],
            text=text.strip(),
            due_at=due_at,
            recurrence=recurrence,
            channel=channel,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._atomic_modify(lambda d: d.__setitem__(r.id, r))
        return r

    def remove(self, rid: str) -> bool:
        result = {"existed": False}

        def _mutate(d):
            if rid in d:
                del d[rid]
                result["existed"] = True

        self._atomic_modify(_mutate)
        return result["existed"]

    def find(self, id_or_substring: str) -> Reminder | None:
        if id_or_substring in self._reminders:
            return self._reminders[id_or_substring]
        needle = id_or_substring.lower()
        for r in self._reminders.values():
            if needle in r.text.lower():
                return r
        return None

    def all(self) -> list[Reminder]:
        return sorted(self._reminders.values(), key=lambda r: r.due_at)

    def due_now(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now()
        out: list[Reminder] = []
        for r in self._reminders.values():
            try:
                if datetime.fromisoformat(r.due_at) <= now:
                    out.append(r)
            except ValueError:
                log.warning("Reminder %s hat ungültiges due_at: %r", r.id, r.due_at)
        return out

    def mark_fired(self, r: Reminder) -> None:
        """Nach Versand aufrufen: rollt recurring vor, löscht One-Shot."""
        if not r.recurrence:
            self.remove(r.id)
            return
        next_iso = _next_due(r.due_at, r.recurrence)
        if not next_iso:
            log.warning("Recurrence '%s' ungültig – Reminder %s wird gelöscht", r.recurrence, r.id)
            self.remove(r.id)
            return

        def _mutate(d):
            existing = d.get(r.id)
            if existing is None:
                return  # zwischenzeitlich von außen entfernt
            existing.due_at = next_iso
            existing.fired_count += 1

        self._atomic_modify(_mutate)


# ── Background Runner ─────────────────────────────────────────────


class ReminderRunner:
    """Polls the store every `interval_sec` seconds and fires due reminders."""

    def __init__(self, store: ReminderStore, hub: MessagingHub, interval_sec: int = 30):
        self.store = store
        self.hub = hub
        self.interval = interval_sec

    async def start(self, stop: asyncio.Event | None = None) -> None:
        log.info("ReminderRunner gestartet (poll alle %ds)", self.interval)
        while True:
            if stop and stop.is_set():
                return
            try:
                # Datei jedes Mal neu lesen – API und Daemon teilen sich
                # reminders.json, also kann ein Eintrag von außen kommen.
                self.store._load()
                for r in self.store.due_now():
                    await self._fire(r)
            except Exception as e:
                log.exception("ReminderRunner loop error: %s", e)
            try:
                if stop:
                    await asyncio.wait_for(stop.wait(), timeout=self.interval)
                    return  # stop wurde gesetzt
                else:
                    await asyncio.sleep(self.interval)
            except TimeoutError:
                pass  # normaler Tick

    async def _fire(self, r: Reminder) -> None:
        msg = f"🔔 Reminder: {r.text}"
        try:
            if r.channel == "all":
                await self.hub.send_all(msg)
            else:
                await self.hub.send_to(r.channel, msg)
            log.info("Reminder gefeuert: %s (%s)", r.id, r.text[:40])
        except Exception as e:
            log.error("Reminder %s konnte nicht gesendet werden: %s", r.id, e)
            return  # nicht als gefeuert markieren → retry beim nächsten Tick
        self.store.mark_fired(r)


# ── Agent-Tools ───────────────────────────────────────────────────


TOOL_DEFS = [
    ToolDefinition(
        name="reminder_create",
        description=(
            "Legt einen Reminder an. Nutze dies wenn der Nutzer sagt 'erinnere "
            "mich an X' oder 'mach mir eine Notiz für…'. "
            "Berechne 'when' als ISO-Datetime relativ zur aktuellen Zeit. "
            "WICHTIG: Fehlt die Uhrzeit, frage explizit nach, bevor du das Tool "
            "aufrufst – rate keine Default-Zeit. "
            "Für wiederkehrende Reminder ('jeden Montag um 8', 'täglich 21 Uhr "
            "Zähneputzen') setze 'recurrence' auf 'daily', 'weekly', 'monthly' "
            "oder einen Cron-Ausdruck."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Worum geht es? Kurz und konkret, z.B. 'Milch kaufen'.",
                },
                "when": {
                    "type": "string",
                    "description": "ISO-Datetime des nächsten Fälligkeitszeitpunkts, z.B. '2026-05-24T17:00:00'.",
                },
                "recurrence": {
                    "type": "string",
                    "description": "Optional: 'daily' | 'weekly' | 'monthly' | Cron-Ausdruck. Leer lassen für One-Shot.",
                },
                "channel": {
                    "type": "string",
                    "description": "Empfangs-Kanal: 'telegram' (default) | 'discord' | 'whatsapp' | 'all'.",
                    "default": "telegram",
                },
            },
            "required": ["text", "when"],
        },
    ),
    ToolDefinition(
        name="reminder_list",
        description="Listet alle offenen Reminder, sortiert nach Fälligkeit.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="reminder_cancel",
        description=(
            "Löscht einen Reminder per ID oder per Substring des Texts "
            "(z.B. 'Milch' findet 'Milch kaufen')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "id_or_text": {
                    "type": "string",
                    "description": "Reminder-ID oder ein Substring des Reminder-Texts.",
                },
            },
            "required": ["id_or_text"],
        },
    ),
]


def _fmt(r: Reminder) -> str:
    rec = f" 🔁 {r.recurrence}" if r.recurrence else ""
    due = r.due_at.replace("T", " ")[:16]
    return f"  [{r.id}] {due} – {r.text}{rec}  →{r.channel}"


def build_handlers(store: ReminderStore) -> dict:
    async def reminder_create(
        text: str,
        when: str,
        recurrence: str = "",
        channel: str = "telegram",
        **_,
    ) -> str:
        try:
            due_dt = datetime.fromisoformat(when)
        except ValueError:
            return (
                f"Ungültiges 'when'-Format: {when!r}. Erwartet ISO-Datetime "
                f"wie '2026-05-24T17:00:00'."
            )
        if due_dt <= datetime.now() and not recurrence:
            return f"Der Zeitpunkt {when} liegt in der Vergangenheit – Reminder nicht angelegt."
        rec = recurrence.strip() or None
        r = store.add(text=text, due_at=when, recurrence=rec, channel=channel)
        rec_label = f" (wiederkehrend: {rec})" if rec else ""
        return (
            f"✓ Reminder angelegt (ID {r.id}): '{r.text}'\n"
            f"  Nächste Fälligkeit: {when}{rec_label}, Kanal: {channel}"
        )

    async def reminder_list(**_) -> str:
        items = store.all()
        if not items:
            return "Keine offenen Reminder."
        return "Offene Reminder:\n" + "\n".join(_fmt(r) for r in items)

    async def reminder_cancel(id_or_text: str, **_) -> str:
        r = store.find(id_or_text)
        if not r:
            return f"Kein Reminder gefunden für '{id_or_text}'."
        store.remove(r.id)
        return f"✓ Reminder [{r.id}] '{r.text}' gelöscht."

    return {
        "reminder_create": reminder_create,
        "reminder_list": reminder_list,
        "reminder_cancel": reminder_cancel,
    }

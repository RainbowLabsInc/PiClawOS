"""
PiClaw OS – Agent Context
=========================
Async-sichere ContextVar für den aktiven User während eines Agent-Runs.

Warum?
  Tool-Handler werden vom Agent als `handler(**call.arguments)` aufgerufen
  — die Argumente kommen vom LLM, das nichts vom User-Kontext weiß. Wir
  müssen `user_id` über einen Side-Channel injizieren, ohne jede einzelne
  Tool-Signatur zu ändern (es sind 30+).

Wie?
  asyncio.contextvars.ContextVar isoliert per Task automatisch — wenn
  zwei User parallel Tasks laufen lassen, sieht jeder Task seinen eigenen
  user_id. Vor jeder Run/Tool-Ausführung setzt der Agent die Variable;
  Tools lesen sie mit `current_user.get()`.

Default = None: bedeutet „kein User-Kontext" → Tools verhalten sich wie
im Single-User-Mode (alle Daten sichtbar/schreibbar). Das hält
existierende Aufrufer & Tests grün.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager

current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "piclaw_current_user", default=None
)


@contextmanager
def user_scope(user_id: str | None):
    """
    Setzt current_user für die Dauer des with-Blocks. Auch im Async-Code
    sicher — ContextVar-Tokens werden korrekt zurückgesetzt.
    """
    token = current_user.set(user_id)
    try:
        yield
    finally:
        current_user.reset(token)


def get_current_user_id() -> str | None:
    """Bequemer Lese-Wrapper."""
    return current_user.get()

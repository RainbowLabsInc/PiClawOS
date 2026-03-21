"""
PiClaw OS – Task Utilities
===========================
create_background_task() verhindert das stille GC-Killen von asyncio Tasks.

Python's asyncio.create_task() gibt eine schwache Referenz zurück.
Wird das Ergebnis nicht gespeichert, kann der GC den Task mitten in der
Ausführung vernichten – kein Fehler, kein Log, Task einfach weg.

Lösung: _TASKS Set hält starke Referenzen, räumt nach done() automatisch auf.
"""
import asyncio
import logging
from typing import Coroutine

log = logging.getLogger("piclaw.tasks")

# Globales Set hält starke Referenzen auf alle laufenden Background-Tasks
_TASKS: set[asyncio.Task] = set()


def create_background_task(
    coro: Coroutine,
    *,
    name: str | None = None,
    log_errors: bool = True,
) -> asyncio.Task:
    """
    Erstellt einen asyncio-Task mit stabiler Referenz (kein GC-Kill).
    Fehler werden geloggt statt still geschluckt.

    Verwendung:
        from piclaw.taskutils import create_background_task
        create_background_task(my_coroutine(), name="my-task")
    """
    task = asyncio.create_task(coro, name=name)
    _TASKS.add(task)

    def _done(t: asyncio.Task):
        _TASKS.discard(t)
        if log_errors and not t.cancelled():
            exc = t.exception()
            if exc:
                tname = t.get_name() or "background-task"
                log.error("Background task '%s' failed: %s", tname, exc, exc_info=exc)

    task.add_done_callback(_done)
    return task


def active_tasks() -> list[str]:
    """Gibt Namen aller aktiven Background-Tasks zurück (für Doctor/Status)."""
    return [t.get_name() or "unnamed" for t in _TASKS if not t.done()]


async def cancel_all() -> int:
    """Bricht alle Background-Tasks ab. Gibt Anzahl zurück."""
    cancelled = 0
    for task in list(_TASKS):
        if not task.done():
            task.cancel()
            cancelled += 1
    if _TASKS:
        await asyncio.gather(*_TASKS, return_exceptions=True)
    _TASKS.clear()
    return cancelled

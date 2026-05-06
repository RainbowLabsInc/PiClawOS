"""
PiClaw OS – IPC (Inter-Process Communication)
Einfaches File-basiertes IPC zwischen piclaw-api und piclaw-agent.

Protokolle:
  run_now:  API schreibt  /etc/piclaw/ipc/run_now_<agent_id>.trigger
            Daemon führt den Agent sofort einmalig aus.

  remove:   API schreibt  /etc/piclaw/ipc/remove_<agent_id>.trigger
            Daemon stoppt den Schedule-Loop UND entfernt aus seiner
            Registry-Memory. Notwendig weil API und Daemon getrennte
            Prozesse mit eigenem Memory-Snapshot der Registry sind —
            ohne diesen Trigger feuert der Daemon-Loop weiter und sein
            nächster mark_run schreibt die alte Memory zurück.

Gewählt weil:
  - Kein zusätzlicher Service nötig
  - Atomares Schreiben/Lesen via rename
  - Einfach zu debuggen (ls /etc/piclaw/ipc/)
"""

import asyncio
import logging

from piclaw.config import CONFIG_DIR
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.ipc")

IPC_DIR = CONFIG_DIR / "ipc"
TRIGGER_SUFFIX = ".trigger"
POLL_INTERVAL = 1.0  # Sekunden


def write_run_now(agent_id: str) -> bool:
    """API: Schreibt einen run_now Trigger für den Daemon."""
    try:
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        trigger = IPC_DIR / f"run_now_{agent_id}{TRIGGER_SUFFIX}"
        trigger.write_text(agent_id)
        log.debug("IPC: run_now trigger geschrieben für %s", agent_id)
        return True
    except Exception as e:
        log.warning("IPC: Fehler beim Schreiben des Triggers: %s", e)
        return False


def write_remove(agent_id: str) -> bool:
    """API: Schreibt einen remove Trigger für den Daemon.

    Der Daemon stoppt den Schedule-Loop und entfernt den Agent aus
    seiner Registry-Memory. Ohne diesen Trigger würde der Daemon den
    Agent weiter feuern (loop hält die SubAgentDef-Referenz) und sein
    nächster mark_run würde die alte Memory zurück auf Disk schreiben.
    """
    try:
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        trigger = IPC_DIR / f"remove_{agent_id}{TRIGGER_SUFFIX}"
        trigger.write_text(agent_id)
        log.debug("IPC: remove trigger geschrieben für %s", agent_id)
        return True
    except Exception as e:
        log.warning("IPC: Fehler beim Schreiben des remove-Triggers: %s", e)
        return False


async def poll_triggers(sa_runner) -> None:
    """
    Daemon: Pollt IPC-Verzeichnis auf run_now/remove Trigger.
    Läuft als Background-Task im Daemon.
    """
    log.info("IPC: Trigger-Polling gestartet (%s)", IPC_DIR)
    while True:
        try:
            if IPC_DIR.exists():
                # ── run_now Trigger ────────────────────────────────────
                for trigger in list(IPC_DIR.glob(f"run_now_*{TRIGGER_SUFFIX}")):
                    try:
                        agent_id = trigger.read_text().strip()
                        trigger.unlink()  # Sofort löschen damit kein Doppel-Trigger
                        agent = sa_runner.registry.get(agent_id)
                        if agent:
                            log.info("IPC: run_now für '%s' empfangen", agent.name)
                            create_background_task(
                                sa_runner._execute(agent),
                                name=f"subagent-ipc-{agent_id}",
                            )
                        else:
                            log.warning("IPC: Agent '%s' nicht gefunden", agent_id)
                    except Exception as e:
                        log.warning("IPC: Fehler beim Verarbeiten von %s: %s", trigger, e)

                # ── remove Trigger ─────────────────────────────────────
                for trigger in list(IPC_DIR.glob(f"remove_*{TRIGGER_SUFFIX}")):
                    try:
                        agent_id = trigger.read_text().strip()
                        trigger.unlink()
                        agent = sa_runner.registry.get(agent_id)
                        agent_label = agent.name if agent else agent_id
                        # Schedule-Loop stoppen (cancelt _run_loop Task)
                        await sa_runner.stop_agent(agent_id)
                        # Aus Daemon-Memory entfernen + Tombstone setzen
                        # damit nächster mark_run-Save den Agent nicht
                        # via stale memory wiederherstellt.
                        sa_runner.registry.remove(agent_id)
                        log.info("IPC: remove für '%s' verarbeitet", agent_label)
                    except Exception as e:
                        log.warning("IPC: Fehler beim Verarbeiten von %s: %s", trigger, e)
        except Exception as e:
            log.warning("IPC: Poll-Fehler: %s", e)
        await asyncio.sleep(POLL_INTERVAL)

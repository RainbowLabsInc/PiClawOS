"""
PiClaw OS – IPC (Inter-Process Communication)
Einfaches File-basiertes IPC zwischen piclaw-api und piclaw-agent.

Protokoll:
  API schreibt:  /etc/piclaw/ipc/run_now_<agent_id>.trigger
  Daemon liest:  alle *.trigger Dateien, führt Agent aus, löscht Datei

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


async def poll_triggers(sa_runner) -> None:
    """
    Daemon: Pollt IPC-Verzeichnis auf run_now Trigger.
    Läuft als Background-Task im Daemon.
    """
    log.info("IPC: Trigger-Polling gestartet (%s)", IPC_DIR)
    while True:
        try:
            if IPC_DIR.exists():
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
        except Exception as e:
            log.warning("IPC: Poll-Fehler: %s", e)
        await asyncio.sleep(POLL_INTERVAL)

#!/usr/bin/env python3
"""
PiClaw OS – QMD stündlicher Update-Job
Wird via systemd timer aufgerufen, nicht direkt vom Agent.
Läuft mit niedrigster Priorität (nice 19) um den Pi nicht zu blockieren.
"""
import asyncio
import logging
import os
import sys

# Nice-Priorität setzen
os.nice(19)

log = logging.getLogger("piclaw.qmd_update")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [QMD-UPDATE] %(message)s")


async def main():
    from piclaw.memory.qmd import QMDBackend
    qmd = QMDBackend()

    if not qmd.is_available():
        log.info("QMD nicht verfügbar – übersprungen")
        return

    log.info("QMD stündliches Update gestartet")
    try:
        await qmd.setup_collections()
        log.info("Collections aktualisiert")
        await qmd.update()
        log.info("Index aktualisiert")
    except Exception as e:
        log.error("QMD update fehlgeschlagen: %s", e)
        sys.exit(1)

    log.info("QMD Update abgeschlossen")


if __name__ == "__main__":
    asyncio.run(main())

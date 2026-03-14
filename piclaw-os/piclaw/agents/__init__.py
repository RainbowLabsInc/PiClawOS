"""PiClaw OS – Sub-Agents package"""

import asyncio
import logging
from pathlib import Path

from piclaw.config import CONFIG_DIR

HEARTBEAT_FILE = CONFIG_DIR / "ipc" / "agent.heartbeat"
log = logging.getLogger("piclaw.agents")


async def heartbeat_loop():
    """Write a heartbeat file every 30s so Watchdog can detect mainagent crashes."""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            HEARTBEAT_FILE.write_text(str(asyncio.get_running_loop().time()))
        except Exception as e:
            log.error("Heartbeat write failed: %s", e)
        await asyncio.sleep(30)


__all__ = ["heartbeat_loop"]

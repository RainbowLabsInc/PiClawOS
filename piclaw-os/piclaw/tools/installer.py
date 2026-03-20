"""
PiClaw OS – Installer & User Confirmation Tools
Allows sub-agents to request confirmation from the user via IPC.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.tools.installer")

def get_ipc_paths():
    ipc_dir = CONFIG_DIR / "ipc"
    return ipc_dir, ipc_dir / "install_req.json", ipc_dir / "install_res.json"

from piclaw.llm.base import ToolDefinition

TOOL_DEFS = [
    ToolDefinition(
        name="installer_confirm",
        description=(
            "Präsentiert dem Nutzer einen Installationsplan und wartet auf Bestätigung. "
            "Gibt 'YES' zurück, wenn der Nutzer zustimmt, oder 'NO' bei Ablehnung/Timeout."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Detaillierter Plan der auszuführenden Befehle und Änderungen."
                },
            },
            "required": ["plan"],
        },
    ),
]


async def installer_confirm(plan: str) -> str:
    """
    Writes a request file for the user and polls for a response file.
    Timeout: 300 seconds (5 minutes).
    """
    ipc_dir, req_file, res_file = get_ipc_paths()
    ipc_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old response if exists
    if res_file.exists():
        res_file.unlink()

    req_data = {
        "ts": time.time(),
        "plan": plan,
        "status": "pending"
    }

    try:
        req_file.write_text(json.dumps(req_data), encoding="utf-8")
        log.info("Installation request written to %s", req_file)
    except Exception as e:
        return f"Fehler beim Erstellen der Anfrage: {e}"

    # Poll for response
    timeout = 300
    start_time = time.time()

    while time.time() - start_time < timeout:
        if res_file.exists():
            try:
                res_data = json.loads(res_file.read_text(encoding="utf-8"))
                decision = res_data.get("decision", "NO").upper()
                res_file.unlink() # consume response
                if req_file.exists():
                    req_file.unlink() # cleanup request
                return decision
            except Exception as e:
                log.error("Error reading response file: %s", e)

        await asyncio.sleep(2)

    # Cleanup on timeout
    if req_file.exists():
        req_file.unlink()

    return "NO (Timeout)"


def build_handlers() -> dict:
    return {
        "installer_confirm": lambda **kw: installer_confirm(**kw),
    }

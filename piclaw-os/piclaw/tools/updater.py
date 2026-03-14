"""
PiClaw OS – Updater Tool
Self-update via pip / git pull
"""

import asyncio
import logging
from piclaw.llm.base import ToolDefinition
from piclaw.config import UpdaterConfig

log = logging.getLogger("piclaw.updater")

TOOL_DEFS = [
    ToolDefinition(
        name="system_update",
        description="Check for and apply PiClaw software updates, or update system packages.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["piclaw", "system", "check"],
                    "description": (
                        "piclaw=update PiClaw itself, "
                        "system=apt upgrade, "
                        "check=check for updates only"
                    ),
                },
            },
            "required": ["target"],
        },
    ),
]


async def _run(cmd: str, timeout: int = 120) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "[TIMEOUT] Update took too long."
    rc  = proc.returncode
    out = out.decode(errors="replace").strip()
    err = err.decode(errors="replace").strip()
    result = out + ("\n[stderr] " + err if err else "")
    return f"[exit {rc}] {result}"


async def system_update(target: str, cfg: UpdaterConfig) -> str:
    if target == "check":
        result = await _run("pip list --outdated 2>&1 | grep piclaw || echo 'PiClaw is up to date'")
        apt    = await _run("apt list --upgradable 2>/dev/null | wc -l")
        return f"PiClaw: {result}\nSystem packages upgradable: {apt.strip()}"

    elif target == "piclaw":
        log.info("Updating PiClaw via pip…")
        if cfg.repo_url and cfg.channel == "stable":
            result = await _run(
                f"pip install --upgrade git+{cfg.repo_url}.git 2>&1"
            )
        else:
            result = await _run("pip install --upgrade piclaw 2>&1")
        # Restart the service after update
        await _run("systemctl restart piclaw-agent piclaw-api 2>/dev/null || true")
        return result + "\n✅ PiClaw updated and restarted."

    elif target == "system":
        log.info("Running apt upgrade…")
        result = await _run(
            "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1",
            timeout=300,
        )
        return result

    return f"Unknown target: {target}"


def build_handlers(cfg: UpdaterConfig) -> dict:
    return {
        "system_update": lambda **kw: system_update(cfg=cfg, **kw),
    }

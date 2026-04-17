"""
PiClaw OS – Services Tool
Manage systemd services (start/stop/restart/status/enable/disable)
"""

import asyncio
from piclaw.llm.base import ToolDefinition
from piclaw.config import ServicesConfig

TOOL_DEFS = [
    ToolDefinition(
        name="service_status",
        description="Get the status of a systemd service.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Service name, e.g. 'ssh' or 'homeassistant'",
                },
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="service_control",
        description="Start, stop, restart, enable or disable a systemd service.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Service name"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "enable", "disable"],
                },
            },
            "required": ["name", "action"],
        },
    ),
    ToolDefinition(
        name="service_list",
        description="List all managed services and their current state.",
        parameters={"type": "object", "properties": {}},
    ),
]


async def _systemctl(
    args: list[str], timeout: int = 15, include_stderr: bool = True
) -> str:
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return "[TIMEOUT]"

    stdout = out.decode(errors="replace").strip()
    if include_stderr:
        stderr = err.decode(errors="replace").strip()
        return (stdout + ("\n" + stderr if stderr else "")).strip()
    return stdout


async def service_status(name: str) -> str:
    return await _systemctl(["status", name, "--no-pager", "-l"])


async def service_control(name: str, action: str, cfg: ServicesConfig) -> str:
    if name not in cfg.managed:
        return (
            f"Service '{name}' is not in the managed list. "
            f"Managed: {', '.join(cfg.managed)}"
        )
    return await _systemctl([action, name])


async def service_list(cfg: ServicesConfig) -> str:
    lines = []
    for name in cfg.managed:
        # For listing, we only care about the clean state (stdout)
        state = await _systemctl(["is-active", name], include_stderr=False)
        if not state:
            state = "inactive"
        icon = "🟢" if state == "active" else "🔴"
        lines.append(f"  {icon} {name}: {state}")
    return "Managed services:\n" + "\n".join(lines)


def build_handlers(cfg: ServicesConfig) -> dict:
    return {
        "service_status": lambda **kw: service_status(**kw),
        "service_control": lambda **kw: service_control(cfg=cfg, **kw),
        "service_list": lambda **_: service_list(cfg),
    }

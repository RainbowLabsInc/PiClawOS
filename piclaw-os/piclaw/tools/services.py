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
                "name": {"type": "string", "description": "Service name, e.g. 'ssh' or 'homeassistant'"},
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
                "name":   {"type": "string", "description": "Service name"},
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


async def _systemctl(args: str, timeout: int = 15) -> str:
    proc = await asyncio.create_subprocess_shell(
        f"systemctl {args}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "[TIMEOUT]"
    return (out.decode(errors="replace") + err.decode(errors="replace")).strip()


async def service_status(name: str) -> str:
    return await _systemctl(f"status {name} --no-pager -l")


async def service_control(name: str, action: str, cfg: ServicesConfig) -> str:
    if name not in cfg.managed:
        return (
            f"Service '{name}' is not in the managed list. "
            f"Managed: {', '.join(cfg.managed)}"
        )
    return await _systemctl(f"{action} {name}")


async def service_list(cfg: ServicesConfig) -> str:
    lines = []
    for name in cfg.managed:
        result = await _systemctl(
            f"is-active {name} 2>/dev/null || echo inactive"
        )
        state = result.strip()
        icon  = "🟢" if state == "active" else "🔴"
        lines.append(f"  {icon} {name}: {state}")
    return "Managed services:\n" + "\n".join(lines)


def build_handlers(cfg: ServicesConfig) -> dict:
    return {
        "service_status":  lambda **kw: service_status(**kw),
        "service_control": lambda **kw: service_control(cfg=cfg, **kw),
        "service_list":    lambda **_:  service_list(cfg),
    }

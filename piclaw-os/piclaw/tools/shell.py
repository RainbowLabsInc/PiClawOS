import logging

log = logging.getLogger(__name__)
"""PiClaw OS – Shell + System Info Tools"""

import asyncio
import shlex
import traceback
import psutil
from datetime import datetime

from piclaw.config import ShellConfig
from piclaw.llm.base import ToolDefinition

TOOL_DEFS = [
    ToolDefinition(
        name="shell",
        description="Execute a shell command on the Raspberry Pi and return stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
            },
            "required": ["command"],
        },
    ),
    ToolDefinition(
        name="system_info",
        description="Get Raspberry Pi hardware stats: CPU, memory, disk, temperature, uptime.",
        parameters={"type": "object", "properties": {}},
    ),
]


def _is_allowed(command: str, cfg: ShellConfig) -> tuple[bool, str]:
    for blocked in cfg.blocklist:
        if blocked.lower() in command.lower():
            return False, f"Blocked: contains '{blocked}'"
    try:
        base = shlex.split(command)[0]
    except Exception:
        return False, "Could not parse command."
    if cfg.allowlist and base not in cfg.allowlist:
        return (
            False,
            f"'{base}' not in allowlist. Allowed: {', '.join(cfg.allowlist[:8])}…",
        )
    return True, ""


async def run_shell(command: str, cfg: ShellConfig) -> str:
    if not cfg.enabled:
        return "Shell tool is disabled."
    ok, reason = _is_allowed(command, cfg)
    if not ok:
        return f"[BLOCKED] {reason}"
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cfg.working_dir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=cfg.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return f"[TIMEOUT] Exceeded {cfg.timeout}s"
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        parts = [f"[exit {proc.returncode}]"]
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr] {err}")
        return "\n".join(parts)
    except Exception:
        return f"[ERROR] {traceback.format_exc()}"


async def system_info() -> str:
    lines = []

    # CPU
    cpu_pct = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
    cpu_freq = await asyncio.to_thread(psutil.cpu_freq)
    lines.append(f"CPU Usage : {cpu_pct:.1f}%")
    if cpu_freq:
        lines.append(f"CPU Freq  : {cpu_freq.current:.0f} MHz")

    # Temperature
    from piclaw.hardware.pi_info import current_temp
    temp_c = await asyncio.to_thread(current_temp)
    if temp_c is not None:
        lines.append(f"CPU Temp  : {temp_c:.1f}°C")

    # Memory
    mem = await asyncio.to_thread(psutil.virtual_memory)
    lines.append(
        f"Memory    : {mem.used // 1_048_576} MB used / "
        f"{mem.total // 1_048_576} MB total ({mem.percent:.0f}%)"
    )

    # Disk
    disk = await asyncio.to_thread(psutil.disk_usage, "/")
    lines.append(
        f"Disk (/)  : {disk.used // 1_073_741_824:.1f} GB used / "
        f"{disk.total // 1_073_741_824:.1f} GB total ({disk.percent:.0f}%)"
    )

    # Uptime
    boot_ts = await asyncio.to_thread(psutil.boot_time)
    uptime_s = datetime.now().timestamp() - boot_ts
    h, rem = divmod(int(uptime_s), 3600)
    m, s = divmod(rem, 60)
    lines.append(f"Uptime    : {h}h {m}m {s}s")

    # Load average
    load = await asyncio.to_thread(psutil.getloadavg)
    lines.append(f"Load avg  : {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")

    return "\n".join(lines)


def build_handlers(cfg: ShellConfig) -> dict:
    return {
        "shell": lambda **kw: run_shell(cfg=cfg, **kw),
        "system_info": lambda **_: system_info(),
    }

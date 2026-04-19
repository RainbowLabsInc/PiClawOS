"""
PiClaw OS – Network Tool
WiFi and network management via nmcli (NetworkManager)
"""

import asyncio
from piclaw.llm.base import ToolDefinition

TOOL_DEFS = [
    ToolDefinition(
        name="network_status",
        description="Get current network status: IP addresses, WiFi connection, signal strength.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="wifi_scan",
        description="Scan for available WiFi networks and return SSID list with signal strength.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="wifi_connect",
        description=(
            "Connect to a WiFi network by SSID. Uses saved credentials if available. "
            "If no saved credentials exist, tell the user to run 'nmcli dev wifi connect SSID password PASS' directly on the Pi terminal."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ssid": {"type": "string", "description": "Network name (SSID)"},
            },
            "required": ["ssid"],
        },
    ),
    ToolDefinition(
        name="wifi_disconnect",
        description="Disconnect from the current WiFi network.",
        parameters={"type": "object", "properties": {}},
    ),
]


async def _run(cmd: list[str], timeout: int = 15, input_data: str = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if input_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        in_bytes = input_data.encode() if input_data is not None else None
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=in_bytes), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return "[TIMEOUT]"
    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    return (out + ("\n[stderr] " + err if err else "")).strip()


async def network_status() -> str:
    ip_info = await _run(["ip", "-brief", "addr", "show"])
    wifi_con = await _run(["nmcli", "-t", "-f", "NAME,TYPE,STATE,DEVICE", "connection", "show", "--active"])

    signal_raw = await _run(["nmcli", "-f", "IN-USE,SSID,SIGNAL,BARS", "dev", "wifi", "list"])
    # Ignore stderr and take first 5 lines
    signal_out = signal_raw.split("\n[stderr]")[0]
    signal = "\n".join(signal_out.splitlines()[:5])

    return f"=== IP Addresses ===\n{ip_info}\n\n=== Active Connections ===\n{wifi_con}\n\n=== WiFi Signal ===\n{signal}"


async def wifi_scan() -> str:
    try:
        await _run(["nmcli", "dev", "wifi", "rescan"])
    except Exception:
        pass

    result_raw = await _run(["nmcli", "-f", "IN-USE,SSID,SIGNAL,BARS,SECURITY", "dev", "wifi", "list"])
    result = result_raw.split("\n[stderr]")[0]
    return result or "No WiFi networks found."


async def wifi_connect(ssid: str, password: str = "") -> str:
    if password:
        # SECURITY: Use --ask and stdin to prevent password exposure in process lists (ps aux)
        cmd = ["nmcli", "--ask", "dev", "wifi", "connect", ssid]
        return await _run(cmd, timeout=30, input_data=password + "\n")
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    return await _run(cmd, timeout=30)


async def wifi_disconnect() -> str:
    # Find the active WiFi device
    dev_raw = await _run(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"])
    dev_out = dev_raw.split("\n[stderr]")[0]

    dev = None
    for line in dev_out.splitlines():
        if ":wifi" in line:
            dev = line.split(":")[0]
            break

    if not dev:
        return "No active WiFi device found."
    return await _run(["nmcli", "dev", "disconnect", dev.strip()])


HANDLERS = {
    "network_status": lambda **_: network_status(),
    "wifi_scan": lambda **_: wifi_scan(),
    "wifi_connect": lambda **kw: wifi_connect(**kw),
    "wifi_disconnect": lambda **_: wifi_disconnect(),
}

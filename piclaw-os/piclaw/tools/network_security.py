"""
PiClaw OS – Security Tools
Includes the Emergency Shutdown feature and other network security integrations.
"""

import asyncio
import ipaddress
import logging
from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.network_security")

_ACTIVE_TRAPS = {}

async def _run_command(*args: str, timeout: int = 10) -> str:
    """Safely runs a subprocess command and returns its output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            return f"[ERROR] Command failed: {stderr.decode().strip()}"
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        proc.kill()
        return "[ERROR] Command timed out"
    except Exception as e:
        return f"[ERROR] {str(e)}"

def _is_local_ip(ip_str: str) -> bool:
    """Checks if an IP address belongs to the local network or loopback."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False

async def whois_lookup(ip: str) -> str:
    """Performs a WHOIS lookup on an IP address."""
    output = await _run_command("whois", ip)
    if len(output) > 2900:
        output = output[:2900] + "\n...[TRUNCATED]"
    return output

async def block_ip(ip: str) -> str:
    """Blocks an IP address using iptables (DROP)."""
    res = await _run_command("sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP")
    if "[ERROR]" in res:
        return f"❌ Failed to block {ip}: {res}"
    return f"✅ SUCCESS: Blocked {ip} via iptables."

async def tarpit_ip(ip: str, port: int) -> str:
    """Deploys a tarpit on a specific IP and port using iptables DROP."""
    res = await _run_command("sudo", "iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-s", ip, "-j", "DROP")
    if "[ERROR]" in res:
        return f"❌ Failed to deploy tarpit against {ip}: {res}"
    return f"✅ SUCCESS: Offensive Tarpit deployed against {ip} on port {port}."

async def generate_abuse_report(ip: str, attack_snippet: str) -> str:
    """Generates an abuse report text."""
    return f"ABUSE REPORT\nIP: {ip}\nDetails: {attack_snippet}"

async def _handle_labyrinth(reader, writer):
    """Endless SSH labyrinth honeypot handler."""
    addr = writer.get_extra_info('peername')
    if addr and _is_local_ip(addr[0]):
        writer.close()
        await writer.wait_closed()
        return

    try:
        while True:
            writer.write(b"username@honeypot:~$ \n")
            await writer.drain()
            await asyncio.sleep(10)
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()

async def _handle_rickroll(reader, writer):
    """HTTP redirect to rickroll honeypot handler."""
    addr = writer.get_extra_info('peername')
    if addr and _is_local_ip(addr[0]):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nYou are safe here.\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return

    try:
        await reader.read(1024) # consume request
        response = b"HTTP/1.1 301 Moved Permanently\r\nLocation: https://www.youtube.com/watch?v=dQw4w9WgXcQ\r\n\r\n"
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()

async def _handle_sinkhole(reader, writer):
    """HTTP gzip bomb honeypot handler."""
    addr = writer.get_extra_info('peername')
    if addr and _is_local_ip(addr[0]):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nLocal LAN detected.\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return

    try:
        await reader.read(1024)
        response = b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 1000000000\r\n\r\n" + (b"\0" * 1024 * 100)
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def deploy_honey_trap(port: int, trap_type: str) -> str:
    """Deploys a honeypot trap on the specified port."""
    if port in _ACTIVE_TRAPS:
        return f"❌ Trap already running on port {port}."

    handlers = {
        "labyrinth": _handle_labyrinth,
        "rickroll": _handle_rickroll,
        "sinkhole": _handle_sinkhole
    }

    if trap_type not in handlers:
        return f"❌ Invalid trap_type. Choose from: {', '.join(handlers.keys())}"

    try:
        server = await asyncio.start_server(handlers[trap_type], '0.0.0.0', port)
        _ACTIVE_TRAPS[port] = {"type": trap_type, "server": server}
        return f"✅ SUCCESS: Honey trap '{trap_type}' deployed on port {port}."
    except Exception as e:
        return f"❌ Failed to deploy honey trap on port {port}: {e}"

async def stop_honey_trap(port: int) -> str:
    """Stops an active honey trap."""
    if port not in _ACTIVE_TRAPS:
        return f"❌ No active trap found on port {port}."

    try:
        server = _ACTIVE_TRAPS[port]["server"]
        server.close()
        await server.wait_closed()
        del _ACTIVE_TRAPS[port]
        return f"✅ Honey trap on port {port} has been disabled."
    except Exception as e:
        return f"❌ Failed to stop honey trap on port {port}: {e}"

async def list_honey_traps() -> str:
    """Lists all active honey traps."""
    if not _ACTIVE_TRAPS:
        return "No honey traps are currently active."

    res = "Active Honey Traps:\n"
    for port, trap in _ACTIVE_TRAPS.items():
        res += f"- Port {port}: {trap['type']}\n"
    return res


TOOL_DEFS = [
    ToolDefinition(
        name="emergency_network_off",
        description=(
            "Initiates an emergency shutdown of the internet connection (modem/router) "
            "by turning off the smart plug. IMPORTANT: If you detect a threat or want to use this, "
            "you MUST first ask the user 'Disconnect network? [Yes/No]' and call this tool "
            "with confirm=True ONLY AFTER they say 'Yes'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "The reason for the emergency shutdown.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "The Home Assistant entity ID of the modem smart plug (e.g. switch.modem).",
                    "default": "switch.modem"
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be set to True ONLY IF the user explicitly replied 'Yes' to the confirmation prompt.",
                    "default": False
                }
            },
            "required": ["reason"],
        },
    ),
    ToolDefinition(
        name="whois_lookup",
        description="Performs a WHOIS lookup on an IP address.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP address"}
            },
            "required": ["ip"]
        }
    ),
    ToolDefinition(
        name="block_ip",
        description="Blocks an IP address using iptables.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP address to block"}
            },
            "required": ["ip"]
        }
    ),
    ToolDefinition(
        name="tarpit_ip",
        description="Deploys an offensive tarpit against an IP address and port.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Target IP address"},
                "port": {"type": "integer", "description": "Target port"}
            },
            "required": ["ip", "port"]
        }
    ),
    ToolDefinition(
        name="generate_abuse_report",
        description="Generates an abuse report for an IP address.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Attacker IP address"},
                "attack_snippet": {"type": "string", "description": "Details or logs of the attack"}
            },
            "required": ["ip", "attack_snippet"]
        }
    ),
    ToolDefinition(
        name="deploy_honey_trap",
        description="Deploys a honeypot trap on a specific port.",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Port to listen on"},
                "trap_type": {"type": "string", "description": "Type of trap (labyrinth, rickroll, sinkhole)"}
            },
            "required": ["port", "trap_type"]
        }
    ),
    ToolDefinition(
        name="stop_honey_trap",
        description="Stops an active honey trap on a specific port.",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Port of the active trap"}
            },
            "required": ["port"]
        }
    ),
    ToolDefinition(
        name="list_honey_traps",
        description="Lists all active honey traps.",
        parameters={"type": "object", "properties": {}}
    )
]

def build_handlers(ha_client=None, notify_fn=None) -> dict:
    async def emergency_network_off(reason: str, entity_id: str = "switch.modem", confirm: bool = False, **_) -> str:
        if not ha_client:
            return "❌ Home Assistant is not configured. Cannot turn off the modem/router."

        if not confirm:
            # If not confirmed, instruct the LLM to ask the user.
            return (
                f"🚨 EMERGENCY SHUTDOWN PENDING 🚨\n"
                f"Reason: {reason}\n"
                f"Action required: Ask the user exactly 'Disconnect network? [Yes/No]'. "
                f"Do NOT execute the shutdown until the user replies 'Yes'."
            )

        # The user has confirmed. Proceed with shutdown.
        try:
            # Call the Home Assistant API directly to turn off the plug
            await ha_client.call_service(
                domain=entity_id.split('.')[0],
                service="turn_off",
                service_data={"entity_id": entity_id}
            )
            return f"✅ Emergency shutdown confirmed. Turned off {entity_id}."
        except Exception as e:
            log.error("Failed to disable network via HA: %s", e)
            return f"❌ Failed to disable network via HA: {e}"

    return {
        "emergency_network_off": emergency_network_off,
        "whois_lookup": lambda **kw: whois_lookup(**kw),
        "block_ip": lambda **kw: block_ip(**kw),
        "tarpit_ip": lambda **kw: tarpit_ip(**kw),
        "generate_abuse_report": lambda **kw: generate_abuse_report(**kw),
        "deploy_honey_trap": lambda **kw: deploy_honey_trap(**kw),
        "stop_honey_trap": lambda **kw: stop_honey_trap(**kw),
        "list_honey_traps": lambda **kw: list_honey_traps(**kw),
    }

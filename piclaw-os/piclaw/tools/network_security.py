"""
PiClaw OS – Network Security Tool (v0.18 prototype)
Provides active network security honeypots and IP blocking.
"""

import asyncio
import logging
import ipaddress
import contextlib

from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.network_security")

TOOL_DEFS = [
    ToolDefinition(
        name="deploy_honeypot",
        description="Deploys an active honeypot on a specific port to trap automated scanners.",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Port to listen on"},
                "trap_type": {
                    "type": "string",
                    "enum": ["ssh_labyrinth", "tarpit", "http_redirect"],
                    "description": "Type of trap to deploy (default: tarpit)",
                    "default": "tarpit"
                }
            },
            "required": ["port"]
        }
    ),
    ToolDefinition(
        name="block_attacker_ip",
        description="Blocks an IP address using iptables DROP. Includes local network safety override.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP address to block"}
            },
            "required": ["ip"]
        }
    )
]

def _is_local_safe(ip: str) -> bool:
    """Local Network Safety Override to prevent blocking/trapping legitimate local users."""
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return False

async def _handle_ssh_labyrinth(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    if addr and _is_local_safe(addr[0]):
        log.info("Safety Override: Refusing to trap local IP %s in ssh_labyrinth", addr[0])
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return

    log.info("Trapped %s in ssh_labyrinth", addr[0] if addr else "unknown")
    try:
        while True:
            # Send fake SSH banners endlessly to stall the scanner
            writer.write(b"SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u1\r\n")
            await writer.drain()
            await asyncio.sleep(10)
    except Exception as _e:
        log.debug("ssh_labyrinth disconnected: %s", _e)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

async def _handle_tarpit(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    if addr and _is_local_safe(addr[0]):
        log.info("Safety Override: Refusing to trap local IP %s in tarpit", addr[0])
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return

    log.info("Trapped %s in tarpit", addr[0] if addr else "unknown")
    try:
        while True:
            # Send a single byte slowly to keep the TCP connection alive and block the scanner
            writer.write(b"x")
            await writer.drain()
            await asyncio.sleep(5)
    except Exception as _e:
        log.debug("tarpit disconnected: %s", _e)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

async def _handle_http_redirect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    if addr and _is_local_safe(addr[0]):
        log.info("Safety Override: Refusing to trap local IP %s in http_redirect", addr[0])
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return

    log.info("Trapped %s in http_redirect", addr[0] if addr else "unknown")
    try:
        # Endless HTTP redirect loop
        writer.write(b"HTTP/1.1 301 Moved Permanently\r\nLocation: /\r\n\r\n")
        await writer.drain()
    except Exception as _e:
        log.debug("http_redirect disconnected: %s", _e)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


_HONEYPOTS = {}

async def deploy_honeypot(port: int, trap_type: str = "tarpit") -> str:
    """Deploys an active honeypot on a specific port to trap automated scanners."""
    if port in _HONEYPOTS:
        return f"Honeypot already running on port {port}."

    if trap_type == "ssh_labyrinth":
        handler = _handle_ssh_labyrinth
    elif trap_type == "http_redirect":
        handler = _handle_http_redirect
    else:
        handler = _handle_tarpit

    try:
        server = await asyncio.start_server(handler, "0.0.0.0", port)
        _HONEYPOTS[port] = server
        log.info("Deployed %s honeypot on port %d", trap_type, port)
        return f"Successfully deployed {trap_type} honeypot on port {port}."
    except Exception as e:
        log.error("Failed to deploy honeypot on port %d: %s", port, e)
        return f"Failed to deploy honeypot: {e}"

async def block_attacker_ip(ip: str) -> str:
    """Blocks an IP address using iptables DROP. Includes local network safety override."""
    if _is_local_safe(ip):
        log.warning("Safety Override: Attempted to block local/private IP %s", ip)
        return f"Safety Override: Cannot block local/private IP {ip}."

    try:
        # Use subprocess_exec to prevent command injection, configure iptables to DROP packets
        proc = await asyncio.create_subprocess_exec(
            "sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            log.info("Successfully blocked %s via iptables DROP", ip)
            return f"Successfully blocked {ip} via iptables DROP."
        else:
            err = stderr.decode().strip()
            log.error("Failed to block IP %s: %s", ip, err)
            return f"Failed to block IP: {err}"
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return "[TIMEOUT] Blocking IP timed out."
    except Exception as e:
        log.error("Error blocking IP %s: %s", ip, e)
        return f"Error blocking IP: {e}"

def build_handlers():
    return {
        "deploy_honeypot": lambda port, trap_type="tarpit": deploy_honeypot(port, trap_type),
        "block_attacker_ip": lambda ip: block_attacker_ip(ip)
    }

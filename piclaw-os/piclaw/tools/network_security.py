"""
PiClaw OS – Network Security Tool (v0.18)
Provides active defense mechanisms and offensive countermeasures.
Requires 'iptables' and 'whois' to be installed on the host.
"""

import asyncio
import logging
import ipaddress

from piclaw.llm.base import ToolDefinition

logger = logging.getLogger("piclaw.tools.network_security")

TOOL_DEFS = [
    ToolDefinition(
        name="whois_lookup",
        description="Performs a WHOIS lookup on an IP address or domain to gather intelligence about an attacker.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "IP address or domain to lookup."}
            },
            "required": ["target"],
        },
    ),
    ToolDefinition(
        name="block_ip",
        description="Blocks all incoming traffic from an attacking IP address using iptables (drops packets).",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "The attacking IP address to block."}
            },
            "required": ["ip"],
        },
    ),
    ToolDefinition(
        name="tarpit_ip",
        description="Active offensive countermeasure: Configures iptables to DROP packets on a specific port for an attacker. This forces the attacker's scanner to wait for a full TCP timeout (often 30+ seconds per probe) rather than receiving a fast REJECT, aggressively slowing down their scanning process.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "The attacking IP address."},
                "port": {"type": "integer", "description": "The port the attacker is targeting."}
            },
            "required": ["ip", "port"],
        },
    ),
    ToolDefinition(
        name="generate_abuse_report",
        description="Generates a standardized abuse report for an attacking IP, which can later be sent to their ISP.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "The attacking IP address."},
                "log_snippet": {"type": "string", "description": "A snippet of the attack log or evidence."}
            },
            "required": ["ip", "log_snippet"],
        },
    ),
    ToolDefinition(
        name="deploy_honey_trap",
        description="Deploys an active, asynchronous honeypot server on a specific port to ensnare and waste the time of automated attacker scanners. Choose from 'labyrinth' (endless SSH banner to trap brute-forcers), 'sinkhole' (endless gzip bomb to crash HTTP scanners), or 'rickroll' (301 redirect).",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "The port to deploy the trap on (e.g., 2222, 8080)."},
                "trap_type": {"type": "string", "description": "The type of trap: 'labyrinth', 'sinkhole', or 'rickroll'."}
            },
            "required": ["port", "trap_type"],
        },
    ),
    ToolDefinition(
        name="stop_honey_trap",
        description="Stops an active honey trap running on a specific port.",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "The port of the trap to stop."}
            },
            "required": ["port"],
        },
    ),
    ToolDefinition(
        name="list_honey_traps",
        description="Lists all currently active honey traps on the system.",
        parameters={"type": "object", "properties": {}},
    ),
]

# Global dictionary to hold references to our running asyncio honey trap servers
_ACTIVE_TRAPS = {}


async def _run_command(cmd: str, *args: str) -> str:
    """Helper to run a shell command safely and return output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            logger.warning("%s exited with %d: %s", cmd, proc.returncode, err_msg)
            return f"[ERROR] Command failed: {err_msg}"

        return stdout.decode().strip()
    except FileNotFoundError:
        return f"[ERROR] Command '{cmd}' not installed."
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except OSError:
            pass
        return f"[ERROR] Command '{cmd}' timed out."
    except Exception as e:
        return f"[ERROR] Execution failed: {e}"


async def whois_lookup(target: str) -> str:
    """Queries WHOIS information for a given target."""
    logger.info("Running WHOIS lookup for %s", target)
    output = await _run_command("whois", target)

    # WHOIS output can be massive. Let's truncate if it's too long
    # so we don't blow up the LLM context.
    if len(output) > 2000:
        return output[:2000] + "\n...[TRUNCATED]"
    return output


async def block_ip(ip: str) -> str:
    """Blocks an IP using iptables."""
    logger.info("Blocking IP %s", ip)
    # Using sudo because iptables requires root.
    # PiClaw OS typically runs with specific sudoers rules.
    output = await _run_command("sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP")

    if "[ERROR]" in output:
        return f"Failed to block {ip}. {output}"

    return f"✅ SUCCESS: IP {ip} has been successfully DROP-blocked via iptables."


async def tarpit_ip(ip: str, port: int) -> str:
    """Uses a DROP rule on a specific port to force TCP scanner timeouts and waste an attacker's time."""
    logger.info("Tarpitting IP %s on port %d by forcing timeouts", ip, port)

    output = await _run_command(
        "sudo", "iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port),
        "-s", ip, "-j", "DROP"
    )

    if "[ERROR]" in output:
        return f"Failed to tarpit {ip} on port {port}. {output}"

    return f"💥 SUCCESS: Offensive Tarpit deployed! Packets from {ip} on port {port} are now silently dropped, forcing their scanners into agonizing TCP timeouts."


async def generate_abuse_report(ip: str, log_snippet: str) -> str:
    """Generates an abuse report template."""
    report = f"""--- ABUSE REPORT ---
To whom it may concern,

We are writing to report malicious activity originating from an IP address under your jurisdiction.

Attacker IP: {ip}
Date/Time (UTC): <Auto-filled by mail agent>

Evidence/Log Snippet:
{log_snippet}

Please investigate this issue and take appropriate action to stop the abuse.

Regards,
PiClaw OS Automated Security Systems
--------------------"""
    return report


def _is_local_ip(ip: str) -> bool:
    """Returns True if the IP address belongs to a local/private network (RFC 1918) or loopback."""
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback
    except ValueError:
        return False  # Not a valid IP string


async def _handle_labyrinth(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Endless SSH Tarpit: Drip-feeds data to keep attacker connection alive forever."""
    addr = writer.get_extra_info('peername')
    ip = addr[0] if addr else "unknown"

    if _is_local_ip(ip):
        logger.info("Trap [Labyrinth] aborted for local IP %s. (Safety Override)", ip)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return

    logger.info("Trap [Labyrinth] sprung on external IP %s", ip)
    try:
        # Endless loop dripping one line of fake SSH banner every 10 seconds
        while True:
            writer.write(b"SSH-2.0-OpenSSH_9.2p1 Debian-2+deb12u2\r\n")
            await writer.drain()
            await asyncio.sleep(10)
    except Exception:
        # Client disconnected or timeout
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _handle_sinkhole(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Gzip Bomb Sinkhole: Overwhelms HTTP scanners by sending a massive payload of zeros."""
    addr = writer.get_extra_info('peername')
    ip = addr[0] if addr else "unknown"

    try:
        # Read the HTTP request (so the client starts listening for our response)
        await asyncio.wait_for(reader.read(1024), timeout=5)

        if _is_local_ip(ip):
            logger.info("Trap [Sinkhole] aborted for local IP %s. (Safety Override)", ip)
            safe_msg = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n\r\n"
                "PiClaw OS: Sinkhole Honey Trap\r\n"
                "Local LAN detected. Trap deactivated for your safety.\r\n"
            )
            writer.write(safe_msg.encode())
            await writer.drain()
            return

        logger.info("Trap [Sinkhole] sprung on external IP %s", ip)

        # Send a valid HTTP 200 response claiming the content is gzip encoded
        response_headers = (
            "HTTP/1.1 200 OK\r\n"
            "Server: nginx/1.24.0\r\n"
            "Content-Type: text/html\r\n"
            "Content-Encoding: gzip\r\n"
            "Connection: keep-alive\r\n\r\n"
        )
        writer.write(response_headers.encode())
        await writer.drain()

        import gzip
        import io

        # We construct a modest chunk of zeroes, compress it, and stream it endlessly
        chunk = b"0" * (1024 * 1024)  # 1 MB of zeroes
        out = io.BytesIO()
        with gzip.GzipFile(fileobj=out, mode='w') as f:
            f.write(chunk)
        compressed_chunk = out.getvalue()

        # Send gigabytes of compressed data to crash their scanner's RAM when decompressed
        for _ in range(1000):
            writer.write(compressed_chunk)
            await writer.drain()
            await asyncio.sleep(0.1)  # small delay to ensure continuous streaming
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _handle_rickroll(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """HTTP Redirect: Swiftly directs curious browsers to Rick Astley."""
    addr = writer.get_extra_info('peername')
    ip = addr[0] if addr else "unknown"

    try:
        await asyncio.wait_for(reader.read(1024), timeout=5)

        if _is_local_ip(ip):
            logger.info("Trap [Rickroll] aborted for local IP %s. (Safety Override)", ip)
            safe_msg = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n\r\n"
                "PiClaw OS: Rickroll Honey Trap\r\n"
                "Local LAN detected. We're no strangers to love, but you are safe here.\r\n"
            )
            writer.write(safe_msg.encode())
            await writer.drain()
            return

        logger.info("Trap [Rickroll] sprung on external IP %s", ip)
        response = (
            "HTTP/1.1 301 Moved Permanently\r\n"
            "Location: https://www.youtube.com/watch?v=dQw4w9WgXcQ\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(response.encode())
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def deploy_honey_trap(port: int, trap_type: str) -> str:
    """Spins up an active honeypot server on the requested port."""
    if port in _ACTIVE_TRAPS:
        return f"A trap is already running on port {port}."

    trap_type = trap_type.lower()
    handlers = {
        "labyrinth": _handle_labyrinth,
        "sinkhole": _handle_sinkhole,
        "rickroll": _handle_rickroll,
    }

    handler = handlers.get(trap_type)
    if not handler:
        return f"Invalid trap_type '{trap_type}'. Available types: labyrinth, sinkhole, rickroll."

    try:
        server = await asyncio.start_server(handler, '0.0.0.0', port)
        _ACTIVE_TRAPS[port] = {
            "server": server,
            "type": trap_type,
        }
        logger.info("Honey trap '%s' successfully deployed on port %d", trap_type, port)
        return f"🍯 SUCCESS: A '{trap_type}' honey trap has been actively deployed and is listening on port {port}!"
    except Exception as e:
        logger.error("Failed to deploy trap on port %d: %s", port, e)
        return f"Failed to deploy trap on port {port}: {e}"


async def stop_honey_trap(port: int) -> str:
    """Stops a specific honey trap."""
    if port not in _ACTIVE_TRAPS:
        return f"No active trap found on port {port}."

    trap = _ACTIVE_TRAPS.pop(port)
    server = trap["server"]
    server.close()
    await server.wait_closed()
    return f"🛑 Honey trap on port {port} ({trap['type']}) has been disabled."


async def list_honey_traps() -> str:
    """Lists all active traps."""
    if not _ACTIVE_TRAPS:
        return "No honey traps are currently active."

    lines = ["Active Honey Traps:"]
    for p, t in _ACTIVE_TRAPS.items():
        lines.append(f" - Port {p}: {t['type']}")
    return "\n".join(lines)


def build_handlers():
    return {
        "whois_lookup": whois_lookup,
        "block_ip": block_ip,
        "tarpit_ip": tarpit_ip,
        "generate_abuse_report": generate_abuse_report,
        "deploy_honey_trap": deploy_honey_trap,
        "stop_honey_trap": stop_honey_trap,
        "list_honey_traps": list_honey_traps,
    }

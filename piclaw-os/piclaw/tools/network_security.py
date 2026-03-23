"""
PiClaw OS – Network Security Tool (v0.18)
Provides active defense mechanisms and offensive countermeasures.
Requires 'iptables' and 'whois' to be installed on the host.
"""

import asyncio
import logging

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
]


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


def build_handlers():
    return {
        "whois_lookup": whois_lookup,
        "block_ip": block_ip,
        "tarpit_ip": tarpit_ip,
        "generate_abuse_report": generate_abuse_report,
    }

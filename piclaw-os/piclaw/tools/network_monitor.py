"""
PiClaw OS – Network Monitor Tool (v0.15)
Provides LAN scanning, port scanning, and new device detection.
Requires 'nmap' to be installed on the host.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime

from piclaw.config import CONFIG_DIR
from piclaw.llm.base import ToolDefinition

logger = logging.getLogger("piclaw.tools.network_monitor")

KNOWN_DEVICES_FILE = CONFIG_DIR / "known_devices.json"


@dataclass
class NetworkDevice:
    ip: str
    mac: str = "unknown"
    hostname: str = "unknown"
    vendor: str = "unknown"
    last_seen: str = ""


TOOL_DEFS = [
    ToolDefinition(
        name="network_scan",
        description="Scans the local network (LAN) for connected devices using nmap.",
        parameters={
            "type": "object",
            "properties": {
                "range": {
                    "type": "string",
                    "description": "IP range to scan (e.g. 192.168.1.0/24). If empty, tries to autodetect.",
                }
            },
        },
    ),
    ToolDefinition(
        name="port_scan",
        description="Scans a specific IP address for open ports.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP address to scan."},
                "fast": {
                    "type": "boolean",
                    "description": "Only scan top 100 ports.",
                    "default": True,
                },
            },
            "required": ["ip"],
        },
    ),
    ToolDefinition(
        name="check_new_devices",
        description="Scans the network and returns only devices not seen before.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="ping_host",
        description="Pings a host to check if it is online.",
        parameters={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Hostname or IP address to ping.",
                }
            },
            "required": ["host"],
        },
    ),
]


async def _run_nmap(args: list[str]) -> str:
    """Helper to run nmap and return output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nmap",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            logger.warning("nmap exited with %d: %s", proc.returncode, stderr.decode())
        return stdout.decode()
    except FileNotFoundError:
        return "[ERROR] nmap not installed. Please run: sudo apt install nmap"
    except Exception as e:
        return f"[ERROR] Network scan failed: {e}"


async def _get_local_range() -> str:
    """Attempts to find the local network range (default fallback: 192.168.1.0/24)."""
    try:
        proc = await asyncio.create_subprocess_shell(
            "ip -4 route show default | awk '{print $3}'",
            stdout=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        gateway = out.decode().strip()
        if gateway:
            # Simple assumption: /24 network
            base = ".".join(gateway.split(".")[:3])
            return f"{base}.0/24"
    except Exception:
        pass
    return "192.168.1.0/24"


async def scan_devices(ip_range: str = "") -> list[NetworkDevice]:
    if not ip_range:
        ip_range = await _get_local_range()

    # -sn: Ping scan (no port scan)
    output = await _run_nmap(["-sn", ip_range])

    devices = []
    # Simple regex parsing for nmap output
    # Host: 192.168.1.53 (hostname)	Status: Up
    # MAC Address: 00:11:22:33:44:55 (Vendor)

    current_dev = None
    for line in output.splitlines():
        # Nmap scan report for 192.168.1.1
        # Nmap scan report for router.local (192.168.1.1)
        m_host = re.search(r"Nmap scan report for (?:(.+) \()?([\d\.]+)\)?", line)
        if m_host:
            current_dev = NetworkDevice(
                ip=m_host.group(2), hostname=m_host.group(1) or "unknown"
            )
            current_dev.last_seen = datetime.now().isoformat()
            devices.append(current_dev)
            continue

        m_mac = re.search(r"MAC Address: ([0-9A-F:]+) \((.+)\)", line, re.IGNORECASE)
        if m_mac and current_dev:
            current_dev.mac = m_mac.group(1)
            current_dev.vendor = m_mac.group(2)

    return devices


async def port_scan(ip: str, fast: bool = True) -> str:
    args = ["-F", ip] if fast else [ip]
    return await _run_nmap(args)


def load_known_devices() -> dict[str, dict]:
    if not KNOWN_DEVICES_FILE.exists():
        return {}
    try:
        return json.loads(KNOWN_DEVICES_FILE.read_text())
    except Exception:
        return {}


def save_known_devices(devices: dict[str, dict]):
    KNOWN_DEVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    KNOWN_DEVICES_FILE.write_text(json.dumps(devices, indent=2))


async def check_new_devices() -> list[NetworkDevice]:
    current_list = await scan_devices()
    known = load_known_devices()
    new_devices = []

    for dev in current_list:
        key = dev.mac if dev.mac != "unknown" else dev.ip
        if key not in known:
            new_devices.append(dev)
            known[key] = asdict(dev)
        else:
            known[key]["last_seen"] = dev.last_seen

    if new_devices:
        save_known_devices(known)

    return new_devices


async def ping_host(host: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "2", host, stdout=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception:
        return False


def build_handlers():
    async def _check_new_devices_handler(**_) -> str:
        devices = await check_new_devices()
        if not devices:
            return "__NO_NEW_DEVICES__"  # Signal für Sub-Agent: keine Meldung
        lines = [f"🔍 {len(devices)} neues Gerät(e) im Netzwerk erkannt!\n"]
        for d in devices:
            lines.append(
                f"  📍 IP: {d.ip}\n"
                f"  🔌 MAC: {d.mac}\n"
                f"  🏭 Hersteller: {d.vendor}\n"
                f"  💻 Hostname: {d.hostname}\n"
            )
        return "\n".join(lines)

    async def _network_scan_handler(range: str = "", **_) -> str:
        devices = await scan_devices(range)
        if not devices:
            return "Keine Geräte gefunden."
        lines = [f"🌐 {len(devices)} Geräte im Netzwerk:\n"]
        for d in devices:
            lines.append(f"  {d.ip:16} {d.mac:20} {d.vendor:25} {d.hostname}")
        return "\n".join(lines)

    return {
        "network_scan": _network_scan_handler,
        "port_scan": lambda ip, fast=True, **_: port_scan(ip, fast),
        "check_new_devices": _check_new_devices_handler,
        "ping_host": lambda host, **_: ping_host(host),
    }

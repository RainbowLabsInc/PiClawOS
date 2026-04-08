"""
PiClaw OS – Network Security Tools (v0.16)

Offensive Verteidigung für den Raspberry Pi:
  - whois_lookup       – IP-Informationen abrufen
  - block_ip           – IP via iptables blockieren
  - tarpit_ip          – Angreifer verlangsamen (TCP-DROP auf Port)
  - generate_abuse_report – Missbrauchsmeldung generieren
  - deploy_honey_trap  – Täuschfallen auf Ports (labyrinth/rickroll/sinkhole)
  - stop_honey_trap    – Falle deaktivieren
  - list_honey_traps   – Aktive Fallen anzeigen
  - emergency_network_off – Notfall: Modem via Home Assistant abschalten

Sicherheitshinweise:
  - iptables-Befehle erfordern sudo (piclaw-user hat entsprechende Sudoers-Regel)
  - Honey Traps sind rein passiv – sie antworten nur, initiieren nichts
  - Lokale IPs (192.168.x.x, 10.x.x.x etc.) sind vor aggressiven Traps geschützt
"""

import asyncio
import ipaddress
import logging
from datetime import datetime

from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.network_security")

# ── Aktive Honey Traps (Port → Trap-Info) ────────────────────────────────────
_ACTIVE_TRAPS: dict[int, dict] = {}


# ── Tool-Definitionen ────────────────────────────────────────────────────────

TOOL_DEFS = [
    ToolDefinition(
        name="whois_lookup",
        description="Führt einen WHOIS-Lookup für eine IP-Adresse durch und gibt Informationen über den Eigentümer zurück.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP-Adresse für den WHOIS-Lookup."}
            },
            "required": ["ip"],
        },
    ),
    ToolDefinition(
        name="block_ip",
        description="Blockiert eine IP-Adresse dauerhaft via iptables (DROP). Nur für externe IPs.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Zu blockierende IP-Adresse."}
            },
            "required": ["ip"],
        },
    ),
    ToolDefinition(
        name="tarpit_ip",
        description=(
            "Setzt eine offensive Tarpit-Falle für eine IP auf einem bestimmten Port. "
            "Der Angreifer wird verlangsamt indem TCP-Pakete gedroppt werden. "
            "Nur für externe IPs verwendbar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Ziel-IP-Adresse."},
                "port": {"type": "integer", "description": "Ziel-Port (z.B. 22 für SSH)."},
            },
            "required": ["ip", "port"],
        },
    ),
    ToolDefinition(
        name="generate_abuse_report",
        description="Generiert eine strukturierte Missbrauchsmeldung für einen Angriff zur Weiterleitung an den ISP/Hoster.",
        parameters={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP-Adresse des Angreifers."},
                "evidence": {"type": "string", "description": "Beweismaterial (Log-Einträge, Beschreibung)."},
            },
            "required": ["ip", "evidence"],
        },
    ),
    ToolDefinition(
        name="deploy_honey_trap",
        description=(
            "Deployt eine Täuschfalle (Honey Trap) auf einem Port. Typen:\n"
            "  labyrinth – Endloser ASCII-Tunnel der Angreifer beschäftigt\n"
            "  rickroll   – HTTP-Redirect zu youtube.com/watch?v=dQw4w9WgXcQ\n"
            "  sinkhole   – Antwortet mit gefälschten aber ungültigen Daten (gzip-Bombe)\n"
            "Schützt automatisch lokale IPs (LAN-Geräte bekommen harmlose Antworten)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Port für die Falle (z.B. 2222, 8080)."},
                "trap_type": {
                    "type": "string",
                    "enum": ["labyrinth", "rickroll", "sinkhole"],
                    "description": "Art der Falle.",
                },
            },
            "required": ["port", "trap_type"],
        },
    ),
    ToolDefinition(
        name="stop_honey_trap",
        description="Deaktiviert eine aktive Honey Trap auf einem Port.",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Port der Falle."}
            },
            "required": ["port"],
        },
    ),
    ToolDefinition(
        name="list_honey_traps",
        description="Listet alle aktiven Honey Traps auf.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="emergency_network_off",
        description=(
            "Notfall-Abschaltung der Internetverbindung via Home Assistant (Smart Plug am Modem). "
            "WICHTIG: Erst Nutzer fragen 'Netzwerk trennen? [Ja/Nein]' – nur bei 'Ja' ausführen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Grund für die Notabschaltung."},
                "entity_id": {
                    "type": "string",
                    "description": "Home Assistant Entity-ID des Modem-Smart-Plugs.",
                    "default": "switch.modem",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Nur True wenn Nutzer explizit 'Ja' gesagt hat.",
                    "default": False,
                },
            },
            "required": ["reason"],
        },
    ),
]


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

async def _run_command(*args: str) -> str:
    """Führt einen Shell-Befehl aus und gibt stdout zurück."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return f"[ERROR] Command failed: {stderr.decode().strip()}"
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        if 'proc' in locals() and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        return "[ERROR] Command timed out"
    except Exception as e:
        return f"[ERROR] {e}"


def _is_valid_ip(ip: str) -> bool:
    """Gibt True zurück wenn die IP eine gültige IPv4/IPv6 Adresse ist."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def _is_local_ip(ip: str) -> bool:
    """Gibt True zurück wenn die IP eine lokale/private Adresse ist."""
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


# ── Tool-Implementierungen ───────────────────────────────────────────────────

async def whois_lookup(ip: str) -> str:
    if not _is_valid_ip(ip):
        return f"❌ Invalid IP address format: {ip}"
    result = await _run_command("whois", ip)
    if len(result) > 2000:
        result = result[:2000] + "\n...[TRUNCATED]"
    return result


async def block_ip(ip: str) -> str:
    if not _is_valid_ip(ip):
        return f"❌ Invalid IP address format: {ip}"
    if _is_local_ip(ip):
        return f"⚠️ {ip} ist eine lokale IP – Blockierung abgebrochen (Schutzmaßnahme)."
    result = await _run_command("sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP")
    if "[ERROR]" in result:
        return f"❌ Failed to block {ip}: {result}"
    return f"✅ SUCCESS: {ip} wurde via iptables blockiert (DROP)."


async def tarpit_ip(ip: str, port: int) -> str:
    if not _is_valid_ip(ip):
        return f"❌ Invalid IP address format: {ip}"
    if _is_local_ip(ip):
        return f"⚠️ {ip} ist eine lokale IP – Tarpit abgebrochen (Schutzmaßnahme)."
    result = await _run_command(
        "sudo", "iptables", "-A", "INPUT",
        "-p", "tcp", "--dport", str(port),
        "-s", ip, "-j", "DROP"
    )
    if "[ERROR]" in result:
        return f"❌ Tarpit-Deployment fehlgeschlagen für {ip}:{port}: {result}"
    return (
        f"🪤 Offensive Tarpit deployed!\n"
        f"  Ziel: {ip}:{port}\n"
        f"  Methode: TCP DROP via iptables\n"
        f"  Effekt: Angreifer-Verbindungen werden lautlos verworfen."
    )


async def generate_abuse_report(ip: str, evidence: str) -> str:
    if not _is_valid_ip(ip):
        return f"❌ Invalid IP address format: {ip}"
    whois = await whois_lookup(ip)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")  # lokale Pi-Zeit (Europe/Berlin)
    return (
        f"=== ABUSE REPORT ===\n"
        f"Datum: {ts}\n"
        f"Angreifer-IP: {ip}\n"
        f"Gemeldet von: PiClaw OS (Raspberry Pi 5)\n\n"
        f"--- Beweismaterial ---\n{evidence}\n\n"
        f"--- WHOIS ---\n{whois[:800]}\n"
        f"===================\n"
        f"Bitte an abuse@<isp> senden."
    )


# ── Honey Trap Handlers ──────────────────────────────────────────────────────

async def _handle_labyrinth(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Endloser ASCII-Tunnel – beschäftigt Angreifer ohne echte Infos."""
    peer = writer.get_extra_info("peername")
    ip = peer[0] if peer else "unknown"
    if _is_local_ip(ip):
        log.debug("Labyrinth: lokale IP %s – sofort schließen", ip)
        writer.close()
        return
    log.info("Labyrinth: Verbindung von %s", ip)
    try:
        banner = (
            b"\r\n  Welcome to the SSH Honeypot v7.3 (Debian)\r\n"
            b"  Last login: " + datetime.now().strftime("%a %b %d %H:%M:%S %Y").encode() + b"\r\n"
            b"  $ \r\n"
        )
        writer.write(banner)
        await writer.drain()
        # Endloser Loop: sendet alle 10s ein Zeichen um Verbindung offen zu halten
        for _ in range(360):  # max 1 Stunde
            await asyncio.sleep(10)
            writer.write(b"\x00")
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _handle_rickroll(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """HTTP-Redirect zu Rick Astley – für Scanner und Web-Crawler."""
    peer = writer.get_extra_info("peername")
    ip = peer[0] if peer else "unknown"
    if _is_local_ip(ip):
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
            b"<html><body><h1>You are safe here :)</h1>"
            b"<p>This is a local LAN device.</p></body></html>"
        )
        writer.write(response)
        await writer.drain()
        writer.close()
        return
    try:
        await asyncio.wait_for(reader.read(1024), timeout=5)
    except Exception:
        pass
    response = (
        b"HTTP/1.1 301 Moved Permanently\r\n"
        b"Location: https://www.youtube.com/watch?v=dQw4w9WgXcQ\r\n"
        b"Content-Length: 0\r\n\r\n"
    )
    try:
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    log.info("Rickroll: %s umgeleitet", ip)


async def _handle_sinkhole(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Antwortet mit gefälschten aber ungültigen gzip-Daten – verwirrt Scanner."""
    peer = writer.get_extra_info("peername")
    ip = peer[0] if peer else "unknown"
    if _is_local_ip(ip):
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"
            b"Local LAN detected. Nothing to see here."
        )
        writer.write(response)
        await writer.drain()
        writer.close()
        return
    try:
        await asyncio.wait_for(reader.read(1024), timeout=5)
    except Exception:
        pass
    # Gefälschter gzip-Header mit Nonsense-Body
    fake_data = b"\x1f\x8b\x08\x00\x00\x00\x00\x00" + b"\xff" * 256
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/octet-stream\r\n"
        b"Content-Encoding: gzip\r\n"
        b"Content-Length: " + str(len(fake_data)).encode() + b"\r\n\r\n"
        + fake_data
    )
    try:
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    log.info("Sinkhole: %s mit falschen Daten versorgt", ip)


_TRAP_HANDLERS = {
    "labyrinth": _handle_labyrinth,
    "rickroll": _handle_rickroll,
    "sinkhole": _handle_sinkhole,
}


async def deploy_honey_trap(port: int, trap_type: str) -> str:
    if trap_type not in _TRAP_HANDLERS:
        return f"❌ Invalid trap_type '{trap_type}'. Erlaubt: {list(_TRAP_HANDLERS.keys())}"
    if port in _ACTIVE_TRAPS:
        return f"⚠️ Port {port} hat bereits eine aktive Falle ({_ACTIVE_TRAPS[port]['type']}). already running"
    handler = _TRAP_HANDLERS[trap_type]
    try:
        server = await asyncio.start_server(handler, "0.0.0.0", port)
        _ACTIVE_TRAPS[port] = {
            "type": trap_type,
            "server": server,
            "started": datetime.now().isoformat(),
        }
        log.info("Honey Trap deployed: port=%d type=%s", port, trap_type)
        return (
            f"✅ SUCCESS: Honey Trap aktiv!\n"
            f"  Port: {port}\n"
            f"  Typ: {trap_type}\n"
            f"  Gestartet: {_ACTIVE_TRAPS[port]['started']}"
        )
    except Exception as e:
        return f"❌ Honey Trap fehlgeschlagen auf Port {port}: {e}"


async def stop_honey_trap(port: int) -> str:
    if port not in _ACTIVE_TRAPS:
        return f"⚠️ No active trap found on port {port}."
    trap = _ACTIVE_TRAPS.pop(port)
    try:
        trap["server"].close()
        await trap["server"].wait_closed()
    except Exception:
        pass
    return f"✅ Honey Trap auf Port {port} ({trap['type']}) has been disabled."


async def list_honey_traps() -> str:
    if not _ACTIVE_TRAPS:
        return "🪤 No honey traps are currently active."
    lines = [f"🪤 Active Honey Traps ({len(_ACTIVE_TRAPS)}):\n"]
    for port, info in _ACTIVE_TRAPS.items():
        lines.append(f"  Port {port:5d} – {info['type']:12} (seit {info['started'][:16]})")
    return "\n".join(lines)


# ── Handler-Registry ─────────────────────────────────────────────────────────

def build_handlers(ha_client=None, notify_fn=None) -> dict:

    async def emergency_network_off(
        reason: str, entity_id: str = "switch.modem", confirm: bool = False, **_
    ) -> str:
        if not ha_client:
            return "❌ Home Assistant nicht konfiguriert – Modem kann nicht abgeschaltet werden."
        if not confirm:
            return (
                f"🚨 NOTFALL-ABSCHALTUNG AUSSTEHEND 🚨\n"
                f"Grund: {reason}\n"
                f"Bitte den Nutzer fragen: 'Netzwerk trennen? [Ja/Nein]'\n"
                f"Erst bei explizitem 'Ja' mit confirm=True erneut aufrufen."
            )
        try:
            await ha_client.call_service(
                domain=entity_id.split(".")[0],
                service="turn_off",
                service_data={"entity_id": entity_id},
            )
            log.warning("Emergency shutdown: %s abgeschaltet. Grund: %s", entity_id, reason)
            return f"✅ Notfall-Abschaltung ausgeführt. {entity_id} wurde deaktiviert."
        except Exception as e:
            log.error("Emergency shutdown fehlgeschlagen: %s", e)
            return f"❌ Notfall-Abschaltung fehlgeschlagen: {e}"

    return {
        "whois_lookup": lambda ip, **_: whois_lookup(ip),
        "block_ip": lambda ip, **_: block_ip(ip),
        "tarpit_ip": lambda ip, port, **_: tarpit_ip(ip, port),
        "generate_abuse_report": lambda ip, evidence, **_: generate_abuse_report(ip, evidence),
        "deploy_honey_trap": lambda port, trap_type, **_: deploy_honey_trap(port, trap_type),
        "stop_honey_trap": lambda port, **_: stop_honey_trap(port),
        "list_honey_traps": lambda **_: list_honey_traps(),
        "emergency_network_off": emergency_network_off,
    }

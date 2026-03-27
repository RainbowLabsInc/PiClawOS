"""
PiClaw Debug – Services & API-Konnektivität
Prüft alle systemd-Services, API-Erreichbarkeit und WebSocket.
Aufruf: piclaw debug → test_debug_services auswählen

Abgedeckte Fehlerquellen (aus CLAUDE_REBUILD.md):
  API_EXITS_IMMEDIATELY   → INV_005: API antwortet auf HTTP
  WEBSOCKET_TIMEOUT_1011  → INV_023: WebSocket Keepalive funktioniert
  API_PERMISSION_DENIED   → Logs auf Permission-Fehler prüfen
"""

import asyncio
import json
import os
import sys
import subprocess
from pathlib import Path

LOG_DIR = Path("/var/log/piclaw")

PASS = []
FAIL = []
WARN = []

SERVICES = [
    "piclaw-api",
    "piclaw-agent",
    "piclaw-watchdog",
    "piclaw-crawler",
]


def section(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")

def ok(label, detail=""):
    msg = f"{label}" + (f" – {detail}" if detail else "")
    print(f"  ✅ {msg}")
    PASS.append(label)

def fail(label, detail="", hint=""):
    msg = f"{label}" + (f" – {detail}" if detail else "")
    print(f"  ❌ {msg}")
    if hint:
        print(f"     💡 {hint}")
    FAIL.append(label)

def warn(label, detail=""):
    msg = f"{label}" + (f" – {detail}" if detail else "")
    print(f"  ⚠️  {msg}")
    WARN.append(label)

def info(m):
    print(f"  ℹ  {m}")


# ── 1. systemd Services ──────────────────────────────────────────
section("1. systemd Services")
for svc in SERVICES:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", svc],
            capture_output=True, text=True, timeout=5
        )
        state = r.stdout.strip()
        if state == "active":
            ok(svc, "active (running)")
        elif state == "inactive":
            warn(svc, "inactive – nicht gestartet?")
        elif state == "failed":
            fail(svc, "failed",
                 f"sudo journalctl -u {svc} -n 30 --no-pager")
        else:
            warn(svc, state)
    except FileNotFoundError:
        warn(f"{svc}", "systemctl nicht verfügbar (kein systemd-System?)")
    except subprocess.TimeoutExpired:
        fail(svc, "Timeout bei systemctl")


# ── 2. API Port ──────────────────────────────────────────────────
section("2. API HTTP-Erreichbarkeit")
try:
    from piclaw.config import load
    cfg = load()
    port = (cfg.api.port if cfg and cfg.api and cfg.api.port else None) or 7842
except Exception:
    port = 7842
    warn("Config nicht ladbar – verwende Standard-Port 7842")

info(f"Prüfe http://127.0.0.1:{port}/health ...")

async def check_http():
    try:
        import aiohttp
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                if resp.status == 200:
                    ok("API HTTP", f"Port {port} antwortet (HTTP {resp.status})")
                elif resp.status == 401:
                    ok("API HTTP", f"Port {port} aktiv – 401 erwartet (kein Token)")
                else:
                    warn("API HTTP", f"HTTP {resp.status}")
    except aiohttp.ClientConnectorError:
        fail("API HTTP nicht erreichbar",
             f"http://127.0.0.1:{port} – Connection refused",
             "sudo systemctl status piclaw-api")
    except Exception as e:
        fail("API HTTP", str(e))

asyncio.run(check_http())


# ── 3. WebSocket ─────────────────────────────────────────────────
section("3. WebSocket-Verbindung (INV_023)")

async def check_ws():
    try:
        import aiohttp
        try:
            from piclaw.config import load
            cfg = load()
            token = cfg.api.secret_key if cfg and cfg.api else None
            port_ = (cfg.api.port if cfg and cfg.api and cfg.api.port else None) or 7842
        except Exception:
            token, port_ = None, port

        if not token:
            warn("Kein API-Token in Config – WebSocket-Test übersprungen",
                 "piclaw config token setzen oder Wizard ausführen")
            return

        url = f"ws://127.0.0.1:{port_}/ws/chat?token={token}"
        info(f"Verbinde: ws://127.0.0.1:{port_}/ws/chat?token=***")

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, timeout=aiohttp.ClientTimeout(total=8)) as ws:
                ok("WebSocket-Handshake erfolgreich")
                # Ping senden
                await ws.ping()
                ok("WebSocket-Ping erfolgreich (Keepalive aktiv)")
                await ws.close()
    except aiohttp.ClientConnectorError:
        fail("WebSocket nicht erreichbar",
             f"ws://127.0.0.1:{port}",
             "piclaw-api Service läuft? sudo systemctl status piclaw-api")
    except aiohttp.WSServerHandshakeError as e:
        if "401" in str(e) or "403" in str(e):
            fail("WebSocket Auth fehlgeschlagen",
                 "Token ungültig?",
                 "piclaw config token prüfen")
        else:
            fail("WebSocket Handshake", str(e))
    except Exception as e:
        fail("WebSocket", str(e))

asyncio.run(check_ws())


# ── 4. Logs auf Fehler prüfen ────────────────────────────────────
section("4. Log-Analyse (letzte 50 Zeilen)")
log_files = {
    "api.log":     LOG_DIR / "api.log",
    "agent.log":   LOG_DIR / "agent.log",
    "watchdog.log":LOG_DIR / "watchdog.log",
}
ERROR_PATTERNS = [
    "PermissionError",
    "FileNotFoundError",
    "ModuleNotFoundError",
    "NameError",
    "AttributeError",
    "RuntimeError",
    "CRITICAL",
    "Traceback",
]
for name, path in log_files.items():
    if not path.exists():
        warn(f"{name}", "nicht vorhanden (Service noch nie gestartet?)")
        continue
    try:
        lines = path.read_text(errors="replace").splitlines()[-50:]
        errors = [l for l in lines if any(p in l for p in ERROR_PATTERNS)]
        size_kb = path.stat().st_size // 1024
        if not errors:
            ok(name, f"{len(lines)} Zeilen analysiert, {size_kb} KB – keine kritischen Fehler")
        else:
            fail(name, f"{len(errors)} kritische Einträge gefunden")
            for e in errors[-5:]:
                print(f"     {e.strip()[:100]}")
    except PermissionError:
        fail(name, "Keine Leseberechtigung",
             "sudo chown -R piclaw:piclaw /var/log/piclaw")


# ── 5. QMD – kein CPU-Abuse ──────────────────────────────────────
section("5. QMD CPU-Check (INV_015)")
try:
    import psutil
    node_procs = [p for p in psutil.process_iter(['name', 'cpu_percent'])
                  if 'node' in (p.info['name'] or '').lower()]
    if node_procs:
        for p in node_procs:
            cpu = p.info.get('cpu_percent', 0)
            if cpu and cpu > 50:
                fail("Node.js-Prozess mit hoher CPU-Last",
                     f"PID {p.pid}: {cpu:.0f}%",
                     "QMD läuft möglicherweise pro Chat-Turn – check INV_015")
            else:
                warn("Node.js-Prozess aktiv", f"PID {p.pid} – {cpu:.0f}% CPU (OK wenn QMD-Timer)")
    else:
        ok("Kein Node.js-Prozess aktiv", "QMD läuft nicht im Vordergrund")
except Exception as e:
    warn(f"CPU-Check übersprungen: {e}")


# ── 6. Timer-Unit ────────────────────────────────────────────────
section("6. piclaw-qmd-update.timer")
try:
    r = subprocess.run(
        ["systemctl", "is-active", "piclaw-qmd-update.timer"],
        capture_output=True, text=True, timeout=5
    )
    state = r.stdout.strip()
    if state == "active":
        ok("piclaw-qmd-update.timer", "aktiv (stündlich, nice 19)")
    else:
        warn("piclaw-qmd-update.timer", state)
except FileNotFoundError:
    warn("systemctl nicht verfügbar")
except Exception as e:
    warn(f"Timer-Check: {e}")


# ── Zusammenfassung ───────────────────────────────────────────────
section("Zusammenfassung")
total = len(PASS) + len(FAIL) + len(WARN)
print(f"  Gesamt : {total} Checks")
print(f"  ✅ OK   : {len(PASS)}")
print(f"  ⚠️  Warn : {len(WARN)}")
print(f"  ❌ Fehler: {len(FAIL)}")
if FAIL:
    print("\n  Fehler:")
    for f in FAIL:
        print(f"    • {f}")
if WARN:
    print("\n  Warnungen:")
    for w in WARN:
        print(f"    • {w}")
if not FAIL:
    print("\n  🎉 Alle kritischen Checks bestanden!")
print(f"\n{'='*60}\n  ✉  Output bei Problemen an Entwickler senden\n{'='*60}\n")

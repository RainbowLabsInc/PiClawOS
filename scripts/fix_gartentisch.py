#!/usr/bin/env python3
"""
Repariert Monitor_Gartentisch direkt auf dem Pi.
Ausführen: sudo /opt/piclaw/venv/bin/python3 /tmp/fix_gartentisch.py

Was dieses Script tut:
  1. Liest /etc/piclaw/subagents.json
  2. Entfernt alle vorhandenen Monitor_Gartentisch Einträge (egal ob fehlerhaft)
  3. Legt neuen Eintrag mit korrektem direct_tool an
  4. Schreibt /etc/piclaw/marketplace_monitors.json mit dem Handler-Param-Eintrag
  5. Neustart von piclaw-agent wird empfohlen
"""

import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

CONFIG_DIR   = Path("/etc/piclaw")
SUBAGENTS    = CONFIG_DIR / "subagents.json"
MP_MONITORS  = CONFIG_DIR / "marketplace_monitors.json"

# ── Konfiguration ─────────────────────────────────────────────
AGENT_NAME   = "Monitor_Gartentisch"
QUERY        = "Gartentisch"
PLATFORMS    = ["kleinanzeigen"]
LOCATION     = None
RADIUS_KM    = None
MAX_PRICE    = None
INTERVAL_SEC = 3600
TOOL_NAME    = "_mp_monitor_gartentisch"   # muss mit agent.py _create_monitor_agent() übereinstimmen


def short_id() -> str:
    return str(uuid.uuid4())[:8]


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️  {path} lesen: {e} – verwende leeres Dict")
    return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── 1. Subagents.json patchen ─────────────────────────────────
print("=" * 55)
print("Monitor_Gartentisch Reparatur-Skript")
print("=" * 55)

agents = load_json(SUBAGENTS)

# Alle alten Gartentisch-Einträge entfernen
before = len(agents)
agents = {k: v for k, v in agents.items()
          if "garten" not in v.get("name", "").lower()}
removed = before - len(agents)
if removed:
    print(f"  🗑  {removed} alten Monitor_Gartentisch Eintrag(e) entfernt")
else:
    print("  ℹ️  Kein vorhandener Monitor_Gartentisch gefunden")

# Neuen Eintrag anlegen
agent_id = short_id()
new_agent = {
    "id":           agent_id,
    "name":         AGENT_NAME,
    "description":  f"Kleinanzeigen: neue Gartentisch-Inserate – stündlich",
    "mission":      f"Direct tool mode: {TOOL_NAME}",
    "tools":        ["marketplace_search"],
    "schedule":     f"interval:{INTERVAL_SEC}",
    "notify":       True,
    "direct_tool":  TOOL_NAME,          # <── kritisch: muss gesetzt sein!
    "enabled":      True,
    "trusted":      False,
    "privileged":   False,
    "created_by":   "fix_gartentisch.py",
    "created_at":   datetime.now().isoformat(),
    "last_run":     None,
    "last_status":  None,
    "max_steps":    8,
    "timeout":      120,
}

agents[agent_id] = new_agent
save_json(SUBAGENTS, agents)
print(f"  ✅ Neuer Agent angelegt: ID={agent_id}, direct_tool={TOOL_NAME}")

# ── 2. marketplace_monitors.json patchen ──────────────────────
mp = load_json(MP_MONITORS)

# Alte Gartentisch-Einträge bereinigen
old_keys = [k for k in mp if "garten" in k.lower()]
for k in old_keys:
    del mp[k]
    print(f"  🗑  Alter MP-Monitor-Param '{k}' entfernt")

mp[TOOL_NAME] = {
    "query":      QUERY,
    "platforms":  PLATFORMS,
    "location":   LOCATION,
    "radius_km":  RADIUS_KM,
    "max_price":  MAX_PRICE,
}
save_json(MP_MONITORS, mp)
print(f"  ✅ marketplace_monitors.json: '{TOOL_NAME}' eingetragen")
print(f"     query={QUERY}, platforms={PLATFORMS}")

# ── 3. Empfehlung ──────────────────────────────────────────────
print()
print("Bitte jetzt piclaw-agent neu starten:")
print("  sudo systemctl restart piclaw-agent")
print()

# Optional: direkt neustarten
answer = input("Jetzt automatisch neustarten? [j/N] ").strip().lower()
if answer in ("j", "y", "ja", "yes"):
    print("Starte piclaw-agent neu...")
    r = subprocess.run(["sudo", "systemctl", "restart", "piclaw-agent"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("  ✅ piclaw-agent neugestartet")
    else:
        print(f"  ❌ Neustart fehlgeschlagen: {r.stderr}")
else:
    print("Kein automatischer Neustart.")

print()
print("Verifizierung nach dem Neustart:")
print(f"  python3 -c \"import json; d=json.load(open('{SUBAGENTS}')); "
      f"g=[v for v in d.values() if 'garten' in v.get('name','').lower()]; "
      f"print(g[0]['direct_tool'])\"")
print("  → Erwartete Ausgabe: _mp_monitor_gartentisch")

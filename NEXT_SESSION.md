# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-03-28 (Session 5)
# Version: 0.15.3

---

## ⚠️ VOR RELEASE (Pflicht)

### 1. /api/shell Endpoint entfernen
**Datei:** `piclaw-os/piclaw/api.py`
**Suche:** `@app.post("/api/shell")`
**Gesamten Block löschen** (~50 Zeilen)
**Test:** `curl -X POST http://localhost:7842/api/shell` → muss 404 zurückgeben

### 2. Groq API Key aus Git-History tilgen
```bash
git filter-repo --replace-text <(echo "gsk_ZVWVs...==>REDACTED")
git push --force
```

### 3. API-Token rotieren
Aktuell: `REDACTED_PICLAW_TOKEN`

---

## 🔧 Bekannte Bugs / Kurzfristig

### 4. direct_tool – neuer Monitor_Netzwerk muss via venv-Python erstellt werden
Wenn Monitor_Netzwerk gelöscht wird, muss er mit venv-Python neu angelegt werden:
```bash
sudo systemctl stop piclaw-agent
/opt/piclaw/.venv/bin/python3 -c "
from piclaw.agents.sa_registry import SubAgentDef, SA_REGISTRY_FILE
from dataclasses import asdict
import json

p = SA_REGISTRY_FILE
d = json.loads(p.read_text())
agent = SubAgentDef(
    name='Monitor_Netzwerk',
    description='Netzwerk-Monitoring: neue Geraete erkennen - alle 5 Minuten',
    mission='Direct mode',
    tools=['check_new_devices', 'network_scan'],
    schedule='interval:300',
    notify=True,
    direct_tool='check_new_devices',
    created_by='system'
)
d[agent.id] = asdict(agent)
p.write_text(json.dumps(d, indent=2))
print('OK:', agent.id)
"
sudo systemctl start piclaw-agent
```
→ Besser: _create_network_monitor_agent() in agent.py korrekt setzt direct_tool,
  und `piclaw chat` → "Überwache Netzwerk" funktioniert direkt.

### 5. Camera-Tools registrieren
`piclaw/hardware/camera.py` hat TOOL_DEFS aber fehlt in `agent.py _build_tools()`.

### 6. Willhaben Kategorie-Filter
"Notebooks" findet auch Taschen/RAM → category_id muss gemappt werden.

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Camera-Tools vollständig integriert |

---

## ✅ Session 5 erledigt

- **Direct Tool Mode:** Monitor_Netzwerk läuft ohne LLM (0 Groq-Calls/Run)
  - `direct_tool` Feld in SubAgentDef + runner._direct_tool_call()
  - api.py leitet `direct_tool` bei POST /api/subagents durch
  - Bestätigt: 14:15, 14:20, 14:25 – kein einziger LLM-Call ✅
- Heartbeat-Heuristik invertiert (default: quiet, außer Gerätekennzeichen)
- Briefing-Uhrzeiten im Setup konfigurierbar
- Telegram-Bug (send ohne async with) gefixt
- Markdown **bold** → *bold* gefixt

---

## 🛠️ Entwicklungs-Tool (solange aktiv)

```javascript
window.pi = async (cmd, timeout=30) => {
    const r = await fetch('/api/shell', {
        method: 'POST',
        headers: new Headers({
            'Authorization': 'Bearer REDACTED_PICLAW_TOKEN',
            'Content-Type': 'application/json'
        }),
        body: JSON.stringify({cmd, timeout})
    });
    const d = await r.json();
    return d.stdout || d.stderr || d.error;
};
```

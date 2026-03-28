# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-03-28 (Session 5 – Abschluss)
# Version: 0.15.3

---

## ⚠️ VOR RELEASE (Pflicht)

### 1. /api/shell Endpoint entfernen
**Datei:** `piclaw-os/piclaw/api.py`
**Suche:** `@app.post("/api/shell")` → gesamten Block löschen (~50 Zeilen)
**Test:** `curl -X POST http://localhost:7842/api/shell` → 404

### 2. Groq API Key aus Git-History tilgen
Key `gsk_ZVWVs...` wurde im Chat geteilt (nicht im Repo)

### 3. API-Token rotieren
`L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA` → vor Release erneuern

---

## 🔧 Bekannte Bugs

### 4. CronJob_0715 – Deutsch-Anweisung testen
Mission-Fix deployed (15:09) – greift erst beim nächsten Run um 07:15 Uhr

### 5. Monitor_Netzwerk – Neuanlage braucht venv-Python
Wenn Agent gelöscht wird:
```bash
sudo systemctl stop piclaw-agent
/opt/piclaw/.venv/bin/python3 -c "
from piclaw.agents.sa_registry import SubAgentDef, SA_REGISTRY_FILE
from dataclasses import asdict; import json
p = SA_REGISTRY_FILE; d = json.loads(p.read_text())
agent = SubAgentDef(name='Monitor_Netzwerk', description='Netzwerk-Monitoring: neue Geraete - alle 5 Minuten',
    mission='Direct mode', tools=['check_new_devices','network_scan'],
    schedule='interval:300', notify=True, direct_tool='check_new_devices', created_by='system')
d[agent.id] = asdict(agent); p.write_text(json.dumps(d, indent=2)); print('OK:', agent.id)
"
sudo systemctl start piclaw-agent
```

---

## ✅ Session 5 komplett erledigt

### Bugs gefixt
- `piclaw briefing` NameError → `if __name__` ans Ende verschoben ✅
- camera.py PermissionError → lazy `_ensure_capture_dir()` ✅
- Camera-Tools in agent.py registriert ✅
- CronJob Mission Deutsch-Anweisung ✅
- `piclaw briefing send` hub.close() Warning ✅

### Features
- **Direct Tool Mode:** Monitor_Netzwerk 0 LLM-Calls/Run ✅ (864→0/Tag)
- **ClawHub Integration:** `piclaw skill install/search/list/remove` ✅
  - API: `https://wry-manatee-359.convex.site/api/v1/`
  - `piclaw skill install caldav-calendar` funktioniert ✅
- **Skill-Auto-Injection:** Installierte Skills in System-Prompt ✅
  - `soul.load_installed_skills()` injiziert SKILL.md in jeden Chat
- **Speicherbereinigung:** 16GB → 12GB (-4GB Ollama CUDA) ✅

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Camera-Tools vollständig integriert |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE/EN/ES) |

---

## 🛠️ Entwicklungs-Tool (vor Release entfernen!)

```javascript
window.pi = async (cmd, timeout=30) => {
    const r = await fetch('/api/shell', {
        method: 'POST',
        headers: new Headers({'Authorization': 'Bearer L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA', 'Content-Type': 'application/json'}),
        body: JSON.stringify({cmd, timeout})
    });
    const d = await r.json();
    return d.stdout || d.stderr || d.error;
};
```

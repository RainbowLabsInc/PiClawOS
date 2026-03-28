# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-03-28 (Session 5 – Final)
# Version: 0.15.3

---

## ⚠️ VOR RELEASE (Pflicht)

### 1. /api/shell Endpoint entfernen
**Datei:** `piclaw-os/piclaw/api.py`  
**Suche:** `@app.post("/api/shell")` → gesamten Block löschen  
**Test:** `curl -X POST http://localhost:7842/api/shell` → muss 404 zurückgeben

### 2. Groq API Key aus Git-History tilgen
Key `gsk_ZVWVs...` wurde im Chat geteilt (nicht im Repo selbst)

### 3. API-Token rotieren
`L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA` → vor Release neu generieren

---

## 🔧 Bekannte Issues

### 4. Neuer Sub-Agent via API → Daemon-Neustart nötig
Die API schreibt in `subagents.json`, aber der Daemon lädt die Registry nur beim Boot.
→ Roadmap: Registry-Reload via IPC-Signal (kein Neustart mehr nötig)

---

## ✅ Session 5 – komplett erledigt

### Bugs gefixt
- Doppel-Telegram: piclaw-api startete auch Sub-Agenten → `start_sub_agents=False` ✅
- Monitor_Gartentisch sendete Netzwerk-Heartbeat → Heartbeat-Guard auf `direct_tool` ✅
- `__NO_NEW_RESULTS__` Token: Marketplace sendet keine Nachricht wenn nichts Neues ✅
- 3× SearchAssistant Anhäufung → Startup-Cleanup in runner.py ✅
- http_fetch aus CronJob-Fallback entfernt ✅
- `piclaw briefing` NameError ✅
- camera.py PermissionError → lazy mkdir ✅

### Features
- **Monitor_Netzwerk als geschützter Sicherheits-Agent:**
  - `_PROTECTED_AGENTS = {"Monitor_Netzwerk"}` in sa_tools.py
  - Tool-Handler blockieren Stop/Delete → ⛔ Fehlermeldung
  - REST-API blockiert DELETE/STOP → HTTP 403
  - Auto-Recreate beim Boot falls fehlt
- **Direct Tool Mode:** 0 LLM-Calls beim Netzwerk-Scan ✅
- **ClawHub:** `piclaw skill install/search/list/remove` ✅
- **Skill-Auto-Injection** in System-Prompt ✅
- **Speicher:** 16GB → 12GB ✅

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System + Registry-Reload via IPC |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Kamera-Tools vollständig integriert |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE/EN/ES) |

---

## 🛠️ DEV-Tool (vor Release entfernen!)

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

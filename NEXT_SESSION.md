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
`L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA` → vor Release neu generieren:
```bash
piclaw config set api_token $(openssl rand -base64 32)
```

---

## ✅ Session 5 – alles erledigt

### Bugs gefixt
- `piclaw briefing` NameError → behoben ✅
- camera.py PermissionError → lazy mkdir ✅
- Camera-Tools in agent.py registriert ✅
- CronJob Mission Deutsch-Zwang ✅
- `piclaw briefing send` hub.close() Warning ✅
- 3× SearchAssistant Anhäufung → Startup-Cleanup in runner.py ✅
- http_fetch aus CronJob-Fallback entfernt ✅
- README + CHANGELOG auf v0.15.3 aktualisiert ✅

### Features
- Direct Tool Mode: Monitor_Netzwerk 0 LLM-Calls ✅
- ClawHub Integration: `piclaw skill install/search/list/remove` ✅
- Skill-Auto-Injection in System-Prompt ✅
- Speicher: 16GB → 12GB (-4GB Ollama CUDA) ✅

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

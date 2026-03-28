# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-03-28 (Session 4)
# Version: 0.15.3

---

## ⚠️ VOR RELEASE (Pflicht)

### 1. /api/shell Endpoint entfernen
**Datei:** `piclaw-os/piclaw/api.py`
**Suche:** `@app.post("/api/shell")`
**Block löschen** (~50 Zeilen bis zur nächsten `@app.` Annotation)
**Test:** `curl -X POST http://localhost:7842/api/shell` → muss 404 zurückgeben

### 2. Groq API Key aus Git-History tilgen
```bash
# BFG Repo Cleaner (empfohlen):
java -jar bfg.jar --replace-text secrets.txt PiClawOS.git
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
```

### 3. Dashboard API-Token rotieren
Aktuell: `L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA`
```bash
piclaw config set api_token $(openssl rand -base64 32)
```

---

## 🔧 Kurzfristige Features

### 4. Camera-Tools registrieren
`piclaw/hardware/camera.py` hat TOOL_DEFS aber fehlt in `agent.py _build_tools()`:
```python
from piclaw.hardware import camera as camera_mod
if camera_mod.is_available():
    _reg(camera_mod.TOOL_DEFS, camera_mod.build_handlers())
```

### 5. Willhaben Kategorie-Filter
"Notebooks" findet auch Taschen und RAM → `category_id` muss noch gemappt werden

### 6. github_token in config.toml
```toml
[updater]
repo_url = "https://github.com/RainbowLabsInc/PiClawOS"
github_token = "ghp_..."
```

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose (ohne HA) |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram Anfragen) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Camera-Tools vollständig integriert |

---

## ✅ Session 4 erledigt

- Telegram-Bug gefixt (send ohne async with → Response nie gelesen → stiller 400 Fehler)
- Markdown-Bug gefixt (**bold** → *bold* für Telegram MarkdownV1)
- Netzwerk-Monitor Heartbeat: 1x/Stunde statt alle 5 Min
- Heuristik: "alles quiet außer Gerätekennzeichen" – robust gegen LLM-Freitext
- Briefing-Uhrzeiten im Setup konfigurierbar (HH:MM → Cron)
- /api/shell Endpoint für direkte Pi-Verbindung implementiert (DEV ONLY)
- IPC-Fix: /api/subagents/{id}/run triggert jetzt den Daemon (nicht API-Prozess)

---

## 🛠️ Entwicklungs-Tool (solange aktiv)

```javascript
window.pi = async (cmd, timeout=30) => {
    const r = await fetch('/api/shell', {
        method: 'POST',
        headers: new Headers({
            'Authorization': 'Bearer L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA',
            'Content-Type': 'application/json'
        }),
        body: JSON.stringify({cmd, timeout})
    });
    const d = await r.json();
    return d.stdout || d.stderr || d.error;
};
```

# PiClaw OS – Offene Punkte für nächste Session
# Erstellt: 2026-03-28
# Fokus: Release-Vorbereitung

---

## ⚠️ VOR RELEASE (Pflicht)

### 1. /api/shell Endpoint entfernen
**Datei:** `piclaw-os/piclaw/api.py`
**Suche:** `@app.post("/api/shell")`
**Aktion:** Gesamten Block (~50 Zeilen) löschen
**Warum:** Erlaubt beliebige Shell-Befehle mit nur Bearer-Token – zu gefährlich für Produktion

```bash
# Auf dem Pi nach dem Entfernen testen:
curl -X POST http://localhost:7842/api/shell \
  -H "Authorization: Bearer TOKEN" \
  -d '{"cmd":"id"}' 
# Muss 404 zurückgeben
```

### 2. Groq API Key aus Git-History entfernen
Der Key `gsk_ZVWVs...` wurde im Chat geteilt – muss aus Git getilgt werden:
```bash
# BFG Repo Cleaner (empfohlen):
java -jar bfg.jar --replace-text secrets.txt PiClawOS.git
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force

# Oder git filter-repo:
git filter-repo --replace-text <(echo "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==>REDACTED")
```

### 3. Telegram debuggen – Nachrichten kommen nicht an
Log sagt "Telegram-Notify OK (154 Zeichen)" aber Nachrichten fehlen:
```
piclaw messaging test
```
Dann in Log schauen: `strings /var/log/piclaw/agent.log | grep -i telegram`
Mögliche Ursachen: Bot-Token abgelaufen, Chat-ID falsch, Bot nicht in Chat

---

## 🔧 Kurzfristige Verbesserungen

### 4. github_token in config.toml eintragen
Damit `piclaw update` ohne Fehler läuft:
```toml
[updater]
repo_url = "https://github.com/RainbowLabsInc/PiClawOS"
github_token = "ghp_..."
```

### 5. Camera-Tools registrieren
`piclaw/hardware/camera.py` hat TOOL_DEFS aber fehlt in `agent.py _build_tools()`:
```python
# In agent.py _build_tools() ergänzen:
from piclaw.hardware import camera as camera_mod
if camera_mod.is_available():
    _reg(camera_mod.TOOL_DEFS, camera_mod.build_handlers())
```

### 6. Willhaben Kategorie-Filter
"Notebooks" findet auch Taschen und RAM-Riegel.
Willhaben unterstützt `category_id` Parameter – muss noch gemappt werden.

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose (ohne HA) |
| v0.17 | fail2ban Integration (SSH Brute-Force-Schutz) |
| v0.18 | Queue System (parallele CLI + Telegram Anfragen) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Camera-Tools vollständig integriert |

---

## 🔑 Laufende Konfiguration (Pi)

- **IP:** 192.168.178.120
- **Dashboard:** http://192.168.178.120:7842
- **Primary LLM:** Groq / moonshotai/kimi-k2-instruct (Prio 9)
- **Secondary:** NVIDIA NIM / meta/llama-3.3-70b-instruct (Prio 7)
- **CPU:** ~52°C (normal)

### Laufende Sub-Agenten
- `Monitor_Netzwerk` – alle 5 Min, Telegram bei neuen Geräten ✅
- `CronJob_0715` – täglich 07:15 Uhr, CPU-Temperatur ✅ (Telegram-Notify noch zu debuggen)

---

## 🛠️ Entwicklungs-Tools (nur lokal, nicht im Release)

### /api/shell – Browser-basierte Shell
Solange der Endpoint noch aktiv ist, im Browser-Kontext nutzbar:
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

// Beispiele:
pi('tail -20 /var/log/piclaw/agent.log').then(console.log)
pi('systemctl status piclaw-agent --no-pager').then(console.log)
pi('strings /var/log/piclaw/agent.log | grep Telegram | tail -10').then(console.log)
```

**API-Token:** L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA  
⚠️ Vor Release rotieren!

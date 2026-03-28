# PiClaw OS – Offene Punkte für nächste Session
# Erstellt: 2026-03-28
# Letztes Update: 2026-03-28 (Session 3 – IPC, Shell-API, Sub-Agent Debugging)

---

## ✅ Gefixt & implementiert in Session 3

### 1. /api/shell – Entwicklungs-Tool (⚠️ VOR RELEASE ENTFERNEN)
- POST /api/shell mit Auth-Token erlaubt direkte Shell-Befehle über den Browser
- Implementiert in: `piclaw/api.py`
- Zweck: Schnelles Debugging ohne manuelle Copy-Paste vom Pi
- **MUSS vor öffentlichem Release deaktiviert/entfernt werden!**
- Entfernen: Den gesamten Block in api.py löschen (siehe Abschnitt unten)

### 2. IPC zwischen piclaw-api und piclaw-agent (Bug-Fix)
- Root Cause: API und Daemon sind zwei separate Python-Prozesse
- /api/subagents/{id}/run rief _execute() im falschen Prozess auf
- Fix: File-basiertes IPC via /etc/piclaw/ipc/run_now_<id>.trigger
- Neue Datei: `piclaw/ipc.py`
- Getestet: Trigger-Datei wird erstellt, Daemon konsumiert sie in <1s ✅

### 3. Telegram-Notify funktioniert
- Monitor_Netzwerk → Telegram-Notify OK ✅
- CronJob_0715 → Telegram-Notify OK (154 Zeichen) ✅
- Log-Eintrag: `Sub-agent 'X': Telegram-Notify OK (NNN Zeichen)`

### 4. piclaw llm test <n> – neuer CLI-Subcommand
- Testet ein LLM-Backend direkt: `piclaw llm test groq-fallback`
- Zeigt Latenz und Antwort

### 5. Groq – Kimi K2 als Primary
- Model: moonshotai/kimi-k2-instruct auf api.groq.com
- Prio 9 (höher als NIM mit Prio 7)
- Tool-Calling funktioniert ✅

---

## 🔧 Noch offen / Nächste Schritte

### A. Telegram-Nachricht von CronJob_0715 nicht angekommen
- Log sagt "Telegram-Notify OK (154 Zeichen)" aber User hat nichts erhalten
- Nächste Session: Telegram-Adapter direkt debuggen
  ```bash
  strings /var/log/piclaw/agent.log | grep -i "telegram\|send\|error" | tail -20
  ```
- Mögliche Ursache: Telegram Bot-Token abgelaufen? Chat-ID falsch?
- Test: `piclaw messaging test`

### B. ⚠️ /api/shell VOR RELEASE ENTFERNEN
- Datei: `piclaw/api.py`
- Zu entfernender Block: Suche nach `@app.post("/api/shell")`
- Der gesamte Endpoint (ca. 40 Zeilen) muss entfernt werden
- Alternativ: Hinter Flag `if cfg.dev_mode:` schützen

### C. Cron-Agent Aufgabenbeschreibung
- "jeden tag" landet als Aufgabe statt "die CPU Temperatur meldet"
- Fix ist im Code (Regex), aber bestehender Agent hat noch alte Beschreibung
- Testen: neuen Cron-Agenten erstellen und Mission im Log prüfen

---

## 📋 Roadmap (längerfristig)

1. **fail2ban Integration** (v0.17)
2. **Emergency Shutdown** via schaltbare Steckdose (v0.16)
3. **Queue System** – parallele CLI + Telegram Anfragen
4. **Willhaben Kategorie-Filter** – "Notebooks" findet auch Taschen
5. **Camera-Tools registrieren** – TOOL_DEFS vorhanden, fehlt in _build_tools()

---

## 🔑 Wichtige Infos

### Pi
- IP: 192.168.178.120
- SSH: pi@192.168.178.120
- Dashboard: http://192.168.178.120:7842
- API Token (Dashboard): REDACTED_PICLAW_TOKEN

### LLM-Backends
- Primary: groq-fallback / moonshotai/kimi-k2-instruct (Prio 9)
- Secondary: openai-default / meta/llama-3.3-70b-instruct (Prio 7, NIM)
- Tertiary: nemotron-nvidia / nvidia/llama-3.1-nemotron-70b-instruct (Prio 6)
- Lokal: Gemma 2B Q4 (automatischer Fallback)

### Laufende Sub-Agenten
- Monitor_Netzwerk – alle 5 Min Netzwerk-Scan, Telegram bei neuen Geräten
- CronJob_0715 – täglich 07:15 Uhr CPU-Temperatur, Telegram-Notify

---

## ⚠️ VOR RELEASE CHECKLISTE

1. [ ] /api/shell Endpoint aus api.py entfernen
2. [ ] Groq API Key aus Git-History entfernen (wurde im Chat geteilt)
       → git filter-branch oder BFG Repo Cleaner
3. [ ] API-Token (Dashboard) rotieren
4. [ ] Pi-IP aus Dokumentation entfernen oder ersetzen
5. [ ] NEXT_SESSION.md auf keine Keys prüfen

---

## 📐 Architektur-Notizen

### Zwei-Prozess-Architektur
```
piclaw-api  (Port 7842)    ←→   HTTP/REST/WS   ←→   Browser/CLI
piclaw-agent (Daemon)      ←→   Telegram/HA    ←→   Messaging

IPC: /etc/piclaw/ipc/
  API schreibt:  run_now_<id>.trigger
  Daemon liest:  poll_triggers() alle 1s (Background-Task)
  → Daemon führt Sub-Agent mit vollem LLM+Tools+Messaging aus
```

### /api/shell Entwicklungs-Endpoint (TEMPORÄR)
```
POST http://192.168.178.120:7842/api/shell
Authorization: Bearer <token>
Content-Type: application/json

Body: {"cmd": "tail -20 /var/log/piclaw/agent.log", "timeout": 30}

Response: {"ok": true, "stdout": "...", "stderr": "...", "returncode": 0}
```

Im Browser-Kontext nutzbar als:
```javascript
window.pi = async (cmd) => {
    const r = await fetch('/api/shell', {
        method: 'POST',
        headers: new Headers({
            'Authorization': 'Bearer REDACTED_PICLAW_TOKEN',
            'Content-Type': 'application/json'
        }),
        body: JSON.stringify({cmd, timeout: 30})
    });
    const d = await r.json();
    return d.stdout || d.stderr || d.error;
};

// Beispiele:
pi('tail -20 /var/log/piclaw/agent.log').then(console.log)
pi('systemctl status piclaw-agent').then(console.log)
pi('strings /var/log/piclaw/agent.log | grep "Telegram"').then(console.log)
```

**SICHERHEITSHINWEIS:** Dieser Endpoint erlaubt beliebige Shell-Befehle
auf dem Pi (mit einfacher Blocklist). Nur für Entwicklung/Debugging!

# PiClaw OS – Offene Punkte für nächste Session
# Erstellt: 2026-03-28
# Letztes Update: 2026-03-28 (Bugfixes applied)

---

## ✅ Gefixt in dieser Session

### 1. Tool-Calling Halluzinationen (Bug #2) – GEFIXT
- **Root Cause A:** `api.py` setzte `tool_choice="auto"` für Llama 3.3 auf NIM,
  obwohl INV_024 dies verbietet → entfernt für ALLE NIM-Modelle.
- **Root Cause B:** `agent.py` Streaming-Heuristik (Zeile 1047) prüfte ob
  gestreamer Text mit `{`/`[`/`<` begann – wenn nicht, wurde der `chat()`-Aufruf
  mit Tools **übersprungen** und die halluzinierte Text-Antwort direkt verwendet.
- **Fix:** Wenn Tools definiert sind, wird IMMER `chat()` statt `stream_chat()`
  verwendet. Streaming nur noch für reine Text-Responses ohne Tools.
- Dateien: `piclaw/llm/api.py`, `piclaw/agent.py`

### 2. `piclaw update` hängt (Bug #1) – GEFIXT
- **Root Cause:** `git pull` wurde ohne Authentifizierung aufgerufen.
  Bei einem privaten Repo wartet git auf Passwort-Eingabe bis zum 120s-Timeout.
- **Fix:** `UpdaterConfig` hat neues Feld `github_token`. Updater setzt
  `git remote set-url origin` mit Token-Auth vor jedem git-Befehl.
- Dateien: `piclaw/config.py`, `piclaw/tools/updater.py`
- **TODO:** `github_token` in `/etc/piclaw/config.toml` eintragen:
  ```toml
  [updater]
  repo_url = "https://github.com/RainbowLabsInc/PiClawOS"
  github_token = "ghp_..."
  ```

---

## 🔧 Noch offen

### 3. Groq als primäres Backend noch nicht getestet
- Priorität wurde auf 9 gesetzt (höher als NIM mit 7)
- Hot-Reload Fix wurde implementiert (7d82bbf) aber noch nicht live getestet
- Test: nach `piclaw update` → `piclaw` → "Bist du da?" → Log prüfen ob Groq antwortet
- Mit dem Tool-Calling Fix sollte Groq jetzt `tool_choice="auto"` korrekt bekommen
  (kein NIM-Sonderfall)

---

## ✅ Fertig aber noch nicht getestet

### Cron-Job Sub-Agent
- `cron:<expr>` Schedule ist implementiert (croniter installiert)
- Noch kein aktiver Cron-Agent vorhanden
- Test: "Erstelle einen Agenten der jeden Tag um 8 Uhr die Temperatur meldet"

### Netzwerk-Monitoring Sub-Agent
- Implementiert: `_detect_network_monitor_intent()` + `_create_network_monitor_agent()`
- nmap muss installiert sein: `sudo apt install nmap -y`
- Test: "Überwache mein Netzwerk auf neue Geräte"

### LLM Hot-Reload
- Registry lädt sich neu wenn `llm_registry.json` sich ändert
- Test: `piclaw llm update groq-fallback --priority 9` → sofort ohne Neustart aktiv?

---

## 📋 Nächste Features (Roadmap)

1. **CLAUDE_REBUILD.md aktualisieren** auf v0.15.2 Stand
2. **fail2ban Integration** (IP-Blocking bei Brute-Force)
3. **Emergency Shutdown** ohne Home Assistant (direkt via schaltbare Steckdose)
4. **Tool-Calling Fix** für NIM/Groq – `tool_choice: required` testen ← TEILWEISE ERLEDIGT
5. **Queue System v0.14** – parallele CLI + Telegram Anfragen
6. **Willhaben Umkreis-Suche** – PLZ → Bundesland-Mapping für areaId

---

## 🔑 Wichtige Infos

- Pi IP: 192.168.178.120
- Primäres LLM: NVIDIA NIM / meta/llama-3.3-70b-instruct (Prio 7)
- Fallback LLM: Groq / llama-3.3-70b-versatile (Prio 9 – soll primary werden)
- Lokales Fallback: Ollama / qwen2.5:1.5b (nur wenn explizit konfiguriert)
- Letzter erfolgreicher `piclaw doctor`: alle grün, CPU 49-51°C

# PiClaw OS – Changelog

## v0.15.1 – 2026-03-21 🎉

### Highlights
- **Marketplace-Suche funktioniert!** PLZ-basierte Suche auf Kleinanzeigen.de vollständig funktionsfähig
- **Multi-Provider LLM** – NVIDIA NIM, Google Gemini, Mistral, Fireworks AI, Anthropic, OpenAI per Auto-Detect
- **`piclaw update`** – Self-Update via git pull
- **`piclaw debug`** – Integrierte Debug-Scripts für schnelle Fehlerdiagnose

### Bugfixes
- WebSocket keepalive bei langen Operationen (Marketplace, LLM)
- `tool_choice` für NVIDIA NIM entfernt (verursachte HTTP 400)
- Gemini Chat-Endpoint `/v1beta/openai/chat/completions` korrekt gesetzt
- PLZ-Extraktion aus Query-String robuster (Lookahead/Lookbehind)
- Marketplace: direkter Handler-Aufruf bei klarer Intent-Erkennung
- `/var/log/piclaw/` Rechte für piclaw-User gesetzt
- Editable install zeigt via Symlink auf `piclaw-os/piclaw/` → `git pull` reicht
- `cmd_update` / `cmd_debug` vor `main()` definiert (NameError behoben)
- HTTP 429 (Quota) im Wizard als gültiger Key behandelt
- Auto-Detect in "Weitere Backends" Wizard-Schritt integriert

### Neue Features
- **Auto-Detect Provider**: Key eingeben → Provider/Modell automatisch erkannt
  - `sk-ant-` → Anthropic Claude
  - `nvapi-` → NVIDIA NIM (Nemotron 70B)
  - `AIza` → Google Gemini 2.0 Flash
  - `fw-` → Fireworks AI (Llama 3.1 70B)
  - `sk-` → OpenAI / Mistral (via /v1/models Probe)
- **`piclaw debug`**: Debug-Scripts in `tests/debug/` direkt ausführbar
- **`piclaw update check`**: Ausstehende Commits anzeigen
- **Sudoers-Regel**: piclaw-User kann eigene Services ohne Passwort neustarten
- **`fix_install_path.sh`**: Einmaliges Repair-Script für bestehende Installationen
- Regex-Patterns in marketplace.py vorcompiliert (Performance)
- `query_summary()` in MetricsDB für effiziente Briefing-Generierung
- Blocking I/O (psutil, sysfs temp) in asyncio.to_thread ausgelagert
- Command Injection in services.py behoben (subprocess_exec statt shell)

---

## v0.15.0 – 2026-03-14

- Version bump von 0.13.3 auf 0.15.0
- boot/-Spiegel-Duplikat eliminiert (`make sync` Workflow)
- Handbücher DE + EN erstellt
- AgentMail, SearchAssistant, InstallerAgent, Tandem Browser integriert
- Netzwerk-Monitoring (nmap)
- LLM Multi-Router mit thermischer Steuerung
- Nemotron 70B als zweites NIM-Backend

---

## v0.13.3 – 2026-02-xx

- Erste stabile Version
- Gemma 2B lokales Modell
- Kleinanzeigen Marketplace-Tool (Grundversion)
- Watchdog, Crawler, API, Agent Services
- Telegram-Integration
- Web-Dashboard

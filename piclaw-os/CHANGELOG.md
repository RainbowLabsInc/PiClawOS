# PiClaw OS – Changelog

## v0.15.2-rc – 2026-03-27

### Technical Debt bereinigt
- **T1 – llama.cpp verbose Output** (`llm/local.py`)
  - `_suppress_stderr()` → `_suppress_output()`: jetzt fd 1 (stdout) + fd 2 (stderr)
  - `LLAMA_CPP_LOG_LEVEL=0`, `GGML_LOG_LEVEL=0`, `LLAMA_LOG_LEVEL=4` vor Import gesetzt
  - Fix: `_infer()` nutzte hardcodierte Phi3-Stop-Tokens – jetzt `_stop_tokens(model_path)`
- **T3 – Dashboard Version** (`piclaw/__init__.py`, `api.py`, `web/index.html`)
  - Single Source of Truth: `__version__ = "0.15.1"` in `__init__.py`
  - `FastAPI(version=__version__)` statt hardcodierter `"0.8.0"`
  - `/api/stats` gibt `version`-Feld zurück
  - Dashboard Header: `hostname · ip · v0.15.1`
  - Neue Version-Karte im Stats-Grid (zeigt Version + Agent-Name)
- **T4 – boot/ pyproject.toml** (`boot/piclaw-src/pyproject.toml`)
  - Version 0.15.0 → 0.15.1
  - `scrapling>=0.2` ergänzt (fehlte)
  - `make sync` hält dies künftig automatisch aktuell
- **T2 – GitHub Token** entfällt mit Public Release

### piclaw doctor erweitert (`cli.py`)
- scrapling-Verfügbarkeitscheck
- Symlink-Check: `/opt/piclaw/piclaw` muss Symlink sein (INV_021)
- Log-Dir-Check: `/var/log/piclaw` Owner = piclaw (INV_022)
- IPC-Dir-Check: `/etc/piclaw/ipc` chmod 1777 (Watchdog)

### Neue Debug-Scripts (`tests/debug/`)
- **`test_debug_install.py`** — Installationsprüfung:
  Python-Version, piclaw-Import, CONFIG_DIR, Symlink, Log-Dir, IPC-Rechte,
  Sudoers, pyproject.toml build-backend, alle Abhängigkeiten, lokales Modell
- **`test_debug_services.py`** — Services & Konnektivität:
  systemd is-active (4 Services + Timer), HTTP /health, WebSocket + Ping,
  Log-Analyse auf Errors/Tracebacks, QMD CPU-Check, Timer-Status

### Wizard UX (`wizard.py`)
- **Status-Badges pro Block**: ✅/⚠️/⬜ mit Kurzhinweis was fehlt
- **Dynamischer Titel**: "Ersteinrichtung" nur bei frischer Installation, sonst "Einstellungen"
- **Offene Blöcke**: Nach Abschluss Hinweis welche Blöcke noch einzurichten sind
- Hilfsfunktion `_block_status(name, cfg)` ausgelagert

---

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

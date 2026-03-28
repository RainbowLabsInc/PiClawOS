# PiClaw OS – Changelog

## v0.15.3 – 2026-03-28 🔔

### Fixes

#### Telegram
- `send()` nutzt jetzt `async with` → Response-Status wird geprüft
- Bei HTTP 400: Fehler wird geloggt + Fallback ohne `parse_mode` (plain text)
- `**Name**` → `*Name*` Konvertierung vor dem Senden (MarkdownV1-Fix)
- runner.py Header war `**{name}**` → jetzt `*{name}*`
- Root Cause: Nachrichten kamen trotz "Notify OK" nicht an, weil Response nie gelesen wurde

#### Netzwerk-Monitor Heartbeat
- Vorher: Alle 5 Minuten eine Telegram-Nachricht (LLM ignorierte Mission)
- Nachher: 1x pro Stunde Heartbeat, sofort bei neuem Gerät
- Fix: `_is_quiet_network_result()` Heuristik – erkennt "alles ruhig" unabhängig
  von der LLM-Formulierung. Logik: alles ist quiet außer der Text enthält
  explizite Gerätekennzeichen (mac:, ip:, 🚨, "neues gerät" etc.)
- Mission verschärft: explizite Anweisung FALL A / FALL B mit Token-Pflicht

### Direct Tool Mode (Netzwerk-Monitor)
- Monitor_Netzwerk läuft jetzt ohne LLM: 0 API-Calls bei ruhigem Netzwerk
- Neues Feld `direct_tool` in SubAgentDef – Tool wird direkt aufgerufen
- Bei neuem Gerät: Tool gibt Gerätedaten zurück → Heartbeat-Heuristik
  erkennt MAC/IP und sendet sofort (kein LLM für "alles ruhig")
- Vorher: 864 Groq-Calls/Tag | Nachher: 0 Calls/Tag (nur nmap)
- Technisch: _direct_tool_call() in runner.py, direct_tool Feld in sa_registry.py
  und api.py POST /api/subagents leitet das Feld durch

#### Briefings (Setup)
- Morgen- und Abend-Briefing Uhrzeit im `piclaw setup` konfigurierbar
- Eingabe HH:MM → wird zu Cron-Expression umgewandelt und in routines.json gespeichert


## v0.15.2 – 2026-03-28 🔒⚡

### Highlights
- **Groq / Kimi K2 als Primary-LLM** – schnellstes verfügbares Modell, kostenlos, Tool-Calling
- **Network Security Tools** – Tarpit, Honey Traps (Labyrinth/Rickroll/Sinkhole), IP-Block, WHOIS, Abuse-Reports
- **IPC zwischen API und Daemon** – run_now Trigger via /etc/piclaw/ipc/ (2-Prozess-Fix)
- **Sub-Agenten: Telegram-Notify** – Ergebnisse werden zuverlässig per Telegram gesendet
- **Willhaben Standortfilter** – areaId-basiert, funktioniert für alle AT-Städte

### Neue Features

#### 🔒 Network Security (piclaw/tools/network_security.py)
- `whois_lookup` – IP-Eigentümer recherchieren
- `block_ip` – IP via iptables DROP dauerhaft sperren
- `tarpit_ip` – Angreifer verlangsamen (TCP-DROP auf Port)
- `generate_abuse_report` – Strukturierter ISP-Abuse-Report
- `deploy_honey_trap` – Täuschfallen: labyrinth/rickroll/sinkhole
- `stop_honey_trap` / `list_honey_traps` – Fallen verwalten
- Lokale IPs (RFC1918) automatisch gegen aggressive Aktionen geschützt

#### 🤖 LLM
- Groq als empfohlener Primary-Provider (Kimi K2 / Llama 3.3 70B)
- `piclaw llm test <n>` – Backend direkt aus CLI testen
- Fallback-Parser für Text-basierte Tool-Calls (Groq-Bug-Workaround)
- `BackendConfig.__post_init__` – Priority/Temperature immer korrekt typisiert

#### 🛒 Marketplace
- Willhaben Standortfilter via areaId (?areaId=601 für Graz etc.)
- Stadtname-Erkennung in Suchanfragen (40+ Städte DE/AT)
- Einheitliche `_fetch_html` Kaskade: Scrapling → aiohttp → Tandem
- Query-Bereinigung für natürlichsprachliche Formulierungen ("ob es neue Anzeigen zu X gibt")

#### 👁️ Sub-Agenten
- Cron-Agent Shortcut: "Erstelle einen Agenten der täglich um HH:MM Uhr X tut"
- IPC-Fix: `/api/subagents/{id}/run` triggert jetzt den richtigen Prozess (Daemon)
- Sandbox-Fix: Cron-Agenten nutzen jetzt `thermal_status`/`pi_info` statt `shell` (BLOCKED_ALWAYS)
- Regex-Fix: Aufgabenbeschreibung wird korrekt aus Zeitangabe extrahiert

#### 🔌 API
- `/api/shell` Endpoint (⚠️ DEV ONLY – vor Release entfernen)
- `ws_ping_interval=None` in uvicorn – kein 1011-Keepalive-Timeout mehr
- IPC-Modul `piclaw/ipc.py` für saubere API↔Daemon-Kommunikation

### Bugfixes
- `TypeError: bad operand type for unary -: 'str'` in registry.py (priority als str)
- `WebSocket-Fehler: 1011 keepalive ping timeout` bei langen Marketplace-Searches
- `_detect_network_monitor_intent` feuerte auf Marketplace-Anfragen
- Groq Tool-Calls als Markdown-Code-Blöcke werden jetzt erkannt
- Willhaben: areaId wurde nie übergeben → österreichweite Suche statt lokale

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

# PiClaw OS – Changelog

## Unreleased 📧

### AgentMail Attribute-Fix
- **`tools/agentmail.py` + `wizard.py`** – AgentMail SDK liefert die
  Inbox-Adresse im Feld `inbox.email`, der Code las `inbox.email_address`
  und erzeugte so `AttributeError: 'Inbox' object has no attribute
  'email_address'` sobald eine reale Inbox abgefragt wurde. Defensiv
  beide Felder: `getattr(ib, "email", None) or getattr(ib, "email_address", "")`.
- **`cli.py` Doctor** – nutzt jetzt `cfg.agentmail.inbox_id` als primäre
  Quelle für die Anzeige der Inbox-Adresse, mit `email_address` als
  Fallback. Sonst zeigte Doctor dauerhaft "(keine Inbox)" obwohl die
  Inbox existierte und per `inbox_id` korrekt konfiguriert war.

## Unreleased 🐛🔇

### Daemon Silent-Crash Fix
- **`agent.py` Monitor_Pakete Auto-Boot** – `SubAgentDef(name=..., mission=...)`
  rief den Konstruktor ohne das Pflichtfeld `description` auf, was
  `TypeError: SubAgentDef.__init__() missing 1 required positional argument:
  'description'` in `agent.boot()` auslöste.
- **`daemon.py` Visibility-Hardening** – `agent.boot()` in Try/Except mit
  Crash-Log gewrappt. Grund: llama-cpp-python's `suppress_stdout_stderr()`
  macht `dup2(/dev/null, 1/2)` beim Model-Load. Jede Python-Logzeile nach
  dem Load landet im Nirvana, sobald der Logger-Handler auf `sys.stdout`
  oder `sys.stderr` schreibt. Die `TypeError` oben war komplett unsichtbar:
  `journalctl` leer nach `Local model loaded ✅`, systemd zeigte aber
  `active (running)` weil der Prozess im `_cancel_all_tasks()`-Cleanup
  hing. Sub-Agent-Scheduler, IPC-Polling, Thermal-Monitor, Proactive-Agent –
  alle nie gestartet. Wrapper schreibt Tracebacks direkt in
  `/etc/piclaw/crashes/daemon-boot-crash.log`.
- **Test** – `test_monitor_pakete_auto_boot_kwargs_complete` in
  `tests/test_registry.py` lockt die Auto-Boot-Kwargs, damit die Regression
  nicht zurückkehrt.



### Sub-Agent Crash Recovery
- **Typ-Coercion in `SubAgentDef`** – `timeout` und `max_steps` werden
  defensiv in `int` umgewandelt, sowohl beim Laden aus `subagents.json` als
  auch nach `PATCH /api/subagents/{id}`. Fallback auf Dataclass-Default bei
  unbrauchbaren Werten.
  Bug: Ein String-Wert in `timeout` ließ `asyncio.wait_for(..., timeout="300")`
  mit `TypeError: '<=' not supported between instances of 'str' and 'int'`
  crashen und erzeugte so einen Error-Loop der pro Interval eine Traceback-
  Nachricht an den Messaging-Hub verschickte (Sauer 505 Fall, 2026-04-17).
- **Auto-Restart für `_PROTECTED_AGENTS`** – `SubAgentRunner._on_done()`
  erkennt unerwartet beendete geschützte Agenten und re-armed mit
  Exponential-Backoff (2/4/8/16/32s, max 5 Versuche pro Stunde).
  Bug: Monitor_Netzwerk konnte still aus dem Scheduler verschwinden wenn
  `_run_loop` durch eine nicht abgefangene Exception endete. Die dokumentierte
  3-Layer-Schutzarchitektur griff erst beim nächsten Daemon-Boot.
- **Regressionstests** in `tests/test_registry.py`: 4 neue Tests decken
  String-Coercion beim Konstruktor, Garbage-Fallback, Legacy-JSON-Heilung und
  PATCH-Coercion ab.

## v0.17.0 – 2026-04-11 🧠🛒⚖️🔐

### Highlights
- **LLM Autonomie** – Dameon findet selbständig neue kostenlose LLM-Backends
- **Zoll-Auktion.de** – neue Suchplattform (Behörden-Versteigerungen, native PLZ + Umkreis)
- **Troostwijk Umkreissuche** – PLZ + Radius mit Haversine-Distanzfilter
- **4 Security-PRs gemergt** – Path-Traversal, Command-Injection, IP-Validierung
- **Wizard-Crashfix** – `None`-Werte in LocationConfig konnten TOML-Serialisierung crashen

### LLM Autonomie
- **`llm_discover` Tool:** Scannt Groq, NVIDIA NIM, Cerebras, OpenRouter nach freien Modellen
  - Provider MIT Key: holt Modell-Liste, testet Kandidaten, registriert automatisch
  - Provider OHNE Key: schlägt Anmeldung via Telegram vor mit Signup-URL
  - Ergebnis-Report mit registrierten + vorgeschlagenen Backends
- **Proaktive Discovery** im Health Monitor: läuft täglich automatisch (nicht nur bei Ausfällen)
- **Regex-Shortcut:** `llm_discover` funktioniert ohne LLM (20+ Trigger-Phrasen)
  - Löst das Henne-Ei-Problem: wenn alle Cloud-Backends down sind, braucht man keine um neue zu finden
- **Free-Tier-Whitelist:** 24 Modelle auf 4 Providern (Groq, NVIDIA, Cerebras, OpenRouter)
  - Neu: `openai/gpt-oss-120b`, `qwen/qwen3-32b`, `deepseek-ai/deepseek-r1`, `llama-4-scout`

### Marketplace: Zoll-Auktion.de
- `_search_zoll_auktion()`: HTML-Scraper für das Auktionshaus von Bund, Ländern und Gemeinden
- **Native PLZ + Umkreis** (20/50/100/250/500km serverseitig)
- Preis-Filter, Restzeit, Gebote-Anzahl werden geparst
- Intent-Detection: "zoll-auktion", "zollauktion" in allen Keyword-Listen
- Emoji: ⚖️ in Text + Telegram Output

### Marketplace: Troostwijk Umkreissuche
- **PLZ → Koordinaten** via zippopotam.us (gecacht)
- **Stadt → Koordinaten** via OpenStreetMap Nominatim (gecacht)
- **Haversine-Distanzberechnung** filtert Auktionen nach Radius um PLZ-Zentrum
- Nutzt `collectionDays[].city` aus der Troostwijk-API für Standort-Extraktion
- Intent-Detection: erkennt PLZ + Radius aus natürlicher Sprache
- Stadtfilter jetzt auch gegen `collectionDays` (nicht nur Auktionsname)

### Security PRs gemergt
- **#123** 🛡️ Path-Traversal in `write_workspace_file` (.resolve() + is_relative_to())
- **#128** 🛡️ IP-Validierung vor Shell-Aufrufen in `network_security.py`
- **#132** 🛡️ Command-Injection in `updater.py` (shlex.quote)
- **#135** 🛡️ `network.py` komplett auf subprocess_exec umgestellt (kein Shell mehr)

### Feature PRs gemergt
- **#125** ⚙️ Async-Sensors-Migration (native async statt Thread-Pool)
- **#133** ⚙️ Igor: Timezone-Setup, Doctor-Timeout, Query-Fixes
- **#129** ⚙️ Location-Regex-Fix + City-Name-Leakage

### Bugfixes
- **Wizard-Crash:** `config.save()` crashte bei `None`-Werten in LocationConfig
  - Fix: `_strip_none()` entfernt `None` rekursiv vor TOML-Serialisierung
- **LLM-Discover-Routing:** Anfragen an lokales Modell geroutet statt Tool direkt aufzurufen
  - Fix: Regex-Shortcut im Dispatch-Chain (wie HA-Shortcuts, 0 Tokens)

## v0.15.4 – 2026-03-28 🏠🔧🧠

### Highlights
- **Home Assistant Integration** – HA-Befehle per Telegram, 11 Tools registriert
- **Smart LLM Routing** – HA-Befehle laufen auf dediziertem groq-actions Backend (Llama 3.3, 30k TPM)
- **HA-Shortcut** – Einfache Befehle (Licht an/aus) ohne LLM, 0 Token, <100ms
- **LLM Health Monitor** – Automatische Selbstheilung bei ausgefallenen Modellen
- **NVIDIA NIM gefixt** – nemotron (404) → Llama 4 Maverick auto-ersetzt
- **Monitor_Netzwerk: Schutzarchitektur** – dreifach geschützt gegen Dameon/API

### Home Assistant
- `ha_mod.start()` läuft jetzt im API-Prozess VOR `Agent(_cfg)` → Tools korrekt registriert
- 11 HA-Tools: `ha_turn_on`, `ha_turn_off`, `ha_toggle`, `ha_get_state`, `ha_list_entities`, u.a.
- Fuzzy Entity-Suche: "Fernsehzimmer" → `light.licht_fernsehzimmer_switch_0`
- `turn_off` Typo behoben (`turn_of` → `turn_off`)
- HA-Shortcut: Schalt-Befehle direkt ohne LLM (~0ms, 0 Token)
  - Erkennt: `schalte/mach/licht + Raum + an/aus`
  - Antwort: "💡 eingeschaltet" / "🌑 ausgeschaltet"
- `piclaw doctor` zeigt: `Home Assist : ✅ verbunden`

### Smart LLM Routing
- Neues `groq-actions` Backend: `llama-3.3-70b-versatile` auf Groq (Priority 10)
  - Tags: `action, home_automation, query, german`
  - 30.000 TPM Free Tier (3x mehr als Kimi K2)
- Classifier: `_regex_classify()` als Stage 0 (< 1ms, kein LLM-Call)
  - HA-Aktionsmuster (Regex) → `action, home_automation` mit 95% Confidence
  - HA-Abfragemuster → `query, home_automation` mit 90% Confidence
- Neue Tags: `action`, `home_automation`, `query`
- Routing: "Licht an" → groq-actions | "Erkläre X" → groq-fallback (Kimi K2)

### LLM Health Monitor (`piclaw/llm/health_monitor.py`)
- Läuft stündlich als Background-Task im Daemon
- **404 (Modell entfernt):** `/models` API des Providers abfragen → Preferred-Liste → Similarity-Match → auto-update Registry
- **429 (Rate-Limit):** Priorität temporär senken, nach 1h wiederherstellen
- **500/Timeout (3×):** Backend deaktivieren + Telegram-Notify
- Provider-Support: Groq, NVIDIA NIM, Together AI, Cerebras, Mistral
- Telegram-Benachrichtigung bei Auto-Repair

### NVIDIA NIM Fix
- `nvidia/llama-3.1-nemotron-70b-instruct` vom Anbieter entfernt (404)
- Ersetzt durch `meta/llama-4-maverick-17b-128e-instruct` (Llama 4)
- Automatisch über Health Monitor entdeckt und repariert

### Bugs gefixt
- **Doppel-Send:** `piclaw-api` und `piclaw-agent` starteten beide Sub-Agenten → `start_sub_agents=False` in api.py
- **Monitor_Gartentisch sendet Netzwerk-Heartbeat:** Heartbeat-Guard nur noch bei `direct_tool` aktiv
- **`__NO_NEW_RESULTS__` Token:** `_intentionally_silent` Flag statt `result=""` (verhindert Fallback-Spam)
- **Monitor_Netzwerk leeres Ergebnis:** Direct-Tool ohne Ergebnis → `__NO_NEW_DEVICES__` statt Fallback-Loop
- **Silent-Token Bug:** `result=""` triggerte Fallback-Bericht alle 5 Min → Flag-basierter Fix
- **Groq TPM-Limit:** CalDAV-Skill entfernt, Context reduziert

### Monitor_Netzwerk Schutzarchitektur
- **Layer 1:** `_PROTECTED_AGENTS` in sa_tools.py → LLM-Tool-Calls blockiert (⛔ Fehlermeldung)
- **Layer 2:** `api.py` REST-API → `DELETE/STOP` gibt HTTP 403 zurück
- **Layer 3:** `agent.boot()` → Auto-Recreate falls fehlt beim Start
- `piclaw doctor`: `Sub-agent scheduler skipped (managed by daemon)` in API-Prozess


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

### ClawHub Integration
- Neues Tool-Modul `piclaw/tools/clawhub.py` – Skills von clawhub.ai installieren
- API: `https://wry-manatee-359.convex.site/api/v1/`
- `clawhub_search()`, `clawhub_info()`, `clawhub_install()`, `clawhub_list_installed()`, `clawhub_uninstall()`
- Neuer CLI-Befehl: `piclaw skill install/search/list/remove <slug>`
- Installierte SKILL.md Dateien werden automatisch in jeden System-Prompt injiziert
- `/etc/piclaw/skills/<slug>/` mit korrekter piclaw:piclaw Ownership im install.sh

### Bug-Fixes (Session 5)
- `piclaw briefing` NameError: `if __name__ == "__main__"` stand vor `cmd_briefing()` – ans Ende verschoben
- `camera.py` PermissionError: modul-level `mkdir()` durch lazy `_ensure_capture_dir()` ersetzt
- Camera-Tools in `agent.py` registriert (waren nie eingebunden)
- CronJob Mission: Explizite Deutsch-Anweisung damit LLM nicht auf Englisch antwortet
- `piclaw briefing send`: `hub.close()` fehlte → Unclosed session Warning behoben

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

---

## Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Camera-Tools vollständig integriert |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE/EN/ES) – Wizard, CLI, Agent reagiert frei in Nutzersprache |

### v1.1 Mehrsprachigkeit – Konzept

- **Wizard/CLI:** i18n-Dict mit ~172 übersetzbaren Strings, Sprachauswahl am Setup-Start
- **Agent Dameon:** Reagiert bereits jetzt frei auf die Sprache des Nutzers (LLM-Fähigkeit)
  Explizite SOUL.md-Direktive: "Antworte immer in der Sprache des Nutzers"
- **Sprachen:** Deutsch (primär), English, Español
- **Aufwand:** ~2 Sessions nach Release


## v0.16.0 – 2026-04-05 🔐🛒🌍

### Highlights
- **Security-Audit abgeschlossen** – 6 Schwachstellen behoben (SEC-1 bis SEC-6)
- **Troostwijk Auktions-Monitor** – neue Auktions-Events nach Land/Stadt überwachen
- **Automatische Zeitzonenerkennung** – LocationConfig für TZ-Setup aus Koordinaten
- **Stabilitäts-Debugrunde** – 16 Bugs behoben (Event-Loop, WebSocket, LLM-Router)

### Security
- **SEC-1 KRITISCH:** WhatsApp Webhook Auth-Bypass geschlossen (`verify_signature` → `return False` wenn kein `app_secret`)
- **SEC-2 KRITISCH:** UFW-Regel auf RFC-1918 LAN beschränkt (war internet-weit offen)
- **SEC-3 KRITISCH:** GitHub-Token aus Prozessliste entfernt → `git credential store`
- **SEC-4:** CORS `allow_origins=["*"]` → `LocalNetworkCORSMiddleware` (nur LAN)
- **SEC-5:** Security-Header (X-Frame-Options, CSP, no-store) + Token nur für lokale IPs
- **SEC-6:** Shell Command-Chaining via Metacharakter geblockt (`&&`, `||`, `;`, `|`, `$(` etc.)
- **SECURITY.md** mit vollständiger Audit-Dokumentation erstellt

### Neue Features
- **Troostwijk Auktions-Monitor:** `_search_troostwijk_auctions()` – API `/de/auctions.json?countries=de`
  - Länderfilter: 20+ Länder (DE, NL, BE, FR, AT, IT, ES, SE, ...)
  - Stadtfilter: Substring-Matching im Auktionsnamen
  - `marketplace_search()` um `country`-Parameter erweitert
  - `_detect_tw_auction_monitor_intent()` in Agent-Intent-Erkennung
- **LocationConfig:** `latitude`, `longitude`, `timezone`, `city` in config.py
  - Vorbereitung für automatische TZ-Erkennung aus Koordinaten
  - `timezonefinder>=6.2` als neue Dependency
- **Cron-Scheduler:** `_start_cron()` + `_cron_loop()` im Scheduler-Tool
- **Sub-Agent API:** PATCH-Endpoint für Live-Updates ohne Delete+Recreate

### Stabilität & Performance
- **`sa_registry.mark_run()`:** `os.fsync()` nur noch bei terminalen Stati (ok/error/timeout) – verhindert 100–500ms Event-Loop-Blockierung bei SD-Karte
- **`api.py`:** `cpu_percent(interval=None)` statt `interval=0.2` (war 200ms Blocking-Sleep)
- **WebSocket:** Session-Leak bei Exception geschlossen, `create_background_task` für Keepalive
- **`multirouter.py`:** Infinite Recursion in `_get_instance()` behoben; `_call_with_fallback()` iterativ statt rekursiv
- **`runner.py`:** Doppelte Heartbeat-Logik konsolidiert; `_SILENT_TOKENS` vor erstem Gebrauch definiert; Tasks aus `_tasks` aufgeräumt
- **`marketplace.py`:** asyncio.Lock für BuildId-Cache (Race Condition bei parallelen Monitoren); robusteres `listData`-Parsing
- **`daemon.py`:** `create_background_task` früh importiert (UnboundLocalError-Zeitbombe)
- **`datetime.utcnow()`:** Ersetzt durch `datetime.now(timezone.utc)` (Python 3.12+ deprecated)

### PRs gemergt
- #117 🛡️ Fix command injection in `wifi_disconnect` (nmcli als Argument-Liste)
- #114 🛡️ Kill zombie processes on camera/shell timeout
- #110 🛡️ Path traversal in camera snapshot (resolve + is_relative_to)
- #105 ⚙️ Cron-Support im Scheduler (Cron-Loop)
- #119 Fix async execution in system_report
- #106/#108 briefing.py/CLI nutzen `current_temp()` helper

### Git-Maintenance
- `piclaw update` repariert root-eigene `.git`-Dateien automatisch (`find .git -not -user`)
- GitHub-Token via credential store statt URL-Einbettung


# PiClaw OS – Projekt-Snapshot v0.9.0

Stand: 2026-03-10

## Was ist PiClaw OS?

Ein KI-Betriebssystem für den Raspberry Pi 5. Es verbindet einen dauerhaft laufenden
Agenten mit lokalem Speicher, mehreren LLM-Backends, einem Web-Dashboard, dynamisch
erstellbaren Sub-Agenten und einem Messaging-Hub (Telegram/Discord/Threema/WhatsApp).

Der Agent läuft als systemd-Service, hat persistent Gedächtnis über Sessions hinweg,
kann eigenständig andere Agenten beauftragen, und ist über Browser, CLI und
Messaging-Apps bedienbar.

---

## Dateibaum (vollständig)

```
piclaw-os/
├── CHANGELOG.md                   ← Vollständiges Changelog
├── GAPS.md                        ← Ursprüngliche Gap-Analyse
├── README.md                      ← Installations- und Nutzungsanleitung
├── SNAPSHOT.md                    ← Dieses Dokument
├── pyproject.toml                 ← Version 0.9.0, croniter>=1.4
├── watchdog.toml                  ← EDIT: Watchdog Telegram-Token + Chat-ID
├── build/build.sh                 ← debootstrap arm64 Image-Builder (root on Linux)
├── cloud-init/
│   ├── user-data.yml              ← EDIT VOR DEM FLASHEN
│   └── meta-data.yml
├── docs/
│   ├── api-auth.md                ← Bearer-Token Auth Doku
│   ├── discord-setup.md           ← Discord Bot Setup
│   ├── multi-llm.md               ← Multi-LLM Routing Doku
│   ├── soul.md                    ← Soul-System Doku
│   └── subagents.md               ← Sub-Agenten Doku (mit Sandboxing)
├── systemd/
│   ├── piclaw-agent.service
│   ├── piclaw-api.service         ← FastAPI Port 7842
│   ├── piclaw-crawler.service
│   └── piclaw-watchdog.service
├── tests/
│   ├── __init__.py
│   ├── conftest.py                ← Session-Level GPIO-Mock + CONFIG_DIR Patch
│   ├── test_auth.py               ← 13 Tests
│   ├── test_classifier.py         ← 17 Tests
│   ├── test_registry.py           ← 20 Tests
│   ├── test_router.py             ← 9 Tests
│   ├── test_sandbox.py            ← 16 Tests
│   └── test_soul.py               ← 12 Tests
└── piclaw/
    ├── __init__.py
    ├── agent.py                   ← Agentic loop, soul, sub-agent wiring, telegram
    ├── api.py                     ← FastAPI + WebSocket + Auth + Webhooks
    ├── auth.py                    ← Bearer-Token Auth (generate/verify/dependency)
    ├── cli.py                     ← piclaw CLI inkl. setup-Wizard (v0.9)
    ├── config.py
    ├── daemon.py                  ← Graceful shutdown
    ├── soul.py                    ← Soul-System (load/save/append/build_system_prompt)
    ├── agents/
    │   ├── __init__.py
    │   ├── crawler.py
    │   ├── ipc.py
    │   ├── orchestration.py
    │   ├── runner.py              ← SubAgentRunner mit Sandbox-Integration
    │   ├── sa_registry.py         ← SubAgentDef (inkl. trusted) + SubAgentRegistry
    │   ├── sa_tools.py            ← agent_list/create/start/stop/remove/update/run_now
    │   ├── sandbox.py             ← Tier-1/Tier-2 Tool-Sandboxing
    │   └── watchdog.py
    ├── llm/
    │   ├── __init__.py
    │   ├── api.py, local.py, base.py, router.py
    │   ├── registry.py            ← BackendConfig + LLMRegistry
    │   ├── classifier.py          ← TaskClassifier (25 Pattern + LLM-Fallback)
    │   ├── multirouter.py         ← MultiLLMRouter (Degradation, Cooldown)
    │   ├── mgmt_tools.py, model_manager.py
    ├── memory/
    │   ├── __init__.py
    │   ├── store.py, qmd.py       ← QMD Hybrid-Suche (BM25 + Vektor + Reranking)
    │   ├── middleware.py          ← MemoryMiddleware (enrich + background facts)
    │   └── tools.py
    ├── messaging/
    │   ├── __init__.py
    │   ├── hub.py                 ← MessagingHub
    │   ├── telegram.py, discord.py, threema.py, whatsapp.py
    ├── tools/
    │   ├── __init__.py
    │   ├── shell.py, network.py, gpio.py
    │   ├── services.py, scheduler.py, updater.py, http.py
    └── web/
        └── index.html             ← SPA: Dashboard/Memory/Agenten/Soul/Chat
```

---

## Architektur-Überblick

### Linux-User & Sicherheit
```
piclaw user:           Haupt-Agent, API, Crawler, Sub-Agenten (asyncio Tasks)
piclaw-watchdog user:  Watchdog only – kann nicht vom Haupt-Agenten gesteuert werden

IPC:
  Haupt-Agent → Crawler:   /etc/piclaw/ipc/jobs.db
  Watchdog → Haupt-Agent:  /etc/piclaw/ipc/watchdog.db (Watchdog schreibt, piclaw liest NUR)
  Watchdog → Telegram:     direkt, eigener Bot-Token, unabhängig
```

### API-Authentifizierung (v0.9)
```
Erster Boot:
  api.secret_key leer → generate_token() → in config.toml gespeichert
  set_token() → Modul-Level Cache

Alle /api/* Requests:
  Authorization: Bearer <token>
  oder ?token=<token> (für WebSocket)

Token anzeigen:  piclaw config token
Token rotieren:  piclaw config set api.secret_key "" → restart

Exempt:
  GET  /              (Token bereits im HTML injiziert)
  GET  /health        (Monitoring)
  *    /webhook/*     (eigene Signaturprüfung)
```

### Soul-System
```
/etc/piclaw/SOUL.md
  ↓ geladen beim Start
  ↓ als erstes Block in jeden System-Prompt injiziert

Prompt-Reihenfolge:
  1. Soul  (Persönlichkeit, Aufgabe, Regeln – User-definiert, nimmt Vorrang)
  2. Capabilities (Tool-Liste, Memory-Instruktionen)
  3. Context (Datum, Hostname, Agent-Name)

Bearbeitung:
  piclaw soul edit / piclaw soul show / piclaw soul reset
  Web-UI Tab "Soul" (Ctrl+S)
  API: GET/POST /api/soul, POST /api/soul/append
```

### Dynamic Sub-Agents
```
Haupt-Agent erstellt SubAgentDef
  → SubAgentRegistry.add() → /etc/piclaw/subagents.json
  → SubAgentRunner.start_agent() → asyncio.Task mit Schedule-Loop:
      once | interval:<s> | cron:<expr> | continuous
  → pro Zyklus: _execute()
      → Sandbox.filter_tools_for_subagent() → erlaubte Tool-Teilmenge
      → asyncio.wait_for(_agentic_loop(), timeout=agent.timeout)
      → Ergebnis → memory_log() → QMD-Speicher
      → Ergebnis → MessagingHub.notify() wenn agent.notify=True

SubAgentDef-Felder:
  id, name, description, mission, tools[], schedule, llm_tags[],
  enabled, max_steps, timeout, notify, trusted, created_by,
  last_run, last_status
```

### Sub-Agent Sandboxing (v0.9)
```
Tier 1 – BLOCKED_ALWAYS (kein Override):
  shell_exec, rm_recursive, system_reboot, system_poweroff, system_halt,
  service_disable, watchdog_stop, watchdog_disable, updater_apply, config_write_raw

Tier 2 – BLOCKED_BY_DEFAULT (freigeschaltet mit trusted=True + explizit gelistet):
  service_stop, service_restart, gpio_write, network_set, scheduler_remove

Tier 3 – Alle anderen Tools:
  Standard verfügbar für alle Sub-Agenten
```

### Multi-LLM Routing
```
Eingehende Nachricht
  → @backend-name Override → direkt
  → TaskClassifier Stage 1: 25 Regex-Muster → Tags (instant)
  → Konfidenz < 65%? → Stage 2: Schnellstes LLM → Tags
  → LLMRegistry.find_by_tags() → sortiert (Überschneidung DESC, Priorität DESC)
  → degradierte Backends gefiltert (>3 Fehler, 120s Cooldown)
  → bestes Backend → bei Fehler: nächstes → Fallback: lokales Phi-3

Classifier-Tags: coding, debugging, analysis, reasoning, creative, writing,
  summarization, translation, math, research, technical, general,
  german, english, french, spanish, fast, detailed, concise
```

### Memory Flow (QMD Hybrid-Suche)
```
User-Nachricht → MemoryMiddleware.enrich() → QMD-Suche (BM25+Vektor+Reranking)
  → Top-5 Snippets in System-Prompt injiziert → LLM → Antwort
  → MemoryMiddleware.after_turn() [Background]: LLM extrahiert Fakten → write_fact()
  → Sub-Agent-Ergebnisse ebenfalls automatisch gespeichert
```

### Messaging-Hub
| Adapter   | Mechanismus       | Public URL nötig | Kosten        |
|-----------|-------------------|------------------|---------------|
| Telegram  | Long-Polling      | Nein             | Kostenlos     |
| Discord   | discord.py Bot    | Nein             | Kostenlos     |
| Threema   | Gateway SDK, E2E  | Nein/Ja          | ~CHF 0.01/Msg |
| WhatsApp  | Meta Cloud API    | Ja               | Free-Tier     |

### Watchdog (isoliert, manipulationssicher)
- Alle 60s: Disk (warn >85%, krit >95%), Temp (warn >75°C, krit >80°C), RAM (>90%), Services, Heartbeat
- Alle 300s: SHA-256 Integritätsprüfung
- Append-Only DB: SQL DELETE/UPDATE Trigger verhindern Log-Manipulation
- Täglich 07:00: Zusammenfassungs-Report via eigenem Telegram-Bot

---

## Schlüssel-Konfiguration

| Datei | Inhalt |
|-------|--------|
| `/etc/piclaw/config.toml` | Haupt-Konfiguration |
| `/etc/piclaw/SOUL.md` | Soul-Datei (Persönlichkeit) |
| `/etc/piclaw/subagents.json` | Sub-Agenten-Definitionen |
| `/etc/piclaw/llm_registry.json` | LLM-Backend-Registry |
| `/etc/piclaw/watchdog.toml` | Watchdog-Konfiguration |

Web-UI: `http://piclaw.local:7842`
SSH: `ssh piclaw@piclaw.local` / Passwort: `piclaw123` (**ändern in cloud-init!**)

### cloud-init VOR DEM FLASHEN bearbeiten:
SSH Public-Key, LLM API-Key, WiFi SSID+Passwort, Zeitzone, Telegram-Token+Chat-ID,
Watchdog-Telegram-Token (separater Bot), optional: Discord, Threema, WhatsApp

---

## CLI-Befehle (v0.9)

```bash
piclaw                         # Interaktiver KI-Agent
piclaw setup                   # ★ NEU: Ersteinrichtungs-Wizard
piclaw doctor                  # Systemprüfung (Token + Soul + Sub-Agenten)
piclaw soul show/edit/reset    # Soul verwalten
piclaw agent list              # Sub-Agenten anzeigen
piclaw agent start/stop/remove/run <name>
piclaw config token            # API-Token anzeigen + curl-Beispiel
piclaw model download/status
piclaw messaging status/test/setup
piclaw config set llm.api_key sk-ant-...
piclaw start/stop/status
```

## API-Endpoints (Port 7842)

```
GET    /health                  (keine Auth)
GET    /                        (Web-UI, Token injiziert)
GET    /api/stats               ← Auth erforderlich
GET    /api/subagents
POST   /api/subagents           ← create (name, description, mission, trusted, ...)
DELETE /api/subagents/{name}
POST   /api/subagents/{name}/start
POST   /api/subagents/{name}/stop
POST   /api/subagents/{name}/run
GET    /api/soul
POST   /api/soul
POST   /api/soul/append
GET    /api/messaging
GET    /api/memory/stats
GET    /api/memory/search?q=...
GET    /api/mode
GET    /api/services
GET    /api/config
GET    /api/schedules
WS     /ws/chat?token=<token>
GET/POST /webhook/whatsapp      (keine Auth, eigene Signaturprüfung)
POST   /webhook/threema         (keine Auth, Threema-Schema)
```

## Build & Flash

```bash
# 1. cloud-init/user-data.yml bearbeiten
# 2. Auf Linux-Host mit root:
sudo ./build/build.sh
# 3. Flashen: sudo dd if=piclaw-os-arm64.img of=/dev/sdX bs=4M status=progress
# 4. Pi booten, ~3 Min warten: ssh piclaw@piclaw.local
# 5. Ersteinrichtung: piclaw setup
```

## Schlüssel-Abhängigkeiten

```
llama-cpp-python>=0.2.90   CPU-only, Phi-3 Mini Q4
aiohttp, fastapi, uvicorn[standard], websockets
psutil, tomli-w, croniter>=1.4
discord.py>=2.3
threema.gateway[e2e]>=8.0
RPi.GPIO, gpiozero (nur arm64)
nodejs, npm, sqlite3 (System-Pakete)
npm install -g @tobilu/qmd
pytest, pytest-asyncio, httpx (für Tests)
```

## Tests ausführen

```bash
# Auf dem Pi (nach: pip install pytest pytest-asyncio httpx):
cd /opt/piclaw
pytest tests/ -v

# Smoke-Tests ohne pytest (überall lauffähig):
python3 -c "import piclaw.llm.classifier as c; r = c.TaskClassifier().classify_sync('debug python'); print(r.tags)"
```

# PiClaw OS – Changelog

## [0.10.1] – 2026-03-10

### Added
- **`piclaw/wizard.py`** – Eigenstaendiger SSH/Terminal Konfigurations-Wizard
  - 9 gefuehrte Schritte: Agent, LLM, Telegram, Discord, MQTT, WLAN, Hardware, API-Token, Soul
  - Sofortige Verbindungsvalidierung (LLM-Test, Telegram-Test, Ollama-Test, Discord-Token)
  - WLAN-Konfiguration via nmcli inkl. Netzwerkscan
  - Visueller Fortschrittsbalken + schrittweise Aenderungs-Zusammenfassung
  - Alle Schritte einzeln ueberspringbar (Enter)
  - Vollstaendiger Retry bei fehlgeschlagenen Tests

### Fixed / Changed
- **SSH-Robustheit** (`piclaw/wizard.py`):
  - TTY-Erkennung: `sys.stdin.isatty()` -- Warnung wenn kein PTY aktiv
  - Klarer Hinweis: `ssh -t pi@piclaw.local piclaw setup` (erzwingt PTY)
  - `secret=True`-Prompts: `getpass` bei TTY, sichtbare Eingabe bei reiner SSH-Session ohne `-t`
  - ANSI-Farben deaktiviert wenn `NO_COLOR` gesetzt oder `TERM=dumb`
  - Alle Sonderzeichen/Emojis durch `_sym(utf8, ascii_fallback)` geschuetzt
  - Kein einziges raw-Unicode-Zeichen in Ausgabe-Strings
- **`piclaw/cli.py`**: `cmd_setup()` ruft `wizard.run()` auf -- alter 5-Schritt-Code entfernt
- **`piclaw/api.py`**: `/setup`-Web-Route entfernt (API laeuft bei Ersteinrichtung noch nicht)

## [0.10.0] – 2026-03-10

### Added
- **Metriken-Engine** (`piclaw/metrics.py`)
  - SQLite Zeitreihen-Ringpuffer (7 Tage Retention)
  - Automatischer Collector: CPU, RAM, Temp, Disk, Load, Netzwerk alle 30s
  - Downsampling-Abfragen für Chart-Darstellung
  - REST-API: `/api/metrics`, `/api/metrics/{name}`, `/api/metrics/chart/{name}`
  - CLI: `piclaw metrics`, `piclaw metrics history <name> <sekunden>`
  - Web-UI: Neuer Tab „📊 Metriken" mit Live-Charts (CPU Temp, CPU/RAM)
  - Gestartet als asyncio-Task in daemon.py

- **Pi-Kamera Integration** (`piclaw/hardware/camera.py`)
  - Unterstützt Pi Camera (libcamera) und USB-Webcams (fswebcam/v4l2)
  - `camera_snapshot` – Foto aufnehmen, verschiedene Auflösungen
  - `camera_describe` – Foto + Vision-LLM-Analyse (Claude 3+ / GPT-4V)
  - `camera_list` – automatische Kamera-Erkennung
  - `camera_timelapse_start/stop` – Zeitraffer als asyncio-Task
  - 5 Agent-Tools registriert
  - REST-API: `/api/camera/list`, `/api/camera/snapshot`, `/api/camera/image/{file}`
  - CLI: `piclaw camera snapshot`, `piclaw camera list`
  - Web-UI: Neuer Tab „📷 Kamera" mit Live-Snapshot-Anzeige

- **MQTT-Adapter** (`piclaw/messaging/mqtt.py`)
  - 5. Messaging-Kanal (neben Telegram, Discord, Threema, WhatsApp)
  - aiomqtt-basiert (async, modernes API)
  - Automatischer Reconnect mit exponential Backoff
  - Home Assistant Auto-Discovery (publiziert Sensor-Entitäten automatisch)
  - `publish_sensor()` – Sensorwerte auf MQTT publizieren
  - `publish_metrics()` – Systemmetriken für HA
  - TLS-Unterstützung, QoS 0/1/2 konfigurierbar
  - Konfiguration: `[mqtt]` in config.toml

- **Backup & Restore** (`piclaw/backup.py`)
  - Sichert config.toml, SOUL.md, subagents.json, sensors.json, llm_registry.json
  - Komprimiertes tar.gz mit Manifest (Version, Timestamp, Dateiliste)
  - Automatische Kopie auf USB-Stick (falls eingesteckt)
  - Retention: max. 10 Backups, älteste automatisch gelöscht
  - Restore mit Dry-Run-Vorschau
  - REST-API: `/api/backup/list`, `/api/backup/create`
  - CLI: `piclaw backup`, `piclaw backup list`, `piclaw backup restore`

- **Neue Tests**
  - `tests/test_metrics.py` – 20 Tests (MetricPoint, MetricsDB, MetricsCollector)
  - `tests/test_backup.py` – 16 Tests (Manifest, BackupInfo, create/list/restore)

### Changed
- `piclaw/daemon.py` – Startet Metriken-Collector als asyncio-Task beim Boot
- `piclaw/web/index.html` – 2 neue Tabs (Metriken, Kamera), 8 Tabs gesamt
- `pyproject.toml` – Version 0.10.0, aiomqtt als optionale Dependency
- `piclaw/cli.py` – 3 neue Befehlsgruppen: backup, metrics, camera
- `piclaw/api.py` – 8 neue Endpunkte für Metriken, Kamera, Backup

## [0.9.0] – 2026-03-10

### Added
- **First-Boot Setup Wizard** (`piclaw setup`)
  - Interaktiver 5-Schritt-Wizard: Agent-Name, LLM-Provider, Telegram, API-Token, Soul
  - Unterstützt Anthropic, OpenAI, Ollama, lokal (Phi-3)
  - Token-Generierung integriert (kein separater Schritt mehr nötig)
  - Soul-Bearbeitung via `$EDITOR` oder Inline-Eingabe
  - Zusammenfassung mit nächsten Schritten am Ende
- **`def main()` Fix** in `cli.py` – Dispatch-Code war fälschlicherweise auf Modul-Ebene

- **API Authentication** (`piclaw/auth.py`)
  - Single Bearer token per installation, auto-generated on first boot
  - Constant-time token comparison via `secrets.compare_digest`
  - All `/api/*` endpoints protected; `/health`, `/`, `/webhook/*` exempt
  - WebSocket auth via `?token=` query parameter
  - Token injected into Web UI HTML by the `/` route (no manual config needed)
  - CLI: `piclaw config token` shows token + ready-to-use `curl` example
  - `piclaw doctor` shows token status

- **Web UI: Agents Tab** (full sub-agent management)
  - List all sub-agents with status icon, schedule, last-run time
  - ▶ Start / ■ Stop / ⚡ Run Now / ✕ Delete per agent
  - Live agent count in Dashboard widget (click → Agents tab)
  - Auto-refresh every 15s

- **Web UI: Soul Tab** (in-browser soul editor)
  - Edit `/etc/piclaw/SOUL.md` directly in browser
  - Ctrl+S to save, character counter, path display
  - ↻ Reload from disk at any time
  - Change banner: "wirkt beim nächsten Gespräch"

- **Web UI: Dashboard improvements**
  - Connection banner when WebSocket disconnects
  - Sub-Agents summary card (total / running count)
  - All `fetch()` calls now use `authFetch()` with Bearer token
  - Fixed `--muted` CSS variable (was undefined, now uses `--text2`)
  - Fixed `showPanel()` to not rely on `event.target` (now passes `tabEl` explicitly)

- **Sub-Agent Sandboxing** (`piclaw/agents/sandbox.py`)
  - Tier 1 (`BLOCKED_ALWAYS`): `shell_exec`, `system_reboot`, `system_poweroff`,
    `watchdog_stop`, `watchdog_disable`, `updater_apply`, `config_write_raw`, etc.
    Blocked for all sub-agents, no override possible.
  - Tier 2 (`BLOCKED_BY_DEFAULT`): `service_stop`, `service_restart`, `gpio_write`,
    `network_set`, `scheduler_remove`.
    Blocked unless agent has `trusted=True` AND tool explicitly listed.
  - `SubAgentDef.trusted` flag (default `False`)
  - `filter_tools_for_subagent()` replaces old `_filter_tools()` in runner
  - `explain_restrictions(tool_name)` – human-readable restriction explanation
  - `audit_agent_tools(name, tools, trusted)` – formatted tool audit report
  - `POST /api/subagents` accepts `trusted` field

- **Test Suite** (`tests/`)
  - `conftest.py` – session-level GPIO mock, CONFIG_DIR patch
  - `test_classifier.py` – 17 tests for pattern-matching classifier
  - `test_registry.py` – 20 tests for SubAgentRegistry + LLMRegistry
  - `test_auth.py` – 13 tests for token generation, verification, FastAPI dependency
  - `test_soul.py` – 12 tests for load/save/append/build_system_prompt
  - `test_router.py` – 9 tests for routing logic and tag overlap
  - `test_sandbox.py` – 16 tests for tier-1/tier-2 sandboxing logic
  - All 29 smoke tests passing inline (pytest-compatible when installed on Pi)

### Changed
- `api.py` fully rewritten with auth (version bumped to 0.8.0)
- `/api/config` no longer exposes `secret_key` or API keys
- `runner.py`: `_filter_tools(agent.tools)` → `_filter_tools(agent)` with sandbox
- `runner.py`: `status_dict()` now includes `trusted` field per agent
- `sa_registry.py`: `SubAgentDef` gains `trusted: bool = False`
- Web UI `index.html`: complete clean rewrite (~650 lines, no regressions)

### Fixed
- `--muted` CSS variable was undefined in old index.html (all `var(--muted)` → `var(--text2)`)
- `showPanel()` used unreliable `event.target` – now receives explicit `tabEl` argument
- `conn-banner` had no CSS style definition
- `authFetch()` definition was missing from index.html after first patch pass

---

## [0.8.0] – 2026-03-09

### Added
- **Soul System** (`piclaw/soul.py`)
  - `/etc/piclaw/SOUL.md` defines personality, purpose, behavioral rules
  - Injected as first block of every system prompt
  - Agent tools: `soul_read`, `soul_write`, `soul_append`
  - CLI: `piclaw soul show/edit/reset`
  - API: `GET/POST /api/soul`, `POST /api/soul/append`

- **Dynamic Sub-Agents** (`piclaw/agents/`)
  - `SubAgentDef` dataclass with schedule, tools, llm_tags, timeout, notify
  - `SubAgentRegistry` – persistent CRUD store (`/etc/piclaw/subagents.json`)
  - `SubAgentRunner` – asyncio task lifecycle manager
  - Schedules: `once | cron:<expr> | interval:<s> | continuous`
  - Per-agent agentic loop with tool scope restriction
  - Results written to QMD memory + optional messaging hub notification
  - Agent tools: `agent_list/create/start/stop/remove/update/run_now`
  - API: full CRUD endpoints `/api/subagents`
  - CLI: `piclaw agent list/start/stop/remove/run`

- **Multi-LLM Routing** (`piclaw/llm/`)
  - `TaskClassifier` – 25 regex patterns → tags (instant, no LLM)
  - Stage 2: LLM fallback when confidence < 65%
  - `LLMRegistry` – persistent backend store with tag-based lookup
  - `MultiLLMRouter` – degradation tracking, auto-fallback to local Phi-3
  - Backend cooldown: >3 failures → 120s cooldown

- **QMD Hybrid Memory** (`piclaw/memory/`)
  - BM25 + vector search + rerank pipeline
  - `MemoryMiddleware` – enriches prompts, extracts facts in background
  - Sub-agent results auto-written to memory

- **Messaging Hub** (`piclaw/messaging/`)
  - Telegram (long-polling), Discord, Threema, WhatsApp
  - `IncomingMessage` → agent → response fan-out

### Fixed
- `croniter>=1.4` added to pyproject.toml (was missing)
- Late-binding `_telegram_send` in agent.py
- Graceful shutdown: `stop_all()` in daemon.py + api.py lifespan

---

## [0.7.0] – 2026-03-08
- Multi-LLM router base
- Discord CLI integration
- Messaging hub foundation

## [0.3.0] – 2026-03-07
- QMD hybrid memory (BM25 + vector)
- MemoryMiddleware

## [0.2.0] – 2026-03-06
- REST API + WebSocket chat
- Web dashboard (Dashboard + Memory + Chat tabs)

## [0.1.0] – 2026-03-05
- Initial: agentic loop, config, tools, systemd services
- Watchdog (isolated, tamper-proof, append-only DB)
- Cloud-init based image builder

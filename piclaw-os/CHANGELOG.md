# PiClaw OS — Changelog

## [0.15.x] — March 2026

### Added
- **Network Monitor** (`tools/network_monitor.py`) — `network_scan`, `port_scan`, `check_new_devices` via nmap; new device detection triggers Telegram alert
- **Parallel Queue** (`agent.py`) — `asyncio.Queue` with 2 workers; CLI and Telegram no longer block each other
- **Installer Sub-Agent** (`tools/installer.py`) — Dameon can autonomously install software from trusted sources (GitHub whitelist, pip, apt) with mandatory user confirmation
- **Tandem Browser** (`tools/tandem.py`) — browser automation tools: `browser_open`, `browser_click`, `browser_read`, `browser_screenshot`; `systemd/piclaw-tandem.service` added
- **LLM Fallback Order** — Kimi K2 (primary) → Nemotron (secondary) → local Gemma 2B with user notice when falling back to local
- **`piclaw llm` CLI** — `list`, `add`, `remove`, `update`, `enable`, `disable` commands for registry management

### Fixed
- Stream fallback warning suppressed when response was already successfully delivered to user
- `piclaw model download` now defaults to `gemma2b-q4` (was `phi3-mini-q4`)
- WebSocket `ping_timeout` increased to 120s to prevent disconnects with slow models (Nemotron)
- Double `/v1/v1/` URL construction when `base_url` already contains `/v1`
- Router fallback no longer re-adds Nemotron backend on every boot
- `piclaw setup` wizard: LLM test now uses `OpenAIBackend` directly instead of `MultiLLMRouter` (avoids timeout on first boot)

---

## [0.14.x] — March 2026

### Added
- **NVIDIA NIM Integration** — Kimi K2 (`moonshotai/kimi-k2-instruct-0905`) as primary backend, Nemotron (`nvidia/llama-3.1-nemotron-nano-vl-8b-v1`) as secondary
- **Multi-LLM Wizard** — purpose-based backend selection (Coding, Chat, Creative, Fast, Offline, etc.); multiple backends configurable during setup
- **SOUL.md excluded from QMD index** — prevents personality file from being injected as a memory context
- **Tool-calling fix for NVIDIA NIM** — explicit `tool_choice: auto` and `parallel_tool_calls: false` in API payload
- **`piclaw llm` CLI command** — full registry management from the command line

### Fixed
- `callable | None` type hint incompatible with Python 3.13 removed from `agent.py`
- llama.cpp verbose output suppressed in `LocalBackend`
- Router fallback warning `⚠️ Backend failed` no longer shown after a successful response

---

## [0.13.3] — 2026-03-12

### Fixed
- `briefing.py` — direct dict access on Home Assistant entities without existence check; entities in `unavailable` state caused `KeyError`. All accesses switched to `.get(key, '?')`. Also fixed typo `"of"` → `"off"` in alarm state comparison.
- `llm/api.py` — `data["choices"][0]` without guard; OpenAI returns an empty `choices` list on content moderation or rate limit → `IndexError`. Fixed with `choices = data.get("choices") or []`. Tool call fields also guarded with `.get()`.
- `llm/local.py` — `result["choices"][0]["text"]` without guard in `_infer()` and streaming path; llama.cpp can return an empty list on OOM or model errors. Fixed with defensive `.get()`.

### Improved
- `backup.py`, `briefing.py`, `metrics.py` — magic number `86400` replaced with named constant `_SECS_PER_DAY = 86_400`.

---

## [0.13.2] — 2026-03-11

### Fixed
- `agents/crawler.py` — `target.replace(day=target.day + 1)` raises `ValueError` on the last day of a month. Fixed with `target += timedelta(days=1)`.
- Removed all bare `except: pass` blocks across 16 files; replaced with `log.debug()` and precise exception types.
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()` in `briefing.py`, `hardware/i2c_scan.py`, `hardware/pi_info.py`, `hardware/sensors.py` (deprecated since Python 3.10).
- `api.py` — `socket.gethostbyname()` in async endpoint blocked the event loop; moved to `loop.run_in_executor()`.
- `llm/model_manager.py` — `aiohttp.ClientSession()` without timeout on large model downloads. Added `ClientTimeout(total=7200, connect=30, sock_read=120)`.
- 14 `.read_text()` calls without `encoding=` — all updated to `encoding="utf-8"`.

---

## [0.13.1] — 2026-03-11

### Fixed
- `proactive.py` — 3 silent `except: pass` blocks replaced with `log.debug()`.
- `metrics.py` — `psutil.cpu_percent(interval=1)` blocked the asyncio event loop for 1 second every 30s. Changed to `interval=None`.
- `metrics.py` — weekly SQLite `VACUUM` after `purge_old` to prevent unbounded file growth.
- `agents/ipc.py` — `init_watchdog_db()` called before every write; now guarded with `_db_initialized` flag.
- `agents/ipc.py` — 5 missing SQLite indexes added for watchdog DB.
- `briefing.py` — `psutil.boot_time()` cached as module-level constant.
- `proactive.py` — `croniter` objects now cached; 10s boot delay added to prevent routine burst on restart.
- `tools/homeassistant.py` — `ssl=False` hardcoded; now respects `verify_ssl` config.

---

## [0.13.0] — 2026-03-11

### Added
- **Proactive Agent** (`briefing.py`, `routines.py`, `proactive.py`)
  - Morning briefing, evening check-in, weekly report, temperature watcher
  - Weather via Open-Meteo (no API key required)
  - Threshold monitoring: CPU temp, disk, RAM with 60-minute cooldown
  - Fully configurable via wizard and CLI (`piclaw routine`, `piclaw briefing`)

---

## [0.12.0] — 2026-03-11

### Added
- **Home Assistant** (`tools/homeassistant.py`) — REST + WebSocket, 11 agent tools, real-time push events, auto-reconnect with exponential backoff

---

## [0.11.0] — 2026-03-11

### Added
- **Boot-partition installer** (`boot/piclaw/`) — copy folder to SD card, works on Windows/macOS/Linux without special tools
- **`piclaw.conf`** — simple key-value config file, no TOML syntax required
- **`boot/piclaw/install.sh`** — offline-capable installer, reads all values from `piclaw.conf`

---

## [0.10.1] — 2026-03-10

### Added
- **Configuration wizard** (`wizard.py`) — 9 guided steps, immediate connection validation, WLAN setup via nmcli, visual progress bar

---

## [0.10.0] — 2026-03-10

### Added
- **Metrics engine** (`metrics.py`) — SQLite ring buffer (7-day retention), live charts in Web UI
- **Camera integration** (`hardware/camera.py`) — Pi Camera + USB webcams, AI-powered image description
- **MQTT adapter** (`messaging/mqtt.py`) — Home Assistant auto-discovery, TLS, QoS 0/1/2
- **Backup & restore** (`backup.py`) — compressed tar.gz, USB stick copy, 10-backup retention

---

## [0.9.0] — 2026-03-10

### Added
- First-boot setup wizard (`piclaw setup`)
- API authentication — single Bearer token, auto-generated on first boot
- Web UI: Agents tab, Soul editor tab
- Sub-agent sandboxing — tier-1 (always blocked) and tier-2 (blocked by default) tool restrictions

---

## [0.8.0] — 2026-03-09

### Added
- Soul system (`soul.py`) — `/etc/piclaw/SOUL.md` defines agent personality, injected into every system prompt
- Dynamic sub-agents — `SubAgentDef`, `SubAgentRegistry`, `SubAgentRunner`; schedules: once, cron, interval, continuous
- Multi-LLM routing — `TaskClassifier`, `LLMRegistry`, `MultiLLMRouter` with degradation tracking
- QMD hybrid memory — BM25 + vector search + rerank, `MemoryMiddleware`
- Messaging hub — Telegram, Discord, Threema, WhatsApp

---

## [0.7.0] — 2026-03-08
- Multi-LLM router base, Discord integration, messaging hub foundation

## [0.3.0] — 2026-03-07
- QMD hybrid memory (BM25 + vector), MemoryMiddleware

## [0.2.0] — 2026-03-06
- REST API + WebSocket chat, web dashboard (Dashboard, Memory, Chat)

## [0.1.0] — 2026-03-05
- Initial release: agentic loop, config, tools, systemd services
- Watchdog (isolated, tamper-proof, append-only DB)
- Cloud-init based image builder

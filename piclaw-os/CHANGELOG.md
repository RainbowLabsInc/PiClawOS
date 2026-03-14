# PiClaw OS – Changelog

## [0.13.3] – 2026-03-12  Debugging-Runde 3

### Bugfixes

**`piclaw/briefing.py`** – Direkte Dict-Zugriffe `t['name']`, `t['current']`,
`a["state"]`, `a['name']` auf Home-Assistant-Entities ohne Existenz-Prüfung.
Home Assistant liefert gelegentlich unvollständige Entities (z.B. bei Geräten
im Unavailable-State). Fix: alle Zugriffe auf `.get(key, '?')` umgestellt.
Außerdem: Tippfehler `"of"` → `"off"` im Alarm-State-Vergleich korrigiert.

**`piclaw/llm/api.py`** – `data["choices"][0]` ohne Guard: wenn OpenAI eine
leere `choices`-Liste zurückschickt (z.B. bei Content-Moderation oder Rate-Limit),
wäre `IndexError` geworfen worden. Fix: `choices = data.get("choices") or []`
mit expliziter Fehlerprüfung. Außerdem `tc["id"]`, `tc["function"]["name"]`
→ alle mit `.get()` abgesichert; Tool-Calls ohne Name werden übersprungen.

**`piclaw/llm/local.py`** – `result["choices"][0]["text"]` ohne Guard in
`_infer()` und im Streaming-Pfad: llama.cpp kann bei Out-of-Memory oder
Modellfehlern eine leere Liste zurückgeben → `IndexError`. Fix: defensive
`.get()`-Auswertung mit expliziter ValueError-Meldung.

### Verbesserungen

- `piclaw/backup.py`, `piclaw/briefing.py`, `piclaw/metrics.py` –
  Magic Number `86400` durch benannte Konstante `_SECS_PER_DAY = 86_400`
  ersetzt (Lesbarkeit, einfachere Wartung).

### Analysiert (kein Fix nötig)

- `backup.py`, `cli.py`, `llm/api.py` – `json.loads()` ohne try/except:
  alle Fundstellen sind bereits durch umschließende `try/except Exception`-
  Blöcke abgesichert. False positive.
- `llm/classifier.py` – `re.compile()` in `__init__`: wird einmalig bei
  Instantiierung ausgeführt und als `self._compiled` gecacht. Korrekt.

## [0.13.2] – 2026-03-11  Debugging Run #2

### Behoben

**Korrektheit (echter Bug):**
- `piclaw/agents/crawler.py` – `target.replace(day=target.day + 1)` wirft
  `ValueError` am letzten Tag des Monats (z.B. 31. Januar → Tag 32).
  Fix: `target += timedelta(days=1)`

**Stabilität – Silent Exceptions (alle `except: pass` entfernt):**
- `piclaw/agents/crawler.py:153` – LLM-Summary-Fehler ungeloggt → `log.debug()`
- `piclaw/agents/watchdog.py:252` – `proc.kill()` nach Timeout ungeloggt → `log.debug()`
- `piclaw/agents/watchdog.py:377` – CPU-Temp in Daily Report: `except Exception` → `except OSError`
- `piclaw/agents/orchestration.py:327` – CPU-Temp Read: `except Exception` → `except OSError`
- `piclaw/api.py:337` – psutil temp fallback ungeloggt → `log.debug()`
- `piclaw/backup.py:98` – Manifest-Lesefehler ungeloggt → `log.debug()`
- `piclaw/briefing.py:234` – Location-Config-Fehler ungeloggt → `log.debug()`
- `piclaw/daemon.py:93` – `memory.after_turn()` Fehler ungeloggt → `log.debug()`
- `piclaw/daemon.py:130,135` – HA/Proactive-Shutdown Fehler ungeloggt → `log.debug()`
- `piclaw/hardware/camera.py:87` – v4l2 Enumeration ungeloggt → `log.debug()`
- `piclaw/hardware/pi_info.py:258` – meminfo Parse ungeloggt → `log.debug()`
- `piclaw/llm/multirouter.py:248` – Thermal-Routing-Check ungeloggt → `log.debug()`
- `piclaw/memory/middleware.py:203` – JSON-Parse: `except Exception` → enger Typ
- `piclaw/messaging/hub.py:102` – Adapter-Stop ungeloggt → `log.debug()` mit Adapter-Name
- `piclaw/messaging/threema.py:103` – Connection-Close ungeloggt → `log.debug()`
- `piclaw/messaging/discord.py:131` – Embed-Fallback ungeloggt → `log.debug()`
- `piclaw/metrics.py:305` – thermal_zone0 Read: `except Exception` → `except OSError`
- `piclaw/metrics.py:313` – psutil Temp-Sensor ungeloggt → `log.debug()`
- `piclaw/wizard.py:802,930,1131,1211` – Display/Save-Fehler: `except Exception: pass`
  → `log.debug()` bzw. `except OSError`
- `piclaw/memory/qmd.py:235,269` – Exception-Typen präzisiert
- `piclaw/llm/api.py:84,130,153` – Streaming-Chunk-Fehler: `except Exception` →
  enger `except (json.JSONDecodeError, KeyError)`

**Deprecated API:**
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()` in 4 Dateien:
  `briefing.py`, `hardware/i2c_scan.py`, `hardware/pi_info.py`, `hardware/sensors.py`
  (deprecated seit Python 3.10, RuntimeWarning in Python 3.12)

**Performance:**
- `piclaw/api.py` – `socket.gethostbyname()` in async Endpoint blockierte Event-Loop
  bei langsamem DNS/mDNS. Fix: `loop.run_in_executor(None, socket.gethostbyname, ...)`
- `piclaw/agents/watchdog.py` – `time.time()` in `rglob()`-Schleife vor Loop gecacht
- `piclaw/llm/model_manager.py` – `aiohttp.ClientSession()` ohne Timeout beim
  Download großer Modelle. Fix: `ClientTimeout(total=7200, connect=30, sock_read=120)`

**Portabilität:**
- 14× `.read_text()` ohne `encoding=` in: `agents/sa_registry.py`,
  `hardware/pi_info.py`, `hardware/sensors.py`, `llm/registry.py`,
  `memory/store.py`, `metrics.py`, `routines.py`, `tools/scheduler.py`,
  `api.py`, `wizard.py`
  → überall `encoding="utf-8"` (bzw. `errors="replace"` für /proc und /sys Dateien)

## [0.13.3] – 2026-03-12  Debugging-Runde 3

### Bugfixes

**`piclaw/briefing.py`** – Direkte Dict-Zugriffe `t['name']`, `t['current']`,
`a["state"]`, `a['name']` auf Home-Assistant-Entities ohne Existenz-Prüfung.
Home Assistant liefert gelegentlich unvollständige Entities (z.B. bei Geräten
im Unavailable-State). Fix: alle Zugriffe auf `.get(key, '?')` umgestellt.
Außerdem: Tippfehler `"of"` → `"off"` im Alarm-State-Vergleich korrigiert.

**`piclaw/llm/api.py`** – `data["choices"][0]` ohne Guard: wenn OpenAI eine
leere `choices`-Liste zurückschickt (z.B. bei Content-Moderation oder Rate-Limit),
wäre `IndexError` geworfen worden. Fix: `choices = data.get("choices") or []`
mit expliziter Fehlerprüfung. Außerdem `tc["id"]`, `tc["function"]["name"]`
→ alle mit `.get()` abgesichert; Tool-Calls ohne Name werden übersprungen.

**`piclaw/llm/local.py`** – `result["choices"][0]["text"]` ohne Guard in
`_infer()` und im Streaming-Pfad: llama.cpp kann bei Out-of-Memory oder
Modellfehlern eine leere Liste zurückgeben → `IndexError`. Fix: defensive
`.get()`-Auswertung mit expliziter ValueError-Meldung.

### Verbesserungen

- `piclaw/backup.py`, `piclaw/briefing.py`, `piclaw/metrics.py` –
  Magic Number `86400` durch benannte Konstante `_SECS_PER_DAY = 86_400`
  ersetzt (Lesbarkeit, einfachere Wartung).

### Analysiert (kein Fix nötig)

- `backup.py`, `cli.py`, `llm/api.py` – `json.loads()` ohne try/except:
  alle Fundstellen sind bereits durch umschließende `try/except Exception`-
  Blöcke abgesichert. False positive.
- `llm/classifier.py` – `re.compile()` in `__init__`: wird einmalig bei
  Instantiierung ausgeführt und als `self._compiled` gecacht. Korrekt.

## [0.13.2] – 2026-03-11  Debugging-Runde 2 + Testvorbereitung

### Kritische Bugfixes

- **[CRASH] `piclaw/wizard.py`** – `log` wurde in 4 except-Blöcken verwendet,
  aber `logging` war nie importiert und `log = getLogger(__name__)` fehlte komplett.
  Jede Ausnahme in wizard.py hätte zu einem `NameError: name 'log' is not defined`
  geführt und den Wizard abgestürzt. Behoben: `import logging` + `log = getLogger`.
  
- **[CRASH] `piclaw/agents/orchestration.py`** – identisches Problem: `log.debug()`
  ohne logging-Import. Jede CPU-Temp-Ausnahme im Orchestration-Modul hätte den
  gesamten Agent-Task terminiert. Behoben: `import logging` + `log = getLogger`.

### Bugfixes

- **`piclaw/tools/shell.py`** – `open("/sys/class/thermal/...")` ohne `with`-Block:
  File-Descriptor wurde bei Exception nie geschlossen (FD-Leak). Behoben: `with open`.

- **`piclaw/cli.py` `_api_call()`** – `except Exception: return None` verschluckte
  alle Fehler ohne Log. Aufrufer konnte nicht unterscheiden ob API unreachable oder
  echter Fehler. Behoben: `URLError` → `log.debug`, alle anderen → `log.warning`.
  Außerdem: `urlopen(timeout=5, encoding=...)` → `encoding` ist kein gültiger
  Parameter für urlopen; Response jetzt explizit als UTF-8 dekodiert.

- **`piclaw/llm/model_manager.py`** – `print()` statt `logging` (4 Stellen).
  Logging ergänzt, `print()` für CLI-Fortschrittsausgabe bewusst behalten.

### Analyse (keine Fixes nötig)

- `asyncio.run()` in `cli.py` L94/L265/L880`: false positive – liegt in sync
  `def cmd_*()`, nicht in `async def _run()`. Korrekt.
- Zirkulärer Import `agent ↔ scheduler`: false positive – Import ist hinter
  `if TYPE_CHECKING:` Guard, wird zur Laufzeit nicht ausgeführt. Korrekt.
- `except Exception: return None` in `pi_info.py`, `metrics.py`, `homeassistant.py`:
  bewusst – Rückgabe optionaler Werte, Aufrufer prüft auf `None`. Korrekt.

## [0.13.1] – 2026-03-11  Debugging & Stabilisierung

### Behoben

**Stabilität:**
- `piclaw/proactive.py` – 3x `except Exception: pass` durch `log.debug()` ersetzt
  (cpu_temp / disk / ram threshold-checks waren vollständig stumm bei Fehler)
- `piclaw/agents/watchdog.py` – bare `except Exception: pass` im Temp-Fallback
  durch `except OSError` + `log.debug()` ersetzt (präzisere Fehlerklasse)
- `piclaw/tools/shell.py` – bare `except Exception: pass` nach temp-sensor-Fallback
  durch `log.debug()` ersetzt

**Performance:**
- `piclaw/metrics.py` – `psutil.cpu_percent(interval=1)` blockierte 1 Sekunde den
  asyncio Event-Loop bei jedem Collector-Tick (alle 30s). Fix: `interval=None`
  (nicht-blockierend, nutzt psutil-internen 30s-Cache). Erster Call: `interval=0.1`
  als Fallback falls Cache leer.
- `piclaw/metrics.py` – Wöchentliches SQLite VACUUM nach purge_old ergänzt.
  Ohne VACUUM wächst die Datei trotz regelmäßigem DELETE.
- `piclaw/agents/ipc.py` – `init_watchdog_db()` wurde vor JEDEM `write_alert()`
  aufgerufen (8 Funktionen × N Calls/Tag). Fix: `_db_initialized` Guard – init
  läuft nur einmal pro Prozess.
- `piclaw/agents/ipc.py` – 5 fehlende SQLite-Indizes für Watchdog-DB ergänzt:
  `idx_alerts_ts`, `idx_alerts_severity`, `idx_alerts_sent`,
  `idx_reports_ts`, `idx_integrity_path`
- `piclaw/briefing.py` – `psutil.boot_time()` bei jedem Briefing-Call neu
  abgefragt. Fix: `_BOOT_TIME` Modul-Cache (Boot-Zeit ändert sich nie)
- `piclaw/proactive.py` – `croniter(routine.cron)` wurde bei jeder Minuten-Prüfung
  NEU kompiliert (für jede aktivierte Routine). Fix: `_cron_cache` Dict hält
  kompilierte Objekte über die Laufzeit.
- `piclaw/proactive.py` – 10s Boot-Schutz ergänzt: Routine-Loop startet erst
  nachdem Daemon vollständig hochgefahren ist (kein Routine-Burst beim Neustart)

**Korrektheit:**
- `piclaw/tools/homeassistant.py` – WebSocket-Listener ignorierte `verify_ssl`-
  Config (`ssl=False` hardcoded). Fix: `ssl=None if cfg.verify_ssl else False`

## [0.13.0] – 2026-03-11

### Added – Proaktiver Agent

- **`piclaw/briefing.py`** – Briefing-Engine
  - Sammelt Kontext parallel: Pi-Status, Wetter (Open-Meteo, kein Key), HA-Snapshot, Metriken-Trends
  - LLM-generierte Briefings: morning, evening, weekly, status
  - Fallback-Templates wenn kein LLM verfuegbar
  - Wetter kostenlos via api.open-meteo.com (kein API-Key noetig)

- **`piclaw/routines.py`** – Routinen-System
  - 4 eingebaute Routinen: Morgen-Briefing (07:00), Abend-Check (22:00),
    Wochenbericht (Mo 08:00), Temperatur-Watcher (alle 30 Min)
  - Alle standardmaessig deaktiviert, gezielt aktivierbar
  - Benutzerdefinierte Routinen: cron | briefing | agent_prompt | notify | ha_scene
  - Persistenz in /etc/piclaw/routines.json
  - 6 Agent-Tools: routine_list/enable/disable/create/run_now, briefing_now

- **`piclaw/proactive.py`** – Hintergrund-Loop
  - cron-Pruefung minuetlich, alle aktivierten Routinen ausgefuehrt
  - Schwellwert-Monitor alle 5 Minuten: CPU-Temp, Disk, RAM
  - 60-Minuten-Cooldown fuer Warnungen (kein Spam)
  - Ergebnisse ueber Messaging Hub an alle Kanaele
  - silent_on_ok: Temp-Check sendet nur bei Problemen

- **Wizard-Schritt** (`piclaw/wizard.py`)
  - Neuer Schritt 'Proaktiver Agent' nach Home Assistant
  - Routinen per Checkbox aktivieren
  - Standort fuer Wetter eintragen (Breitengrad/Laengengrad)
  - Schwellwerte konfigurieren

- **CLI-Befehle** (`piclaw/cli.py`)
  - `piclaw routine` – alle Routinen anzeigen
  - `piclaw routine enable <n>` – aktivieren
  - `piclaw routine disable <n>` – deaktivieren
  - `piclaw briefing [morning|evening|weekly|status]` – sofort ausgeben
  - `piclaw briefing send morning` – generieren und per Messaging senden

- **Daemon-Integration** (`piclaw/daemon.py`)
  - ProactiveRunner startet nach Agent-Boot
  - Routing-Tools automatisch im Agent registriert
  - Graceful Shutdown

### Beispiele (per Telegram)
  'Aktiviere das Morgen-Briefing'   -> routine_enable
  'Was ist der Status?'              -> briefing_now(status)
  'Erstelle eine Routine die mich freitags an das Backup erinnert' -> routine_create

## [0.12.0] – 2026-03-11

### Added
- **`piclaw/tools/homeassistant.py`** – Home Assistant Connector
  - REST API Client: Zustaende lesen, Services aufrufen, Automationen triggern
  - WebSocket Event-Listener: Echtzeit-Events (Bewegung, Tuer, Alarm, Rauch, Wasser)
  - Push-Benachrichtigungen: HA-Events -> Telegram/Discord/WhatsApp/MQTT
  - 11 Agent-Tools: ha_get_state, ha_list_entities, ha_turn_on/off/toggle,
    ha_set_temperature, ha_media, ha_summary, ha_trigger_automation,
    ha_run_script, ha_call_service
  - Auto-Reconnect WebSocket mit exponential backoff
  - Entity-Modell mit describe() fuer sprachnatuerliche Zustandsbeschreibung

- **HA-Tools im Agent** (`piclaw/agent.py`)
  - Alle 11 HA-Tools automatisch registriert wenn HA konfiguriert ist
  - Agent versteht natuerliche Befehle: 'Mach das Licht aus', 'Wie warm ist es?'

- **Daemon-Integration** (`piclaw/daemon.py`)
  - HA-Client startet beim Daemon-Boot vor dem Agent
  - WebSocket-Listener laeuft als asyncio-Task
  - Notify-Callback an Messaging Hub weitergeleitet (kein doppelter Hub)
  - Graceful Shutdown: HA-Client wird sauber geschlossen

- **Wizard-Schritt** (`piclaw/wizard.py`)
  - Neuer Schritt 'Home Assistant' zwischen Discord und MQTT
  - URL + Token eingeben, sofortiger Verbindungstest
  - Push-Event-Auswahl: welche Ereignisse per Nachricht gemeldet werden
  - Schreibt [homeassistant] Sektion in config.toml

- **Boot-Installer** (`boot/piclaw/install.sh`)
  - Liest PICLAW_HA_URL, PICLAW_HA_TOKEN, PICLAW_HA_NOTIFY_EVENTS aus piclaw.conf
  - Schreibt [homeassistant] Block in generierte config.toml

- **piclaw.conf** (`boot/piclaw/piclaw.conf`)
  - Neuer Abschnitt 6: Home Assistant (PICLAW_HA_URL, PICLAW_HA_TOKEN, Events)

### Flow
  Du (Telegram) -> 'Mach das Wohnzimmerlicht aus'
  -> PiClaw Agent (LLM erkennt Intent)
  -> ha_turn_off(light.wohnzimmer)
  -> Home Assistant REST API
  -> 'Wohnzimmerlicht ausgeschaltet' -> Telegram

  HA (Bewegungsmelder) -> state_changed Event (WebSocket)
  -> HAEventListener filtert relevante Events
  -> Notify-Callback -> Messaging Hub -> alle konfigurierten Kanaele
  -> 'Bewegung erkannt: Eingangsbereich'

## [0.11.0] – 2026-03-11

### Added
- **Boot-Partition Installer** (`boot/piclaw/`)
  - Neuer primärer Installationsweg: Ordner auf SD-Karte kopieren, fertig
  - Funktioniert auf Windows, macOS und Linux ohne Sondertools
  - Kein Image-Bau, kein Docker, kein debootstrap noetig

- **`boot/piclaw/piclaw.conf`** – Einfache Konfigurationsdatei
  - Kein Code, keine TOML-Syntax, nur KEY = "Wert" Zeilen
  - Konfigurierbar: API-Key, Agent-Name, Telegram, WLAN, Hostname, Port, Luefter
  - Auto-Erkennung des LLM-Providers aus dem Key-Format (sk-ant- vs sk-)
  - Oeffnet auf jedem Betriebssystem direkt im Standard-Texteditor

- **`boot/piclaw/install.sh`** – Offline-faehiger Boot-Installer
  - Liest alle Werte aus piclaw.conf (kein interaktives Abfragen noetig)
  - Installiert aus piclaw-src/ Ordner (offline) ODER klont von GitHub
  - 10-Schritte-Prozess: Pruefung, Hostname, WLAN, Pakete, Code, Hardware, Config, CLI, Services, Start
  - Schreibt fertige config.toml mit allen Werten aus piclaw.conf
  - Generiert API-Token automatisch
  - Aktiviert I2C/SPI/1-Wire in config.txt
  - SSH-sicher: Farben nur wenn TTY vorhanden

- **`boot/piclaw/piclaw-src/`** – Kompletter PiClaw-Code (offline)
  - Alle Python-Module, Tests, Docs, systemd-Units
  - Wird 1:1 nach /opt/piclaw/ kopiert

- **`boot/piclaw/README.txt`** – Nutzerfreundliche Anleitung
  - Plain Text (kein Markdown) - oeffnet auf Windows direkt im Editor
  - 5-Schritt-Anleitung + haeufige Probleme + Loesungen

### Changed
- `docs/sdcard-setup.md` NEU: Schritt-fuer-Schritt-Anleitung SD-Karte
- Primärer Installationsweg ist jetzt Boot-Partition (statt curl | bash)

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

"""
PiClaw OS – Proaktiver Hintergrund-Loop
========================================

Läuft als asyncio-Task im Daemon und:
  1. Prüft stündlich ob Routinen ausgeführt werden sollen (cron)
  2. Überwacht Schwellwerte (Temp, Disk, RAM) und benachrichtigt
  3. Führt Routinen aus und sendet Ergebnisse über die Messaging-Kanäle

Konfiguration in config.toml unter [proactive].
"""

import asyncio
import logging
import time
from datetime import datetime
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.proactive")


# ── Fehler-Dedup fürs Monitoring ──────────────────────────────────
# Die Threshold-/Direct-Checks laufen alle paar Minuten. Auf DEBUG (wie
# früher) sterben sie im INFO-Betrieb des Daemons unsichtbar; pures
# WARNING würde bei einem dauerhaft kaputten Check das Log fluten.
# Kompromiss: erstes Auftreten WARNING, Wiederholung höchstens alle
# 30 Minuten mit Zähler, dazwischen DEBUG.

_REPEAT_LOG_INTERVAL = 30 * 60  # Sekunden
_check_failures: dict[str, dict] = {}


def _log_check_failure(key: str, exc: Exception, *, silent: bool = False) -> None:
    """Loggt einen fehlgeschlagenen Monitor-Check dedupliziert.

    silent=True für erwartbare Fälle (z.B. vcgencmd fehlt auf Nicht-Pi):
    dauerhaft DEBUG statt WARNING.
    """
    now = time.monotonic()
    entry = _check_failures.get(key)
    if entry is None:
        _check_failures[key] = {"count": 1, "last_logged": now}
        (log.debug if silent else log.warning)(
            "Monitor-Check '%s' fehlgeschlagen: %r", key, exc
        )
        return
    entry["count"] += 1
    if not silent and now - entry["last_logged"] >= _REPEAT_LOG_INTERVAL:
        log.warning(
            "Monitor-Check '%s' fehlgeschlagen (%d× seit letzter Meldung): %r",
            key, entry["count"], exc,
        )
        entry["last_logged"] = now
        entry["count"] = 0
    else:
        log.debug("Monitor-Check '%s' fehlgeschlagen: %r", key, exc)


class ProactiveRunner:
    """
    Verwaltet den proaktiven Hintergrund-Loop.
    Wird vom Daemon gestartet und kennt alle nötigen Abhängigkeiten.
    """

    def __init__(self, cfg, hub, llm, agent=None):
        self.cfg = cfg
        self.hub = hub  # Messaging Hub (Telegram, Discord, ...)
        self.llm = llm  # LLM-Backend für Briefing-Generierung
        self.agent = agent  # Agent-Instanz für agent_prompt-Aktionen

        from piclaw.config import CONFIG_DIR
        from piclaw.routines import RoutineRegistry

        routines_file = CONFIG_DIR / "routines.json"
        self.registry = RoutineRegistry(routines_file)
        self._stop = asyncio.Event()
        self._last_threshold_alert: dict[str, datetime] = {}

    # ── Haupt-Loop ────────────────────────────────────────────────

    async def run(self) -> None:
        """Startet den proaktiven Loop. Blockiert bis stop() aufgerufen wird."""
        log.info(
            "Proaktiver Agent gestartet (%d Routinen, %d aktiv)",
            len(self.registry.all()),
            len(self.registry.enabled()),
        )

        # Wave 3.9: Cron-Routinen aus der Downtime nachholen, bevor die
        # regulären Loops starten. Eine Routine, die täglich 07:00 läuft
        # und der Pi war über die Zeit aus, würde sonst still übersprungen.
        await self._catch_up_missed_routines()

        # Tasks parallel starten
        await asyncio.gather(
            self._routine_loop(),
            self._threshold_loop(),
            return_exceptions=True,
        )

    # ── Missed-Run Catch-Up (Wave 3.9) ────────────────────────────

    async def _catch_up_missed_routines(self) -> None:
        """Beim Boot: alle Routinen nachholen, die während Downtime fällig waren.

        Begrenzt auf ein 24h-Fenster nach hinten. Längere Lücken sind
        wahrscheinlich geplante Maintenance – die wollen wir nicht
        stundenweise nachholen (Reboot um 9:00 würde sonst sieben
        verpasste stündliche Tasks auf einmal feuern).

        Pro Routine wird höchstens EIN Catch-Up-Run gefeuert.
        """
        try:
            from croniter import croniter as _croniter
        except ImportError:
            log.debug("croniter not installed – skipping missed-run catch-up")
            return

        MAX_CATCHUP_HOURS = 24
        now = datetime.now()
        caught_up = 0

        for routine in self.registry.enabled():
            try:
                cron = _croniter(routine.cron, now, ret_type=datetime)
                last_due = cron.get_prev(datetime)

                age_s = (now - last_due).total_seconds()
                if age_s > MAX_CATCHUP_HOURS * 3600:
                    continue
                if age_s < 60:
                    # Würde im normalen _routine_loop ohnehin gleich feuern
                    continue

                # Hat die Routine seit last_due schon gelaufen?
                last_run_str = routine.last_run or ""
                last_run = None
                if last_run_str:
                    try:
                        last_run = datetime.fromisoformat(last_run_str)
                    except ValueError:
                        try:
                            # Fallback für ältere Formate ohne Microseconds
                            last_run = datetime.strptime(
                                last_run_str[:19], "%Y-%m-%dT%H:%M:%S"
                            )
                        except ValueError:
                            last_run = None

                if last_run is None or last_run < last_due:
                    log.info(
                        "Routine '%s': missed run from %s (vor %.0f min) – catching up",
                        routine.name,
                        last_due.strftime("%Y-%m-%d %H:%M"),
                        age_s / 60,
                    )
                    create_background_task(
                        self._run_routine_safe(routine),
                        name=f"routine-catchup-{routine.id}",
                    )
                    caught_up += 1
                    # Staffeln, damit nicht alle Catch-Ups gleichzeitig
                    # auf hub.send_all() drücken (Telegram-Rate-Limit)
                    await asyncio.sleep(2)
            except Exception as e:
                log.warning("Catch-up check '%s' Fehler: %s", routine.name, e)

        if caught_up:
            log.info("Catch-up complete: %d missed routine(s) re-fired", caught_up)

    def stop(self) -> None:
        self._stop.set()

    # ── Cron-Loop (Routinen) ──────────────────────────────────────

    async def _routine_loop(self) -> None:
        """Prüft minütlich ob eine Routine fällig ist."""
        try:
            from croniter import croniter as _croniter
        except ImportError:
            log.warning("croniter nicht installiert – Routine-Loop deaktiviert")
            return

        # Vorab kompilierte croniter-Objekte pro Routine-ID (Caching)
        _cron_cache: dict[str, _croniter] = {}

        def _get_cron(routine) -> _croniter:
            if routine.id not in _cron_cache:
                _cron_cache[routine.id] = _croniter(routine.cron, ret_type=datetime)
            return _cron_cache[routine.id]

        last_minute = ""
        # Boot-Schutz: erste Prüfung erst nach 10s damit Daemon vollständig läuft
        await asyncio.sleep(10)

        while not self._stop.is_set():
            try:
                now = datetime.now()
                minute = now.strftime("%Y-%m-%d %H:%M")

                if minute != last_minute:
                    last_minute = minute
                    enabled = self.registry.enabled()
                    for routine in enabled:
                        try:
                            cron = _get_cron(routine)
                            # get_prev() gibt letzten Fälligkeitszeitpunkt zurück
                            prev = cron.get_prev(datetime)
                            delta_s = (now - prev).total_seconds()
                            already_ran = routine.last_run and routine.last_run[
                                :16
                            ] == now.strftime("%Y-%m-%d %H:%M")
                            if delta_s < 60 and not already_ran:
                                log.info(
                                    "Routine fällig: %s (vor %.0fs)",
                                    routine.name,
                                    delta_s,
                                )
                                await asyncio.sleep(0)  # yield to event loop
                                create_background_task(
                                    self._run_routine_safe(routine),
                                    name=f"routine-{routine.id}",
                                )
                        except Exception as e:
                            log.warning("Cron-Prüfung '%s' Fehler: %s", routine.name, e)
                            # Bei ungültiger Cron-Expression: aus Cache entfernen
                            _cron_cache.pop(routine.id, None)

            except Exception as e:
                log.error("Routine-Loop Fehler: %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
            except TimeoutError:
                pass

    async def _run_routine_safe(self, routine) -> None:
        """Führt eine Routine aus und loggt Fehler."""
        try:
            result = await self.execute_routine(routine)
            self.registry.mark_ran(routine.id)
            if result:
                log.info("Routine '%s' abgeschlossen: %s", routine.name, result[:80])
        except Exception as e:
            log.error("Routine '%s' Fehler: %s", routine.name, e)

    # ── Schwellwert-Loop ──────────────────────────────────────────

    async def _threshold_loop(self) -> None:
        """Überwacht System-Schwellwerte und sendet Warnungen."""
        # Cooldown: gleiche Warnung max. alle 60 Minuten
        COOLDOWN_MINUTES = 60

        while not self._stop.is_set():
            try:
                await self._check_thresholds(COOLDOWN_MINUTES)
            except Exception as e:
                _log_check_failure("threshold_loop", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=300)  # alle 5 Min
            except TimeoutError:
                pass

    async def _check_thresholds(self, cooldown_minutes: int) -> None:
        """Prüft Schwellwerte und sendet Warnungen bei Überschreitung."""
        import psutil

        now = datetime.now()

        def _cooldown_ok(key: str) -> bool:
            last = self._last_threshold_alert.get(key)
            if last is None:
                return True
            return (now - last).total_seconds() > cooldown_minutes * 60

        def _mark(key: str):
            self._last_threshold_alert[key] = now

        # Proaktive-Config lesen
        pcfg = getattr(self.cfg, "proactive", None)
        temp_warn = getattr(pcfg, "temp_warn_c", 80) if pcfg else 80
        disk_warn = getattr(pcfg, "disk_warn_pct", 85) if pcfg else 85
        ram_warn = getattr(pcfg, "ram_warn_pct", 90) if pcfg else 90

        warnings: list[str] = []

        # CPU-Temperatur – asyncio.to_thread statt subprocess.run (kein Event-Loop-Block)
        try:
            import subprocess as _sp
            result_obj = await asyncio.wait_for(
                asyncio.to_thread(
                    _sp.run,
                    ["vcgencmd", "measure_temp"],
                    capture_output=True, text=True,
                ),
                timeout=3,
            )
            if result_obj.returncode == 0:
                temp = float(result_obj.stdout.strip().replace("temp=", "").replace("'C", ""))
                if temp >= temp_warn and _cooldown_ok("cpu_temp"):
                    warnings.append(f"⚠ Pi CPU: {temp}°C (Grenze: {temp_warn}°C)")
                    _mark("cpu_temp")
        except Exception as _e:
            # vcgencmd fehlt auf Nicht-Pi-Systemen – das ist kein Fehler
            _log_check_failure("cpu_temp", _e, silent=isinstance(_e, FileNotFoundError))

        # Disk
        try:
            disk = psutil.disk_usage("/")
            if disk.percent >= disk_warn and _cooldown_ok("disk"):
                free_gb = round(disk.free / 1024**3, 1)
                warnings.append(f"⚠ Disk {disk.percent:.0f}% voll ({free_gb} GB frei)")
                _mark("disk")
        except Exception as _e:
            _log_check_failure("disk", _e)

        # RAM
        try:
            mem = psutil.virtual_memory()
            if mem.percent >= ram_warn and _cooldown_ok("ram"):
                warnings.append(f"⚠ RAM {mem.percent:.0f}% belegt")
                _mark("ram")
        except Exception as _e:
            _log_check_failure("ram", _e)

        # Warnungen senden
        if warnings and self.hub:
            msg = "PiClaw Warnung:\n" + "\n".join(warnings)
            try:
                await self.hub.send_all(msg)
                log.info("Schwellwert-Warnung gesendet: %s", ", ".join(warnings))
            except Exception as e:
                log.warning("Warnung senden fehlgeschlagen: %s", e)

    # ── Routine ausführen ─────────────────────────────────────────

    async def execute_routine(self, routine) -> str:
        """
        Führt eine einzelne Routine aus.
        Gibt das Ergebnis als String zurück.
        Sendet automatisch über hub wenn konfiguriert.

        Multi-User: setzt den User-Kontext (routine.owner_id) für die Dauer der
        Ausführung. Tool-Handler in der Routine sehen damit die Daten des
        Routinen-Owners (z.B. nur dessen Pakete im Morgenbriefing).
        """
        from piclaw.agent_context import user_scope

        action = routine.action
        params = routine.params

        result = ""

        # Mit User-Kontext der Routine — owner_id=None für System-Routinen
        # bedeutet "kein User-Filter" (volle Sicht).
        with user_scope(getattr(routine, "owner_id", None)):
            return await self._execute_routine_body(routine, action, params)

    async def _execute_routine_body(self, routine, action: str, params: dict) -> str:
        """Eigentliche Action-Dispatch — Wrapper hält user_scope offen."""
        result = ""

        if action == "briefing":
            from piclaw.briefing import generate_briefing

            briefing_type = params.get("type", "status")
            result = await generate_briefing(briefing_type, self.cfg, self.llm)

        elif action == "notify":
            result = params.get("message", "")

        elif action == "agent_prompt":
            prompt = params.get("prompt", "")
            silent = params.get("silent_on_ok", False)
            if prompt and self.agent:
                try:
                    response = await asyncio.wait_for(
                        self.agent.chat(prompt, context="routine"),
                        timeout=60,
                    )
                    result = str(response).strip()
                    # Bei silent_on_ok: nichts senden wenn "alles OK" o.ä.
                    if silent and _looks_ok(result):
                        log.debug("Routine '%s': alles OK, still.", routine.name)
                        return result
                except TimeoutError:
                    result = f"Routine '{routine.name}' Timeout."
                except Exception as e:
                    result = f"Fehler: {e}"
            elif prompt:
                result = f"[Kein Agent – Prompt: {prompt[:80]}]"

        elif action == "direct_check":
            # ── Tokenloser Check: kein LLM, direkte Systemabfragen ──────────
            result = await _run_direct_check(params, routine.name)

        elif action == "ha_scene":
            scene = params.get("scene_id", "")
            if scene:
                try:
                    from piclaw.tools.homeassistant import get_client

                    client = get_client()
                    if client:
                        ok = await client.call_service("scene", "turn_on", scene)
                        result = f"Szene '{scene}' {'aktiviert' if ok else 'fehlgeschlagen'}."
                    else:
                        result = "Home Assistant nicht verbunden."
                except Exception as e:
                    result = f"HA Fehler: {e}"

        # Nachricht senden
        if result and self.hub:
            try:
                channel = routine.channel
                if channel == "all":
                    await self.hub.send_all(result)
                else:
                    await self.hub.send_to(channel, result)
            except Exception as e:
                log.warning("Routine-Nachricht senden fehlgeschlagen: %s", e)

        return result


async def _run_direct_check(params: dict, routine_name: str) -> str:
    """
    Tokenloser Direct-Check: Prüft Schwellwerte und Netzwerk ohne LLM-Aufruf.

    Unterstützte check_type-Werte:
      cpu_temp  – CPU-Temperatur via vcgencmd
      disk      – Disk-Auslastung via psutil
      ram       – RAM-Auslastung via psutil
      new_devices – Neue Netzwerkgeräte via network_monitor
      ha_state  – Home-Assistant Entity-State vergleichen
    """
    check_type = params.get("check_type", "cpu_temp")
    threshold = params.get("threshold")

    # ── CPU-Temperatur ──────────────────────────────────────────────
    if check_type == "cpu_temp":
        limit = float(threshold) if threshold is not None else 80.0
        try:
            import subprocess as _sp
            r = await asyncio.wait_for(
                asyncio.to_thread(
                    _sp.run, ["vcgencmd", "measure_temp"],
                    capture_output=True, text=True,
                ),
                timeout=3,
            )
            if r.returncode != 0:
                return ""
            temp = float(r.stdout.strip().replace("temp=", "").replace("'C", ""))
            if temp >= limit:
                return f"⚠️ Pi CPU-Temperatur: {temp}°C (Grenze: {limit}°C)"
        except Exception as e:
            _log_check_failure(f"direct_check cpu_temp@{routine_name}", e,
                               silent=isinstance(e, FileNotFoundError))
        return ""  # Kein Problem → keine Nachricht

    # ── Disk ────────────────────────────────────────────────────────
    elif check_type == "disk":
        limit = float(threshold) if threshold is not None else 85.0
        try:
            import psutil
            disk = psutil.disk_usage("/")
            if disk.percent >= limit:
                free_gb = round(disk.free / 1024**3, 1)
                return f"⚠️ Disk {disk.percent:.0f}% voll ({free_gb} GB frei)"
        except Exception as e:
            _log_check_failure(f"direct_check disk@{routine_name}", e)
        return ""

    # ── RAM ─────────────────────────────────────────────────────────
    elif check_type == "ram":
        limit = float(threshold) if threshold is not None else 90.0
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent >= limit:
                return f"⚠️ RAM {mem.percent:.0f}% belegt"
        except Exception as e:
            _log_check_failure(f"direct_check ram@{routine_name}", e)
        return ""

    # ── Neue Netzwerkgeräte ─────────────────────────────────────────
    elif check_type == "new_devices":
        try:
            from piclaw.tools.network_monitor import check_new_devices
            new = await asyncio.wait_for(check_new_devices(), timeout=120)
            if new:
                lines = [f"🔍 {len(new)} neues Gerät(e) im Netzwerk erkannt:"]
                for d in new:
                    lines.append(f"  📍 {d.ip}  {d.mac}  {d.vendor}  {d.hostname}")
                return "\n".join(lines)
        except Exception as e:
            _log_check_failure(f"direct_check new_devices@{routine_name}", e)
        return ""

    # ── Home Assistant State ─────────────────────────────────────────
    elif check_type == "ha_state":
        entity_id = params.get("entity_id", "")
        expected = params.get("expected_state", "")
        alert_msg = params.get("alert_message", "")
        if not entity_id:
            return ""
        try:
            from piclaw.tools.homeassistant import get_client
            client = get_client()
            if client:
                state = await client.get_state(entity_id)
                actual = state.get("state", "") if isinstance(state, dict) else str(state)
                if expected and actual != expected:
                    msg = alert_msg or f"⚠️ {entity_id}: Status ist '{actual}' (erwartet: '{expected}')"
                    return msg
        except Exception as e:
            _log_check_failure(f"direct_check ha_state@{routine_name}", e)
        return ""

    log.warning("direct_check: unbekannter check_type '%s' in Routine '%s'", check_type, routine_name)
    return ""


def _looks_ok(text: str) -> bool:
    """Prüft ob eine Antwort 'alles in Ordnung' bedeutet (für silent_on_ok)."""
    ok_phrases = [
        "alles",
        "normal",
        "in ordnung",
        "keine warnung",
        "kein problem",
        "stabil",
        "optimal",
        "gut",
        "ok",
        "temperature",
        "within",
    ]
    text_lower = text.lower()
    # Wenn keine Warnsignale UND mindestens ein OK-Ausdruck
    warn_phrases = [
        "warn",
        "kritisch",
        "hoch",
        "voll",
        "fehler",
        "problem",
        "überhitzt",
    ]
    has_warning = any(w in text_lower for w in warn_phrases)
    has_ok = any(o in text_lower for o in ok_phrases)
    return has_ok and not has_warning


# ── Lifecycle ─────────────────────────────────────────────────────

_runner: ProactiveRunner | None = None


def get_runner() -> ProactiveRunner | None:
    return _runner


async def start(cfg, hub, llm, agent=None) -> ProactiveRunner:
    global _runner
    _runner = ProactiveRunner(cfg, hub, llm, agent)
    create_background_task(_runner.run(), name="proactive-runner")
    return _runner


async def stop():
    if _runner:
        _runner.stop()

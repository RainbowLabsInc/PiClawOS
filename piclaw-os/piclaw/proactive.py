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
from datetime import datetime
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.proactive")


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

        # Tasks parallel starten
        await asyncio.gather(
            self._routine_loop(),
            self._threshold_loop(),
            return_exceptions=True,
        )

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
                log.debug("Threshold-Check Fehler: %s", e)

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

        # CPU-Temperatur
        try:
            import subprocess

            r = subprocess.run(
                ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                temp = float(r.stdout.strip().replace("temp=", "").replace("'C", ""))
                if temp >= temp_warn and _cooldown_ok("cpu_temp"):
                    warnings.append(f"⚠ Pi CPU: {temp}°C (Grenze: {temp_warn}°C)")
                    _mark("cpu_temp")
        except Exception as _e:
            log.debug("cpu_temp check: %s", _e)

        # Disk
        try:
            disk = psutil.disk_usage("/")
            if disk.percent >= disk_warn and _cooldown_ok("disk"):
                free_gb = round(disk.free / 1024**3, 1)
                warnings.append(f"⚠ Disk {disk.percent:.0f}% voll ({free_gb} GB frei)")
                _mark("disk")
        except Exception as _e:
            log.debug("disk check: %s", _e)

        # RAM
        try:
            mem = psutil.virtual_memory()
            if mem.percent >= ram_warn and _cooldown_ok("ram"):
                warnings.append(f"⚠ RAM {mem.percent:.0f}% belegt")
                _mark("ram")
        except Exception as _e:
            log.debug("ram check: %s", _e)

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
        """
        action = routine.action
        params = routine.params

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

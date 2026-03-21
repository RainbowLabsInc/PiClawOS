"""
PiClaw OS – Briefing Engine
============================

Sammelt Kontext aus allen verfügbaren Quellen und baut daraus
eine strukturierte Briefing-Nachricht zusammen.

Quellen:
  - Pi-Hardware: CPU-Temp, RAM, Disk, Uptime
  - Wetter:      OpenMeteo (kostenlos, kein API-Key)
  - Home Assistant: Lichter, Thermostate, Alarme
  - Metriken:    Trends aus der SQLite-Datenbank
  - System:      laufende Services, letzte Fehler

Das Briefing wird vom LLM zu einer natürlichen Nachricht zusammengefasst.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

_SECS_PER_DAY = 86_400  # Sekunden pro Tag


log = logging.getLogger("piclaw.briefing")


# ── Kontext-Sammler ───────────────────────────────────────────────

async def _gather_pi_status() -> dict[str, Any]:
    """Pi-Hardware-Status."""
    try:
        import psutil, subprocess
        cpu_temp = None
        try:
            loop = asyncio.get_running_loop()
            def _vcgencmd():
                r = subprocess.run(
                    ["vcgencmd", "measure_temp"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0:
                    return float(r.stdout.strip().replace("temp=", "").replace("'C", ""))
                return None
            cpu_temp = await loop.run_in_executor(None, _vcgencmd)
        except Exception:
            temps = psutil.sensors_temperatures()
            for key in ("cpu_thermal", "coretemp", "k10temp"):
                if key in temps and temps[key]:
                    cpu_temp = temps[key][0].current
                    break

        mem   = psutil.virtual_memory()
        disk  = psutil.disk_usage("/")
        if _BOOT_TIME is None:
            _BOOT_TIME = psutil.boot_time()
        boot  = datetime.fromtimestamp(_BOOT_TIME, tz=timezone.utc)
        now   = datetime.now(tz=timezone.utc)
        uptime_h = round((now - boot).total_seconds() / 3600, 1)

        return {
            "cpu_temp_c":    round(cpu_temp, 1) if cpu_temp else None,
            "ram_used_pct":  round(mem.percent, 1),
            "ram_used_mb":   round(mem.used / 1024**2),
            "ram_total_mb":  round(mem.total / 1024**2),
            "disk_used_pct": round(disk.percent, 1),
            "disk_free_gb":  round(disk.free / 1024**3, 1),
            "uptime_h":      uptime_h,
        }
    except Exception as e:
        log.debug("Pi-Status Fehler: %s", e)
        return {}


async def _gather_weather(lat: float, lon: float) -> dict[str, Any]:
    """
    Wetter von Open-Meteo (kostenlos, kein API-Key).
    https://open-meteo.com/
    """
    try:
        import aiohttp
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "weather_code"
            "&timezone=auto&forecast_days=2"
        )
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return {}
                data = await r.json()

        current = data.get("current", {})
        daily   = data.get("daily", {})

        # WMO Weather Code -> Beschreibung
        wmo_codes = {
            0: "klar", 1: "überwiegend klar", 2: "teilweise bewölkt",
            3: "bedeckt", 45: "neblig", 48: "gefrierender Nebel",
            51: "leichter Nieselregen", 53: "Nieselregen", 55: "starker Nieselregen",
            61: "leichter Regen", 63: "Regen", 65: "starker Regen",
            71: "leichter Schnee", 73: "Schnee", 75: "starker Schnee",
            80: "leichte Schauer", 81: "Schauer", 82: "starke Schauer",
            95: "Gewitter", 99: "starkes Gewitter",
        }
        code = current.get("weather_code", -1)
        desc = wmo_codes.get(code, f"Code {code}")

        result: dict[str, Any] = {
            "temp_c":        current.get("temperature_2m"),
            "feels_like_c":  current.get("apparent_temperature"),
            "humidity_pct":  current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation", 0),
            "wind_kmh":      current.get("wind_speed_10m"),
            "description":   desc,
        }

        # Tages-Vorhersage
        if daily.get("temperature_2m_max"):
            result["today_max_c"]   = daily["temperature_2m_max"][0]
            result["today_min_c"]   = daily["temperature_2m_min"][0]
            result["today_rain_mm"] = daily["precipitation_sum"][0]
            today_code              = daily["weather_code"][0]
            result["today_desc"]    = wmo_codes.get(today_code, f"Code {today_code}")

        # Morgen
        if daily.get("temperature_2m_max") and len(daily["temperature_2m_max"]) > 1:
            result["tomorrow_max_c"] = daily["temperature_2m_max"][1]
            result["tomorrow_min_c"] = daily["temperature_2m_min"][1]
            result["tomorrow_desc"]  = wmo_codes.get(
                daily["weather_code"][1], ""
            )

        return result

    except Exception as e:
        log.debug("Wetter Fehler: %s", e)
        return {}


async def _gather_ha_snapshot() -> dict[str, Any]:
    """Schnappschuss relevanter HA-Entitäten."""
    try:
        from piclaw.tools.homeassistant import get_client
        client = get_client()
        if not client:
            return {}

        result: dict[str, Any] = {}

        # Lichter die an sind
        lights = await client.get_states(domain="light")
        on_lights = [e.name for e in lights if e.state == "on"]
        result["lights_on"] = on_lights

        # Thermostate
        climates = await client.get_states(domain="climate")
        result["thermostats"] = [
            {
                "name":    e.name,
                "current": e.attributes.get("current_temperature"),
                "target":  e.attributes.get("temperature"),
                "mode":    e.attributes.get("hvac_mode", e.state),
            }
            for e in climates
        ]

        # Alarme
        alarms = await client.get_states(domain="alarm_control_panel")
        result["alarms"] = [
            {"name": e.name, "state": e.state}
            for e in alarms
        ]

        # Offene Türen/Fenster
        doors = await client.get_states(domain="binary_sensor")
        open_doors = [
            e.name for e in doors
            if e.state == "on" and any(
                k in e.entity_id for k in ("door", "window", "tuer", "fenster")
            )
        ]
        result["open_doors"] = open_doors

        return result
    except Exception as e:
        log.debug("HA Snapshot Fehler: %s", e)
        return {}


async def _gather_metrics_trends() -> dict[str, Any]:
    """Trends aus der Metriken-Datenbank (letzte 24h)."""
    try:
        from piclaw.metrics import get_db
        db  = get_db()
        result: dict[str, Any] = {}

        summary = db.query_summary(
            names=["cpu_temp_c", "cpu_percent", "ram_percent"],
            since_s=_SECS_PER_DAY
        )

        for metric, stats in summary.items():
            result[f"{metric}_avg24h"] = stats["avg"]
            result[f"{metric}_max24h"] = stats["max"]

        return result
    except Exception as e:
        log.debug("Metriken Fehler: %s", e)
        return {}


# ── Briefing zusammenstellen ──────────────────────────────────────

async def gather_context(cfg=None) -> dict[str, Any]:
    """Sammelt alle verfügbaren Kontext-Daten parallel."""

    tasks = {
        "pi":      _gather_pi_status(),
        "ha":      _gather_ha_snapshot(),
        "metrics": _gather_metrics_trends(),
    }

    # Wetter nur wenn Koordinaten konfiguriert
    lat = lon = None
    if cfg:
        try:
            loc = getattr(cfg, "location", None)
            if loc:
                lat = getattr(loc, "latitude",  None)
                lon = getattr(loc, "longitude", None)
        except Exception as _e:
            log.debug("location config read: %s", _e)

    if lat and lon:
        tasks["weather"] = _gather_weather(lat, lon)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    context: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "weekday":   ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                      "Freitag", "Samstag", "Sonntag"][datetime.now().weekday()],
    }
    for key, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            log.debug("Kontext '%s' Fehler: %s", key, result)
        elif isinstance(result, dict):
            context[key] = result

    return context


def _format_context_for_llm(ctx: dict) -> str:
    """Formatiert den Kontext als strukturierten Text für den LLM-Prompt."""
    lines: list[str] = [
        f"Aktuelle Zeit: {ctx['timestamp']} ({ctx['weekday']})",
        "",
    ]

    # Pi-Status
    pi = ctx.get("pi", {})
    if pi:
        lines.append("=== Raspberry Pi Status ===")
        if pi.get("cpu_temp_c"):
            warn = " (!)" if pi["cpu_temp_c"] > 75 else ""
            lines.append(f"CPU Temperatur: {pi['cpu_temp_c']}°C{warn}")
        lines.append(f"RAM: {pi.get('ram_used_pct', '?')}% belegt ({pi.get('ram_used_mb', '?')} MB)")
        lines.append(f"Disk: {pi.get('disk_used_pct', '?')}% belegt ({pi.get('disk_free_gb', '?')} GB frei)")
        lines.append(f"Uptime: {pi.get('uptime_h', '?')}h")
        lines.append("")

    # Wetter
    weather = ctx.get("weather", {})
    if weather:
        lines.append("=== Wetter ===")
        lines.append(f"Aktuell: {weather.get('temp_c', '?')}°C, {weather.get('description', '')}")
        if weather.get("feels_like_c"):
            lines.append(f"Gefühlt: {weather['feels_like_c']}°C")
        if weather.get("today_max_c"):
            lines.append(f"Heute: {weather['today_min_c']}–{weather['today_max_c']}°C, {weather.get('today_desc', '')}")
        if weather.get("today_rain_mm", 0) > 0:
            lines.append(f"Niederschlag heute: {weather['today_rain_mm']} mm")
        if weather.get("tomorrow_max_c"):
            lines.append(f"Morgen: bis {weather['tomorrow_max_c']}°C, {weather.get('tomorrow_desc', '')}")
        lines.append("")

    # Home Assistant
    ha = ctx.get("ha", {})
    if ha:
        lines.append("=== Home Assistant ===")
        lights_on = ha.get("lights_on", [])
        if lights_on:
            lines.append(f"Lichter an: {', '.join(lights_on[:5])}")
        else:
            lines.append("Alle Lichter aus")

        open_doors = ha.get("open_doors", [])
        if open_doors:
            lines.append(f"Offen: {', '.join(open_doors)}")

        for t in ha.get("thermostats", [])[:3]:
            if t.get("current"):
                lines.append(
                    f"Thermostat {t.get('name', '?')}: {t.get('current')}°C "
                    f"(Soll: {t.get('target', '?')}°C)"
                )
        for a in ha.get("alarms", []):
            state = a.get("state", "")
            if state not in ("disarmed", "off", ""):
                lines.append(f"ALARM {a.get('name', '?')}: {state}")
        lines.append("")

    # Metriken-Trends
    metrics = ctx.get("metrics", {})
    if metrics:
        lines.append("=== 24h Trends ===")
        if metrics.get("cpu_temp_c_avg24h"):
            lines.append(f"CPU Temp: Ø {metrics.get('cpu_temp_c_avg24h')}°C, Max {metrics.get('cpu_temp_c_max24h', '?')}°C")
        if metrics.get("cpu_percent_avg24h"):
            lines.append(f"CPU Last: Ø {metrics.get('cpu_percent_avg24h')}%")
        if metrics.get("ram_percent_avg24h"):
            lines.append(f"RAM: Ø {metrics.get('ram_percent_avg24h')}%")

    return "\n".join(lines)


async def generate_briefing(
    briefing_type: str,
    cfg=None,
    llm=None,
) -> str:
    """
    Erstellt ein vollständiges Briefing.

    briefing_type: "morning" | "evening" | "weekly" | "status"
    Gibt die fertige Nachricht zurück (via LLM oder Fallback-Template).
    """
    ctx = await gather_context(cfg)
    context_text = _format_context_for_llm(ctx)

    prompts = {
        "morning": (
            "Erstelle ein prägnantes Morgen-Briefing auf Deutsch. "
            "Fasse die wichtigsten Punkte kurz zusammen: Wetter, Pi-Status, "
            "Home Assistant Besonderheiten (nur wenn relevant). "
            "Ton: freundlich, informativ, max. 5-8 Zeilen. "
            "Beginne mit einem Tagesgruß."
        ),
        "evening": (
            "Erstelle eine kurze Abend-Zusammenfassung auf Deutsch. "
            "Fokus: offene Lichter, Türen, Pi-Temperatur, "
            "Hinweise für die Nacht falls nötig. "
            "Ton: entspannt, max. 4-6 Zeilen. "
            "Frage ob noch etwas zu erledigen ist."
        ),
        "weekly": (
            "Erstelle eine wöchentliche Systemzusammenfassung auf Deutsch. "
            "Analysiere die 24h-Trends kritisch: Was lief gut? "
            "Gibt es Auffälligkeiten bei Temperatur, RAM oder Disk? "
            "Empfiehl konkrete Maßnahmen falls nötig. "
            "Max. 8-10 Zeilen."
        ),
        "status": (
            "Erstelle einen kompakten Statusbericht auf Deutsch. "
            "Alle wichtigen Werte auf einen Blick. "
            "Hebe kritische Werte hervor. Max. 6 Zeilen."
        ),
    }

    system_prompt = prompts.get(briefing_type, prompts["status"])

    if llm:
        try:
            messages = [
                {
                    "role": "user",
                    "content": (
                        "Hier sind die aktuellen Systemdaten:\n\n"
                        f"{context_text}\n\n"
                        f"{system_prompt}"
                    ),
                }
            ]
            response = await asyncio.wait_for(
                llm.complete(messages),
                timeout=30,
            )
            text = str(response).strip()
            if text:
                return text
        except asyncio.TimeoutError:
            log.warning("LLM Briefing Timeout (>30s) – Fallback auf Template")
        except Exception as e:
            log.warning("LLM Briefing Fehler: %s – Fallback", e)

    # Fallback: Template-basiertes Briefing (kein LLM nötig)
    return _template_briefing(briefing_type, ctx)


def _template_briefing(briefing_type: str, ctx: dict) -> str:
    """Einfaches Template-Briefing ohne LLM."""
    now = ctx["timestamp"]
    weekday = ctx["weekday"]
    lines: list[str] = []

    pi    = ctx.get("pi", {})
    wthr  = ctx.get("weather", {})
    ha    = ctx.get("ha", {})

    if briefing_type == "morning":
        lines.append(f"Guten Morgen! Es ist {weekday}, {now}.")
        if wthr:
            lines.append(
                f"Wetter: {wthr.get('temp_c', '?')}°C, "
                f"{wthr.get('description', '')}. "
                f"Heute bis {wthr.get('today_max_c', '?')}°C."
            )
        if pi.get("cpu_temp_c", 0) > 75:
            lines.append(f"⚠ Pi läuft warm: {pi['cpu_temp_c']}°C – bitte prüfen.")

    elif briefing_type == "evening":
        lines.append(f"Guten Abend! {now}.")
        lights = ha.get("lights_on", [])
        if lights:
            lines.append(f"Noch an: {', '.join(lights)}. Soll ich ausschalten?")
        else:
            lines.append("Alle Lichter sind aus. Gute Nacht!")
        open_d = ha.get("open_doors", [])
        if open_d:
            lines.append(f"Noch offen: {', '.join(open_d)}.")

    elif briefing_type == "weekly":
        lines.append(f"Wochenbericht – {now}:")
        metrics = ctx.get("metrics", {})
        if metrics.get("cpu_temp_c_max24h", 0) > 80:
            lines.append(f"⚠ Hohe Temperaturen diese Woche (Max: {metrics['cpu_temp_c_max24h']}°C).")
        if pi.get("disk_used_pct", 0) > 80:
            lines.append(f"⚠ Disk fast voll: {pi['disk_used_pct']}% belegt.")
        lines.append("System läuft stabil.")

    else:
        lines.append(f"PiClaw Status – {now}")
        if pi:
            lines.append(f"Temp: {pi.get('cpu_temp_c', '?')}°C | RAM: {pi.get('ram_used_pct', '?')}% | Disk: {pi.get('disk_used_pct', '?')}%")

    return "\n".join(lines) or "Alles in Ordnung."
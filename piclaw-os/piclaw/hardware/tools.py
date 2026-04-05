"""
PiClaw OS – Hardware Agent Tools
Exposes hardware capabilities to the LLM agent.

Tools:
  pi_info          Read Pi hardware status (temp, throttle, clocks, voltages)
  i2c_scan         Scan I2C buses for connected devices
  sensor_list      List all registered named sensors
  sensor_read      Read a specific named sensor
  sensor_read_all  Read all enabled sensors
  sensor_add       Register a new named sensor
  sensor_remove    Remove a named sensor
  thermal_status   Get current thermal state and LLM routing recommendation
"""

import logging
from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.hardware.tools")


# ── Tool definitions (schema for LLM) ────────────────────────────

TOOL_DEFS = [
    ToolDefinition(
        name="pi_info",
        description=(
            "Read Raspberry Pi hardware telemetry: CPU temperature, throttle status, "
            "CPU/GPU clock frequencies, core voltage, GPU memory split, Pi model and RAM. "
            "Use this to check if the Pi is running hot, throttled, or under-voltage."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="i2c_scan",
        description=(
            "Scan I2C buses for connected devices and identify them by address. "
            "Returns a list of found devices with names (e.g. 'BMP280 pressure sensor at 0x76'). "
            "Use this to discover what hardware is physically connected."
        ),
        parameters={
            "type": "object",
            "properties": {
                "bus": {
                    "type": "integer",
                    "description": "I2C bus number to scan (default: 1, the main GPIO bus). Use -1 to scan all.",
                    "default": 1,
                }
            },
        },
    ),
    ToolDefinition(
        name="sensor_list",
        description="List all registered named sensors with their type, description, and last reading.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="sensor_read",
        description=(
            "Read the current value from a named sensor (e.g. 'balcony_temp', 'pir_front_door'). "
            "Returns temperature, humidity, distance, voltage, etc. depending on sensor type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Sensor name as registered"},
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="sensor_read_all",
        description="Read all enabled sensors concurrently. Returns all current values in one call.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="sensor_add",
        description=(
            "Register a new named sensor. "
            "Types: DHT22, DS18B20, BMP280, SHT40, BH1750, ADS1115, INA219, PIR, HC_SR04, GPIO_INPUT. "
            "Config examples: DHT22={pin:4}, BMP280={i2c_bus:1,address:118}, PIR={pin:17}, "
            "HC_SR04={trigger_pin:23,echo_pin:24}, INA219={i2c_bus:1,address:64,shunt_ohm:0.1}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique sensor name"},
                "type": {
                    "type": "string",
                    "description": "Sensor type (DHT22, BMP280, PIR, etc.)",
                },
                "description": {
                    "type": "string",
                    "description": "What this sensor monitors",
                },
                "config": {
                    "type": "object",
                    "description": "Driver config (pin, address, etc.)",
                },
            },
            "required": ["name", "type"],
        },
    ),
    ToolDefinition(
        name="sensor_remove",
        description="Remove a named sensor from the registry.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Sensor name to remove"},
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="thermal_status",
        description=(
            "Get the current thermal state of the Pi: temperature, throttle state, "
            "and whether local LLM inference is advisable. "
            "States: cool (<55°C), warm (55–70°C), hot (70–80°C, cloud preferred), "
            "critical (80–85°C, local disabled), emergency (>85°C)."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="system_report",
        description=(
            "Erstellt einen deutschen Systembericht (Temperatur, RAM, CPU, Disk) ohne LLM. "
            "Ideal als direct_tool für täglich geplante CronJob-Agenten."
        ),
        parameters={"type": "object", "properties": {}},
    ),
]


# ── Handler implementations ───────────────────────────────────────


async def _pi_info() -> str:
    try:
        from piclaw.hardware.pi_info import read_pi_info

        info = await read_pi_info()
        return info.format_report()
    except Exception as e:
        return f"[pi_info error] {e}"


async def _i2c_scan(bus: int = 1) -> str:
    try:
        from piclaw.hardware.i2c_scan import (
            scan_bus,
            scan_all_buses,
            format_scan_report,
        )

        if bus == -1:
            results = await scan_all_buses()
        else:
            results = [await scan_bus(bus)]
        return format_scan_report(results)
    except Exception as e:
        return f"[i2c_scan error] {e}"


def _get_registry():
    """Lazily import and return the global sensor registry."""
    from piclaw.hardware import get_sensor_registry

    return get_sensor_registry()


async def _sensor_list() -> str:
    try:
        reg = _get_registry()
        return reg.summary()
    except Exception as e:
        return f"[sensor_list error] {e}"


async def _sensor_read(name: str) -> str:
    try:
        from piclaw.hardware.sensors import read_sensor

        reg = _get_registry()
        sensor = reg.get(name)
        if not sensor:
            return (
                f"Sensor '{name}' not found. Use sensor_list to see available sensors."
            )
        reading = await read_sensor(sensor)
        reg.update_reading(name, reading)
        return str(reading)
    except Exception as e:
        return f"[sensor_read error] {e}"


async def _sensor_read_all() -> str:
    try:
        from piclaw.hardware.sensors import read_all_sensors

        reg = _get_registry()
        readings = await read_all_sensors(reg)
        if not readings:
            return "No sensors registered. Use sensor_add to add sensors."
        return "\n".join(str(r) for r in readings)
    except Exception as e:
        return f"[sensor_read_all error] {e}"


async def _sensor_add(
    name: str, sensor_type: str, description: str = "", config: dict = None
) -> str:
    try:
        from piclaw.hardware.sensors import SensorDef, ALL_TYPES

        if type not in ALL_TYPES:
            return f"Unknown sensor type '{type}'. Valid types: {', '.join(ALL_TYPES)}"
        reg = _get_registry()
        if reg.get(name):
            return f"Sensor '{name}' already exists. Remove it first or use a different name."
        sensor = SensorDef(
            name=name,
            type=type,
            description=description,
            config=config or {},
        )
        reg.add(sensor)
        return (
            f"Sensor '{name}' ({type}) registered. Use sensor_read {name} to test it."
        )
    except Exception as e:
        return f"[sensor_add error] {e}"


async def _sensor_remove(name: str) -> str:
    try:
        reg = _get_registry()
        if reg.remove(name):
            return f"Sensor '{name}' removed."
        return f"Sensor '{name}' not found."
    except Exception as e:
        return f"[sensor_remove error] {e}"


async def _thermal_status() -> str:
    try:
        from piclaw.hardware.thermal import get_thermal_state, make_status
        from piclaw.hardware.pi_info import current_temp, is_throttled

        status = get_thermal_state()
        if status is None:
            # Manual one-shot read
            temp = current_temp()
            if temp is None:
                return "Temperature not available (not running on Pi hardware)"
            throttled = is_throttled()
            status = make_status(temp, throttle_active=throttled)
        lines = [
            status.message,
            f"  Local LLM:  {'✅ allowed' if status.local_ok else '❌ disabled (too hot)'}",
            f"  Cloud pref: {'yes' if status.cloud_pref else 'no'}",
        ]
        if status.throttle_active:
            lines.append(
                "  ⚠️  Firmware throttling active (check power supply / cooling)"
            )
        if status.under_voltage:
            lines.append("  ⚠️  Under-voltage detected – use official Pi power supply")
        return "\n".join(lines)
    except Exception as e:
        return f"[thermal_status error] {e}"



async def _system_report() -> str:
    """
    Erstellt einen deutschen Systembericht ohne LLM.
    Wird als direct_tool für CronJob-Agenten genutzt um Groq/NIM Token zu sparen.
    Ersetzt den LLM-basierten Systembericht (vorher: ~3-5 LLM-Calls/Tag).
    """
    from datetime import datetime

    lines = [f"🖥️ *Systembericht* – {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"]

    # Temperatur
    try:
        temp_text = await _thermal_status()
        # Erste Zeile extrahieren (enthält Status + Temperatur)
        temp_line = temp_text.splitlines()[0] if temp_text else "–"
        lines.append(f"🌡️ {temp_line}")
    except Exception as e:
        lines.append(f"🌡️ Temperatur: Fehler ({e})")

    # System-Info
    try:
        info_text = await _pi_info()
        # Relevante Zeilen aus pi_info extrahieren
        for line in info_text.splitlines():
            line_str = line.strip()
            if any(k in line_str.lower() for k in ("cpu", "ram", "disk", "speicher", "uptime", "load", "memory")):
                lines.append(f"  {line_str}")
    except Exception as e:
        lines.append(f"  System-Info: Fehler ({e})")

    # psutil für RAM/Disk (schnell, kein LLM nötig)
    try:
        import psutil
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu = psutil.cpu_percent(interval=0.5)
        lines.append(f"💾 RAM: {mem.percent:.0f}% ({mem.used//1024//1024}/{mem.total//1024//1024} MB)")
        lines.append(f"💽 Disk: {disk.percent:.0f}% ({disk.used//1024**3:.1f}/{disk.total//1024**3:.1f} GB)")
        lines.append(f"⚙️  CPU: {cpu:.0f}%")
    except ImportError:
        pass
    except Exception as e:
        lines.append(f"  Stats: Fehler ({e})")

    # Bewertung
    try:
        temp_val = None
        import re
        m = re.search(r"(\d+\.\d+)\s*°C", "\n".join(lines))
        if m:
            temp_val = float(m.group(1))
        if temp_val and temp_val >= 75:
            lines.append("\n⚠️ Temperatur kritisch – Lüftung prüfen!")
        elif temp_val and temp_val >= 60:
            lines.append("\n⚠️ Temperatur erhöht.")
        else:
            lines.append("\n✅ System läuft stabil.")
    except Exception:
        pass

    return "\n".join(lines)


# ── Handler dispatch map ──────────────────────────────────────────

HANDLERS: dict[str, callable] = {
    "pi_info": lambda **_: _pi_info(),
    "i2c_scan": lambda **kw: _i2c_scan(**kw),
    "sensor_list": lambda **_: _sensor_list(),
    "sensor_read": lambda **kw: _sensor_read(**kw),
    "sensor_read_all": lambda **_: _sensor_read_all(),
    "sensor_add": lambda **kw: _sensor_add(**kw),
    "sensor_remove": lambda **kw: _sensor_remove(**kw),
    "thermal_status": lambda **_: _thermal_status(),
    "system_report":  lambda **_: _system_report(),
}

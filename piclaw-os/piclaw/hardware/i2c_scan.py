"""
PiClaw OS – I2C Bus Scanner
Scans I2C buses and matches addresses against a database of known devices.

Pi 5 has two I2C buses accessible on the GPIO header:
  i2c-1  (SDA=GPIO2, SCL=GPIO3) – standard, most common
  i2c-0  (GPIO0/1)               – system/HAT bus, usually reserved

Supports both smbus2 (Python) and i2cdetect (system tool) as fallback.

Known device database covers ~40 common hobby sensors and modules.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("piclaw.hardware.i2c_scan")


# ── Known I2C device database ─────────────────────────────────────
# address → {name, description, driver_hint, category}
KNOWN_I2C_DEVICES: dict[int, dict] = {
    # ── Temperature / Humidity / Pressure ──
    0x48: {"name": "ADS1115", "desc": "16-bit ADC (4 channels)", "cat": "adc"},
    0x49: {"name": "ADS1115", "desc": "16-bit ADC (addr A1)", "cat": "adc"},
    0x4A: {"name": "ADS1115", "desc": "16-bit ADC (addr A2)", "cat": "adc"},
    0x4B: {"name": "ADS1115", "desc": "16-bit ADC (addr A3)", "cat": "adc"},
    0x40: {
        "name": "HTU21D/SHT20",
        "desc": "Temperature & humidity sensor",
        "cat": "environment",
    },
    # Note: 0x44 is also used by INA219
    0x44: {
        "name": "SHT40/SHT31/INA219",
        "desc": "Temp & humidity or Current monitor",
        "cat": "environment",
    },
    0x45: {
        "name": "SHT40/SHT31",
        "desc": "High-accuracy temp & humidity (alt addr)",
        "cat": "environment",
    },
    0x76: {
        "name": "BMP280/BME280",
        "desc": "Pressure, temperature, (humidity)",
        "cat": "environment",
    },
    0x77: {
        "name": "BMP280/BME280/BMP180",
        "desc": "Pressure, temperature",
        "cat": "environment",
    },
    0x5C: {
        "name": "AM2320",
        "desc": "Temperature & humidity sensor",
        "cat": "environment",
    },
    0x38: {
        "name": "AHT10/AHT20",
        "desc": "Temperature & humidity sensor",
        "cat": "environment",
    },
    0x39: {
        "name": "AHT10",
        "desc": "Temperature & humidity (alt addr)",
        "cat": "environment",
    },
    # ── Light / Color ──
    0x29: {
        "name": "VL53L0X/TCS34725/VL53L1X",
        "desc": "ToF distance or color sensor",
        "cat": "optical",
    },
    0x23: {"name": "BH1750", "desc": "Ambient light sensor (lux)", "cat": "optical"},
    0x5B: {"name": "BH1750", "desc": "Ambient light (H-mode addr)", "cat": "optical"},
    # ── Current / Power ──
    # Note: 0x40-0x4F are all valid INA219 addresses, 0x44 is defined under environment
    0x41: {"name": "INA219/PCA9685", "desc": "Current monitor or 16-ch PWM", "cat": "power"},
    0x4C: {"name": "INA219", "desc": "Current/power monitor", "cat": "power"},
    0x4D: {"name": "INA219", "desc": "Current/power monitor", "cat": "power"},
    # ── Motor / Servo / PWM ──
    0x60: {"name": "PCA9685", "desc": "16-channel PWM/servo driver", "cat": "actuator"},
    # ── Display / OLED ──
    0x3C: {
        "name": "SSD1306/SH1106",
        "desc": "OLED display (128x64 or 128x32)",
        "cat": "display",
    },
    0x3D: {"name": "SSD1306", "desc": "OLED display (alt addr)", "cat": "display"},
    # ── Real-time clock ──
    0x68: {"name": "DS3231/DS1307", "desc": "Real-time clock module", "cat": "rtc"},
    0x50: {"name": "DS3231/HAT EEPROM", "desc": "RTC EEPROM or Pi HAT config", "cat": "rtc"},
    # ── GPIO expanders ──
    0x20: {
        "name": "PCF8574/MCP23017",
        "desc": "8/16-channel GPIO expander",
        "cat": "gpio",
    },
    0x21: {
        "name": "PCF8574",
        "desc": "8-channel GPIO expander (addr 1)",
        "cat": "gpio",
    },
    0x24: {"name": "MCP23017", "desc": "16-channel GPIO expander", "cat": "gpio"},
    0x27: {"name": "PCF8574", "desc": "GPIO expander / LCD backpack", "cat": "gpio"},
    # ── Accelerometer / IMU ──
    0x53: {"name": "ADXL345", "desc": "3-axis accelerometer", "cat": "motion"},
    0x1C: {
        "name": "MMA8452Q/FXOS8700",
        "desc": "3-axis accelerometer",
        "cat": "motion",
    },
    0x1D: {
        "name": "MMA8452Q",
        "desc": "3-axis accelerometer (alt addr)",
        "cat": "motion",
    },
    0x19: {
        "name": "LSM303/LIS3DH",
        "desc": "Accelerometer/magnetometer",
        "cat": "motion",
    },
    0x69: {
        "name": "MPU-6050",
        "desc": "6-axis gyro + accelerometer (alt addr)",
        "cat": "motion",
    },
    0x6A: {"name": "MPU-6050/ICM-20689", "desc": "IMU", "cat": "motion"},
    0x1E: {"name": "HMC5883L", "desc": "3-axis magnetometer/compass", "cat": "motion"},
    # ── Distance ──
    0x52: {
        "name": "VL6180X",
        "desc": "ToF distance & ambient light",
        "cat": "distance",
    },
    # ── Misc / RP2040-based ──
    0x0D: {"name": "Pimoroni Pico", "desc": "RP2040 I2C bridge", "cat": "bridge"},
    0x55: {"name": "MAX17043", "desc": "LiPo battery fuel gauge", "cat": "power"},
    # ── Pi Hat EEPROM (always present on properly designed HATs) ──
    # Note: 0x50 is already defined under RTC
}


@dataclass
class I2CDevice:
    address: int
    bus: int
    name: str
    desc: str
    category: str
    known: bool

    def __str__(self):
        prefix = "★" if self.known else "?"
        return (
            f"{prefix} 0x{self.address:02X} (bus {self.bus}): {self.name} – {self.desc}"
        )


@dataclass
class I2CScanResult:
    bus: int
    devices: list[I2CDevice] = field(default_factory=list)
    error: Optional[str] = None
    simulated: bool = False

    @property
    def count(self) -> int:
        return len(self.devices)


async def scan_bus(bus: int = 1) -> I2CScanResult:
    """
    Scan an I2C bus for connected devices.
    Tries smbus2 first (pure Python, no external tool),
    then falls back to i2cdetect subprocess.
    Returns I2CScanResult.
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: _scan_sync(bus))
    return result


def _scan_sync(bus: int) -> I2CScanResult:
    """Synchronous I2C scan. Returns I2CScanResult."""
    # Try smbus2
    import importlib.util

    if importlib.util.find_spec("smbus2") is not None:
        try:
            return _scan_smbus2(bus)
        except Exception as e:
            log.debug("smbus2 scan failed: %s", e)
    else:
        log.debug("smbus2 not available, trying i2cdetect")

    # Try i2cdetect
    try:
        return _scan_i2cdetect(bus)
    except Exception as e:
        log.debug("i2cdetect failed: %s", e)

    return I2CScanResult(
        bus=bus,
        error="No I2C scanning method available (smbus2 or i2cdetect required)",
        simulated=True,
    )


def _scan_smbus2(bus: int) -> I2CScanResult:
    """Scan using smbus2 library."""
    import smbus2

    devices: list[I2CDevice] = []
    try:
        with smbus2.SMBus(bus) as b:
            for addr in range(0x08, 0x78):  # valid I2C address range
                try:
                    b.write_quick(addr)
                    device = _make_device(addr, bus)
                    devices.append(device)
                    log.info("I2C bus %s: found %s", bus, device)
                except OSError:
                    pass  # no device at this address
    except Exception as e:
        return I2CScanResult(bus=bus, error=str(e))
    return I2CScanResult(bus=bus, devices=devices)


def _scan_i2cdetect(bus: int) -> I2CScanResult:
    """Scan using i2cdetect system tool."""
    import subprocess

    result = subprocess.run(
        ["i2cdetect", "-y", "-r", str(bus)], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        return I2CScanResult(
            bus=bus, error=f"i2cdetect failed: {result.stderr.strip()}"
        )

    devices: list[I2CDevice] = []
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split()[1:]  # skip row label
        for col, val in enumerate(parts):
            if val not in ("--", "UU", ""):
                try:
                    addr = int(val, 16)
                    devices.append(_make_device(addr, bus))
                except ValueError:
                    pass
    return I2CScanResult(bus=bus, devices=devices)


def _make_device(address: int, bus: int) -> I2CDevice:
    """Create an I2CDevice, looking up known info if available."""
    info = KNOWN_I2C_DEVICES.get(address)
    if info:
        return I2CDevice(
            address=address,
            bus=bus,
            name=info["name"],
            desc=info["desc"],
            category=info["cat"],
            known=True,
        )
    return I2CDevice(
        address=address,
        bus=bus,
        name=f"Unknown (0x{address:02X})",
        desc="Unrecognized device",
        category="unknown",
        known=False,
    )


async def scan_all_buses() -> list[I2CScanResult]:
    """Scan all available I2C buses (typically 0 and 1 on Pi)."""
    results = []
    for bus in range(4):  # check buses 0–3
        dev_path = f"/dev/i2c-{bus}"
        try:
            import os

            if not os.path.exists(dev_path):
                continue
        except Exception:
            continue
        result = await scan_bus(bus)
        results.append(result)
    if not results:
        # Simulate bus 1 for dev environments
        results.append(
            I2CScanResult(
                bus=1,
                devices=[],
                simulated=True,
                error="No I2C buses found (not running on Pi)",
            )
        )
    return results


def format_scan_report(results: list[I2CScanResult]) -> str:
    """Format scan results as readable text."""
    if not results:
        return "No I2C buses found."
    lines = []
    for r in results:
        lines.append(f"\nI2C Bus {r.bus}:" + (" [SIMULATED]" if r.simulated else ""))
        if r.error:
            lines.append(f"  Error: {r.error}")
        elif not r.devices:
            lines.append("  No devices found")
        else:
            lines.append(f"  {r.count} device(s) found:")
            for d in r.devices:
                lines.append(f"    {d}")
    return "\n".join(lines)

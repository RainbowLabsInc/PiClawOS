"""
PiClaw OS – Sensor Registry
Named sensor abstraction layer for Raspberry Pi hardware.

Instead of dealing with pin numbers and driver details, the agent works
with named sensors: "balcony_temp", "pir_front_door", "power_rail_5v"

Supported sensor types:
  TEMP_1WIRE    DS18B20  – 1-Wire temperature (GPIO 4 by default)
  DHT22         DHT22/DHT11 – Temperature + humidity on single GPIO pin
  BMP280        BMP280/BME280 – I2C pressure + temperature
  SHT40         SHT40/SHT31 – I2C high-accuracy temp + humidity
  BH1750        BH1750 – I2C ambient light (lux)
  ADS1115       ADS1115 – I2C 16-bit ADC (0–3.3V or with divider)
  INA219        INA219 – I2C current + voltage + power
  PIR           HC-SR501 or similar – GPIO digital motion sensor
  ULTRASONIC    HC-SR04 – GPIO trigger/echo distance sensor
  GPIO_INPUT    Any GPIO input (button, switch, door contact, etc.)

Storage: /etc/piclaw/sensors.json
Each sensor has a user-defined name, type, config, and last reading.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.hardware.sensors")

SENSOR_FILE = CONFIG_DIR / "sensors.json"

# Sensor type constants
TYPE_DHT22 = "DHT22"
TYPE_DS18B20 = "DS18B20"
TYPE_BMP280 = "BMP280"
TYPE_SHT40 = "SHT40"
TYPE_BH1750 = "BH1750"
TYPE_ADS1115 = "ADS1115"
TYPE_INA219 = "INA219"
TYPE_PIR = "PIR"
TYPE_ULTRASONIC = "HC_SR04"
TYPE_GPIO_INPUT = "GPIO_INPUT"

ALL_TYPES = [
    TYPE_DHT22,
    TYPE_DS18B20,
    TYPE_BMP280,
    TYPE_SHT40,
    TYPE_BH1750,
    TYPE_ADS1115,
    TYPE_INA219,
    TYPE_PIR,
    TYPE_ULTRASONIC,
    TYPE_GPIO_INPUT,
]


@dataclass
class SensorReading:
    """A single sensor reading with timestamp."""

    sensor_name: str
    values: dict[str, Any]  # e.g. {"temp_c": 22.3, "humidity_pct": 65.1}
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    error: str | None = None
    simulated: bool = False

    def __str__(self) -> str:
        if self.error:
            return f"[{self.sensor_name}] ERROR: {self.error}"
        vals = ", ".join(f"{k}={v}" for k, v in self.values.items())
        sim = " [SIM]" if self.simulated else ""
        return f"[{self.sensor_name}]{sim} {vals} @ {self.timestamp[:16]}"


@dataclass
class SensorDef:
    """A registered sensor with its configuration."""

    name: str  # user-defined name, e.g. "balcony_temp"
    type: str  # one of ALL_TYPES
    description: str = ""  # human-readable, e.g. "DHT22 on balcony"
    config: dict = field(default_factory=dict)
    # config examples:
    #   DHT22:      {"pin": 4}
    #   DS18B20:    {"device_id": "28-000000abcdef"}  or {"pin": 4} for auto
    #   BMP280:     {"i2c_bus": 1, "address": 118}    (0x76)
    #   INA219:     {"i2c_bus": 1, "address": 64}     (0x40), "shunt_ohm": 0.1
    #   PIR:        {"pin": 17}
    #   HC_SR04:    {"trigger_pin": 23, "echo_pin": 24}
    #   GPIO_INPUT: {"pin": 22, "pull_up": true}
    #   ADS1115:    {"i2c_bus": 1, "address": 72, "channel": 0}  (0x48)

    enabled: bool = True
    last_reading: dict | None = None  # SensorReading dict
    last_error: str | None = None
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class SensorRegistry:
    """
    Persistent store for named sensor definitions.
    Thread-safe for asyncio (operations happen on executor for file I/O).
    """

    def __init__(self):
        self._sensors: dict[str, SensorDef] = {}
        self._load()

    def _load(self):
        if not SENSOR_FILE.exists():
            return
        try:
            data = json.loads(SENSOR_FILE.read_text(encoding="utf-8"))
            for name, d in data.items():
                self._sensors[name] = SensorDef(**d)
            log.info("Loaded %s sensors from registry", len(self._sensors))
        except Exception as e:
            log.error("Sensor registry load error: %s", e)

    def _save(self):
        SENSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {name: s.to_dict() for name, s in self._sensors.items()}
        from piclaw.fileutils import safe_write_json

        safe_write_json(SENSOR_FILE, data, label="sensors")

    def add(self, sensor: SensorDef) -> str:
        self._sensors[sensor.name] = sensor
        self._save()
        return sensor.name

    def get(self, name: str) -> SensorDef | None:
        return self._sensors.get(name)

    def remove(self, name: str) -> bool:
        if name not in self._sensors:
            return False
        del self._sensors[name]
        self._save()
        return True

    def list_all(self) -> list[SensorDef]:
        return list(self._sensors.values())

    def list_enabled(self) -> list[SensorDef]:
        return [s for s in self._sensors.values() if s.enabled]

    def update_reading(self, name: str, reading: SensorReading):
        s = self._sensors.get(name)
        if s:
            s.last_reading = asdict(reading)
            s.last_error = reading.error
            self._save()

    def summary(self) -> str:
        if not self._sensors:
            return "No sensors registered."
        lines = [f"Sensors ({len(self._sensors)}):"]
        for s in self._sensors.values():
            status = "✅" if s.enabled else "⏸"
            last = ""
            if s.last_reading:
                vals = s.last_reading.get("values", {})
                last = " → " + ", ".join(f"{k}={v}" for k, v in list(vals.items())[:3])
            lines.append(f"  {status} {s.name} ({s.type}){last}")
        return "\n".join(lines)


# ── Sensor drivers ────────────────────────────────────────────────


async def read_sensor(sensor: SensorDef) -> SensorReading:
    """
    Read a sensor and return a SensorReading.
    Dispatches to the appropriate driver based on sensor.type.
    All drivers degrade gracefully if hardware not available.
    """
    try:
        if sensor.type == TYPE_DHT22:
            return await _read_dht22(sensor)
        elif sensor.type == TYPE_DS18B20:
            return await _read_ds18b20(sensor)
        elif sensor.type == TYPE_BMP280:
            return await _read_bmp280(sensor)
        elif sensor.type == TYPE_SHT40:
            return await _read_sht40(sensor)
        elif sensor.type == TYPE_BH1750:
            return await _read_bh1750(sensor)
        elif sensor.type == TYPE_ADS1115:
            return await _read_ads1115(sensor)
        elif sensor.type == TYPE_INA219:
            return await _read_ina219(sensor)
        elif sensor.type == TYPE_PIR:
            return await _read_pir(sensor)
        elif sensor.type == TYPE_ULTRASONIC:
            return await _read_ultrasonic(sensor)
        elif sensor.type == TYPE_GPIO_INPUT:
            return await _read_gpio_input(sensor)
        else:
            return SensorReading(
                sensor_name=sensor.name,
                values={},
                error=f"Unknown sensor type: {sensor.type}",
            )
    except Exception as e:
        log.error("Sensor read error (%s): %s", sensor.name, e)
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── DHT22 / DHT11 ─────────────────────────────────────────────────


async def _read_dht22(sensor: SensorDef) -> SensorReading:
    def _sync_read():
        pin = sensor.config.get("pin", 4)
        try:
            import adafruit_dht
            import board

            pin_obj = getattr(board, f"D{pin}")
            dht = adafruit_dht.DHT22(pin_obj, use_pulseio=False)
            try:
                temp = dht.temperature
                hum = dht.humidity
                dht.exit()
                return SensorReading(
                    sensor_name=sensor.name,
                    values={"temp_c": round(temp, 1), "humidity_pct": round(hum, 1)},
                )
            except RuntimeError as e:
                dht.exit()
                return SensorReading(
                    sensor_name=sensor.name,
                    values={},
                    error=f"DHT read failed (retry): {e}",
                )
        except ImportError:
            # Fallback: try Adafruit_DHT legacy
            try:
                import Adafruit_DHT

                sensor_type = Adafruit_DHT.DHT22
                hum, temp = Adafruit_DHT.read_retry(sensor_type, pin)
                if temp is not None and hum is not None:
                    return SensorReading(
                        sensor_name=sensor.name,
                        values={"temp_c": round(temp, 1), "humidity_pct": round(hum, 1)},
                    )
                return SensorReading(
                    sensor_name=sensor.name,
                    values={},
                    error="DHT returned None (check wiring)",
                )
            except ImportError:
                return SensorReading(
                    sensor_name=sensor.name,
                    values={},
                    error="adafruit_dht or Adafruit_DHT library required",
                )
    return await asyncio.to_thread(_sync_read)


# ── DS18B20 1-Wire ────────────────────────────────────────────────


async def _read_ds18b20(sensor: SensorDef) -> SensorReading:
    def _sync_read():
        device_id = sensor.config.get("device_id")
        # Search /sys/bus/w1/devices/ for DS18B20 sensors
        w1_path = Path("/sys/bus/w1/devices")
        if not w1_path.exists():
            return SensorReading(
                sensor_name=sensor.name,
                values={},
                error="1-Wire not enabled. Add 'dtoverlay=w1-gpio' to /boot/config.txt",
            )
        try:
            # Find all DS18B20 devices (start with 28-)
            devices = list(w1_path.glob("28-*"))
            if not devices:
                return SensorReading(
                    sensor_name=sensor.name,
                    values={},
                    error="No DS18B20 sensors found on 1-Wire bus",
                )
            # Select specific device or first found
            if device_id:
                target = w1_path / device_id
            else:
                target = devices[0]
            raw = (target / "w1_slave").read_text(encoding="utf-8", errors="replace")
            if "YES" not in raw:
                return SensorReading(
                    sensor_name=sensor.name, values={}, error="DS18B20 CRC check failed"
                )
            temp_str = raw.split("t=")[1].strip()
            temp = int(temp_str) / 1000.0
            return SensorReading(
                sensor_name=sensor.name,
                values={"temp_c": round(temp, 2), "device": str(target.name)},
            )
        except Exception as e:
            return SensorReading(sensor_name=sensor.name, values={}, error=str(e))
    return await asyncio.to_thread(_sync_read)


# ── BMP280 / BME280 ────────────────────────────────────────────────


async def _read_bmp280(sensor: SensorDef) -> SensorReading:
    def _sync_read():
        bus_num = sensor.config.get("i2c_bus", 1)
        address = sensor.config.get("address", 0x76)
        try:
            import smbus2
            import bme280

            bus = smbus2.SMBus(bus_num)
            calibration = bme280.load_calibration_params(bus, address)
            data = bme280.sample(bus, address, calibration)
            values = {
                "temp_c": round(data.temperature, 2),
                "pressure_hpa": round(data.pressure, 2),
            }
            if hasattr(data, "humidity") and data.humidity:
                values["humidity_pct"] = round(data.humidity, 1)
            return SensorReading(sensor_name=sensor.name, values=values)
        except ImportError:
            # Try adafruit-circuitpython-bmp280
            try:
                import board
                import busio
                import adafruit_bmp280

                i2c = busio.I2C(board.SCL, board.SDA)
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=address)
                return SensorReading(
                    sensor_name=sensor.name,
                    values={
                        "temp_c": round(bmp.temperature, 2),
                        "pressure_hpa": round(bmp.pressure, 2),
                    },
                )
            except ImportError:
                return SensorReading(
                    sensor_name=sensor.name,
                    values={},
                    error="smbus2+bme280 or adafruit-circuitpython-bmp280 required",
                )
        except Exception as e:
            return SensorReading(sensor_name=sensor.name, values={}, error=str(e))
    return await asyncio.to_thread(_sync_read)


# ── SHT40 / SHT31 ─────────────────────────────────────────────────


async def _read_sht40(sensor: SensorDef) -> SensorReading:
    bus_num = sensor.config.get("i2c_bus", 1)
    address = sensor.config.get("address", 0x44)
    try:
        import smbus2

        bus = smbus2.SMBus(bus_num)
        # SHT40: send measure command 0xFD (high precision)
        bus.write_byte(address, 0xFD)
        await asyncio.sleep(0.01)
        data = bus.read_i2c_block_data(address, 0, 6)
        # Temperature: bytes 0-1, humidity: bytes 3-4
        t_raw = (data[0] << 8) | data[1]
        h_raw = (data[3] << 8) | data[4]
        temp = -45 + 175 * t_raw / 65535
        hum = max(0, min(100, -6 + 125 * h_raw / 65535))
        return SensorReading(
            sensor_name=sensor.name,
            values={"temp_c": round(temp, 2), "humidity_pct": round(hum, 1)},
        )
    except ImportError:
        return SensorReading(
            sensor_name=sensor.name, values={}, error="smbus2 required"
        )
    except Exception as e:
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── BH1750 Light sensor ───────────────────────────────────────────


async def _read_bh1750(sensor: SensorDef) -> SensorReading:
    bus_num = sensor.config.get("i2c_bus", 1)
    address = sensor.config.get("address", 0x23)
    try:
        import smbus2

        bus = smbus2.SMBus(bus_num)
        # One-time high resolution mode
        bus.write_byte(address, 0x20)
        await asyncio.sleep(0.18)
        data = bus.read_i2c_block_data(address, 0x20, 2)
        lux = ((data[0] << 8) | data[1]) / 1.2
        return SensorReading(sensor_name=sensor.name, values={"lux": round(lux, 1)})
    except ImportError:
        return SensorReading(
            sensor_name=sensor.name, values={}, error="smbus2 required"
        )
    except Exception as e:
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── ADS1115 ADC ───────────────────────────────────────────────────


async def _read_ads1115(sensor: SensorDef) -> SensorReading:
    bus_num = sensor.config.get("i2c_bus", 1)
    address = sensor.config.get("address", 0x48)
    channel = sensor.config.get("channel", 0)  # 0–3
    gain = sensor.config.get("gain", 1)  # 1=±4.096V, 2=±2.048V
    try:
        import smbus2

        bus = smbus2.SMBus(bus_num)
        # Config register: single-shot, selected channel, PGA gain
        mux = 0b100 | (channel & 0b11)  # AINx vs GND
        pga = {1: 0b010, 2: 0b011, 4: 0b100}[gain]
        config = (0x80 << 8) | (mux << 12) | (pga << 9) | 0x0183
        hi, lo = (config >> 8) & 0xFF, config & 0xFF
        bus.write_i2c_block_data(address, 0x01, [hi, lo])
        await asyncio.sleep(0.01)
        result = bus.read_i2c_block_data(address, 0x00, 2)
        raw = (result[0] << 8) | result[1]
        if raw > 0x7FFF:
            raw -= 0x10000
        fsr = {1: 4.096, 2: 2.048, 4: 1.024}[gain]
        voltage = raw * fsr / 32767
        return SensorReading(
            sensor_name=sensor.name,
            values={"voltage_v": round(voltage, 4), "raw": raw, "channel": channel},
        )
    except ImportError:
        return SensorReading(
            sensor_name=sensor.name, values={}, error="smbus2 required"
        )
    except Exception as e:
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── INA219 Current/Power ──────────────────────────────────────────


async def _read_ina219(sensor: SensorDef) -> SensorReading:
    def _sync_read():
        bus_num = sensor.config.get("i2c_bus", 1)
        address = sensor.config.get("address", 0x40)
        shunt_ohm = sensor.config.get("shunt_ohm", 0.1)
        try:
            from ina219 import INA219, DeviceRangeError

            ina = INA219(shunt_ohm, busnum=bus_num, address=address)
            ina.configure()
            try:
                return SensorReading(
                    sensor_name=sensor.name,
                    values={
                        "voltage_v": round(ina.voltage(), 3),
                        "current_ma": round(ina.current(), 1),
                        "power_mw": round(ina.power(), 1),
                    },
                )
            except DeviceRangeError:
                return SensorReading(
                    sensor_name=sensor.name,
                    values={},
                    error="INA219 measurement out of range",
                )
        except ImportError:
            return SensorReading(
                sensor_name=sensor.name, values={}, error="pi-ina219 library required"
            )
        except Exception as e:
            return SensorReading(sensor_name=sensor.name, values={}, error=str(e))
    return await asyncio.to_thread(_sync_read)


# ── PIR Motion Sensor ─────────────────────────────────────────────


async def _read_pir(sensor: SensorDef) -> SensorReading:
    pin = sensor.config.get("pin", 17)
    try:
        from gpiozero import MotionSensor

        pir = MotionSensor(pin)

        await asyncio.sleep(0.01)
        motion = pir.motion_detected
        pir.close()
        return SensorReading(
            sensor_name=sensor.name,
            values={"motion": motion, "state": "MOTION" if motion else "CLEAR"},
        )
    except ImportError:
        return SensorReading(
            sensor_name=sensor.name, values={}, error="gpiozero required for PIR sensor"
        )
    except Exception as e:
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── HC-SR04 Ultrasonic Distance ───────────────────────────────────


async def _read_ultrasonic(sensor: SensorDef) -> SensorReading:
    trigger_pin = sensor.config.get("trigger_pin", 23)
    echo_pin = sensor.config.get("echo_pin", 24)
    try:
        from gpiozero import DistanceSensor

        d = DistanceSensor(echo=echo_pin, trigger=trigger_pin, max_distance=4.0)
        await asyncio.sleep(0.06)  # let sensor stabilize
        dist = d.distance * 100  # metres → cm
        d.close()
        return SensorReading(
            sensor_name=sensor.name,
            values={"distance_cm": round(dist, 1)},
        )
    except ImportError:
        return SensorReading(
            sensor_name=sensor.name,
            values={},
            error="gpiozero required for ultrasonic sensor",
        )
    except Exception as e:
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── Generic GPIO Input ────────────────────────────────────────────


async def _read_gpio_input(sensor: SensorDef) -> SensorReading:
    pin = sensor.config.get("pin", 22)
    pull_up = sensor.config.get("pull_up", True)
    try:
        from gpiozero import Button

        btn = Button(pin, pull_up=pull_up)

        await asyncio.sleep(0.005)
        state = btn.is_pressed
        btn.close()
        return SensorReading(
            sensor_name=sensor.name,
            values={"pressed": state, "state": "HIGH" if state else "LOW"},
        )
    except ImportError:
        return SensorReading(
            sensor_name=sensor.name, values={}, error="gpiozero required for GPIO input"
        )
    except Exception as e:
        return SensorReading(sensor_name=sensor.name, values={}, error=str(e))


# ── Read all registered sensors ───────────────────────────────────


async def read_all_sensors(
    registry: SensorRegistry, update_registry: bool = True
) -> list[SensorReading]:
    """Read all enabled sensors concurrently."""
    sensors = registry.list_enabled()
    if not sensors:
        return []

    tasks = [read_sensor(s) for s in sensors]
    readings = await asyncio.gather(*tasks, return_exceptions=False)

    if update_registry:
        for sensor, reading in zip(sensors, readings):
            registry.update_reading(sensor.name, reading)

    return list(readings)


# ── Hardware context for agent system prompt ──────────────────────


def build_hardware_context(registry: SensorRegistry) -> str:
    """
    Build a short hardware inventory string for injection into the agent's
    system prompt, so the agent knows what sensors are available.
    """
    sensors = registry.list_enabled()
    if not sensors:
        return ""

    lines = ["Connected sensors:"]
    for s in sensors:
        last = ""
        if s.last_reading and not s.last_reading.get("error"):
            vals = s.last_reading.get("values", {})
            if vals:
                last = (
                    " (last: "
                    + ", ".join(f"{k}={v}" for k, v in list(vals.items())[:2])
                    + ")"
                )
        lines.append(f"  - {s.name} ({s.type}): {s.description}{last}")
    return "\n".join(lines)

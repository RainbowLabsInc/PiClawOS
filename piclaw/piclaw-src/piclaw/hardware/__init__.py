"""
PiClaw OS – Hardware Package
Provides Pi-specific hardware abstraction:
  - Pi info (vcgencmd, throttle, clocks)
  - I2C bus scanner with known-device matching
  - Named sensor registry (DHT22, DS18B20, BMP280, PIR, etc.)
  - Thermal manager (temp-aware LLM routing, fan control)
  - Agent tools for all of the above
"""

from .sensors import SensorRegistry
from .tools   import TOOL_DEFS, HANDLERS

# Global sensor registry singleton
_sensor_registry = None


def get_sensor_registry() -> SensorRegistry:
    """Return the global SensorRegistry (created on first call)."""
    global _sensor_registry
    if _sensor_registry is None:
        _sensor_registry = SensorRegistry()
    return _sensor_registry


__all__ = [
    "SensorRegistry",
    "get_sensor_registry",
    "TOOL_DEFS",
    "HANDLERS",
]

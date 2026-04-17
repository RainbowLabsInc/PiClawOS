"""
PiClaw OS – GPIO Tool
Hardware control via gpiozero (safe, Pi 5 compatible)
Falls back gracefully if not running on real hardware.
"""

import logging
from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.gpio")

TOOL_DEFS = [
    ToolDefinition(
        name="gpio_read",
        description="Read the state of a GPIO pin (HIGH/LOW) or an analog sensor value.",
        parameters={
            "type": "object",
            "properties": {
                "pin": {"type": "integer", "description": "BCM pin number (e.g. 17)"},
            },
            "required": ["pin"],
        },
    ),
    ToolDefinition(
        name="gpio_write",
        description="Set a GPIO output pin HIGH or LOW (e.g. control an LED or relay).",
        parameters={
            "type": "object",
            "properties": {
                "pin": {"type": "integer", "description": "BCM pin number"},
                "state": {"type": "boolean", "description": "true=HIGH, false=LOW"},
            },
            "required": ["pin", "state"],
        },
    ),
    ToolDefinition(
        name="gpio_pwm",
        description="Set PWM duty cycle on a pin (0–100). Useful for LED dimming or servo control.",
        parameters={
            "type": "object",
            "properties": {
                "pin": {"type": "integer", "description": "BCM pin number"},
                "duty_cycle": {"type": "number", "description": "Duty cycle 0–100"},
                "frequency": {
                    "type": "number",
                    "description": "Frequency Hz (default 100)",
                },
            },
            "required": ["pin", "duty_cycle"],
        },
    ),
    ToolDefinition(
        name="gpio_status",
        description="List all currently configured GPIO pins and their states.",
        parameters={"type": "object", "properties": {}},
    ),
]

# In-memory state for configured pins
_pins: dict[int, object] = {}


def _gpiozero():
    try:
        import gpiozero

        return gpiozero
    except ImportError:
        return None


async def gpio_read(pin: int) -> str:
    gz = _gpiozero()
    if not gz:
        return f"[SIMULATED] Pin {pin}: LOW (gpiozero not available on this host)"
    try:
        from gpiozero import Button

        btn = Button(pin, pull_up=False)
        state = "HIGH" if btn.is_pressed else "LOW"
        btn.close()
        return f"Pin {pin} (BCM): {state}"
    except Exception as e:
        return f"[GPIO ERROR] {e}"


async def gpio_write(pin: int, state: bool) -> str:
    gz = _gpiozero()
    if not gz:
        return f"[SIMULATED] Pin {pin} set to {'HIGH' if state else 'LOW'}"
    try:
        from gpiozero import LED

        if pin not in _pins:
            _pins[pin] = LED(pin)
        led = _pins[pin]
        led.on() if state else led.off()
        return f"Pin {pin} set to {'HIGH' if state else 'LOW'}"
    except Exception as e:
        return f"[GPIO ERROR] {e}"


async def gpio_pwm(pin: int, duty_cycle: float, frequency: float = 100.0) -> str:
    gz = _gpiozero()
    if not gz:
        return f"[SIMULATED] Pin {pin} PWM: {duty_cycle:.1f}% @ {frequency:.0f}Hz"
    try:
        from gpiozero import PWMLED

        if pin not in _pins:
            _pins[pin] = PWMLED(pin)
        pwm = _pins[pin]
        pwm.value = max(0.0, min(1.0, duty_cycle / 100.0))
        return f"Pin {pin} PWM set to {duty_cycle:.1f}% @ {frequency:.0f}Hz"
    except Exception as e:
        return f"[GPIO ERROR] {e}"


async def gpio_status() -> str:
    if not _pins:
        return "No GPIO pins currently configured."
    lines = []
    for pin, obj in _pins.items():
        try:
            val = getattr(obj, "value", "?")
            lines.append(f"Pin {pin}: {type(obj).__name__} = {val}")
        except Exception:
            lines.append(f"Pin {pin}: (error reading state)")
    return "\n".join(lines)


HANDLERS = {
    "gpio_read": lambda **kw: gpio_read(**kw),
    "gpio_write": lambda **kw: gpio_write(**kw),
    "gpio_pwm": lambda **kw: gpio_pwm(**kw),
    "gpio_status": lambda **_: gpio_status(),
}

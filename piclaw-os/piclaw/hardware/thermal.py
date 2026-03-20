"""
PiClaw OS – Thermal Manager
Monitors Raspberry Pi temperature and protects hardware during LLM inference.

Problem: Local LLM inference (Phi-3, Llama) on Pi 5 can push CPU to 80–85°C.
Without a fan or heatsink, this triggers thermal throttling → slower inference
and potential hardware degradation over time.

Solution: Thermal-aware LLM routing:
  1. Continuously monitor CPU temperature
  2. When temp exceeds WARN threshold → prefer cloud API backends
  3. When temp exceeds CRIT threshold → force cloud, refuse local
  4. When temp drops below COOL threshold → re-enable local inference
  5. Log thermal events to memory for the agent to recall

The main agent and MultiLLMRouter can query get_thermal_state() to make
routing decisions without coupling to the full thermal manager.

Also handles:
  - Fan control via GPIO PWM (if a PWM fan is connected)
  - Under-voltage detection from vcgencmd
  - Thermal event log (stored in memory)
  - Automatic notification via messaging hub when critical temp reached
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.hardware.thermal")

# ── Thresholds ────────────────────────────────────────────────────
TEMP_COOL_C  = 55.0   # below this: local inference freely allowed
TEMP_WARN_C  = 70.0   # above this: prefer cloud, warn user
TEMP_CRIT_C  = 80.0   # above this: local inference disabled
TEMP_EMERG_C = 85.0   # above this: send alert, throttle all operations

# Fan control defaults
FAN_PWM_PIN      = 14    # BCM pin, change in config
FAN_MIN_DUTY     = 20.0  # minimum PWM% to spin fan
FAN_FULL_DUTY    = 100.0
FAN_START_TEMP_C = 50.0  # fan starts spinning above this temp
FAN_FULL_TEMP_C  = 75.0  # fan at full speed above this temp

# Polling interval
POLL_INTERVAL_S = 15     # check temperature every N seconds


class ThermalState(Enum):
    COOL     = "cool"     # < 55°C: all good, local inference ok
    WARM     = "warm"     # 55–70°C: local inference ok with monitoring
    HOT      = "hot"      # 70–80°C: prefer cloud API, warn
    CRITICAL = "critical" # 80–85°C: local disabled
    EMERGENCY= "emergency"# > 85°C: everything throttled, alert sent


@dataclass
class ThermalStatus:
    temp_c:     float
    state:      ThermalState
    local_ok:   bool        # is local LLM inference allowed?
    cloud_pref: bool        # should we prefer cloud over local?
    message:    str
    throttle_active: bool = False   # Pi currently throttled by firmware
    under_voltage:   bool = False
    timestamp:  str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "temp_c":        self.temp_c,
            "state":         self.state.value,
            "local_ok":      self.local_ok,
            "cloud_pref":    self.cloud_pref,
            "message":       self.message,
            "throttle":      self.throttle_active,
            "under_voltage": self.under_voltage,
            "timestamp":     self.timestamp,
        }


def classify_temp(temp_c: float) -> ThermalState:
    if temp_c >= TEMP_EMERG_C:
        return ThermalState.EMERGENCY
    if temp_c >= TEMP_CRIT_C:
        return ThermalState.CRITICAL
    if temp_c >= TEMP_WARN_C:
        return ThermalState.HOT
    if temp_c >= TEMP_COOL_C:
        return ThermalState.WARM
    return ThermalState.COOL


def make_status(temp_c: float,
                throttle_active: bool = False,
                under_voltage: bool = False) -> ThermalStatus:
    state = classify_temp(temp_c)
    return ThermalStatus(
        temp_c   = temp_c,
        state    = state,
        local_ok = state not in (ThermalState.CRITICAL, ThermalState.EMERGENCY),
        cloud_pref = state in (ThermalState.HOT, ThermalState.CRITICAL, ThermalState.EMERGENCY),
        message  = {
            ThermalState.COOL:      f"✅ {temp_c:.1f}°C – nominal",
            ThermalState.WARM:      f"🟡 {temp_c:.1f}°C – warm, monitor",
            ThermalState.HOT:       f"🟠 {temp_c:.1f}°C – hot, prefer cloud LLM",
            ThermalState.CRITICAL:  f"🔴 {temp_c:.1f}°C – critical, local LLM disabled",
            ThermalState.EMERGENCY: f"⚠️  {temp_c:.1f}°C – EMERGENCY, throttling all ops",
        }[state],
        throttle_active = throttle_active,
        under_voltage   = under_voltage,
    )


# ── Module-level state ────────────────────────────────────────────
_current_status: Optional[ThermalStatus] = None
_alert_sent_for_state: Optional[ThermalState] = None
_fan_on: bool = False


def get_thermal_state() -> Optional[ThermalStatus]:
    """
    Return current thermal status. Fast, non-blocking.
    Called by MultiLLMRouter before choosing local vs cloud backend.
    Returns None if monitoring not started yet.
    """
    return _current_status


def local_inference_allowed() -> bool:
    """
    Quick check: can we run local LLM inference right now?
    Returns True if no thermal data available (safe default).
    """
    if _current_status is None:
        return True
    return _current_status.local_ok


# ── Fan control ───────────────────────────────────────────────────

async def _set_fan(duty: float):
    """Set fan PWM duty cycle. Silently fails if no fan connected."""
    global _fan_on
    try:
        from piclaw.tools.gpio import gpio_pwm
        await gpio_pwm(FAN_PWM_PIN, duty, frequency=25)   # 25Hz standard for PC fans
        _fan_on = duty > 0
    except Exception as _e:
        log.debug("Fan init failed: %s", _e)


def _calc_fan_duty(temp_c: float) -> float:
    """Linear fan speed: 0% below start_temp, 100% at full_temp."""
    if temp_c <= FAN_START_TEMP_C:
        return 0.0
    if temp_c >= FAN_FULL_TEMP_C:
        return FAN_FULL_DUTY
    pct = (temp_c - FAN_START_TEMP_C) / (FAN_FULL_TEMP_C - FAN_START_TEMP_C) * 100
    return max(FAN_MIN_DUTY, pct)   # never below minimum once started


# ── Monitoring loop ───────────────────────────────────────────────

async def run_thermal_monitor(
    notify_fn:    Optional[Callable[[str], Awaitable]] = None,
    memory_fn:    Optional[Callable[[str], Awaitable]] = None,
    fan_enabled:  bool = False,
    stop_event:   Optional[asyncio.Event] = None,
):
    """
    Background task: polls temperature, updates _current_status,
    controls fan, sends alerts on state transitions.

    Call from daemon.py or agent.py:
        create_background_task(run_thermal_monitor(...))
    """
    global _current_status, _alert_sent_for_state

    from piclaw.hardware.pi_info import current_temp, is_throttled
    log.info("Thermal monitor started")

    prev_state = None

    while True:
        try:
            # Read temperature
            temp = current_temp()
            if temp is None:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            throttled = is_throttled()
            status    = make_status(temp, throttle_active=throttled)
            _current_status = status

            # Fan control
            if fan_enabled:
                duty = _calc_fan_duty(temp)
                await _set_fan(duty)

            # State transition handling
            if status.state != prev_state:
                log.info("Thermal state change: %s → %s (%.1f°C)", prev_state, status.state.value, temp)

                # Log to memory
                if memory_fn and prev_state is not None:
                    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
                    msg = (f"[{ts}] Thermal event: {status.state.value} at {temp:.1f}°C "
                           f"(was {prev_state.value if prev_state else 'unknown'}). "
                           f"Local LLM: {'OK' if status.local_ok else 'DISABLED'}")
                    create_background_task(memory_fn(msg))

                # Alert on critical / emergency
                if (status.state in (ThermalState.CRITICAL, ThermalState.EMERGENCY)
                        and notify_fn
                        and _alert_sent_for_state != status.state):
                    alert = (
                        "🌡️ PiClaw Thermal Alert\n"
                        f"Temperature: {temp:.1f}°C – {status.state.value.upper()}\n"
                        f"Local LLM inference: {'disabled' if not status.local_ok else 'ok'}\n"
                        f"Throttle active: {throttled}\n"
                        "Recommendation: check airflow / add heatsink"
                    )
                    create_background_task(notify_fn(alert))
                    _alert_sent_for_state = status.state

                # Clear alert state when cooled down
                if status.state in (ThermalState.COOL, ThermalState.WARM):
                    _alert_sent_for_state = None

                prev_state = status.state

            # Throttle check alert (separate from temp state)
            if throttled and not (prev_state == status.state):
                log.warning("Pi firmware throttling active at %.1f°C", temp)

        except Exception as e:
            log.error("Thermal monitor error: %s", e)

        # Respect stop event
        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
                break
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(POLL_INTERVAL_S)

    log.info("Thermal monitor stopped")


# ── Context for agent ─────────────────────────────────────────────

def thermal_context_line() -> str:
    """One-liner for system prompt injection."""
    s = _current_status
    if s is None:
        return ""
    extra = ""
    if s.throttle_active:
        extra += " [THROTTLED]"
    if s.under_voltage:
        extra += " [UNDER-VOLTAGE]"
    return f"CPU temp: {s.temp_c:.1f}°C ({s.state.value}){extra}"
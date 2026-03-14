"""
PiClaw OS – Raspberry Pi Hardware Info
Reads Pi-specific telemetry that psutil cannot provide:
  - CPU/GPU/memory frequencies (actual, not nominal)
  - Supply voltage (under-voltage detection)
  - Throttle flags (thermal/power events since boot)
  - CPU temperature from the Pi's own sensor
  - GPU memory split
  - Hardware revision / model string
  - ARM frequency cap (from config.txt / firmware)

Works on Pi 5, Pi 4B, Pi CM4; degrades gracefully on non-Pi hardware.

vcgencmd availability:
  On a real Pi: /usr/bin/vcgencmd (firmware command)
  In simulation: returns structured placeholders with [SIM] tag
"""

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("piclaw.hardware.pi_info")


# ── Throttle flag decoder ─────────────────────────────────────────
# vcgencmd get_throttled returns a bitmask. Each bit has a meaning.
# https://www.raspberrypi.com/documentation/computers/os.html#get_throttled
THROTTLE_FLAGS = {
    0:  "Under-voltage detected",
    1:  "ARM frequency capped",
    2:  "Currently throttled",
    3:  "Soft temperature limit reached",
    16: "Under-voltage occurred (since boot)",
    17: "ARM frequency capping occurred (since boot)",
    18: "Throttling occurred (since boot)",
    19: "Soft temperature limit occurred (since boot)",
}

THROTTLE_CURRENT_MASK = 0x000F   # bits 0–3: current state
THROTTLE_HISTORIC_MASK = 0x000F0000  # bits 16–19: since-boot events


@dataclass
class ThrottleStatus:
    raw_hex:     str
    raw_int:     int
    current:     list[str] = field(default_factory=list)   # active right now
    historic:    list[str] = field(default_factory=list)   # occurred since boot
    healthy:     bool = True                                # no current issues

    @property
    def summary(self) -> str:
        if not self.current and not self.historic:
            return "✅ No throttling – healthy"
        parts = []
        if self.current:
            parts.append("🔴 NOW: " + ", ".join(self.current))
        if self.historic:
            parts.append("⚠️  HISTORY: " + ", ".join(self.historic))
        return " | ".join(parts)


@dataclass
class PiClocks:
    arm_mhz:  Optional[float] = None   # CPU clock
    core_mhz: Optional[float] = None   # GPU/VideoCore clock
    h264_mhz: Optional[float] = None   # H264 block
    isp_mhz:  Optional[float] = None   # ISP
    v3d_mhz:  Optional[float] = None   # 3D engine
    uart_hz:  Optional[float] = None   # UART
    pwm_hz:   Optional[float] = None   # PWM


@dataclass
class PiVoltages:
    core_v:   Optional[float] = None   # GPU/SoC core
    sdram_c_v: Optional[float] = None  # SDRAM controller
    sdram_i_v: Optional[float] = None  # SDRAM I/O
    sdram_p_v: Optional[float] = None  # SDRAM phy


@dataclass
class PiInfo:
    model:         str  = "Unknown"
    revision:      str  = ""
    serial:        str  = ""
    ram_mb:        int  = 0
    simulated:     bool = False         # True if vcgencmd not available

    temp_celsius:  Optional[float] = None
    temp_gpu_c:    Optional[float] = None
    under_voltage: bool = False
    throttled:     Optional[ThrottleStatus] = None
    clocks:        Optional[PiClocks]    = None
    voltages:      Optional[PiVoltages]  = None
    gpu_mem_mb:    Optional[int]         = None

    def to_dict(self) -> dict:
        d = {
            "model":         self.model,
            "revision":      self.revision,
            "serial":        self.serial,
            "ram_mb":        self.ram_mb,
            "simulated":     self.simulated,
            "temp_celsius":  self.temp_celsius,
            "temp_gpu_c":    self.temp_gpu_c,
            "under_voltage": self.under_voltage,
        }
        if self.throttled:
            d["throttle"] = {
                "raw":     self.throttled.raw_hex,
                "current": self.throttled.current,
                "history": self.throttled.historic,
                "healthy": self.throttled.healthy,
                "summary": self.throttled.summary,
            }
        if self.clocks:
            d["clocks_mhz"] = {
                k: v for k, v in {
                    "arm":   self.clocks.arm_mhz,
                    "core":  self.clocks.core_mhz,
                    "v3d":   self.clocks.v3d_mhz,
                }.items() if v is not None
            }
        if self.voltages:
            d["voltages_v"] = {
                k: v for k, v in {
                    "core":    self.voltages.core_v,
                    "sdram_c": self.voltages.sdram_c_v,
                }.items() if v is not None
            }
        if self.gpu_mem_mb is not None:
            d["gpu_mem_mb"] = self.gpu_mem_mb
        return d

    def format_report(self) -> str:
        lines = [
            "Raspberry Pi – Hardware Report",
            f"  Model:       {self.model}" + (" [SIMULATED]" if self.simulated else ""),
            f"  RAM:         {self.ram_mb} MB",
        ]
        if self.temp_celsius is not None:
            lines.append(f"  CPU Temp:    {self.temp_celsius:.1f}°C")
        if self.throttled:
            lines.append(f"  Throttle:    {self.throttled.summary}")
        if self.clocks and self.clocks.arm_mhz:
            lines.append(f"  CPU Clock:   {self.clocks.arm_mhz:.0f} MHz")
        if self.voltages and self.voltages.core_v:
            lines.append(f"  Core Volt:   {self.voltages.core_v:.3f} V")
        if self.gpu_mem_mb is not None:
            lines.append(f"  GPU Memory:  {self.gpu_mem_mb} MB")
        return "\n".join(lines)


# ── vcgencmd helpers ──────────────────────────────────────────────

def _vcgencmd(cmd: str) -> Optional[str]:
    """Run vcgencmd synchronously. Returns stdout or None."""
    try:
        result = subprocess.run(
            ["vcgencmd"] + cmd.split(),
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _parse_measure(raw: Optional[str]) -> Optional[float]:
    """Parse 'measure_clock arm=1200000000' → 1200.0 (MHz)."""
    if not raw:
        return None
    m = re.search(r"=(\d+)", raw)
    if m:
        return int(m.group(1)) / 1_000_000
    return None


def _parse_volt(raw: Optional[str]) -> Optional[float]:
    """Parse 'volt=0.8625V' → 0.8625"""
    if not raw:
        return None
    m = re.search(r"=([\d.]+)V", raw)
    if m:
        return float(m.group(1))
    return None


def _parse_throttle(raw: Optional[str]) -> Optional[ThrottleStatus]:
    """Parse 'throttled=0x50005' → ThrottleStatus"""
    if not raw:
        return None
    m = re.search(r"0x([0-9a-fA-F]+)", raw)
    if not m:
        return None
    val = int(m.group(1), 16)
    current  = [msg for bit, msg in THROTTLE_FLAGS.items() if bit < 16 and (val >> bit) & 1]
    historic = [msg for bit, msg in THROTTLE_FLAGS.items() if bit >= 16 and (val >> bit) & 1]
    return ThrottleStatus(
        raw_hex  = "0x" + m.group(1),
        raw_int  = val,
        current  = current,
        historic = historic,
        healthy  = len(current) == 0,
    )


# ── Model detection ───────────────────────────────────────────────

_MODEL_MAP = {
    "d04170": "Pi 5 Model B (2GB)",
    "d04171": "Pi 5 Model B (4GB)",
    "d04172": "Pi 5 Model B (8GB)",
    "c03115": "Pi 4 Model B (4GB)",
    "c03114": "Pi 4 Model B (2GB)",
    "c03112": "Pi 4 Model B (1GB)",
    "b03114": "Pi 4 Model B (2GB)",
    "a03111": "Pi 4 Model B (1GB)",
}


def _read_model_info() -> tuple[str, str, str, int]:
    """Returns (model_str, revision, serial, ram_mb)"""
    model_str, revision, serial, ram_mb = "Unknown Pi", "", "", 0
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        for line in cpuinfo.splitlines():
            if line.startswith("Model"):
                model_str = line.split(":", 1)[1].strip()
            elif line.startswith("Revision"):
                revision  = line.split(":", 1)[1].strip()
            elif line.startswith("Serial"):
                serial    = line.split(":", 1)[1].strip()
    except Exception as _e:
        log.debug("pi_info cpuinfo parse: %s", _e)

    # Try /proc/device-tree/model for cleaner string
    try:
        dt = Path("/proc/device-tree/model").read_bytes()
        model_str = dt.decode("utf-8", errors="replace").strip("\x00")
    except Exception as _e:
        log.debug("pi_info device-tree read: %s", _e)

    # RAM from /proc/meminfo
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal"):
                kb = int(line.split()[1])
                ram_mb = kb // 1024
                break
    except Exception as _e:
        log.debug("meminfo parse: %s", _e)

    return model_str, revision, serial, ram_mb


# ── CPU Temperature (works without vcgencmd) ──────────────────────

def _read_cpu_temp() -> Optional[float]:
    """Read CPU temperature in Celsius from /sys."""
    paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
    ]
    for p in paths:
        try:
            raw = Path(p).read_text(encoding="utf-8", errors="replace").strip()
            val = int(raw)
            return val / 1000 if val > 1000 else float(val)
        except Exception:
            continue
    return None


# ── Main async read ───────────────────────────────────────────────

async def read_pi_info() -> PiInfo:
    """
    Read all available Pi hardware info.
    Non-blocking: runs vcgencmd calls in thread pool.
    Degrades gracefully on non-Pi hardware (simulated=True).
    """
    loop = asyncio.get_running_loop()

    model_str, revision, serial, ram_mb = await loop.run_in_executor(
        None, _read_model_info
    )
    cpu_temp = await loop.run_in_executor(None, _read_cpu_temp)

    # vcgencmd calls – wrapped in executor to not block event loop
    def _fetch_vcgencmd():
        return {
            "throttle": _vcgencmd("get_throttled"),
            "temp_gpu": _vcgencmd("measure_temp"),
            "clock_arm":  _vcgencmd("measure_clock arm"),
            "clock_core": _vcgencmd("measure_clock core"),
            "clock_v3d":  _vcgencmd("measure_clock v3d"),
            "volt_core":  _vcgencmd("measure_volts core"),
            "volt_sdram": _vcgencmd("measure_volts sdram_c"),
            "gpu_mem":    _vcgencmd("get_mem gpu"),
        }

    vc = await loop.run_in_executor(None, _fetch_vcgencmd)
    simulated = all(v is None for v in vc.values())

    # Parse throttle
    throttle = _parse_throttle(vc["throttle"])

    # GPU temp from vcgencmd
    gpu_temp = None
    if vc["temp_gpu"]:
        m = re.search(r"([\d.]+)'C", vc["temp_gpu"])
        if m:
            gpu_temp = float(m.group(1))

    # Use GPU temp as CPU temp if /sys not available and vcgencmd has it
    if cpu_temp is None and gpu_temp is not None:
        cpu_temp = gpu_temp

    # Clocks
    clocks = PiClocks(
        arm_mhz  = _parse_measure(vc["clock_arm"]),
        core_mhz = _parse_measure(vc["clock_core"]),
        v3d_mhz  = _parse_measure(vc["clock_v3d"]),
    )

    # Voltages
    voltages = PiVoltages(
        core_v   = _parse_volt(vc["volt_core"]),
        sdram_c_v = _parse_volt(vc["volt_sdram"]),
    )

    # GPU memory
    gpu_mem = None
    if vc["gpu_mem"]:
        m = re.search(r"(\d+)M", vc["gpu_mem"])
        if m:
            gpu_mem = int(m.group(1))

    # Simulated fallback values
    if simulated:
        model_str = model_str or "Raspberry Pi 5 Model B [SIM]"
        ram_mb    = ram_mb or 4096
        if cpu_temp is None:
            cpu_temp = 45.0

    return PiInfo(
        model         = model_str,
        revision      = revision,
        serial        = serial,
        ram_mb        = ram_mb,
        simulated     = simulated,
        temp_celsius  = cpu_temp,
        temp_gpu_c    = gpu_temp,
        under_voltage = bool(throttle and throttle.current and
                            "Under-voltage" in " ".join(throttle.current)),
        throttled     = throttle,
        clocks        = clocks,
        voltages      = voltages,
        gpu_mem_mb    = gpu_mem,
    )


def is_throttled() -> bool:
    """Quick synchronous check: is the Pi currently throttled?"""
    raw = _vcgencmd("get_throttled")
    if raw is None:
        return False
    m = re.search(r"0x([0-9a-fA-F]+)", raw)
    if not m:
        return False
    val = int(m.group(1), 16)
    return bool(val & THROTTLE_CURRENT_MASK)


def current_temp() -> Optional[float]:
    """Quick synchronous read of CPU temp in Celsius."""
    return _read_cpu_temp()
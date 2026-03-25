## 2025-05-14 - Optimize CPU Temperature Reading
**Learning:** Found multiple places (watchdog, metrics, shell, briefing, API) re-implementing CPU temperature reading logic using file I/O to `/sys/class/thermal/thermal_zone0/temp` and falling back to `psutil.sensors_temperatures()`. `psutil.sensors_temperatures()` is unnecessarily slow as it reads and parses multiple `/sys/class/hwmon` directories.
**Action:** Centralize and reuse the highly efficient, dedicated `current_temp()` function from `piclaw.hardware.pi_info` instead of scattering slow ad-hoc temperature checks across the codebase.

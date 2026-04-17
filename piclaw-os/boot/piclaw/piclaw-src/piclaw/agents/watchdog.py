"""
PiClaw OS – Watchdog Sub-Agent
Runs as piclaw-watchdog systemd service under its OWN Linux user.

Security model:
  - Separate user 'piclaw-watchdog' owns watchdog.db and its logs
  - Main piclaw user has READ-ONLY access to watchdog.db
  - Watchdog CANNOT be commanded by mainagent (no IPC in that direction)
  - Has its own Telegram bot token (independent of mainagent)
  - Writes append-only to watchdog.db (SQLite ROLLBACK on delete attempts)

Check schedule:
  Full check every 60s
  Disk/temp checks: every 60s
  Service checks:   every 60s
  Integrity checks: every 300s (5 min)
  Daily report:     configurable, default 07:00

Alert thresholds:
  Disk  >  85% → WARNING,  > 95% → CRITICAL
  Temp  >  75°C → WARNING, > 80°C → CRITICAL
  RAM   > 90% → WARNING
  Service down → WARNING (first time), CRITICAL after 3 checks
"""

import asyncio
import contextlib
import hashlib
import logging
import os
import signal
import socket
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

from piclaw.agents.ipc import (
    WatchdogAlert,
    WatchdogReport,
    AlertSeverity,
    write_alert,
    write_report,
    write_integrity_entry,
    init_watchdog_db,
    WATCHDOG_DB,
)
from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.agents.watchdog")

WATCHDOG_CONFIG_FILE = CONFIG_DIR / "watchdog.toml"
WATCHDOG_LOG_DIR = Path("/var/log/piclaw-watchdog")

# ── Thresholds ────────────────────────────────────────────────────
DISK_WARN_PCT = 85
DISK_CRIT_PCT = 95
TEMP_WARN_C = 75.0
TEMP_CRIT_C = 80.0
RAM_WARN_PCT = 90

# Files to integrity-check (SHA-256 snapshot)
INTEGRITY_PATHS = [
    CONFIG_DIR / "config.toml",
    Path("/etc/systemd/system/piclaw-agent.service"),
    Path("/etc/systemd/system/piclaw-api.service"),
    Path("/etc/systemd/system/piclaw-watchdog.service"),
    Path("/etc/ssh/sshd_config"),
    Path("/etc/sudoers"),
]

# Managed services to check
WATCHED_SERVICES = [
    "piclaw-agent",
    "piclaw-api",
    "piclaw-crawler",
    "ssh",
    "avahi-daemon",
]

# Heartbeat file written by mainagent every ~30s
HEARTBEAT_FILE = CONFIG_DIR / "ipc" / "agent.heartbeat"

# Installer lock file
INSTALLER_LOCK_FILE = Path("/tmp/piclaw_installer.lock")


class Watchdog:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self._hostname = socket.gethostname()
        self._integrity_base: dict[str, str] = {}
        self._service_fail_counts: dict[str, int] = {}
        self._cfg = self._load_config()
        WATCHDOG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        init_watchdog_db()
        self._read_db_trigger()

    # ── Config ────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        defaults = {
            "telegram_token": "",
            "telegram_chat_id": "",
            "daily_report_time": "07:00",
            "check_interval_s": 60,
            "integrity_interval_s": 300,
        }
        if WATCHDOG_CONFIG_FILE.exists():
            try:
                import tomllib

                with open(WATCHDOG_CONFIG_FILE, "rb") as f:
                    loaded = tomllib.load(f)
                defaults.update(loaded)
            except Exception as e:
                log.warning("Could not load watchdog config: %s", e)
        return defaults

    # ── SQLite append-only trigger ────────────────────────────────

    def _read_db_trigger(self):
        """
        Attach a SQLite UPDATE/DELETE trigger so the watchdog DB is truly
        append-only. Called once on startup.
        """
        try:
            con = sqlite3.connect(str(WATCHDOG_DB))
            for tbl in ("alerts", "reports", "integrity_log"):
                con.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS no_update_{tbl}
                    BEFORE UPDATE ON {tbl}
                    BEGIN SELECT RAISE(ABORT, 'Updates not allowed on {tbl}'); END
                """)
                con.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS no_delete_{tbl}
                    BEFORE DELETE ON {tbl}
                    BEGIN SELECT RAISE(ABORT, 'Deletes not allowed on {tbl}'); END
                """)
            con.commit()
            con.close()
            log.info("Watchdog DB append-only triggers installed.")
        except Exception as e:
            log.error("Failed to install DB triggers: %s", e)

    # ── System checks ─────────────────────────────────────────────

    async def _check_disk(self) -> list[WatchdogAlert]:
        alerts = []
        try:
            usage = await asyncio.to_thread(psutil.disk_usage, "/")
            pct = usage.percent
            if pct >= DISK_CRIT_PCT:
                alerts.append(
                    WatchdogAlert(
                        severity=AlertSeverity.CRITICAL,
                        category="disk",
                        message=f"Disk critically full: {pct:.0f}%",
                        detail=f"{usage.used // 1_073_741_824:.1f}/{usage.total // 1_073_741_824:.1f} GB",
                        hostname=self._hostname,
                    )
                )
            elif pct >= DISK_WARN_PCT:
                alerts.append(
                    WatchdogAlert(
                        severity=AlertSeverity.WARNING,
                        category="disk",
                        message=f"Disk almost full: {pct:.0f}%",
                        detail=f"{usage.used // 1_073_741_824:.1f}/{usage.total // 1_073_741_824:.1f} GB",
                        hostname=self._hostname,
                    )
                )
        except Exception as e:
            log.error("Disk check error: %s", e)
        return alerts

    async def _check_temperature(self) -> list[WatchdogAlert]:
        alerts = []
        temp = None
        from piclaw.hardware.pi_info import current_temp
        temp = await asyncio.to_thread(current_temp)
        if temp is None:
            return alerts
        if temp >= TEMP_CRIT_C:
            alerts.append(
                WatchdogAlert(
                    severity=AlertSeverity.CRITICAL,
                    category="temp",
                    message=f"CPU critically hot: {temp:.1f}°C",
                    detail="Throttling begins at 80°C. Check cooling.",
                    hostname=self._hostname,
                )
            )
        elif temp >= TEMP_WARN_C:
            alerts.append(
                WatchdogAlert(
                    severity=AlertSeverity.WARNING,
                    category="temp",
                    message=f"CPU temperature high: {temp:.1f}°C",
                    detail=f"Warn threshold: {TEMP_WARN_C}°C",
                    hostname=self._hostname,
                )
            )
        return alerts

    async def _check_memory(self) -> list[WatchdogAlert]:
        alerts = []
        try:
            mem = await asyncio.to_thread(psutil.virtual_memory)
            swap = await asyncio.to_thread(psutil.swap_memory)
            if mem.percent >= RAM_WARN_PCT:
                alerts.append(
                    WatchdogAlert(
                        severity=AlertSeverity.WARNING,
                        category="memory",
                        message=f"High RAM usage: {mem.percent:.0f}%",
                        detail=f"{mem.used // 1_048_576}/{mem.total // 1_048_576} MB used",
                        hostname=self._hostname,
                    )
                )
            if swap.total > 0 and swap.percent > 50:
                alerts.append(
                    WatchdogAlert(
                        severity=AlertSeverity.WARNING,
                        category="memory",
                        message=f"Swap in use: {swap.percent:.0f}%",
                        detail=f"{swap.used // 1_048_576}/{swap.total // 1_048_576} MB",
                        hostname=self._hostname,
                    )
                )
        except Exception as e:
            log.error("Memory check: %s", e)
        return alerts

    async def _check_services(self) -> list[WatchdogAlert]:
        alerts = []
        for svc in WATCHED_SERVICES:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "systemctl", "is-active", svc,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                state = out.decode().strip()
                if state != "active":
                    self._service_fail_counts[svc] = (
                        self._service_fail_counts.get(svc, 0) + 1
                    )
                    fails = self._service_fail_counts[svc]
                    sev = (
                        AlertSeverity.CRITICAL if fails >= 3 else AlertSeverity.WARNING
                    )
                    alerts.append(
                        WatchdogAlert(
                            severity=sev,
                            category="service",
                            message=f"Service '{svc}' is {state} (fail #{fails})",
                            detail=f"Systemd state: {state}",
                            hostname=self._hostname,
                        )
                    )
                else:
                    self._service_fail_counts[svc] = 0
            except TimeoutError:
                log.warning("Service check '%s' timeout – systemctl hängt", svc)
                try:
                    proc.kill()
                except Exception as _e:
                    log.debug("kill timed-out proc: %s", _e)
            except Exception as e:
                log.error("Service check %s: %s", svc, e)
        return alerts

    async def _check_agent_heartbeat(self) -> list[WatchdogAlert]:
        """Detect if mainagent has stopped writing heartbeat."""
        alerts = []
        try:
            exists = await asyncio.to_thread(HEARTBEAT_FILE.exists)
            if exists:
                stat = await asyncio.to_thread(HEARTBEAT_FILE.stat)
                age = time.time() - stat.st_mtime
                if age > 120:
                    alerts.append(
                        WatchdogAlert(
                            severity=AlertSeverity.WARNING,
                            category="agent",
                            message=f"Mainagent heartbeat stale ({int(age)}s old)",
                            detail="Expected heartbeat every 30s from piclaw-agent.",
                            hostname=self._hostname,
                        )
                    )
            else:
                alerts.append(
                    WatchdogAlert(
                        severity=AlertSeverity.INFO,
                        category="agent",
                        message="Mainagent heartbeat file not found.",
                        detail=str(HEARTBEAT_FILE),
                        hostname=self._hostname,
                    )
                )
        except Exception as e:
            log.error("Heartbeat check: %s", e)
        return alerts

    async def _check_integrity(self) -> list[WatchdogAlert]:
        """Hash-check critical files against stored baseline."""
        alerts = []
        for path in INTEGRITY_PATHS:
            exists = await asyncio.to_thread(path.exists)
            if not exists:
                continue
            try:
                content = await asyncio.to_thread(path.read_bytes)
                sha = hashlib.sha256(content).hexdigest()
                prev = self._integrity_base.get(str(path))
                changed = prev is not None and prev != sha
                if changed:
                    detail = f"Previous: {prev[:16]}…  Current: {sha[:16]}…"
                    alerts.append(
                        WatchdogAlert(
                            severity=AlertSeverity.CRITICAL,
                            category="integrity",
                            message=f"File modified: {path.name}",
                            detail=detail,
                            hostname=self._hostname,
                        )
                    )
                    log.warning("INTEGRITY CHANGE: %s", path)
                write_integrity_entry(
                    str(path), sha, changed, "changed" if changed else "ok"
                )
                self._integrity_base[str(path)] = sha
            except Exception as e:
                log.error("Integrity check %s: %s", path, e)
        return alerts

    async def _check_new_executables(self) -> list[WatchdogAlert]:
        """Alert on unexpected new executable files in skills dir."""
        alerts = []
        skills_dir = CONFIG_DIR / "skills"

        exists = await asyncio.to_thread(skills_dir.exists)
        if not exists:
            return alerts

        try:

            def _find_executables():
                found_alerts = []
                _now = time.time()
                for p in skills_dir.rglob("*"):
                    if not p.is_file():
                        continue
                    age = _now - p.stat().st_mtime
                    if age < 300 and os.access(p, os.X_OK):
                        found_alerts.append(p)
                return found_alerts

            executables = await asyncio.to_thread(_find_executables)
            for p in executables:
                alerts.append(
                    WatchdogAlert(
                        severity=AlertSeverity.WARNING,
                        category="security",
                        message=f"New executable in skills dir: {p.name}",
                        detail=str(p),
                        hostname=self._hostname,
                    )
                )
        except Exception as e:
            log.error("Executable scan: %s", e)
        return alerts

    def _check_installer_hang(self) -> list[WatchdogAlert]:
        """Detect if an installer process is hung (lock file older than 15 min)."""
        alerts = []
        try:
            if INSTALLER_LOCK_FILE.exists():
                age = time.time() - INSTALLER_LOCK_FILE.stat().st_mtime
                if age > 900:  # 15 minutes
                    alerts.append(
                        WatchdogAlert(
                            severity=AlertSeverity.CRITICAL,
                            category="service",
                            message="Installer Hang Detected",
                            detail=f"Installer lock file is {int(age / 60)} minutes old.",
                            hostname=self._hostname,
                        )
                    )
        except Exception as e:
            log.error("Installer lock check error: %s", e)
        return alerts

    # ── Full check cycle ──────────────────────────────────────────

    async def run_checks(self) -> list[WatchdogAlert]:
        all_alerts: list[WatchdogAlert] = []
        all_alerts += await self._check_disk()
        all_alerts += await self._check_temperature()
        all_alerts += await self._check_memory()
        all_alerts += await self._check_services()
        all_alerts += await self._check_agent_heartbeat()
        all_alerts += await self._check_new_executables()
        all_alerts += self._check_installer_hang()

        for alert in all_alerts:
            write_alert(alert)
            log.warning("[%s] %s: %s", alert.severity, alert.category, alert.message)
            # Immediate Telegram push for WARNING+ alerts
            if alert.severity in (AlertSeverity.WARNING, AlertSeverity.CRITICAL):
                await self._telegram_alert(alert)

        return all_alerts

    async def run_integrity_checks(self):
        alerts = await self._check_integrity()
        for alert in alerts:
            write_alert(alert)
            await self._telegram_alert(alert)

    # ── Daily report ──────────────────────────────────────────────

    async def send_daily_report(self):
        from piclaw.agents.ipc import get_recent_alerts

        try:
            recent = get_recent_alerts(limit=100)
            total = len(recent)
            crits = sum(1 for a in recent if a["severity"] == AlertSeverity.CRITICAL)
            warns = sum(1 for a in recent if a["severity"] == AlertSeverity.WARNING)

            mem = await asyncio.to_thread(psutil.virtual_memory)
            disk = await asyncio.to_thread(psutil.disk_usage, "/")
            load = await asyncio.to_thread(psutil.getloadavg)
            temp = None
            from piclaw.hardware.pi_info import current_temp
            temp = await asyncio.to_thread(current_temp)

            summary = (
                f"📊 *PiClaw Daily Report* – {self._hostname}\n"
                f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                "*System*\n"
                f"  CPU Temp : {f'{temp:.1f}°C' if temp else 'N/A'}\n"
                f"  Memory   : {mem.percent:.0f}% ({mem.used // 1_048_576}/{mem.total // 1_048_576} MB)\n"
                f"  Disk     : {disk.percent:.0f}% ({disk.used // 1_073_741_824:.1f}/{disk.total // 1_073_741_824:.1f} GB)\n"
                f"  Load     : {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}\n\n"
                "*Alerts (24h)*\n"
                f"  Critical : {crits}\n"
                f"  Warning  : {warns}\n"
                f"  Total    : {total}\n"
            )

            if crits > 0:
                crit_items = [
                    a for a in recent if a["severity"] == AlertSeverity.CRITICAL
                ][:3]
                summary += "\n*Recent critical alerts:*\n"
                for a in crit_items:
                    summary += f"  ⛔ [{a['category']}] {a['message']}\n"

            report = WatchdogReport(
                summary=summary,
                alerts_new=total,
                alerts_crit=crits,
                system_ok=(crits == 0),
            )
            write_report(report)
            await self._telegram_send(summary)
            log.info("Daily report sent.")

        except Exception as e:
            log.error("Daily report failed: %s", e, exc_info=True)

    # ── Telegram ──────────────────────────────────────────────────

    async def _telegram_alert(self, alert: WatchdogAlert):
        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "⛔"}[alert.severity]
        text = (
            f"{icon} *PiClaw Watchdog* – {alert.hostname}\n"
            f"[{alert.category.upper()}] {alert.message}\n"
            f"_{alert.detail}_\n"
            f"`{alert.ts}`"
        )
        await self._telegram_send(text)

    async def _telegram_send(self, text: str):
        token = self._cfg.get("telegram_token", "")
        chat_id = self._cfg.get("telegram_chat_id", "")
        if not token or not chat_id:
            return
        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with aiohttp.ClientSession() as s:
                for chunk in [text[i : i + 4096] for i in range(0, len(text), 4096)]:
                    await s.post(
                        url,
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": "Markdown",
                        },
                        timeout=aiohttp.ClientTimeout(total=10),
                    )
        except Exception as e:
            log.error("Watchdog Telegram send failed: %s", e)

    # ── Main daemon ───────────────────────────────────────────────

    async def run_daemon(self):
        log.info("PiClaw Watchdog started on %s", self._hostname)
        # init_watchdog_db() + _read_db_trigger() bereits in __init__() aufgerufen
        check_interval = int(self._cfg.get("check_interval_s", 60))
        integrity_interval = int(self._cfg.get("integrity_interval_s", 300))
        daily_time = self._cfg.get("daily_report_time", "07:00")

        last_integrity = 0.0
        last_daily = ""

        # Seed integrity baseline on startup
        await self._check_integrity()

        while not self._stop_event.is_set():
            now = time.time()

            # Regular checks
            await self.run_checks()

            # Integrity check
            if now - last_integrity >= integrity_interval:
                await self.run_integrity_checks()
                last_integrity = now

            # Daily report
            today_key = datetime.now().strftime(f"%Y-%m-%d-{daily_time}")
            if today_key != last_daily:
                h, m = daily_time.split(":")
                now_dt = datetime.now()
                if now_dt.hour == int(h) and now_dt.minute >= int(m):
                    await self.send_daily_report()
                    last_daily = today_key

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=check_interval)

        log.info("Watchdog stopped.")

    def stop(self):
        self._stop_event.set()


# ── Entrypoint ────────────────────────────────────────────────────


def run():
    WATCHDOG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [WATCHDOG] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(WATCHDOG_LOG_DIR / "watchdog.log")),
        ],
    )
    wd = Watchdog()

    def _sig(*_):
        wd.stop()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    asyncio.run(wd.run_daemon())


if __name__ == "__main__":
    run()

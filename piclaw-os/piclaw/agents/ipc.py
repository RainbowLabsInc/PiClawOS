"""
PiClaw OS – Inter-Agent IPC
SQLite-backed message bus with strict ownership rules.

DB files:
  jobs.db       → owned by piclaw  (crawler reads/writes, mainagent writes)
  watchdog.db   → owned by piclaw-watchdog (watchdog writes, mainagent reads ONLY)

Schema is intentionally simple – no ORM, plain sqlite3.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Optional

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.agents.ipc")

IPC_DIR = CONFIG_DIR / "ipc"
JOBS_DB = IPC_DIR / "jobs.db"
WATCHDOG_DB = IPC_DIR / "watchdog.db"


# ── Job schema (Crawler IPC) ─────────────────────────────────────


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrawlMode(StrEnum):
    ONCE = "once"
    RECURRING = "recurring"
    UNTIL_FOUND = "until_found"


@dataclass
class CrawlJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    query: str = ""
    urls: list = field(default_factory=list)  # seed URLs (optional)
    mode: str = CrawlMode.ONCE
    cron: str = ""  # e.g. "0 8 * * *" for recurring
    interval_sec: int = 0  # alternative to cron
    max_depth: int = 1  # link-following depth
    max_pages: int = 10  # max pages per run
    timeout_sec: int = 300  # hard job timeout (5 min default)
    until_pattern: str = ""  # stop condition for UNTIL_FOUND
    notify_chat: str = ""  # telegram chat_id to notify
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = JobStatus.PENDING
    last_run: str = ""
    run_count: int = 0
    last_result: str = ""  # summary of last crawl
    error: str = ""
    stopped_at: str = ""


# ── Alert schema (Watchdog IPC) ──────────────────────────────────


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class WatchdogAlert:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    severity: str = AlertSeverity.INFO
    category: str = ""  # disk|memory|temp|service|agent|integrity|security
    message: str = ""
    detail: str = ""
    hostname: str = ""
    ts: str = field(default_factory=lambda: datetime.now().isoformat())
    sent: bool = False  # True once Telegram notification was sent
    read: bool = False  # True once mainagent read it


@dataclass
class WatchdogReport:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    ts: str = field(default_factory=lambda: datetime.now().isoformat())
    period: str = "daily"
    summary: str = ""
    alerts_new: int = 0
    alerts_crit: int = 0
    system_ok: bool = True
    sent: bool = False


# ── DB helpers ────────────────────────────────────────────────────


def _ensure_dirs():
    IPC_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn(db_path: Path):
    _ensure_dirs()
    con = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ── Jobs DB ───────────────────────────────────────────────────────


def init_jobs_db():
    with _conn(JOBS_DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                query        TEXT,
                urls         TEXT,
                mode         TEXT,
                cron         TEXT,
                interval_sec INTEGER,
                max_depth    INTEGER,
                max_pages    INTEGER,
                timeout_sec  INTEGER,
                until_pattern TEXT,
                notify_chat  TEXT,
                created_at   TEXT,
                status       TEXT,
                last_run     TEXT,
                run_count    INTEGER DEFAULT 0,
                last_result  TEXT,
                error        TEXT,
                stopped_at   TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS job_results (
                id          TEXT PRIMARY KEY,
                job_id      TEXT,
                ts          TEXT,
                pages_crawled INTEGER,
                summary     TEXT,
                raw_content TEXT,
                found_match TEXT
            )
        """)


def write_job(job: CrawlJob):
    init_jobs_db()
    d = asdict(job)
    d["urls"] = json.dumps(d["urls"])
    with _conn(JOBS_DB) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO jobs VALUES (
                :id,:query,:urls,:mode,:cron,:interval_sec,
                :max_depth,:max_pages,:timeout_sec,:until_pattern,
                :notify_chat,:created_at,:status,:last_run,
                :run_count,:last_result,:error,:stopped_at
            )""",
            d,
        )


def get_job(job_id: str) -> CrawlJob | None:
    init_jobs_db()
    with _conn(JOBS_DB) as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(status: str | None = None) -> list[CrawlJob]:
    init_jobs_db()
    with _conn(JOBS_DB) as con:
        if status:
            rows = con.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_status(job_id: str, status: str, result: str = "", error: str = ""):
    init_jobs_db()
    ts = datetime.now().isoformat()
    with _conn(JOBS_DB) as con:
        con.execute(
            """
            UPDATE jobs SET status=?, last_run=?, run_count=run_count+1,
            last_result=?, error=?
            WHERE id=?
        """,
            (status, ts, result, error, job_id),
        )


def cancel_job(job_id: str):
    init_jobs_db()
    with _conn(JOBS_DB) as con:
        con.execute(
            "UPDATE jobs SET status=?, stopped_at=? WHERE id=?",
            (JobStatus.CANCELLED, datetime.now().isoformat(), job_id),
        )


def write_job_result(job_id: str, pages: int, summary: str, raw: str, found: str = ""):
    init_jobs_db()
    rid = str(uuid.uuid4())[:12]
    with _conn(JOBS_DB) as con:
        con.execute(
            """
            INSERT INTO job_results VALUES (?,?,?,?,?,?,?)
        """,
            (
                rid,
                job_id,
                datetime.now().isoformat(),
                pages,
                summary,
                raw[:50000],
                found,
            ),
        )


def _row_to_job(row) -> CrawlJob:
    d = dict(row)
    urls_raw = d.get("urls") or "[]"
    try:
        d["urls"] = json.loads(urls_raw)
    except json.JSONDecodeError:
        log.warning("_row_to_job: korrupte urls-Spalte: %.80s", urls_raw)
        d["urls"] = []
    return CrawlJob(
        **{k: v for k, v in d.items() if k in CrawlJob.__dataclass_fields__}
    )


# ── Watchdog DB (append-only by design) ───────────────────────────

_db_initialized = False  # Guard: init nur einmal pro Prozess ausführen


def init_watchdog_db(force: bool = False) -> None:
    """Erstellt Tabellen + Indizes. Nach dem ersten Aufruf kein Overhead mehr."""
    global _db_initialized
    if _db_initialized and not force:
        return
    with _conn(WATCHDOG_DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id        TEXT PRIMARY KEY,
                severity  TEXT,
                category  TEXT,
                message   TEXT,
                detail    TEXT,
                hostname  TEXT,
                ts        TEXT,
                sent      INTEGER DEFAULT 0,
                read      INTEGER DEFAULT 0
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id          TEXT PRIMARY KEY,
                ts          TEXT,
                period      TEXT,
                summary     TEXT,
                alerts_new  INTEGER,
                alerts_crit INTEGER,
                system_ok   INTEGER,
                sent        INTEGER DEFAULT 0
            )
        """)
        # Integrity log: file hash snapshots
        con.execute("""
            CREATE TABLE IF NOT EXISTS integrity_log (
                id       TEXT PRIMARY KEY,
                ts       TEXT,
                filepath TEXT,
                sha256   TEXT,
                changed  INTEGER DEFAULT 0,
                detail   TEXT
            )
        """)
        # Indizes für häufige Abfragen (ts-Range, severity-Filter)
        con.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts       ON alerts(ts)")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity, ts)"
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_alerts_sent     ON alerts(sent)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_reports_ts      ON reports(ts)")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_integrity_path  ON integrity_log(filepath, ts)"
        )
    _db_initialized = True


def write_alert(alert: WatchdogAlert):
    """Append-only – never updates existing rows."""
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO alerts VALUES (?,?,?,?,?,?,?,?,?)
        """,
            (
                alert.id,
                alert.severity,
                alert.category,
                alert.message,
                alert.detail,
                alert.hostname,
                alert.ts,
                int(alert.sent),
                int(alert.read),
            ),
        )


def write_report(report: WatchdogReport):
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO reports VALUES (?,?,?,?,?,?,?,?)
        """,
            (
                report.id,
                report.ts,
                report.period,
                report.summary,
                report.alerts_new,
                report.alerts_crit,
                int(report.system_ok),
                int(report.sent),
            ),
        )


def write_integrity_entry(filepath: str, sha256: str, changed: bool, detail: str = ""):
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        con.execute(
            """
            INSERT INTO integrity_log VALUES (?,?,?,?,?,?)
        """,
            (
                str(uuid.uuid4())[:12],
                datetime.now().isoformat(),
                filepath,
                sha256,
                int(changed),
                detail,
            ),
        )


# Read-only accessors (for mainagent)
def get_unsent_alerts() -> list[WatchdogAlert]:
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        rows = con.execute(
            "SELECT * FROM alerts WHERE sent=0 ORDER BY ts DESC LIMIT 50"
        ).fetchall()
    return [WatchdogAlert(**dict(r)) for r in rows]


def mark_alert_sent(alert_id: str):
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        con.execute("UPDATE alerts SET sent=1, read=1 WHERE id=?", (alert_id,))


def get_unsent_reports() -> list[WatchdogReport]:
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        rows = con.execute(
            "SELECT * FROM reports WHERE sent=0 ORDER BY ts DESC"
        ).fetchall()
    return [WatchdogReport(**dict(r)) for r in rows]


def mark_report_sent(report_id: str):
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        con.execute("UPDATE reports SET sent=1 WHERE id=?", (report_id,))


def get_recent_alerts(limit: int = 20) -> list[dict]:
    init_watchdog_db()
    with _conn(WATCHDOG_DB) as con:
        rows = con.execute(
            "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

"""
PiClaw OS – Metriken-Engine (v0.10)

Speichert CPU, RAM, Temperatur, Disk und Sensor-Werte in einer
SQLite-Ringpuffer-Datenbank. Die Web-UI zeigt daraus Live-Charts.

Schema:
  metrics(ts INTEGER, name TEXT, value REAL, unit TEXT, tags TEXT)

Retention: 7 Tage (default), konfigurierbar.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil
from piclaw.taskutils import create_background_task

_SECS_PER_DAY = 86_400  # Sekunden pro Tag


logger = logging.getLogger(__name__)

# ── Konfiguration ────────────────────────────────────────────────
DB_DEFAULT   = Path("/etc/piclaw/metrics.db")
RETENTION_S  = 7 * 24 * 3600   # 7 Tage
COLLECT_S    = 30               # Sammle alle 30 Sekunden


# ── Datenmodell ──────────────────────────────────────────────────
@dataclass
class MetricPoint:
    name: str
    value: float
    unit: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    ts: int = field(default_factory=lambda: int(time.time()))

    def tags_json(self) -> str:
        return json.dumps(self.tags, ensure_ascii=False) if self.tags else "{}"


# ── Datenbank ────────────────────────────────────────────────────
class MetricsDB:
    """Leichtgewichtige SQLite-Zeitreihendatenbank mit Ringpuffer."""

    def __init__(self, path: Path = DB_DEFAULT, retention_s: int = RETENTION_S):
        self.path = Path(path)
        self.retention_s = retention_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")      # besser bei gleichzeitigem Lesen/Schreiben
        con.execute("PRAGMA synchronous=NORMAL")    # Geschwindigkeit ohne Datenverlust-Risiko
        con.execute("PRAGMA cache_size=-4000")      # 4 MB Page-Cache
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    ts    INTEGER NOT NULL,
                    name  TEXT    NOT NULL,
                    value REAL    NOT NULL,
                    unit  TEXT    DEFAULT '',
                    tags  TEXT    DEFAULT '{}'
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts   ON metrics(ts)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name, ts)")
        logger.debug("MetricsDB initialisiert: %s", self.path)

    # ── Schreiben ─────────────────────────────────────────────────

    def write(self, point: MetricPoint) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO metrics (ts, name, value, unit, tags) VALUES (?,?,?,?,?)",
                (point.ts, point.name, point.value, point.unit, point.tags_json()),
            )

    def write_many(self, points: list[MetricPoint]) -> None:
        with self._conn() as con:
            con.executemany(
                "INSERT INTO metrics (ts, name, value, unit, tags) VALUES (?,?,?,?,?)",
                [(p.ts, p.name, p.value, p.unit, p.tags_json()) for p in points],
            )

    # ── Lesen ─────────────────────────────────────────────────────

    def query(
        self,
        name: str,
        since_s: int = 3600,
        limit: int = 500,
    ) -> list[dict]:
        """Gibt Zeitreihenpunkte zurück, neueste zuerst."""
        since_ts = int(time.time()) - since_s
        with self._conn() as con:
            rows = con.execute(
                """SELECT ts, name, value, unit, tags
                   FROM metrics
                   WHERE name = ? AND ts >= ?
                   ORDER BY ts DESC
                   LIMIT ?""",
                (name, since_ts, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def query_latest(self, name: str) -> dict | None:
        """Letzten Messwert für einen Namen."""
        with self._conn() as con:
            row = con.execute(
                "SELECT ts, name, value, unit, tags FROM metrics WHERE name=? ORDER BY ts DESC LIMIT 1",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    def query_range(
        self,
        names: list[str],
        since_s: int = 3600,
        resolution: int = 60,
    ) -> dict[str, list[dict]]:
        """
        Mehrere Metriken gleichzeitig, mit optionaler Downsampling-Auflösung.
        resolution=60  → je ein Durchschnittswert pro Minute
        resolution=0   → alle Rohwerte
        """
        since_ts = int(time.time()) - since_s
        result: dict[str, list[dict]] = {}
        for name in names:
            if resolution > 0:
                rows = self._query_downsampled(name, since_ts, resolution)
            else:
                rows = self.query(name, since_s)
            result[name] = rows
        return result

    def _query_downsampled(self, name: str, since_ts: int, resolution: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                f"""SELECT (ts / {resolution}) * {resolution} AS bucket,
                           AVG(value) AS value,
                           unit
                   FROM metrics
                   WHERE name = ? AND ts >= ?
                   GROUP BY bucket
                   ORDER BY bucket DESC
                   LIMIT 500""",
                (name, since_ts),
            ).fetchall()
        return [{"ts": r["bucket"], "name": name, "value": round(r["value"], 2), "unit": r["unit"]} for r in rows]

    def query_summary(self, names: list[str], since_s: int = 86400) -> dict[str, dict[str, float]]:
        """
        Berechnet Durchschnitt und Maximum für mehrere Metriken gleichzeitig.
        Gibt ein Dictionary zurück: { "metric_name": {"avg": 42.5, "max": 60.0} }
        """
        if not names:
            return {}

        since_ts = int(time.time()) - since_s
        placeholders = ",".join("?" for _ in names)
        query = f"""
            SELECT name, AVG(value) as avg_val, MAX(value) as max_val
            FROM metrics
            WHERE name IN ({placeholders}) AND ts >= ?
            GROUP BY name
        """

        params = tuple(names) + (since_ts,)

        result: dict[str, dict[str, float]] = {}
        with self._conn() as con:
            rows = con.execute(query, params).fetchall()
            for row in rows:
                if row["avg_val"] is not None and row["max_val"] is not None:
                    result[row["name"]] = {
                        "avg": round(row["avg_val"], 1),
                        "max": round(row["max_val"], 1),
                    }
        return result

    def list_metrics(self) -> list[str]:
        """Alle bekannten Metrik-Namen."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT name FROM metrics ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def stats(self) -> dict[str, Any]:
        """Datenbank-Statistiken."""
        with self._conn() as con:
            total = con.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
            oldest = con.execute("SELECT MIN(ts) FROM metrics").fetchone()[0]
            names = con.execute("SELECT COUNT(DISTINCT name) FROM metrics").fetchone()[0]
        size_kb = round(self.path.stat().st_size / 1024, 1) if self.path.exists() else 0
        return {
            "total_points": total,
            "distinct_metrics": names,
            "oldest_ts": oldest,
            "size_kb": size_kb,
            "retention_days": round(self.retention_s / _SECS_PER_DAY, 1),
        }

    # ── Wartung ───────────────────────────────────────────────────

    def purge_old(self) -> int:
        """Löscht Einträge älter als retention_s. Gibt Anzahl gelöschter Zeilen zurück."""
        cutoff = int(time.time()) - self.retention_s
        with self._conn() as con:
            cur = con.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
            deleted = cur.rowcount
        if deleted:
            logger.info("MetricsDB: %d alte Einträge gelöscht (älter als %dd)", deleted, self.retention_s // 86400)
        return deleted

    def vacuum(self):
        with self._conn() as con:
            con.execute("VACUUM")


# ── Collector ────────────────────────────────────────────────────

class MetricsCollector:
    """
    Sammelt Systemmetriken und schreibt sie in die DB.
    Läuft als asyncio-Hintergrundtask.
    """

    def __init__(self, db: MetricsDB, interval_s: int = COLLECT_S):
        self.db = db
        self.interval_s = interval_s
        self._stop = asyncio.Event()

    async def run(self) -> None:
        logger.info("MetricsCollector gestartet (Intervall: %ds)", self.interval_s)
        purge_counter = 0
        while not self._stop.is_set():
            try:
                points = await asyncio.to_thread(self._collect)
                await asyncio.to_thread(self.db.write_many, points)

                # Stündlich aufräumen, wöchentlich VACUUM
                purge_counter += 1
                if purge_counter >= (3600 // self.interval_s):
                    deleted = await asyncio.to_thread(self.db.purge_old)
                    purge_counter = 0
                    # Wöchentliches VACUUM (nach ~168 purge-Runden)
                    if not hasattr(self, "_vacuum_counter"):
                        self._vacuum_counter = 0
                    self._vacuum_counter += 1
                    if deleted and self._vacuum_counter >= 168:
                        await asyncio.to_thread(self.db.vacuum)
                        self._vacuum_counter = 0
                        logger.info("MetricsDB: VACUUM abgeschlossen")

            except Exception as e:
                logger.warning("MetricsCollector Fehler: %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
                break
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    def _collect(self) -> list[MetricPoint]:
        points: list[MetricPoint] = []
        ts = int(time.time())

        try:
            # CPU
            # interval=None: nicht-blockierend, nutzt internen psutil-Cache vom letzten Aufruf
            # Der Collector läuft alle 30s – damit ist der Cache immer aktuell
            cpu = psutil.cpu_percent(interval=None)
            if cpu == 0.0:
                # Erster Aufruf liefert 0.0 – kurzer blocking Fallback nur beim Start
                cpu = psutil.cpu_percent(interval=0.1)
            points.append(MetricPoint("cpu_percent", cpu, "%", ts=ts))

            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                points.append(MetricPoint("cpu_mhz", round(cpu_freq.current, 0), "MHz", ts=ts))

            # RAM
            mem = psutil.virtual_memory()
            points.append(MetricPoint("ram_percent", mem.percent, "%", ts=ts))
            points.append(MetricPoint("ram_used_mb", round(mem.used / 1024 / 1024, 0), "MB", ts=ts))

            # Disk
            disk = psutil.disk_usage("/")
            points.append(MetricPoint("disk_percent", disk.percent, "%", ts=ts))
            points.append(MetricPoint("disk_free_gb", round(disk.free / 1024**3, 2), "GB", ts=ts))

            # CPU-Temperatur (Pi: /sys/class/thermal/thermal_zone0/temp)
            temp = _read_cpu_temp()
            if temp is not None:
                points.append(MetricPoint("cpu_temp_c", round(temp, 1), "°C", ts=ts))

            # Netzwerk (Rx/Tx Bytes delta)
            net = psutil.net_io_counters()
            points.append(MetricPoint("net_rx_mb", round(net.bytes_recv / 1024 / 1024, 1), "MB", ts=ts))
            points.append(MetricPoint("net_tx_mb", round(net.bytes_sent / 1024 / 1024, 1), "MB", ts=ts))

            # Load Average
            load = psutil.getloadavg()
            points.append(MetricPoint("load_1m", round(load[0], 2), "", ts=ts))

        except Exception as e:
            logger.debug("Collect-Fehler: %s", e)

        return points


def _read_cpu_temp() -> float | None:
    """Liest CPU-Temperatur – funktioniert auf Pi und in psutil-Fallback."""
    # Pi: /sys/class/thermal/thermal_zone0/temp (in Milligrad)
    try:
        t = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
        return int(t) / 1000.0
    except OSError:
        pass  # thermal_zone0 not present on non-Pi
    # psutil fallback (Linux allgemein)
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "cpu_thermal", "cpu-thermal", "acpitz"):
            if key in temps and temps[key]:
                return temps[key][0].current
    except Exception as _e:
        logger.debug("psutil temp sensors: %s", _e)
    return None


# ── Singleton ─────────────────────────────────────────────────────
_db: MetricsDB | None = None
_collector: MetricsCollector | None = None


def get_db() -> MetricsDB:
    global _db
    if _db is None:
        from piclaw.config import load_config
        cfg = load_config()
        db_path = Path(cfg.config_dir) / "metrics.db"
        _db = MetricsDB(db_path)
    return _db


async def start_collector(interval_s: int = COLLECT_S) -> MetricsCollector:
    global _collector
    db = get_db()
    _collector = MetricsCollector(db, interval_s)
    create_background_task(_collector.run(), name="metrics_collector")
    return _collector


def get_collector() -> MetricsCollector | None:
    return _collector
"""Tests für piclaw.metrics – Zeitreihen-Engine."""
import asyncio
import time
from pathlib import Path

import pytest

from piclaw.metrics import MetricPoint, MetricsDB, MetricsCollector


@pytest.fixture
def db(tmp_path):
    return MetricsDB(path=tmp_path / "test_metrics.db", retention_s=3600)


# ── MetricPoint ───────────────────────────────────────────────────

def test_metricpoint_defaults():
    p = MetricPoint("cpu_percent", 42.5)
    assert p.name == "cpu_percent"
    assert p.value == 42.5
    assert p.unit == ""
    assert p.tags == {}
    assert abs(p.ts - int(time.time())) < 2


def test_metricpoint_tags_json():
    p = MetricPoint("cpu", 50.0, tags={"host": "piclaw"})
    j = p.tags_json()
    import json
    data = json.loads(j)
    assert data["host"] == "piclaw"


def test_metricpoint_empty_tags_json():
    p = MetricPoint("cpu", 50.0)
    assert p.tags_json() == "{}"


# ── MetricsDB ─────────────────────────────────────────────────────

def test_db_write_and_read(db):
    ts = int(time.time())
    db.write(MetricPoint("cpu_percent", 55.5, "%", ts=ts))
    rows = db.query("cpu_percent", since_s=60)
    assert len(rows) == 1
    assert rows[0]["value"] == 55.5
    assert rows[0]["unit"] == "%"


def test_db_write_many(db):
    points = [MetricPoint("ram_percent", float(i), "%") for i in range(10)]
    db.write_many(points)
    rows = db.query("ram_percent", since_s=60)
    assert len(rows) == 10


def test_db_query_latest(db):
    t1 = int(time.time()) - 100
    t2 = int(time.time())
    db.write(MetricPoint("temp", 40.0, "°C", ts=t1))
    db.write(MetricPoint("temp", 55.0, "°C", ts=t2))
    latest = db.query_latest("temp")
    assert latest is not None
    assert latest["value"] == 55.0


def test_db_query_latest_none(db):
    result = db.query_latest("nonexistent_metric")
    assert result is None


def test_db_query_latest_all(db):
    t1 = int(time.time()) - 100
    t2 = int(time.time())
    db.write(MetricPoint("temp", 40.0, "°C", ts=t1))
    db.write(MetricPoint("temp", 55.0, "°C", ts=t2))
    db.write(MetricPoint("cpu", 10.0, "%", ts=t1))

    result = db.query_latest_all()
    assert len(result) == 2
    assert "temp" in result
    assert result["temp"]["value"] == 55.0
    assert "cpu" in result
    assert result["cpu"]["value"] == 10.0


def test_db_query_latest_all_empty(db):
    result = db.query_latest_all()
    assert isinstance(result, dict)
    assert len(result) == 0


def test_db_list_metrics(db):
    db.write(MetricPoint("cpu_percent", 1.0))
    db.write(MetricPoint("ram_percent", 2.0))
    db.write(MetricPoint("cpu_percent", 3.0))
    names = db.list_metrics()
    assert "cpu_percent" in names
    assert "ram_percent" in names
    # Keine Duplikate
    assert len(names) == len(set(names))


def test_db_stats(db):
    db.write_many([MetricPoint("x", float(i)) for i in range(5)])
    stats = db.stats()
    assert stats["total_points"] == 5
    assert stats["distinct_metrics"] == 1
    assert stats["size_kb"] > 0


def test_db_query_range(db):
    # Alle Punkte mit resolution=0 abfragen, um alle Rohwerte zu bekommen
    for i in range(5):
        db.write(MetricPoint("cpu_percent", float(i * 10)))
        db.write(MetricPoint("ram_percent", float(i * 5)))
    result = db.query_range(["cpu_percent", "ram_percent"], since_s=60, resolution=0)
    assert "cpu_percent" in result
    assert "ram_percent" in result
    assert len(result["cpu_percent"]) == 5


def test_db_purge_old(db):
    old_ts = int(time.time()) - 7200  # 2 Stunden alt
    new_ts = int(time.time())
    db.write(MetricPoint("cpu", 10.0, ts=old_ts))
    db.write(MetricPoint("cpu", 20.0, ts=new_ts))
    deleted = db.purge_old()
    assert deleted == 1
    rows = db.query("cpu", since_s=3600)
    assert len(rows) == 1
    assert rows[0]["value"] == 20.0


def test_db_limit(db):
    db.write_many([MetricPoint("cpu", float(i)) for i in range(100)])
    rows = db.query("cpu", since_s=60, limit=10)
    assert len(rows) == 10


def test_db_since_filter(db):
    old_ts = int(time.time()) - 7200
    new_ts = int(time.time())
    db.write(MetricPoint("cpu", 10.0, ts=old_ts))
    db.write(MetricPoint("cpu", 20.0, ts=new_ts))
    rows = db.query("cpu", since_s=60)
    assert len(rows) == 1
    assert rows[0]["value"] == 20.0


def test_db_downsampled(db):
    # Mehrere Punkte in der gleichen Minute
    ts_base = (int(time.time()) // 60) * 60
    for i in range(5):
        db.write(MetricPoint("cpu", float(i * 10), ts=ts_base + i))
    rows = db._query_downsampled("cpu", ts_base - 1, resolution=60)
    assert len(rows) == 1
    assert rows[0]["value"] == pytest.approx(20.0, abs=1.0)  # avg(0,10,20,30,40)


def test_db_vacuum(db):
    """Vacuum sollte keine Exception werfen."""
    db.write(MetricPoint("cpu", 1.0))
    db.vacuum()


# ── MetricsCollector ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_collects(tmp_path):
    db = MetricsDB(path=tmp_path / "collect.db")
    collector = MetricsCollector(db, interval_s=1)

    # Einen Collect-Durchlauf manuell auslösen
    points = await asyncio.to_thread(collector._collect)
    assert len(points) > 0
    names = [p.name for p in points]
    assert "cpu_percent" in names
    assert "ram_percent" in names


@pytest.mark.asyncio
async def test_collector_stop(tmp_path):
    db = MetricsDB(path=tmp_path / "stop.db")
    collector = MetricsCollector(db, interval_s=100)  # langer Intervall
    task = asyncio.create_task(collector.run())
    await asyncio.sleep(0.1)
    collector.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()

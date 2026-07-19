"""Tests für piclaw.agents.sa_history (Run-Historie, Ring-Puffer) und
den next_run-Helfer im Runner."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from piclaw.agents import sa_history
from piclaw.agents.runner import _next_run_iso
from piclaw.agents.sa_registry import SubAgentDef


@pytest.fixture
def hist_file(tmp_path):
    """Pro Test isolierte History-Datei (zusätzlich zur Session-Isolation
    in conftest.patch_config_dir)."""
    f = tmp_path / "sa_history.json"
    with patch.object(sa_history, "HISTORY_FILE", f):
        yield f


class TestRecordRun:
    def test_record_and_read_newest_first(self, hist_file):
        sa_history.record_run("a1", "Agent1", "ok", 1.0, "erster Lauf", None)
        sa_history.record_run("a1", "Agent1", "error", 2.0, "zweiter Lauf", "u1")

        hist = sa_history.history_for("a1")
        assert len(hist) == 2
        assert hist[0]["result"] == "zweiter Lauf"
        assert hist[0]["status"] == "error"
        assert hist[0]["owner_id"] == "u1"
        assert hist[1]["result"] == "erster Lauf"

    def test_latest_per_agent(self, hist_file):
        sa_history.record_run("a1", "Agent1", "ok", 1.0, "alt", None)
        sa_history.record_run("a1", "Agent1", "ok", 1.0, "neu", None)
        sa_history.record_run("a2", "Agent2", "timeout", 300.0, "t", None)

        latest = sa_history.latest_per_agent()
        assert latest["a1"]["result"] == "neu"
        assert latest["a2"]["status"] == "timeout"

    def test_ring_buffer_trims_per_agent(self, hist_file):
        for i in range(sa_history.MAX_ENTRIES_PER_AGENT + 5):
            sa_history.record_run("a1", "Agent1", "ok", 0.1, f"lauf {i}", None)

        hist = sa_history.history_for("a1", limit=100)
        assert len(hist) == sa_history.MAX_ENTRIES_PER_AGENT
        # Älteste Einträge (0-4) sind raus, der neueste ist vorn
        assert hist[0]["result"] == f"lauf {sa_history.MAX_ENTRIES_PER_AGENT + 4}"
        assert all(h["result"] != "lauf 0" for h in hist)

    def test_result_truncated(self, hist_file):
        sa_history.record_run("a1", "Agent1", "ok", 0.1, "x" * 2000, None)
        hist = sa_history.history_for("a1")
        assert len(hist[0]["result"]) == sa_history.MAX_RESULT_CHARS

    def test_global_agent_cap(self, hist_file):
        for i in range(sa_history.MAX_AGENTS + 5):
            sa_history.record_run(f"a{i}", f"Agent{i}", "ok", 0.1, "r", None)

        data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert len(data) == sa_history.MAX_AGENTS
        # Der zuletzt geschriebene Agent überlebt den Prune
        assert f"a{sa_history.MAX_AGENTS + 4}" in data

    def test_corrupt_file_recovers(self, hist_file):
        hist_file.write_text("{kaputt", encoding="utf-8")
        assert sa_history.history_for("a1") == []
        assert sa_history.record_run("a1", "Agent1", "ok", 0.1, "r", None)
        assert sa_history.history_for("a1")[0]["result"] == "r"

    def test_none_result(self, hist_file):
        sa_history.record_run("a1", "Agent1", "error", 0.1, None, None)
        assert sa_history.history_for("a1")[0]["result"] == ""


class TestNextRun:
    def _agent(self, schedule, **kw):
        return SubAgentDef(
            name="T", description="d", mission="m", tools=[], schedule=schedule, **kw
        )

    def test_cron_next_run(self):
        nxt = _next_run_iso(self._agent("cron:15 7 * * *"))
        assert nxt is not None
        dt = datetime.fromisoformat(nxt)
        assert (dt.hour, dt.minute) == (7, 15)
        assert dt > datetime.now()

    def test_interval_from_last_run(self):
        agent = self._agent("interval:600")
        agent.last_run = datetime.now().isoformat()
        nxt = datetime.fromisoformat(_next_run_iso(agent))
        delta = nxt - datetime.now()
        assert timedelta(seconds=500) < delta < timedelta(seconds=700)

    def test_interval_overdue_clamps_to_now(self):
        agent = self._agent("interval:600")
        agent.last_run = (datetime.now() - timedelta(hours=2)).isoformat()
        nxt = datetime.fromisoformat(_next_run_iso(agent))
        assert nxt >= datetime.now() - timedelta(seconds=5)

    def test_once_continuous_disabled(self):
        assert _next_run_iso(self._agent("once")) is None
        assert _next_run_iso(self._agent("continuous")) is None
        assert _next_run_iso(self._agent("cron:15 7 * * *", enabled=False)) is None

    def test_invalid_schedules(self):
        assert _next_run_iso(self._agent("cron:kaputt")) is None
        assert _next_run_iso(self._agent("interval:abc")) is None

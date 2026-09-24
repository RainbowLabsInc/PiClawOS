"""Regressionstests für den Service-Neustart nach einem Update.

Hintergrund (2026-09-24): Der Updater startete nur piclaw-api und
piclaw-agent neu - Crawler und Watchdog liefen seit dem 09.09. mit altem
Code weiter. Zudem gingen beide Units in EINEN sudo-Aufruf, die sudoers-Regel
erlaubt aber nur "systemctl restart <unit>" mit genau einer Unit.
"""

from pathlib import Path

from piclaw.config import UpdaterConfig
from piclaw.tools import updater
from piclaw.tools.updater import _RESTART_UNITS, _own_unit, _restart_order

ALL_UNITS = {"piclaw-api", "piclaw-agent", "piclaw-crawler", "piclaw-watchdog"}


def test_restart_units_cover_all_code_services():
    assert set(_RESTART_UNITS) == ALL_UNITS


def test_restart_order_puts_own_unit_last():
    for own in ALL_UNITS:
        order = _restart_order(own)
        assert order[-1] == own
        assert set(order) == ALL_UNITS
        assert len(order) == len(ALL_UNITS)


def test_restart_order_outside_service_keeps_all():
    # CLI-Aufruf aus einer Shell: keine eigene piclaw-Unit
    assert set(_restart_order(None)) == ALL_UNITS
    assert set(_restart_order("user@1000")) == ALL_UNITS


def test_own_unit_from_cgroup(monkeypatch):
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: "0::/system.slice/piclaw-agent.service\n",
    )
    assert _own_unit() == "piclaw-agent"


def test_own_unit_none_for_user_session(monkeypatch):
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: "0::/user.slice/user-1000.slice/session-3.scope\n",
    )
    assert _own_unit() is None


async def test_update_restarts_each_unit_separately_own_last(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    cmds: list[str] = []

    async def fake_run(cmd: str, timeout: int = 120):
        cmds.append(cmd)
        if "git pull" in cmd:
            return 0, "Updating a11120c..b22231d\nFast-forward"
        if "git stash" in cmd:
            return 0, "No local changes to save"
        return 0, ""

    monkeypatch.setattr(updater, "_run", fake_run)
    monkeypatch.setattr(updater, "_own_unit", lambda: "piclaw-api")

    result = await updater.system_update(target="piclaw", cfg=UpdaterConfig())

    restarts = [c for c in cmds if "systemctl restart" in c]
    # je Unit ein eigener Aufruf, exakt im sudoers-Format
    assert {c.split()[3] for c in restarts} == ALL_UNITS
    assert all(c == f"sudo systemctl restart {c.split()[3]} 2>&1" for c in restarts)
    assert "piclaw-api" in restarts[-1]
    assert "Services neu gestartet" in result


async def test_update_reports_failed_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    async def fake_run(cmd: str, timeout: int = 120):
        if "git pull" in cmd:
            return 0, "Fast-forward"
        if "restart piclaw-watchdog" in cmd:
            return 1, "sudo: a password is required"
        return 0, ""

    monkeypatch.setattr(updater, "_run", fake_run)
    monkeypatch.setattr(updater, "_own_unit", lambda: None)

    result = await updater.system_update(target="piclaw", cfg=UpdaterConfig())

    assert "piclaw-watchdog: sudo: a password is required" in result
    assert "✅ Services neu gestartet" not in result

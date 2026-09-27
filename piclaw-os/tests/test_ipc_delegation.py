"""
Regression tests: Sub-Agents aus dem API-Prozess laufen im Daemon.

Background: ``Monitor_EgunBeretta`` wurde per Telegram angelegt – also im
piclaw-api-Prozess – und dort direkt per ``sa_runner.start_agent`` gestartet.
Der Daemon hatte seine Registry vorher geladen und kannte den Agent nicht.
Folgen: der Schedule-Loop lief bis zum nächsten gemeinsamen Neustart im API-
Prozess (weg bei Neustart nur von piclaw-api, doppelt bei Neustart nur von
piclaw-agent), und die veraltete Daemon-Memory überschrieb stündlich last_run.

Der Fix: im API-Prozess (``delegate_to_daemon``) gehen start/stop/run_now
per IPC-Trigger an den Daemon, der die Definition frisch von Disk lädt.
Die zwei Registries/Runner in diesen Tests simulieren die beiden Prozesse.
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from piclaw import ipc
from piclaw.agents.runner import SubAgentRunner
from piclaw.agents.sa_registry import SubAgentDef, SubAgentRegistry


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("piclaw.agents.sa_registry.SA_REGISTRY_FILE", tmp_path / "subagents.json")
    monkeypatch.setattr(ipc, "IPC_DIR", tmp_path / "ipc")
    monkeypatch.setattr(ipc, "POLL_INTERVAL", 0.01)
    return tmp_path / "ipc"


def _make_runner(handlers: dict | None = None, *, delegate: bool) -> SubAgentRunner:
    runner = SubAgentRunner(
        registry=SubAgentRegistry(),
        llm=None,  # direct_tool path never touches the LLM
        tool_defs=[],
        handlers=handlers or {},
        notify=None,
        memory_log=None,
        report_to_main=None,
    )
    runner.delegate_to_daemon = delegate
    return runner


def _agent(**overrides) -> SubAgentDef:
    defaults = dict(
        name="Monitor_Test",
        description="test monitor",
        mission="",
        tools=[],
        schedule="interval:3600",
        direct_tool="count_tool",
        timeout=5,
        notify=False,
    )
    defaults.update(overrides)
    return SubAgentDef(**defaults)


@contextlib.asynccontextmanager
async def _polling(runner: SubAgentRunner):
    task = asyncio.create_task(ipc.poll_triggers(runner))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await runner.stop_all()


async def _wait_for(cond, timeout: float = 2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def test_api_start_runs_in_daemon_not_locally(_isolated):
    calls = []
    daemon = _make_runner({"count_tool": lambda: calls.append(1) or "ok"}, delegate=False)
    api = _make_runner(delegate=True)  # erst NACH dem Daemon angelegt

    agent = _agent()
    api.registry.add(agent)
    assert daemon.registry.get(agent.id) is None  # Daemon kennt ihn noch nicht

    result = await api.start_agent(agent.id)

    assert "gestartet" in result
    assert api.running_agents() == []
    assert (_isolated / f"start_{agent.id}.trigger").exists()

    async with _polling(daemon):
        await _wait_for(lambda: calls)
        assert daemon.running_agents() == [agent.id]
        assert not (_isolated / f"start_{agent.id}.trigger").exists()


async def test_api_once_agent_stays_local(_isolated):
    calls = []
    api = _make_runner({"count_tool": lambda: calls.append(1) or "ok"}, delegate=True)
    agent = _agent(name="SearchAssistant", schedule="once")
    api.registry.add(agent)

    await api.start_agent(agent.id)

    await _wait_for(lambda: calls)
    assert not _isolated.exists() or not list(_isolated.glob("start_*"))


async def test_api_stop_stops_daemon_loop(_isolated):
    daemon = _make_runner({"count_tool": lambda: "ok"}, delegate=False)
    api = _make_runner(delegate=True)
    agent = _agent()
    api.registry.add(agent)

    async with _polling(daemon):
        await api.start_agent(agent.id)
        await _wait_for(lambda: daemon.running_agents() == [agent.id])

        result = await api.stop_agent(agent.id)

        assert "gestoppt" in result
        await _wait_for(lambda: daemon.running_agents() == [])


async def test_api_run_now_executes_in_daemon(_isolated):
    calls = []
    daemon = _make_runner({"count_tool": lambda: calls.append(1) or "ok"}, delegate=False)
    api = _make_runner(delegate=True)
    agent = _agent(schedule="once")
    api.registry.add(agent)

    api.run_now(agent)

    assert (_isolated / f"run_now_{agent.id}.trigger").exists()
    async with _polling(daemon):
        await _wait_for(lambda: calls)


async def test_api_shutdown_does_not_stop_daemon_agents(_isolated):
    api = _make_runner(delegate=True)
    agent = _agent()
    api.registry.add(agent)

    await api.stop_all()

    assert not _isolated.exists() or not list(_isolated.glob("stop_*"))


async def test_ipc_failure_falls_back_to_local_start(_isolated, monkeypatch):
    api = _make_runner({"count_tool": lambda: "ok"}, delegate=True)
    agent = _agent()
    api.registry.add(agent)
    monkeypatch.setattr(ipc, "write_start", lambda agent_id: False)

    await api.start_agent(agent.id)

    assert api.running_agents() == [agent.id]
    await api.stop_all()


async def test_daemon_start_is_local(_isolated):
    daemon = _make_runner({"count_tool": lambda: "ok"}, delegate=False)
    agent = _agent()
    daemon.registry.add(agent)

    await daemon.start_agent(agent.id)

    assert daemon.running_agents() == [agent.id]
    assert not _isolated.exists() or not list(_isolated.glob("start_*"))
    await daemon.stop_all()


def test_reload_agent_picks_up_external_definition(_isolated):
    daemon_reg = SubAgentRegistry()
    api_reg = SubAgentRegistry()
    agent = _agent()
    api_reg.add(agent)

    reloaded = daemon_reg.reload_agent(agent.id)

    assert reloaded is not None and reloaded.name == "Monitor_Test"
    assert daemon_reg.get(agent.id) is reloaded
    assert daemon_reg.reload_agent("does-not-exist") is None

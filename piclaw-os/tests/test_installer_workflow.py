import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from piclaw.agent import Agent
from piclaw.config import PiClawConfig
from piclaw.agents.sa_registry import SubAgentDef

@pytest.fixture
def mock_cfg():
    cfg = PiClawConfig()
    cfg.llm.backend = "mock"
    return cfg

@pytest.mark.asyncio
async def test_installer_delegation(mock_cfg):
    # Setup agent with mocks
    agent = Agent(mock_cfg)
    agent.sa_runner = AsyncMock()

    # Trigger @installer
    user_input = "@installer Install tandem-browser"
    response = await agent.run(user_input)

    assert "Installer-Subagent wurde gestartet" in response

    # Verify sub-agent creation
    agents = agent.sa_registry.list_all()
    installer = next((a for a in agents if a.name == "InstallerAgent"), None)

    assert installer is not None
    assert installer.privileged is True
    assert "tandem-browser" in installer.description
    assert "shell" in installer.tools
    assert "installer_confirm" in installer.tools

@pytest.mark.asyncio
async def test_installer_confirm_tool(tmp_path, monkeypatch):
    from piclaw.tools.installer import installer_confirm

    # Mock CONFIG_DIR to use tmp_path
    monkeypatch.setattr("piclaw.tools.installer.CONFIG_DIR", tmp_path)
    req_file = tmp_path / "ipc" / "install_req.json"
    res_file = tmp_path / "ipc" / "install_res.json"

    async def simulate_user_response():
        await asyncio.sleep(1)
        res_file.parent.mkdir(parents=True, exist_ok=True)
        res_file.write_text(json.dumps({"decision": "YES"}))

    # Start confirm tool
    confirm_task = asyncio.create_task(installer_confirm("apt install tandem"))
    # Start simulator
    asyncio.create_task(simulate_user_response())

    result = await confirm_task
    assert result == "YES"
    assert not req_file.exists()
    assert not res_file.exists()

@pytest.mark.asyncio
async def test_watchdog_installer_hang(tmp_path, monkeypatch):
    from piclaw.agents.watchdog import Watchdog

    # Mock INSTALLER_LOCK_FILE and WATCHDOG_LOG_DIR
    lock_file = tmp_path / "piclaw_installer.lock"
    monkeypatch.setattr("piclaw.agents.watchdog.INSTALLER_LOCK_FILE", lock_file)
    log_dir = tmp_path / "log"
    monkeypatch.setattr("piclaw.agents.watchdog.WATCHDOG_LOG_DIR", log_dir)

    # Create an "old" lock file
    lock_file.write_text("lock")
    import time
    import os
    # Backdate mtime by 20 minutes
    old_ts = time.time() - 1200
    os.utime(lock_file, (old_ts, old_ts))

    wd = Watchdog()
    alerts = wd._check_installer_hang()

    assert len(alerts) == 1
    assert alerts[0].message == "Installer Hang Detected"
    assert alerts[0].severity == "critical"

@pytest.mark.asyncio
async def test_installer_lock_creation_and_cleanup(mock_cfg, tmp_path, monkeypatch):
    from piclaw.agents.watchdog import INSTALLER_LOCK_FILE

    # Mock lock file location
    test_lock = tmp_path / "installer.lock"
    # We patch the modules where the lock file is actually used
    import piclaw.agents.watchdog
    import piclaw.agent
    import piclaw.agents.runner

    monkeypatch.setattr(piclaw.agents.watchdog, "INSTALLER_LOCK_FILE", test_lock)
    monkeypatch.setattr(piclaw.agent, "INSTALLER_LOCK_FILE", test_lock, raising=False)
    monkeypatch.setattr(piclaw.agents.runner, "INSTALLER_LOCK_FILE", test_lock, raising=False)

    # Setup agent
    agent = Agent(mock_cfg)
    # Mock runner and registry
    agent.sa_runner = AsyncMock()
    agent.sa_runner._tasks = {}

    # We need to simulate the task finishing to trigger the callback
    mock_task = MagicMock()
    agent.sa_runner.start_agent = AsyncMock(return_value="Started")

    # Store the callback
    cleanup_callbacks = []
    def mock_add_done_callback(cb):
        cleanup_callbacks.append(cb)

    mock_task.add_done_callback = mock_add_done_callback

    async def mock_start_agent(aid):
        agent.sa_runner._tasks[aid] = mock_task
        # Simulate runner.py registering the cleanup
        def _cleanup(t):
            if test_lock.exists():
                test_lock.unlink()
        mock_task.add_done_callback(_cleanup)
        return "Started"

    agent.sa_runner.start_agent.side_effect = mock_start_agent

    # Trigger @installer
    await agent.run("@installer test")

    # Check lock file created
    assert test_lock.exists()
    assert "test" in test_lock.read_text()

    # Trigger cleanup callback
    for cb in cleanup_callbacks:
        cb(mock_task)

    # Check lock file removed
    assert not test_lock.exists(), f"Lock file {test_lock} still exists"

def test_build_handlers(monkeypatch):
    from piclaw.tools.installer import build_handlers

    # Mock the installer_confirm function to track if it was called
    mock_called_with = {}

    async def mock_installer_confirm(**kwargs):
        mock_called_with.update(kwargs)
        return "YES"

    monkeypatch.setattr("piclaw.tools.installer.installer_confirm", mock_installer_confirm)

    handlers = build_handlers()

    # Verify the dictionary structure
    assert isinstance(handlers, dict)
    assert "installer_confirm" in handlers
    assert callable(handlers["installer_confirm"])

    # Verify the lambda correctly proxies arguments
    import asyncio
    result = asyncio.run(handlers["installer_confirm"](plan="test plan"))

    assert result == "YES"
    assert mock_called_with == {"plan": "test plan"}

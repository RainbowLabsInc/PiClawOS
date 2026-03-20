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

    # Mock INSTALLER_LOCK_FILE
    lock_file = tmp_path / "piclaw_installer.lock"
    monkeypatch.setattr("piclaw.agents.watchdog.INSTALLER_LOCK_FILE", lock_file)

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

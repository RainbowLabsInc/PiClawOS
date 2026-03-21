import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import builtins
import sys

from piclaw.cli import cmd_doctor

def test_cmd_doctor_happy_path(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.agent.Agent") as mock_agent_class, \
         patch("psutil.virtual_memory") as mock_vmem, \
         patch("psutil.disk_usage") as mock_disk, \
         patch("socket.gethostname") as mock_hostname, \
         patch("platform.python_version", return_value="3.11.2"), \
         patch("platform.platform", return_value="Linux-Pi5"), \
         patch("builtins.open") as mock_open, \
         patch("piclaw.soul.get_path") as mock_soul_path, \
         patch("piclaw.agents.sa_registry.SubAgentRegistry") as mock_registry:

        # Mock config
        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClaw"
        mock_cfg.llm.backend = "api"
        mock_cfg.llm.model = "gpt-4"
        mock_cfg.api.secret_key = "secret"
        mock_load.return_value = mock_cfg

        # Mock Agent
        mock_agent = MagicMock()
        mock_agent.llm.health_check = AsyncMock(return_value=True)
        mock_agent_class.return_value = mock_agent

        # Mock psutil
        mock_mem = MagicMock()
        mock_mem.used = 1048576 * 100  # 100 MB
        mock_mem.total = 1048576 * 1000 # 1000 MB
        mock_vmem.return_value = mock_mem

        mock_d = MagicMock()
        mock_d.used = 1073741824 * 10  # 10 GB
        mock_d.total = 1073741824 * 100 # 100 GB
        mock_disk.return_value = mock_d

        mock_hostname.return_value = "raspberrypi"

        # Mock CPU temp
        # Python 3 built-in open() returns a context manager but also read() directly
        mock_file = MagicMock()
        mock_file.read.return_value = "45000"
        mock_open.return_value = mock_file
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock Soul
        mock_soul = MagicMock()
        mock_soul.exists.return_value = True
        mock_soul.stat.return_value.st_size = 1024
        mock_soul.__str__.return_value = "/path/to/soul.md"
        mock_soul_path.return_value = mock_soul

        # Mock Registry
        mock_reg_inst = MagicMock()
        agent1 = MagicMock()
        agent1.last_status = "ok"
        agent2 = MagicMock()
        agent2.last_status = "running"
        mock_reg_inst.list_all.return_value = [agent1, agent2]
        mock_registry.return_value = mock_reg_inst

        # Run function
        cmd_doctor()

        # Check output
        captured = capsys.readouterr()
        out = captured.out

        assert "PiClaw Doctor" in out
        assert "Agent       : PiClaw" in out
        assert "LLM backend : api / gpt-4" in out
        assert "LLM health  : ✅ OK" in out
        assert "Python      : 3.11.2" in out
        assert "Platform    : Linux-Pi5" in out
        assert "Hostname    : raspberrypi" in out
        assert "Memory      : 100 / 1000 MB" in out
        assert "Disk        : 10.0 / 100.0 GB" in out
        assert "CPU Temp    : 45.0°C" in out
        assert "API Token   : ✅ set (piclaw config token)" in out
        assert "Soul        : ✅ /path/to/soul.md (1024 B)" in out
        assert "Sub-Agents  : ✅ 2 defined  (ok=1, error=0, running=1)" in out
        assert "aiohttp     : ✅" in out
        assert "fastapi     : ✅" in out

def test_cmd_doctor_llm_failure(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.agent.Agent") as mock_agent_class, \
         patch("psutil.virtual_memory") as mock_vmem, \
         patch("psutil.disk_usage") as mock_disk, \
         patch("socket.gethostname") as mock_hostname, \
         patch("platform.python_version", return_value="3.11.2"), \
         patch("platform.platform", return_value="Linux-Pi5"), \
         patch("builtins.open") as mock_open, \
         patch("piclaw.soul.get_path") as mock_soul_path, \
         patch("piclaw.agents.sa_registry.SubAgentRegistry") as mock_registry:

        # Mock config
        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClaw"
        mock_cfg.llm.backend = "api"
        mock_cfg.llm.model = "gpt-4"
        mock_cfg.api.secret_key = "secret"
        mock_load.return_value = mock_cfg

        # Mock Agent
        mock_agent = MagicMock()
        mock_agent.llm.health_check = AsyncMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        mock_mem = MagicMock()
        mock_mem.used = 1048576 * 100
        mock_mem.total = 1048576 * 1000
        mock_vmem.return_value = mock_mem

        mock_d = MagicMock()
        mock_d.used = 1073741824 * 10
        mock_d.total = 1073741824 * 100
        mock_disk.return_value = mock_d

        mock_hostname.return_value = "raspberrypi"

        mock_file = MagicMock()
        mock_file.read.return_value = "45000"
        mock_open.return_value = mock_file
        mock_open.return_value.__enter__.return_value = mock_file

        mock_soul = MagicMock()
        mock_soul.exists.return_value = True
        mock_soul.stat.return_value.st_size = 1024
        mock_soul.__str__.return_value = "/path/to/soul.md"
        mock_soul_path.return_value = mock_soul

        mock_reg_inst = MagicMock()
        mock_reg_inst.list_all.return_value = []
        mock_registry.return_value = mock_reg_inst

        # Run function
        cmd_doctor()

        # Check output
        captured = capsys.readouterr()
        out = captured.out

        assert "LLM health  : ❌ UNREACHABLE (check API key)" in out
        assert "Sub-Agents  : ⬜ None defined" in out

def test_cmd_doctor_local_llm_missing(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.agent.Agent") as mock_agent_class, \
         patch("psutil.virtual_memory") as mock_vmem, \
         patch("psutil.disk_usage") as mock_disk, \
         patch("socket.gethostname") as mock_hostname, \
         patch("platform.python_version", return_value="3.11.2"), \
         patch("platform.platform", return_value="Linux-Pi5"), \
         patch("builtins.open") as mock_open, \
         patch("piclaw.soul.get_path") as mock_soul_path, \
         patch("piclaw.agents.sa_registry.SubAgentRegistry") as mock_registry:

        # Mock config
        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClaw"
        mock_cfg.llm.backend = "local"
        mock_cfg.llm.model = ""
        mock_cfg.api.secret_key = ""
        mock_load.return_value = mock_cfg

        # Mock Agent
        mock_agent = MagicMock()
        mock_agent.llm.health_check = AsyncMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        mock_mem = MagicMock()
        mock_mem.used = 1048576 * 100
        mock_mem.total = 1048576 * 1000
        mock_vmem.return_value = mock_mem

        mock_d = MagicMock()
        mock_d.used = 1073741824 * 10
        mock_d.total = 1073741824 * 100
        mock_disk.return_value = mock_d

        mock_hostname.return_value = "raspberrypi"

        mock_file = MagicMock()
        mock_file.read.return_value = "45000"
        mock_open.return_value = mock_file
        mock_open.return_value.__enter__.return_value = mock_file

        mock_soul = MagicMock()
        mock_soul.exists.return_value = False
        mock_soul_path.return_value = mock_soul

        mock_reg_inst = MagicMock()
        mock_reg_inst.list_all.return_value = []
        mock_registry.return_value = mock_reg_inst

        with patch("pathlib.Path.exists", return_value=False):
            # Run function
            cmd_doctor()

        # Check output
        captured = capsys.readouterr()
        out = captured.out

        assert "LLM health  : ❌ Modell nicht gefunden – piclaw model download" in out
        assert "API Token   : ⬜ not generated yet" in out
        assert "Soul        : ⬜ Not created yet (will be on first boot)" in out

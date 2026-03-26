import pytest
import builtins
import sys
import json
from piclaw.cli import cmd_chat
from unittest.mock import patch, MagicMock, AsyncMock

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

        with patch("piclaw.hardware.pi_info.current_temp", return_value=45.0):

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


def test_cmd_chat_api_success(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.cli._api_running", return_value=True), \
         patch("websockets.connect") as mock_ws_connect, \
         patch("builtins.input", side_effect=["hello", "help", "exit"]), \
         patch("piclaw.auth.get_token", return_value="test_token"):

        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClawTest"
        mock_cfg.api.port = 8000
        mock_load.return_value = mock_cfg

        mock_ws = AsyncMock()
        # The code receives from mock_ws in a while loop, so we need to return messages that correspond to inputs.
        # But `cmd_chat` does not break out of its `while True` loop over inputs.
        # The exception or end of side_effects raises StopIteration, but mock objects by default raise StopAsyncIteration
        # when an AsyncMock side_effect list is exhausted, or it might just error out. Let's fix this properly.
        mock_ws.recv.side_effect = [
            json.dumps({"type": "thinking"}),
            json.dumps({"type": "reply", "text": "Hi there!"})
        ]
        mock_ws_connect.return_value.__aenter__.return_value = mock_ws

        cmd_chat()

        captured = capsys.readouterr()
        out = captured.out

        assert "PiClawTest ready" in out
        assert "Verbunden mit laufendem Daemon" in out
        assert "Thinking" in out
        assert "Hi there!" in out
        assert "Commands:" in out  # From the HELP print
        assert "Goodbye." in out

        mock_ws.send.assert_called_with(json.dumps({"text": "hello"}))


def test_cmd_chat_api_no_token(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.cli._api_running", return_value=True), \
         patch("piclaw.auth.get_token", return_value=None):

        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClawTest"
        mock_cfg.api.port = 8000
        mock_cfg.api.secret_key = None
        mock_load.return_value = mock_cfg


        with patch("piclaw.agent.Agent") as mock_agent_class, \
             patch("builtins.input", side_effect=["exit"]):

            mock_agent = MagicMock()
            mock_agent.boot = AsyncMock()
            mock_agent_class.return_value = mock_agent

            cmd_chat()

        captured = capsys.readouterr()
        out = captured.out
        # Should fall back to direct mode
        assert "Offline-Modus" in out
        assert "Goodbye." in out


def test_cmd_chat_direct_fallback(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.cli._api_running", return_value=False), \
         patch("piclaw.agent.Agent") as mock_agent_class, \
         patch("builtins.input", side_effect=["hello", "help", "exit"]):

        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClawTest"
        mock_load.return_value = mock_cfg

        mock_agent = MagicMock()
        mock_agent.boot = AsyncMock()
        mock_agent.run = AsyncMock(return_value="Direct reply!")
        mock_agent_class.return_value = mock_agent

        cmd_chat()

        captured = capsys.readouterr()
        out = captured.out

        assert "PiClawTest ready" in out
        assert "Offline-Modus" in out
        assert "Thinking" in out
        assert "Direct reply!" in out
        assert "Commands:" in out  # From the HELP print
        assert "Goodbye." in out


        from piclaw.llm import Message as _Msg
        history_calls = mock_agent.run.call_args.kwargs['history']
        assert len(history_calls) == 2
        assert history_calls[0].role == "user"
        assert history_calls[0].content == "hello"
        assert history_calls[1].role == "assistant"
        assert history_calls[1].content == "Direct reply!"



def test_cmd_chat_interrupt(capsys):
    with patch("piclaw.config.load") as mock_load, \
         patch("piclaw.cli._api_running", return_value=False), \
         patch("piclaw.agent.Agent") as mock_agent_class, \
         patch("builtins.input", side_effect=KeyboardInterrupt):

        mock_cfg = MagicMock()
        mock_cfg.agent_name = "PiClawTest"
        mock_load.return_value = mock_cfg

        mock_agent = MagicMock()
        mock_agent.boot = AsyncMock()
        mock_agent_class.return_value = mock_agent

        cmd_chat()

        captured = capsys.readouterr()
        out = captured.out

        assert "Session ended." in out

import pytest
import asyncio
from unittest.mock import patch, MagicMock

from piclaw.config import ShellConfig
from piclaw.tools.shell import build_handlers, run_shell, system_info, _is_allowed

@pytest.fixture
def shell_cfg():
    return ShellConfig()

class TestBuildHandlers:
    @pytest.mark.asyncio
    async def test_build_handlers_keys(self, shell_cfg):
        handlers = build_handlers(shell_cfg)
        assert "shell" in handlers
        assert "system_info" in handlers

    @pytest.mark.asyncio
    @patch("piclaw.tools.shell.run_shell")
    async def test_shell_handler_calls_run_shell(self, mock_run_shell, shell_cfg):
        handlers = build_handlers(shell_cfg)
        mock_run_shell.return_value = "mock_shell_out"

        result = await handlers["shell"](command="echo 'hello'")

        mock_run_shell.assert_called_once_with(cfg=shell_cfg, command="echo 'hello'")
        assert result == "mock_shell_out"

    @pytest.mark.asyncio
    @patch("piclaw.tools.shell.system_info")
    async def test_system_info_handler_calls_system_info(self, mock_system_info, shell_cfg):
        handlers = build_handlers(shell_cfg)
        mock_system_info.return_value = "mock_sys_info"

        result = await handlers["system_info"]()

        mock_system_info.assert_called_once_with()
        assert result == "mock_sys_info"

class TestRunShell:
    @pytest.mark.asyncio
    async def test_run_shell_disabled(self):
        cfg = ShellConfig(enabled=False)
        result = await run_shell("echo 'hello'", cfg)
        assert result == "Shell tool is disabled."

    @pytest.mark.asyncio
    async def test_run_shell_blocked(self):
        cfg = ShellConfig(enabled=True, blocklist=["rm -rf"], allowlist=[])
        result = await run_shell("rm -rf /", cfg)
        assert "[BLOCKED]" in result
        assert "rm -rf" in result.lower()

    @pytest.mark.asyncio
    async def test_run_shell_not_in_allowlist(self):
        cfg = ShellConfig(enabled=True, allowlist=["ls", "echo"])
        result = await run_shell("cat /etc/passwd", cfg)
        assert "[BLOCKED]" in result
        assert "not in allowlist" in result

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_shell")
    @patch("asyncio.wait_for")
    async def test_run_shell_success(self, mock_wait_for, mock_create_subprocess_shell):
        cfg = ShellConfig(enabled=True, allowlist=["echo"])

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_create_subprocess_shell.return_value = mock_proc

        mock_wait_for.return_value = (b"hello\n", b"")

        result = await run_shell("echo 'hello'", cfg)

        assert "[exit 0]" in result
        assert "hello" in result
        assert "[stderr]" not in result

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_shell")
    @patch("asyncio.wait_for")
    async def test_run_shell_timeout(self, mock_wait_for, mock_create_subprocess_shell):
        cfg = ShellConfig(enabled=True, allowlist=["sleep"], timeout=1)

        mock_proc = MagicMock()
        mock_create_subprocess_shell.return_value = mock_proc

        mock_wait_for.side_effect = asyncio.TimeoutError()

        result = await run_shell("sleep 10", cfg)

        mock_proc.kill.assert_called_once()
        assert "[TIMEOUT]" in result


class TestSystemInfo:
    @pytest.mark.asyncio
    @patch("psutil.cpu_percent", return_value=12.5)
    @patch("psutil.cpu_freq")
    @patch("psutil.virtual_memory")
    @patch("psutil.disk_usage")
    @patch("psutil.boot_time")
    @patch("psutil.getloadavg", return_value=(0.1, 0.2, 0.3))
    @patch("piclaw.hardware.pi_info.current_temp", return_value=45.0)
    async def test_system_info_success(
        self, mock_current_temp, mock_getloadavg, mock_boot_time, mock_disk_usage,
        mock_virtual_memory, mock_cpu_freq, mock_cpu_percent
    ):
        # Mock CPU Freq
        mock_freq = MagicMock()
        mock_freq.current = 1500
        mock_cpu_freq.return_value = mock_freq

        # Mock Virtual Memory
        mock_vmem = MagicMock()
        mock_vmem.used = 1_048_576 * 1024  # 1024 MB
        mock_vmem.total = 1_048_576 * 4096 # 4096 MB
        mock_vmem.percent = 25.0
        mock_virtual_memory.return_value = mock_vmem

        # Mock Disk Usage
        mock_disk = MagicMock()
        mock_disk.used = 1_073_741_824 * 10  # 10 GB
        mock_disk.total = 1_073_741_824 * 100 # 100 GB
        mock_disk.percent = 10.0
        mock_disk_usage.return_value = mock_disk

        # Mock Boot Time
        from datetime import datetime, timedelta
        mock_boot_time.return_value = (datetime.now() - timedelta(hours=1, minutes=30)).timestamp()


        result = await system_info()

        assert "CPU Usage : 12.5%" in result
        assert "CPU Freq  : 1500 MHz" in result
        assert "CPU Temp  : 45.0°C" in result
        assert "Memory    : 1024 MB used / 4096 MB total (25%)" in result
        assert "Disk (/)  : 10.0 GB used / 100.0 GB total (10%)" in result
        assert "Uptime    : 1h 29m" in result or "Uptime    : 1h 30m" in result
        assert "Load avg  : 0.10 0.20 0.30" in result

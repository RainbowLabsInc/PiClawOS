import pytest
from unittest.mock import AsyncMock, patch
from piclaw.tools.network_security import (
    whois_lookup,
    block_ip,
    tarpit_ip,
    generate_abuse_report,
    deploy_honey_trap,
    stop_honey_trap,
    list_honey_traps,
    _ACTIVE_TRAPS,
    _run_command,
    _is_local_ip,
    _handle_labyrinth,
    _handle_sinkhole,
    _handle_rickroll,
)
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def clean_traps():
    """Ensure _ACTIVE_TRAPS is empty before each test."""
    _ACTIVE_TRAPS.clear()
    yield

@pytest.fixture
def mock_run_command():
    with patch("piclaw.tools.network_security._run_command", new_callable=AsyncMock) as mock:
        yield mock

@pytest.mark.asyncio
async def test_invalid_ip_validation(mock_run_command):
    # Test that invalid IPs are rejected
    res1 = await whois_lookup("invalid_ip")
    assert "Invalid IP address format" in res1

    res2 = await block_ip("-s")
    assert "Invalid IP address format" in res2

    res3 = await tarpit_ip("; ls", 22)
    assert "Invalid IP address format" in res3

    res4 = await generate_abuse_report("999.999.999.999", "evidence")
    assert "Invalid IP address format" in res4

    # Ensure run_command is not called
    mock_run_command.assert_not_called()


@pytest.mark.asyncio
async def test_whois_lookup(mock_run_command):
    mock_run_command.return_value = "WHOIS DATA for 8.8.8.8"

    result = await whois_lookup("8.8.8.8")
    mock_run_command.assert_called_once_with("whois", "8.8.8.8")
    assert "WHOIS DATA" in result

@pytest.mark.asyncio
async def test_whois_lookup_truncation(mock_run_command):
    long_output = "A" * 3000
    mock_run_command.return_value = long_output

    result = await whois_lookup("8.8.8.8")
    assert len(result) < 3000
    assert "...[TRUNCATED]" in result

@pytest.mark.asyncio
async def test_block_ip(mock_run_command):
    mock_run_command.return_value = ""

    result = await block_ip("8.8.8.8")
    mock_run_command.assert_called_once_with("sudo", "iptables", "-A", "INPUT", "-s", "8.8.8.8", "-j", "DROP")
    assert "SUCCESS" in result
    assert "8.8.8.8" in result

@pytest.mark.asyncio
async def test_block_ip_error(mock_run_command):
    mock_run_command.return_value = "[ERROR] Command failed: iptables v1.8.9"

    result = await block_ip("8.8.8.8")
    assert "Failed to block" in result

@pytest.mark.asyncio
async def test_tarpit_ip(mock_run_command):
    mock_run_command.return_value = ""

    result = await tarpit_ip("8.8.8.8", 22)
    mock_run_command.assert_called_once_with(
        "sudo", "iptables", "-A", "INPUT", "-p", "tcp", "--dport", "22", "-s", "8.8.8.8", "-j", "DROP"
    )
    assert "Offensive Tarpit deployed" in result
    assert "8.8.8.8" in result
    assert "22" in result

@pytest.mark.asyncio
async def test_generate_abuse_report():
    result = await generate_abuse_report("1.2.3.4", "Attack snippet")
    assert "1.2.3.4" in result
    assert "Attack snippet" in result
    assert "ABUSE REPORT" in result

@pytest.mark.asyncio
@patch("piclaw.tools.network_security.asyncio.create_subprocess_exec")
@patch("piclaw.tools.network_security.asyncio.wait_for", new_callable=AsyncMock)
async def test_run_command_success(mock_wait_for, mock_create_subprocess_exec):
    from unittest.mock import MagicMock
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    # communicate() returns a tuple of (stdout, stderr)
    mock_wait_for.return_value = (b"success output\n", b"")
    mock_create_subprocess_exec.return_value = mock_proc

    result = await _run_command("echo", "hello")
    assert result == "success output"

@pytest.mark.asyncio
@patch("piclaw.tools.network_security.asyncio.create_subprocess_exec")
@patch("piclaw.tools.network_security.asyncio.wait_for", new_callable=AsyncMock)
async def test_run_command_error(mock_wait_for, mock_create_subprocess_exec):
    from unittest.mock import MagicMock
    mock_proc = MagicMock()
    mock_proc.returncode = 1

    # communicate() returns a tuple of (stdout, stderr)
    mock_wait_for.return_value = (b"", b"permission denied\n")
    mock_create_subprocess_exec.return_value = mock_proc

    result = await _run_command("iptables", "-L")
    assert "[ERROR] Command failed: permission denied" in result

@pytest.mark.asyncio
async def test_honey_trap_lifecycle():
    # Test deploying a trap
    res = await deploy_honey_trap(9999, "rickroll")
    assert "SUCCESS" in res
    assert 9999 in _ACTIVE_TRAPS
    assert _ACTIVE_TRAPS[9999]["type"] == "rickroll"

    # Test listing traps
    list_res = await list_honey_traps()
    assert "Active Honey Traps" in list_res
    assert "Port  9999" in list_res
    assert "rickroll" in list_res

    # Test duplicate trap
    dup_res = await deploy_honey_trap(9999, "sinkhole")
    assert "already running" in dup_res

    # Test invalid trap
    inv_res = await deploy_honey_trap(8888, "invalid_trap")
    assert "Invalid trap_type" in inv_res

    # Test stopping the trap
    stop_res = await stop_honey_trap(9999)
    assert "has been disabled" in stop_res
    assert 9999 not in _ACTIVE_TRAPS

    # Test stopping nonexistent trap
    stop_none = await stop_honey_trap(1234)
    assert "No active trap found" in stop_none

@pytest.mark.asyncio
async def test_list_empty_traps():
    res = await list_honey_traps()
    assert "No honey traps are currently active" in res

def test_is_local_ip():
    assert _is_local_ip("127.0.0.1") is True
    assert _is_local_ip("192.168.1.100") is True
    assert _is_local_ip("10.0.0.5") is True
    assert _is_local_ip("172.16.0.1") is True

    assert _is_local_ip("8.8.8.8") is False
    assert _is_local_ip("142.250.190.46") is False

    assert _is_local_ip("invalid_ip") is False

@pytest.mark.asyncio
async def test_local_ip_safeguard_labyrinth():
    reader = AsyncMock()
    writer = MagicMock()
    writer.get_extra_info.return_value = ("192.168.1.50", 12345)
    writer.wait_closed = AsyncMock()

    # Run the handler
    await _handle_labyrinth(reader, writer)

    # It should have instantly closed without writing the endless banner
    writer.write.assert_not_called()
    writer.close.assert_called_once()

@pytest.mark.asyncio
async def test_local_ip_safeguard_rickroll():
    reader = AsyncMock()
    reader.read = AsyncMock(return_value=b"GET / HTTP/1.1\r\n\r\n")
    writer = MagicMock()
    writer.get_extra_info.return_value = ("10.0.0.5", 12345)
    writer.wait_closed = AsyncMock()
    writer.drain = AsyncMock()

    await _handle_rickroll(reader, writer)

    # The response should be a friendly 200 OK, not a 301 Redirect to youtube
    writer.write.assert_called_once()
    output = writer.write.call_args[0][0].decode()
    assert "200 OK" in output
    assert "safe here" in output
    assert "youtube.com" not in output

@pytest.mark.asyncio
async def test_local_ip_safeguard_sinkhole():
    reader = AsyncMock()
    reader.read = AsyncMock(return_value=b"GET / HTTP/1.1\r\n\r\n")
    writer = MagicMock()
    writer.get_extra_info.return_value = ("127.0.0.1", 12345)
    writer.wait_closed = AsyncMock()
    writer.drain = AsyncMock()

    await _handle_sinkhole(reader, writer)

    # The response should be a friendly 200 OK without gzip
    writer.write.assert_called_once()
    output = writer.write.call_args[0][0].decode()
    assert "200 OK" in output
    assert "Content-Encoding: gzip" not in output
    assert "Local LAN detected" in output

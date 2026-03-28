"""Tests for piclaw.tools.network_monitor"""
import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from piclaw.tools.network_monitor import scan_devices, check_new_devices, NetworkDevice

NMAP_OUTPUT = """
Starting Nmap 7.94SVN ( https://nmap.org ) at 2026-03-20 12:00 CET
Nmap scan report for router.local (192.168.1.1)
Host is up (0.0020s latency).
MAC Address: AA:BB:CC:DD:EE:FF (TP-Link)
Nmap scan report for 192.168.1.53
Host is up (0.050s latency).
MAC Address: 11:22:33:44:55:66 (Raspberry Pi Foundation)
Nmap done: 256 IP addresses (2 hosts up) scanned in 2.10 seconds
"""

@pytest.mark.asyncio
async def test_scan_devices_parsing():
    with patch("piclaw.tools.network_monitor._run_nmap", return_value=NMAP_OUTPUT):
        devices = await scan_devices("192.168.1.0/24")
        assert len(devices) == 2
        assert devices[0].ip == "192.168.1.1"
        assert devices[0].hostname == "router.local"
        assert devices[0].mac == "AA:BB:CC:DD:EE:FF"
        assert devices[0].vendor == "TP-Link"

        assert devices[1].ip == "192.168.1.53"
        assert devices[1].hostname == "unknown"
        assert devices[1].mac == "11:22:33:44:55:66"

@pytest.mark.asyncio
async def test_check_new_devices(tmp_path):
    known_file = tmp_path / "known_devices.json"
    with patch("piclaw.tools.network_monitor.KNOWN_DEVICES_FILE", known_file), \
         patch("piclaw.tools.network_monitor._run_nmap", return_value=NMAP_OUTPUT):

        # First run: all are new
        new_devs = await check_new_devices()
        assert len(new_devs) == 2

        # Second run: none are new
        new_devs = await check_new_devices()
        assert len(new_devs) == 0

        # Add a new device to output
        new_output = NMAP_OUTPUT + "\nNmap scan report for 192.168.1.100\nHost is up.\nMAC Address: 00:00:00:00:00:00 (NewDevice)\n"
        with patch("piclaw.tools.network_monitor._run_nmap", return_value=new_output):
            new_devs = await check_new_devices()
            assert len(new_devs) == 1
            assert new_devs[0].ip == "192.168.1.100"

def test_wake_device_mac_address():
    from piclaw.tools.network_monitor import wake_device
    with patch("piclaw.tools.network_monitor.socket.socket") as mock_socket:
        mock_sock_inst = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_inst

        result = wake_device("AA:BB:CC:DD:EE:FF")
        assert "✅ Magic packet sent" in result

        # Verify the broadcast packet was sent
        mock_sock_inst.sendto.assert_called_once()
        args, _ = mock_sock_inst.sendto.call_args
        magic_packet, target_addr = args
        assert target_addr == ("255.255.255.255", 9)
        assert len(magic_packet) == 102
        assert magic_packet.startswith(b"\xff" * 6)

def test_wake_device_hostname_resolution():
    from piclaw.tools.network_monitor import wake_device
    known_devices = {
        "11:22:33:44:55:66": {
            "ip": "192.168.1.53",
            "mac": "11:22:33:44:55:66",
            "hostname": "raspberrypi"
        }
    }

    with patch("piclaw.tools.network_monitor.load_known_devices", return_value=known_devices), \
         patch("piclaw.tools.network_monitor.socket.socket") as mock_socket:

        mock_sock_inst = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_inst

        result = wake_device("raspberrypi")
        assert "✅ Magic packet sent" in result
        mock_sock_inst.sendto.assert_called_once()

def test_wake_device_not_found():
    from piclaw.tools.network_monitor import wake_device
    with patch("piclaw.tools.network_monitor.load_known_devices", return_value={}):
        result = wake_device("unknown-host")
        assert "❌ Could not resolve MAC address" in result

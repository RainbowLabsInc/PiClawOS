import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient

from piclaw.api import app, _cfg
from piclaw.config import PiClawConfig

client = TestClient(app)


@pytest.fixture
def mock_cfg():
    cfg = MagicMock(spec=PiClawConfig)
    cfg.services = MagicMock()
    cfg.services.managed = ["test-service1", "test-service2"]

    with patch("piclaw.api._cfg", new=cfg):
        yield cfg


@pytest.fixture
def auth_header():
    with patch("piclaw.api.require_auth", return_value="token"):
        yield


@pytest.mark.asyncio
async def test_services_endpoint_success(mock_cfg, auth_header):
    # Mock subprocess exec
    mock_proc1 = AsyncMock()
    mock_proc1.communicate.return_value = (b"active\n", b"")
    mock_proc1.returncode = 0

    mock_proc2 = AsyncMock()
    mock_proc2.communicate.return_value = (b"inactive\n", b"")
    mock_proc2.returncode = 0

    with patch(
        "asyncio.create_subprocess_exec", side_effect=[mock_proc1, mock_proc2]
    ) as mock_exec:
        from piclaw.api import services

        result = await services(auth_header)

        assert len(result) == 2
        assert result[0] == {"name": "test-service1", "state": "active", "active": True}
        assert result[1] == {
            "name": "test-service2",
            "state": "inactive",
            "active": False,
        }

        # Verify correct args passed to avoid shell
        mock_exec.assert_any_call(
            "systemctl",
            "is-active",
            "test-service1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )


@pytest.mark.asyncio
async def test_services_endpoint_failure_fallback(mock_cfg, auth_header):
    # Mock subprocess exec failing, like when service doesn't exist
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 3  # systemctl returns 3 for inactive

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        from piclaw.api import services

        result = await services(auth_header)

        assert len(result) == 2
        assert result[0] == {
            "name": "test-service1",
            "state": "inactive",
            "active": False,
        }

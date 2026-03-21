import asyncio
import logging
from unittest.mock import patch, MagicMock

import pytest

from piclaw.daemon import run
from piclaw.config import LOG_DIR


def test_daemon_run_happy_path():
    """Test that `run` sets up logging and starts the asyncio loop correctly."""
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("piclaw.daemon.logging.basicConfig") as mock_basic_config, \
         patch("piclaw.daemon.logging.StreamHandler") as mock_stream_handler, \
         patch("piclaw.daemon.logging.FileHandler") as mock_file_handler, \
         patch("piclaw.daemon.asyncio.run") as mock_asyncio_run, \
         patch("piclaw.daemon._daemon_main") as mock_daemon_main:

        # Setup mocks
        # We need to mock _daemon_main such that it's just a regular function mock
        # rather than an AsyncMock which it automatically becomes because it's an async function.

        mock_stream_inst = MagicMock()
        mock_stream_handler.return_value = mock_stream_inst

        mock_file_inst = MagicMock()
        mock_file_handler.return_value = mock_file_inst

        # Call the function
        run()

        # Assertions
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

        mock_stream_handler.assert_called_once()
        mock_file_handler.assert_called_once_with(str(LOG_DIR / "agent.log"))

        mock_basic_config.assert_called_once_with(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[mock_stream_inst, mock_file_inst],
        )

        mock_daemon_main.assert_called_once()
        mock_asyncio_run.assert_called_once()

        # Verify the argument passed to asyncio.run is what _daemon_main returned
        # Because it's an async function mock, it returns a coroutine.
        args, kwargs = mock_asyncio_run.call_args
        import inspect
        assert inspect.iscoroutine(args[0])
        # Manually close it to avoid the RuntimeWarning in tests
        try:
            args[0].close()
        except Exception:
            pass

def test_daemon_run_mkdir_permission_error():
    """Test that if LOG_DIR.mkdir fails, the exception propagates."""
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Denied")), \
         patch("piclaw.daemon.logging.basicConfig") as mock_basic_config, \
         patch("piclaw.daemon.asyncio.run") as mock_asyncio_run:

        with pytest.raises(PermissionError, match="Denied"):
            run()

        mock_basic_config.assert_not_called()
        mock_asyncio_run.assert_not_called()

def test_daemon_run_asyncio_run_error():
    """Test that if asyncio.run fails, the exception propagates."""
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("piclaw.daemon.logging.basicConfig"), \
         patch("piclaw.daemon.logging.StreamHandler"), \
         patch("piclaw.daemon.logging.FileHandler"), \
         patch("piclaw.daemon.asyncio.run", side_effect=RuntimeError("Loop error")), \
         patch("piclaw.daemon._daemon_main"):

        with pytest.raises(RuntimeError, match="Loop error"):
            run()

        mock_mkdir.assert_called_once()

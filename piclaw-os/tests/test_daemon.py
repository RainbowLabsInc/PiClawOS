import inspect
import logging
from unittest.mock import patch

import pytest

from piclaw.daemon import run


def test_daemon_run_happy_path():
    """`run` konfiguriert das Logging und startet die asyncio-Loop."""
    with patch("piclaw.logging_setup.configure_logging") as mock_configure, \
         patch("piclaw.daemon.asyncio.run") as mock_asyncio_run, \
         patch("piclaw.daemon._daemon_main") as mock_daemon_main:

        run()

        mock_configure.assert_called_once_with(level=logging.INFO)
        mock_daemon_main.assert_called_once()
        mock_asyncio_run.assert_called_once()

        # asyncio.run bekommt die Coroutine aus _daemon_main
        args, _ = mock_asyncio_run.call_args
        assert inspect.iscoroutine(args[0])
        args[0].close()  # RuntimeWarning über nie-awaited Coroutine vermeiden


def test_daemon_run_asyncio_run_error():
    """Fehler aus asyncio.run propagieren nach außen."""
    with patch("piclaw.logging_setup.configure_logging"), \
         patch("piclaw.daemon.asyncio.run", side_effect=RuntimeError("Loop error")), \
         patch("piclaw.daemon._daemon_main"):

        with pytest.raises(RuntimeError, match="Loop error"):
            run()

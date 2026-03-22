"""
Shared pytest fixtures and configuration.

Patches CONFIG_DIR globally so no test ever touches /etc/piclaw.
"""

import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch

# ── Ensure piclaw package is importable ───────────────────────────
# When running from project root: pytest tests/
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session", autouse=True)
def patch_config_dir(tmp_path_factory):
    """
    Replace CONFIG_DIR with a temp dir for the entire test session.
    This prevents tests from reading/writing /etc/piclaw.
    """
    import piclaw.config  # Import explicit to avoid AttributeError

    cfg_dir = tmp_path_factory.mktemp("piclaw_config")
    with patch("piclaw.config.CONFIG_DIR", cfg_dir):
        yield cfg_dir


@pytest.fixture(scope="session", autouse=True)
def mock_gpio():
    """GPIO is only available on real Pi hardware – mock it everywhere."""
    gpio_mock = pytest.importorskip  # noqa
    try:
        import RPi.GPIO  # noqa
    except ImportError:
        # Not on a Pi – patch to prevent ImportError during tool loading
        import types

        fake_gpio = types.ModuleType("RPi")
        fake_gpio.GPIO = types.ModuleType("RPi.GPIO")
        sys.modules.setdefault("RPi", fake_gpio)
        sys.modules.setdefault("RPi.GPIO", fake_gpio.GPIO)
        fake_gpiozero = types.ModuleType("gpiozero")
        sys.modules.setdefault("gpiozero", fake_gpiozero)

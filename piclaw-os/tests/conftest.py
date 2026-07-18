"""
Shared pytest fixtures and configuration.

Patches CONFIG_DIR globally so no test ever touches /etc/piclaw.
"""
import contextlib
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

    Wichtig: Viele Module leiten ihre Store-Pfade ZUR IMPORTZEIT von
    CONFIG_DIR ab (z.B. sa_registry.SA_REGISTRY_FILE); ein Patch nur auf
    piclaw.config.CONFIG_DIR greift dort nicht. Genau so leakte 'SlowAgent'
    (interval:1) aus test_runner_timeout in die Produktiv-Registry auf dem
    Pi und erzeugte 6 Tage Dauerlast. Deshalb hier alle abgeleiteten
    Konstanten mitpatchen.
    """
    import piclaw.config
    import piclaw.agents as agents_pkg
    import piclaw.agents.ipc as agents_ipc
    import piclaw.agents.sa_registry as sa_registry_mod
    import piclaw.agents.watchdog as watchdog_mod
    import piclaw.hardware.sensors as sensors_mod
    import piclaw.ipc as ipc_mod
    import piclaw.llm.registry as llm_registry_mod
    import piclaw.memory.store as memory_store_mod
    import piclaw.soul as soul_mod
    import piclaw.users as users_mod

    cfg_dir = tmp_path_factory.mktemp("piclaw_config")
    ipc_dir = cfg_dir / "ipc"
    targets = [
        (piclaw.config, "CONFIG_DIR", cfg_dir),
        (piclaw.config, "CONFIG_FILE", cfg_dir / "config.toml"),
        (piclaw.config, "SKILLS_DIR", cfg_dir / "skills"),
        (piclaw.config, "LOG_DIR", cfg_dir / "logs"),
        (piclaw.config, "CRASH_DIR", cfg_dir / "crashes"),
        (piclaw.config, "REMINDERS_DB", cfg_dir / "reminders.json"),
        (sa_registry_mod, "SA_REGISTRY_FILE", cfg_dir / "subagents.json"),
        (users_mod, "USERS_FILE", cfg_dir / "users.json"),
        (llm_registry_mod, "REGISTRY_FILE", cfg_dir / "llm_registry.json"),
        (sensors_mod, "SENSOR_FILE", cfg_dir / "sensors.json"),
        (soul_mod, "SOUL_FILE", cfg_dir / "SOUL.md"),
        (memory_store_mod, "MEMORY_ROOT", cfg_dir / "memory"),
        (ipc_mod, "IPC_DIR", ipc_dir),
        (agents_ipc, "IPC_DIR", ipc_dir),
        (agents_ipc, "JOBS_DB", ipc_dir / "jobs.db"),
        (agents_ipc, "WATCHDOG_DB", ipc_dir / "watchdog.db"),
        (agents_pkg, "HEARTBEAT_FILE", ipc_dir / "agent.heartbeat"),
        (watchdog_mod, "WATCHDOG_CONFIG_FILE", cfg_dir / "watchdog.toml"),
        (watchdog_mod, "WATCHDOG_LOG_DIR", cfg_dir / "logs" / "watchdog"),
        (watchdog_mod, "HEARTBEAT_FILE", ipc_dir / "agent.heartbeat"),
        (watchdog_mod, "INSTALLER_LOCK_FILE", ipc_dir / "piclaw_installer.lock"),
    ]
    with contextlib.ExitStack() as stack:
        for mod, attr, value in targets:
            stack.enter_context(patch.object(mod, attr, value))
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

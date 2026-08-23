"""
Regressionstest für den Integritäts-Check des Watchdogs.

Vorfall 23.08.2026: `piclaw-watchdog` lief seit Wochen in einer
Restart-Schleife (systemd-Restart-Zähler 58220, ~21 Tage). Der Dienst
loggte "PiClaw Watchdog started" und starb rund eine Sekunde später mit
exit-code 1 - im journal stand nichts, weil die Unit stdout/stderr nach
/var/log/piclaw/watchdog.log umleitet.

Ursache war eine Zeile im Konstruktor:

    self._perm_denied_warned: set[str] = {}

`{}` ist ein dict, kein set. Sobald der Integritäts-Check auf eine Datei
traf, die der Service-User nicht lesen darf, lief der PermissionError-Handler
in `.add(key)` und warf AttributeError. Ausgerechnet der Code, der
Rechteprobleme zu einer einmaligen Warnung entschärfen sollte, machte sie
damit tödlich - und der Watchdog, der alles andere überwachen soll, war
selbst dauerhaft tot.
"""

import pytest
from unittest.mock import patch


@pytest.fixture
def watchdog(tmp_path):
    from piclaw.agents import watchdog as wd_mod

    with patch.object(wd_mod, "WATCHDOG_LOG_DIR", tmp_path / "logs"), \
         patch.object(wd_mod, "init_watchdog_db", lambda: None), \
         patch.object(wd_mod.Watchdog, "_read_db_trigger", lambda self: None), \
         patch.object(wd_mod.Watchdog, "_load_config", lambda self: {}):
        yield wd_mod.Watchdog()


def test_perm_denied_warned_is_a_set(watchdog):
    """Die Annotation sagt set[str] - `{}` erzeugt aber ein dict."""
    assert isinstance(watchdog._perm_denied_warned, set), (
        "Mit einem dict wirft der PermissionError-Handler AttributeError "
        "und reisst den ganzen Watchdog-Daemon mit."
    )


def test_unreadable_file_does_not_crash_integrity_check(watchdog, tmp_path):
    """Eine nicht lesbare Datei muss eine Warnung sein, kein Absturz."""
    from piclaw.agents import watchdog as wd_mod

    secret = tmp_path / "secret.conf"
    secret.write_text("x")

    def _boom(*a, **kw):
        raise PermissionError(13, "Permission denied")

    with patch.object(wd_mod, "INTEGRITY_PATHS", [secret]), \
         patch.object(type(secret), "read_bytes", _boom):
        alerts = watchdog._check_integrity()

    assert alerts == []
    assert str(secret) in watchdog._perm_denied_warned


def test_permission_warning_is_logged_only_once(watchdog, tmp_path, caplog):
    """Der Handler soll die Warnung entprellen - alle 5 Minuten wäre Spam."""
    from piclaw.agents import watchdog as wd_mod

    secret = tmp_path / "secret.conf"
    secret.write_text("x")

    def _boom(*a, **kw):
        raise PermissionError(13, "Permission denied")

    with patch.object(wd_mod, "INTEGRITY_PATHS", [secret]), \
         patch.object(type(secret), "read_bytes", _boom):
        with caplog.at_level("WARNING", logger="piclaw.agents.watchdog"):
            watchdog._check_integrity()
            watchdog._check_integrity()
            watchdog._check_integrity()

    denied = [r for r in caplog.records if "PERMISSION DENIED" in r.getMessage()]
    assert len(denied) == 1, f"Genau eine Warnung erwartet, war: {len(denied)}"

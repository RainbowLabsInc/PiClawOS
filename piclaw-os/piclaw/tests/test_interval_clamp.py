"""
Minimum-Intervall für interval:-Schedules.

Regression für den 18.07.2026 gefundenen Dauerlast-Bug: der Debug-Sub-Agent
'SlowAgent' (interval:1, Überbleibsel der Hard-Cap-Session vom 12.07.) lief
sekündlich; jeder Run triggerte memory_log → `qmd update` (Node-Prozess,
~1 CPU-Kern) → ~2.5 Load und 67°C über sechs Tage. Der Runner hebt
Intervalle unter MIN_INTERVAL_SEC jetzt auf das Minimum an.
"""

from piclaw.agents.runner import MIN_INTERVAL_SEC, _interval_seconds


def test_second_interval_is_clamped_to_minimum():
    assert _interval_seconds("interval:1", "SlowAgent") == MIN_INTERVAL_SEC


def test_minimum_boundary_passes_unchanged():
    assert _interval_seconds(f"interval:{MIN_INTERVAL_SEC}", "X") == MIN_INTERVAL_SEC


def test_regular_interval_passes_unchanged():
    assert _interval_seconds("interval:3600", "Monitor") == 3600


def test_invalid_interval_returns_none():
    assert _interval_seconds("interval:abc", "X") is None
    assert _interval_seconds("interval:", "X") is None

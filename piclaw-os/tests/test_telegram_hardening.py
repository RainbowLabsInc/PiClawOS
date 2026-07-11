"""
Regressionstests für das Telegram-Poll-Backoff (fix: statt 5s-Dauerhammer
bei DNS-/Netzwerk-Ausfall exponentiell bis 300s).
"""

from piclaw.messaging.telegram import _poll_backoff


def test_backoff_starts_at_five_seconds():
    assert _poll_backoff(1) == 5.0


def test_backoff_doubles():
    assert _poll_backoff(2) == 10.0
    assert _poll_backoff(3) == 20.0
    assert _poll_backoff(4) == 40.0


def test_backoff_caps_at_300s():
    assert _poll_backoff(7) == 300.0
    assert _poll_backoff(50) == 300.0
    # kein Overflow bei absurden Zählerständen
    assert _poll_backoff(10_000) == 300.0


def test_backoff_monotonic():
    values = [_poll_backoff(n) for n in range(1, 20)]
    assert values == sorted(values)


def test_no_errors_no_backoff():
    assert _poll_backoff(0) == 0.0
    assert _poll_backoff(-1) == 0.0

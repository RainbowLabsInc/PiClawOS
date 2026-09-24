"""
Regressionstests für die Cron-Fälligkeitsprüfung des ProactiveRunner
und die Recurrence-Berechnung der Reminder.

Bug 1 (proactive.py): Der Routine-Loop cachte pro Routine EIN croniter-
Objekt und rief darauf minütlich get_prev() auf. croniter bewegt dabei
einen internen Cursor rückwärts – jeder Aufruf lieferte einen älteren
Fälligkeitstermin, delta_s wurde nie < 60, und geplante Routinen haben
nie gefeuert (nur der Boot-Catch-Up lief, weil er frische Objekte baut).

Bug 2 (tools/reminders.py): "weekly"-Recurrence setzte base.weekday()
(Python: 0=Montag) direkt als Cron-dow (0=Sonntag) ein – jeder
wöchentliche Reminder rollte auf den Vortag (Mi-Reminder → Di).
"""

from datetime import datetime, timedelta

from piclaw.proactive import _routine_prev_due
from piclaw.tools.reminders import _next_due


# ── _routine_prev_due: kein Cursor-Drift ──────────────────────────


def test_prev_due_stable_over_repeated_calls():
    """Wiederholte Aufrufe mit demselben `now` liefern denselben Termin."""
    now = datetime(2026, 9, 24, 12, 30, 15)
    results = [_routine_prev_due("0 7 * * *", now) for _ in range(5)]
    assert all(r == datetime(2026, 9, 24, 7, 0) for r in results)


def test_prev_due_fires_within_due_minute():
    """Simuliert den Minuten-Loop: erst in der Fälligkeitsminute wird
    delta_s < 60 – und zwar auch nach vielen vorherigen Prüfungen."""
    due = datetime(2026, 9, 24, 7, 0)
    # 120 Minuten-Ticks vor der Fälligkeit (der alte Cache wanderte hier
    # pro Tick einen Tag zurück). Wie im echten Loop liegt der Tick ein
    # paar Sekunden hinter dem Minutenwechsel (datetime.now()).
    tick = due - timedelta(minutes=120) + timedelta(seconds=5)
    fired = []
    for _ in range(121):
        prev = _routine_prev_due("0 7 * * *", tick)
        delta_s = (tick - prev).total_seconds()
        if 0 <= delta_s < 60:
            fired.append(tick)
        tick += timedelta(minutes=1)
    # … genau der Tick in der Minute 07:00 feuert.
    assert fired == [due + timedelta(seconds=5)]


def test_prev_due_sees_changed_cron_expression():
    """Geänderte Cron-Ausdrücke greifen sofort (kein Cache pro Routine-ID)."""
    now = datetime(2026, 9, 24, 9, 0, 10)
    assert _routine_prev_due("0 7 * * *", now) == datetime(2026, 9, 24, 7, 0)
    assert _routine_prev_due("0 9 * * *", now) == datetime(2026, 9, 24, 9, 0)


# ── Reminder-Recurrence: Wochentag bleibt erhalten ────────────────


def test_weekly_reminder_keeps_weekday():
    # Mittwoch, 23.09.2026 ist ein Mittwoch (weekday()==2)
    base = datetime(2026, 9, 23, 17, 0)
    assert base.weekday() == 2
    nxt = datetime.fromisoformat(_next_due(base.isoformat(), "weekly"))
    assert nxt == base + timedelta(days=7)
    assert nxt.weekday() == base.weekday()


def test_weekly_reminder_sunday():
    # Sonntag ist der Randfall der Modulo-Umrechnung (Python 6 → Cron 0).
    base = datetime(2026, 9, 27, 8, 30)
    assert base.weekday() == 6
    nxt = datetime.fromisoformat(_next_due(base.isoformat(), "weekly"))
    assert nxt == base + timedelta(days=7)


def test_daily_and_monthly_unchanged():
    base = datetime(2026, 9, 23, 17, 0)
    daily = datetime.fromisoformat(_next_due(base.isoformat(), "daily"))
    assert daily == base + timedelta(days=1)
    monthly = datetime.fromisoformat(_next_due(base.isoformat(), "monthly"))
    assert monthly == datetime(2026, 10, 23, 17, 0)

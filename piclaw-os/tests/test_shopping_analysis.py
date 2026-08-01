"""
Preisverfall-Erkennung.

Kernszenario aus der Anforderung: ein Artikel ist tagelang gleich teuer und
wird dann günstiger, ohne als Aktion gekennzeichnet zu sein. Dazu die
Gegenproben, die verhindern, dass die Heuristik zur Spam-Quelle wird.
"""

import time

import pytest

from piclaw.shopping import analysis

DAY = 86_400


def series(prices, end_ts=None, step=DAY):
    """Baut [(ts, preis)] mit einem Messwert pro Tag, ältester zuerst."""
    end_ts = end_ts or int(time.time())
    start = end_ts - (len(prices) - 1) * step
    return [(start + i * step, p) for i, p in enumerate(prices)]


# ── Kernszenario ─────────────────────────────────────────────────────────


def test_preisrutsch_wird_erkannt():
    """1,10 über zwei Wochen, dann 0,90 → Alert."""
    now = int(time.time())
    history = series([1.10] * 14, end_ts=now - DAY)

    verdict = analysis.evaluate(history, price=0.90, now=now)

    assert verdict.is_drop
    assert verdict.baseline == pytest.approx(1.10)
    assert verdict.drop_pct == pytest.approx(0.1818, abs=0.001)
    assert verdict.is_all_time_low
    assert "unter den üblichen" in verdict.reason
    assert "1,10" in verdict.reason  # deutsche Schreibweise, kein Punkt


def test_gleicher_preis_loest_nichts_aus():
    now = int(time.time())
    history = series([1.10] * 14, end_ts=now - DAY)

    verdict = analysis.evaluate(history, price=1.10, now=now)

    assert not verdict.is_drop
    assert verdict.baseline == pytest.approx(1.10)


def test_kleiner_rueckgang_unter_schwelle_loest_nichts_aus():
    """5% Rückgang bei 10% Schwelle: kein Alert."""
    now = int(time.time())
    history = series([1.10] * 14, end_ts=now - DAY)

    verdict = analysis.evaluate(history, price=1.05, now=now)

    assert not verdict.is_drop
    assert verdict.drop_pct == pytest.approx(0.045, abs=0.005)


# ── Mindestdatenlage ─────────────────────────────────────────────────────


def test_zu_wenige_messwerte_ergeben_keinen_alert():
    """Drei Punkte reichen nicht – sonst feuert in Woche 1 alles."""
    now = int(time.time())
    history = series([1.10, 1.10, 1.10], end_ts=now - DAY)

    verdict = analysis.evaluate(history, price=0.50, now=now)

    assert not verdict.is_drop
    assert not verdict.has_baseline
    assert "Messwerten" in verdict.reason


def test_genug_messwerte_aber_zu_kurzer_zeitraum():
    """Sechs Messwerte innerhalb eines Tages sind keine Historie."""
    now = int(time.time())
    history = series([1.10] * 6, end_ts=now - 3600, step=600)

    verdict = analysis.evaluate(history, price=0.50, now=now)

    assert not verdict.is_drop
    assert not verdict.has_baseline
    assert "Tagen" in verdict.reason


def test_leere_historie_ist_kein_fehler():
    verdict = analysis.evaluate([], price=1.00)

    assert not verdict.is_drop
    assert not verdict.has_baseline
    assert verdict.describe() == "Datenaufbau läuft"


# ── Median-Eigenschaften ─────────────────────────────────────────────────


def test_einzelne_aktionswoche_zieht_baseline_nicht_mit():
    """Der Median ignoriert den Ausreißer, der Mittelwert täte es nicht.

    Bei 11 Tagen zu 2,00 und 3 Tagen zu 1,00 liegt der Mittelwert bei ~1,79,
    gegen den wären 1,60 kein Alert. Der Median bleibt bei 2,00.
    """
    now = int(time.time())
    history = series([2.00] * 11 + [1.00, 1.00, 1.00], end_ts=now - DAY)

    verdict = analysis.evaluate(history, price=1.60, now=now)

    assert verdict.baseline == pytest.approx(2.00)
    assert verdict.is_drop


def test_alte_werte_ausserhalb_des_fensters_zaehlen_nicht():
    """Preise jenseits von baseline_days fließen nicht in die Baseline ein."""
    now = int(time.time())
    alt = series([5.00] * 10, end_ts=now - 60 * DAY)
    neu = series([1.00] * 10, end_ts=now - DAY)

    verdict = analysis.evaluate(alt + neu, price=0.95, now=now)

    assert verdict.baseline == pytest.approx(1.00)
    assert verdict.samples == 10
    assert not verdict.is_drop


def test_allzeittief_beruecksichtigt_auch_alte_werte():
    """is_all_time_low schaut über das Baseline-Fenster hinaus."""
    now = int(time.time())
    alt = series([0.50] * 3, end_ts=now - 200 * DAY)
    neu = series([1.00] * 10, end_ts=now - DAY)

    verdict = analysis.evaluate(alt + neu, price=0.80, now=now)

    assert verdict.is_drop
    assert not verdict.is_all_time_low  # 0,50 war mal günstiger


# ── Dedup ────────────────────────────────────────────────────────────────


def test_erster_alert_geht_durch():
    now = int(time.time())
    history = series([1.10] * 14, end_ts=now - DAY)
    verdict = analysis.evaluate(history, price=0.90, now=now)

    assert analysis.should_alert(verdict, None, history, now=now)


def test_gleiches_preisniveau_alarmiert_nicht_erneut():
    """Solange die Aktion läuft, darf nicht täglich dieselbe Meldung kommen.

    Realistische Abfolge: 14 Tage 1,10 – gestern fiel der Preis auf 0,90 und
    wurde gemeldet – heute steht er immer noch auf 0,90.
    """
    now = int(time.time())
    history = series([1.10] * 14 + [0.90], end_ts=now - DAY)
    alert_ts = history[-1][0]
    verdict = analysis.evaluate(history, price=0.90, now=now)
    last = {"price": 0.90, "ts": alert_ts}

    assert verdict.is_drop  # der Rückgang besteht weiterhin …
    assert not analysis.should_alert(verdict, last, history, now=now)  # … wird aber nicht wiederholt


def test_weiterer_rutsch_nach_unten_alarmiert_erneut():
    now = int(time.time())
    history = series([1.10] * 14 + [0.90], end_ts=now - DAY)
    alert_ts = history[-1][0]
    verdict = analysis.evaluate(history, price=0.75, now=now)
    last = {"price": 0.90, "ts": alert_ts}

    assert analysis.should_alert(verdict, last, history, now=now)


def test_nach_rueckkehr_auf_normalpreis_wird_wieder_alarmiert():
    """Abgeschlossener Aktionszyklus → die nächste Aktion ist neu.

    Vor 10 Tagen Alert bei 0,90, danach wieder Normalpreis – jetzt erneut 0,90.
    """
    now = int(time.time())
    alt = series([1.10] * 14 + [0.90], end_ts=now - 10 * DAY)
    alert_ts = alt[-1][0]
    zurueck = series([1.10] * 9, end_ts=now - DAY)
    history = alt + zurueck
    verdict = analysis.evaluate(history, price=0.90, now=now)
    last = {"price": 0.90, "ts": alert_ts}

    assert analysis.should_alert(verdict, last, history, now=now)


def test_kein_drop_kein_alert():
    now = int(time.time())
    history = series([1.10] * 14, end_ts=now - DAY)
    verdict = analysis.evaluate(history, price=1.10, now=now)

    assert not analysis.should_alert(verdict, None, history, now=now)


# ── Darstellung ──────────────────────────────────────────────────────────


def test_describe_bei_drop_nennt_prozent_und_baseline():
    now = int(time.time())
    history = series([2.00] * 14, end_ts=now - DAY)
    verdict = analysis.evaluate(history, price=1.00, now=now)

    text = verdict.describe()
    assert "50%" in text
    assert "2,00" in text
    assert "Allzeittief" in text


@pytest.mark.parametrize(
    "prices, erwartet",
    [
        ([1.0, 1.0, 1.0, 0.5], "down"),
        ([1.0, 1.0, 1.0, 2.0], "up"),
        ([1.0, 1.0, 1.0, 1.0], "flat"),
        ([1.0], "flat"),
        ([], "flat"),
    ],
)
def test_trend(prices, erwartet):
    assert analysis.trend(series(prices)) == erwartet

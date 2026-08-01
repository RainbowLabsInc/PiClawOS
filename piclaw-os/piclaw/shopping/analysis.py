"""
PiClaw OS – Preisverfall-Erkennung

Beantwortet: "Ist der aktuelle Preis auffällig günstig?" – unabhängig davon,
ob der Händler das Produkt als Aktion kennzeichnet. Genau der Fall aus der
Anforderung:

    Mo 1,10 €   Di 1,10 €   Mi 1,10 €   Do 0,90 €  → Alert

Kernentscheidungen:

* **Median statt Mittelwert** als Baseline. Eine einzelne Aktionswoche im
  Fenster darf die Vergleichsbasis nicht nach unten ziehen, sonst erkennt man
  die nächste Aktion nicht mehr.
* **Mindestdatenlage.** Ohne genug Punkte über genug Tage gibt es keinen
  Alert. Sonst feuert in der ersten Woche alles, weil die Baseline aus einem
  einzigen Wert besteht.
* **Ein Preisniveau alarmiert genau einmal.** Erneut nur, wenn es noch tiefer
  geht oder der Preis zwischenzeitlich wieder normal war. Sonst kommt jeden
  Tag dieselbe Meldung, solange die Aktion läuft.
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass

log = logging.getLogger("piclaw.shopping.analysis")

_SECS_PER_DAY = 86_400

# Defaults; werden von der Config überschrieben (ShoppingConfig).
DEFAULT_DROP_PCT = 0.10
DEFAULT_BASELINE_DAYS = 28
DEFAULT_MIN_SAMPLES = 5
DEFAULT_MIN_SPAN_DAYS = 7


@dataclass
class PriceVerdict:
    """Ergebnis der Bewertung eines Preises gegen seine Historie."""

    is_drop: bool = False
    price: float = 0.0
    baseline: float | None = None
    drop_pct: float = 0.0
    is_all_time_low: bool = False
    samples: int = 0
    span_days: float = 0.0
    reason: str = ""

    @property
    def has_baseline(self) -> bool:
        return self.baseline is not None

    def describe(self) -> str:
        """Kurztext für Dashboard und Telegram."""
        if not self.has_baseline:
            return "Datenaufbau läuft"
        if self.is_drop:
            txt = f"−{self.drop_pct * 100:.0f}% gegenüber üblich {self.baseline:.2f} €"
            return txt + " · Allzeittief" if self.is_all_time_low else txt
        return f"üblich {self.baseline:.2f} €"


def evaluate(
    history: list[tuple[int, float]],
    price: float,
    now: int | None = None,
    drop_pct: float = DEFAULT_DROP_PCT,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_span_days: int = DEFAULT_MIN_SPAN_DAYS,
) -> PriceVerdict:
    """Bewertet `price` gegen die bisherige Reihe `history` [(ts, price), …].

    `history` enthält die Punkte VOR dem aktuellen Preis. Ist zu wenig
    Historie da, kommt ein Verdict ohne Baseline zurück – kein Alert, aber
    auch kein Fehler.
    """
    now = int(now if now is not None else time.time())
    cutoff = now - baseline_days * _SECS_PER_DAY
    window = [(ts, p) for ts, p in history if ts >= cutoff and p > 0]

    verdict = PriceVerdict(price=price, samples=len(window))
    if len(window) < min_samples:
        verdict.reason = f"nur {len(window)} von {min_samples} nötigen Messwerten"
        return verdict

    span_days = (max(ts for ts, _ in window) - min(ts for ts, _ in window)) / _SECS_PER_DAY
    verdict.span_days = round(span_days, 1)
    if span_days < min_span_days:
        verdict.reason = (
            f"Historie umfasst nur {span_days:.1f} von {min_span_days} nötigen Tagen"
        )
        return verdict

    baseline = statistics.median(p for _, p in window)
    verdict.baseline = round(baseline, 4)
    if baseline <= 0:
        verdict.reason = "Baseline unbrauchbar"
        return verdict

    verdict.drop_pct = max(0.0, (baseline - price) / baseline)
    verdict.is_all_time_low = price < min(p for _, p in history if p > 0)

    if price <= baseline * (1 - drop_pct):
        verdict.is_drop = True
        verdict.reason = (
            f"{price:.2f} € liegt {verdict.drop_pct * 100:.0f}% unter der "
            f"üblichen {baseline:.2f} €"
        )
    else:
        verdict.reason = f"kein auffälliger Rückgang (üblich {baseline:.2f} €)"
    return verdict


def should_alert(
    verdict: PriceVerdict,
    last_alert: dict | None,
    history: list[tuple[int, float]],
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    now: int | None = None,
) -> bool:
    """Entscheidet, ob aus einem Verdict eine Meldung wird.

    Unterdrückt Wiederholungen desselben Preisniveaus. Erneut gemeldet wird
    nur, wenn der Preis noch tiefer gefallen ist oder seit dem letzten Alert
    zwischenzeitlich wieder über der Baseline lag – dann ist ein Aktionszyklus
    abgeschlossen und der nächste ist eine echte Neuigkeit.
    """
    if not verdict.is_drop:
        return False
    if not last_alert:
        return True

    last_price = float(last_alert.get("price") or 0.0)
    last_ts = int(last_alert.get("ts") or 0)

    # Noch günstiger als beim letzten Mal → in jedem Fall melden.
    if verdict.price < last_price - 1e-9:
        return True

    # Lag der Preis seit dem letzten Alert wieder auf Normalniveau?
    baseline = verdict.baseline or 0.0
    recovered = any(
        ts > last_ts and p >= baseline * 0.99
        for ts, p in history
        if p > 0
    )
    if recovered:
        return True

    log.debug(
        "Alert unterdrückt: %.2f € bereits am %s gemeldet",
        verdict.price, time.strftime("%d.%m.", time.localtime(last_ts)),
    )
    return False


def trend(history: list[tuple[int, float]]) -> str:
    """Grobe Richtung der letzten Messwerte – für ein Badge im Dashboard."""
    prices = [p for _, p in history if p > 0]
    if len(prices) < 2:
        return "flat"
    last, prev = prices[-1], statistics.median(prices[:-1])
    if last < prev * 0.97:
        return "down"
    if last > prev * 1.03:
        return "up"
    return "flat"


__all__ = [
    "PriceVerdict",
    "evaluate",
    "should_alert",
    "trend",
    "DEFAULT_DROP_PCT",
    "DEFAULT_BASELINE_DAYS",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_MIN_SPAN_DAYS",
]

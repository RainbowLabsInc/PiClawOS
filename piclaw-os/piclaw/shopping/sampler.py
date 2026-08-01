"""
PiClaw OS – Täglicher Preis-Sammellauf

Holt für jeden Artikel der Liste die aktuellen Angebote, schreibt pro Produkt
einen Preispunkt und prüft, ob der Preis auffällig gefallen ist.

Wichtig für die Datenqualität:

* Nur **aktive** Angebote werden gesampelt. marktguru liefert auch Angebote,
  die erst nächste Woche starten – die als heutigen Preis zu speichern würde
  die Reihe verfälschen.
* Pro Produkt und Lauf genau **ein** Preispunkt, der günstigste. Dasselbe
  Produkt kommt sonst doppelt (einmal direkt von Lidl, einmal über
  marktguru) und verzerrt den Median.
* Netzwerk zuerst, Schreiben danach – nie einen HTTP-Call innerhalb einer
  Transaktion.

Der Lauf ist bewusst still (`__SILENT__`): er füllt in Stufe 1 nur die
Datenbasis. Das Melden übernimmt später der Push-Monitor über die
alerts-Tabelle.
"""

from __future__ import annotations

import logging
import time

import aiohttp

from piclaw.shopping import analysis, location
from piclaw.shopping.matching import matches_item, normalize_title
from piclaw.shopping.providers import search_all
from piclaw.shopping.store import PricePoint, ShoppingDB, get_db

log = logging.getLogger("piclaw.shopping.sampler")

SILENT = "__SILENT__"


async def run_sample(
    session: aiohttp.ClientSession | None = None,
    cfg=None,
    db: ShoppingDB | None = None,
    now: int | None = None,
) -> dict:
    """Führt den Sammellauf aus und gibt eine Zusammenfassung zurück."""
    if session is None:
        async with aiohttp.ClientSession() as own_session:
            return await run_sample(own_session, cfg=cfg, db=db, now=now)

    db = db or get_db()
    now = int(now if now is not None else time.time())
    sc = location._shopping_cfg(cfg)

    summary = {
        "items": 0, "products": 0, "points": 0, "alerts": 0,
        "skipped": [], "error": "",
    }

    items = [i for i in db.list_items(owner_id=None) if not i.muted]
    if not items:
        summary["error"] = "keine Artikel auf der Liste"
        return summary

    home, surroundings = await location.resolve(session, cfg=cfg, db=db)
    if home is None:
        summary["error"] = "kein Wohnort hinterlegt"
        return summary

    retailer_keys = surroundings.retailer_keys or None
    if not retailer_keys:
        log.info("Keine Ketten im Umkreis erkannt – Angebote werden nicht "
                 "auf erreichbare Märkte gefiltert")

    for item in items:
        term = item.search_term
        if not term:
            continue
        summary["items"] += 1
        try:
            offers = await search_all(
                session, term,
                zip_code=home.zip_code, lat=home.lat, lon=home.lon,
                providers=sc.providers, retailer_keys=retailer_keys,
                active_only=True, limit=30,
            )
        except Exception as exc:
            # search_all fängt Provider-Fehler selbst ab; hier landet nur
            # Unerwartetes. Ein Artikel darf den Lauf nicht abbrechen.
            log.exception("Sammellauf: '%s' fehlgeschlagen: %s", term, exc)
            summary["skipped"].append(term)
            continue

        if not offers:
            log.debug("shopping_sample '%s': keine aktiven Angebote", term)
            continue

        # Pro Produkt den günstigsten Treffer dieses Laufs behalten.
        best: dict[tuple[str, str], tuple[float, str, str, bool]] = {}
        rejected = 0
        for offer in offers:
            if offer.price is None or offer.price <= 0:
                continue
            retailer = offer.retailer_key or offer.retailer.lower()
            title_norm = normalize_title(offer.brand, offer.title)
            if not title_norm:
                continue
            # Thematische Ausreißer draußen halten: die Provider-Suche nach
            # "Butter" liefert auch "Buttermilch". Ohne diesen Filter bekäme
            # jeder Ausreißer eine eigene Preisreihe und würde als
            # günstigster Preis des Artikels angezeigt.
            if not matches_item(title_norm, term):
                rejected += 1
                continue
            key = (retailer, title_norm)
            current = best.get(key)
            if current is None or offer.price < current[0]:
                best[key] = (offer.price, offer.title, offer.unit,
                             bool(offer.old_price))

        points: list[PricePoint] = []
        for (retailer, title_norm), (price, title, unit, is_promo) in best.items():
            product_id = db.upsert_product(
                item.id, retailer, title, title_norm, unit, ts=now
            )
            if not product_id:
                continue
            summary["products"] += 1

            history = db.history(product_id)
            verdict = analysis.evaluate(
                history, price, now=now,
                drop_pct=sc.price_drop_pct,
                baseline_days=sc.baseline_days,
                min_samples=sc.min_samples,
                min_span_days=sc.min_span_days,
            )
            if analysis.should_alert(verdict, db.last_alert(product_id), history, now=now):
                db.add_alert(product_id, price, verdict.baseline or 0.0,
                             verdict.drop_pct, ts=now)
                summary["alerts"] += 1
                log.info("Preisrutsch: '%s' bei %s – %.2f € (%s)",
                         title, retailer, price, verdict.reason)

            points.append(PricePoint(product_id, price, now, is_promo))

        summary["points"] += db.record_prices(points)
        # Eine Diagnosezeile pro Artikel – so lässt sich ein leeres Ergebnis
        # später als "kein Angebot" von "Provider tot" unterscheiden.
        log.debug("shopping_sample '%s': %d Angebote, %d verworfen, "
                  "%d Produkte, %d Preispunkte",
                  term, len(offers), rejected, len(best), len(points))

    db.purge_old(now=now)
    log.info("Sammellauf: %d Artikel, %d Produkte, %d Preispunkte, %d Alerts",
             summary["items"], summary["products"], summary["points"],
             summary["alerts"])
    return summary


async def sample_silent() -> str:
    """direct_tool-Einstieg des Sammel-Sub-Agenten.

    Gibt immer den stillen Token zurück: in Stufe 1 wird nichts gepusht, der
    Lauf füllt nur die Datenbasis für Sparkline und spätere Alerts.
    """
    try:
        summary = await run_sample()
    except Exception as exc:
        log.exception("Sammellauf fehlgeschlagen: %s", exc)
        return SILENT
    if summary.get("error"):
        log.info("Sammellauf übersprungen: %s", summary["error"])
    return SILENT


__all__ = ["run_sample", "sample_silent", "SILENT"]

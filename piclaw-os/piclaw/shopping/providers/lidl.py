"""
Angebotsquelle Lidl – direkter Händler-Endpoint, unabhängig von marktguru.

Anders gebaut als marktguru: es gibt keine Suche. Man holt alle Angebote einer
Filiale (~70) und filtert lokal. Deshalb wird die Filialliste pro Prozess
gecacht – sonst zöge ein Sammellauf über 20 Artikel 20-mal denselben
Volldownload.

Öffentliche Lidl-Plus-Routen, kein Account nötig (Stand 08/2026):
  https://stores.lidlplus.com/api/v1/autocomplete/DE?input=…&latitude=…&longitude=…
  https://offers.lidlplus.com/app/api/v4/DE/<storeKey>/offers

Preisstruktur: priceBox.largePartNumeric ist der Aktionspreis,
smallPartNumeric der durchgestrichene Normalpreis (nur wenn strikethrough).
"""

from __future__ import annotations

import logging
import time

import aiohttp

from piclaw.shopping.matching import normalize_retailer, normalize_title
from piclaw.shopping.providers.base import Offer

log = logging.getLogger("piclaw.shopping.providers.lidl")

NAME = "lidl"
RETAILER = "Lidl"
APP_VERSION = "17.0.5"
STORES_BASE = "https://stores.lidlplus.com/api"
OFFERS_BASE = "https://offers.lidlplus.com/app/api"

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-DE",
    "User-Agent": f"LidlPlus/{APP_VERSION} Android okhttp/4.12.0",
    "X-Client-Version": APP_VERSION,
    "X-Client-Platform": "android",
}

# Angebote wechseln wöchentlich; 30 Minuten Cache reichen völlig und machen
# einen Sammellauf über viele Artikel zu genau einem Download.
_OFFERS_TTL = 1800
_STORE_TTL = 86_400

_offers_cache: dict[str, tuple[float, list[Offer]]] = {}
_store_cache: dict[str, tuple[float, dict]] = {}


def reset_cache() -> None:
    """Leert Filial- und Angebots-Cache (Tests)."""
    _offers_cache.clear()
    _store_cache.clear()


def _num(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def parse_offer(raw: dict) -> Offer | None:
    """Wandelt ein Lidl-Angebot in ein Offer. None ohne konkreten Preis.

    Rabattaktionen ohne Stückpreis ("auf alle Baby, Kids & Toys Artikel")
    haben keinen largePartNumeric und fallen hier raus – für eine
    Preisbeobachtung sind sie wertlos.
    """
    box = raw.get("priceBox") or {}
    price = _num(box.get("largePartNumeric"))
    if price is None:
        return None

    old_price = _num(box.get("smallPartNumeric")) if box.get("strikethrough") else None

    brand = (raw.get("brand") or "").strip()
    title = (raw.get("title") or "").strip() or brand or "Angebot"

    # packaging enthält mehrzeilig Menge, Normalpreis und Grundpreis.
    packaging = (raw.get("packaging") or "").strip()
    unit_parts = [line.strip() for line in packaging.splitlines() if line.strip()]
    ppu = (raw.get("pricePerUnit") or "").strip()
    if ppu and ppu not in unit_parts:
        unit_parts.append(ppu)

    return Offer(
        title=title,
        retailer=RETAILER,
        retailer_key=normalize_retailer(RETAILER),
        price=price,
        old_price=old_price,
        unit=" · ".join(unit_parts),
        brand=brand,
        valid_from=str(raw.get("startValidityDateUTC") or raw.get("startValidityDate") or ""),
        valid_to=str(raw.get("endValidityDateUTC") or raw.get("endValidityDate") or ""),
        source=NAME,
        image=str(raw.get("imageUrl") or ""),
    )


async def _nearest_store(
    session: aiohttp.ClientSession, lat: float, lon: float, zip_code: str = ""
) -> dict | None:
    """Nächstgelegene Lidl-Filiale zu Koordinaten."""
    cache_key = f"{lat:.3f},{lon:.3f}"
    cached = _store_cache.get(cache_key)
    if cached and time.time() - cached[0] < _STORE_TTL:
        return cached[1]

    params = {
        "input": zip_code or "Lidl",
        "language": "de",
        "latitude": f"{lat}",
        "longitude": f"{lon}",
    }
    try:
        async with session.get(
            f"{STORES_BASE}/v1/autocomplete/DE", params=params, headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                log.warning("lidl: Filialsuche HTTP %s", resp.status)
                return None
            data = await resp.json(content_type=None)
    except Exception as exc:
        log.warning("lidl: Filialsuche fehlgeschlagen: %s", exc)
        return None

    stores = data if isinstance(data, list) else (data or {}).get("stores") or []
    if not stores:
        log.debug("lidl: keine Filiale für %s gefunden", cache_key)
        return None
    # Die API sortiert nach distance; defensiv trotzdem selbst sortieren.
    stores.sort(key=lambda s: s.get("distance") or float("inf"))
    store = stores[0]
    _store_cache[cache_key] = (time.time(), store)
    log.debug("lidl: Filiale %s (%s) in %.1f km",
              store.get("storeKey"), store.get("name"),
              (store.get("distance") or 0) / 1000)
    return store


async def _store_offers(
    session: aiohttp.ClientSession, store_key: str
) -> list[Offer]:
    cached = _offers_cache.get(store_key)
    if cached and time.time() - cached[0] < _OFFERS_TTL:
        return cached[1]

    try:
        async with session.get(
            f"{OFFERS_BASE}/v4/DE/{store_key}/offers", headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            if resp.status != 200:
                log.warning("lidl: Angebote HTTP %s", resp.status)
                return []
            data = await resp.json(content_type=None)
    except Exception as exc:
        log.warning("lidl: Angebote fehlgeschlagen: %s", exc)
        return []

    raw_offers = (data or {}).get("offers") or []
    # Ein kaputter Datensatz darf den Rest nicht mitreißen – die API ist
    # inoffiziell und ändert Feldformen ohne Ankündigung.
    offers: list[Offer] = []
    for raw in raw_offers:
        try:
            offer = parse_offer(raw)
        except Exception as exc:
            log.debug("lidl: Angebot nicht parsebar (%s)", exc)
            continue
        if offer:
            offers.append(offer)
    _offers_cache[store_key] = (time.time(), offers)
    log.debug("lidl: %d Angebote für Filiale %s", len(offers), store_key)
    return offers


class LidlProvider:
    """Holt alle Angebote der nächsten Filiale und filtert lokal."""

    name = NAME

    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
        zip_code: str = "",
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 24,
    ) -> list[Offer]:
        query = (query or "").strip()
        if not query:
            return []
        if lat is None or lon is None:
            # Ohne Koordinaten keine Filiale – marktguru deckt Lidl mit ab.
            log.debug("lidl: ohne Koordinaten übersprungen")
            return []

        store = await _nearest_store(session, lat, lon, zip_code)
        if not store or not store.get("storeKey"):
            return []

        offers = await _store_offers(session, str(store["storeKey"]))
        if not offers:
            return []

        needle = normalize_title(query)
        tokens = [t for t in needle.split() if t]
        if not tokens:
            return offers[:limit]

        hits = [
            offer for offer in offers
            if any(tok in normalize_title(offer.brand, offer.title, offer.unit)
                   for tok in tokens)
        ]
        log.debug("lidl: '%s' → %d von %d Angeboten", query, len(hits), len(offers))
        return hits[:limit]


__all__ = ["LidlProvider", "NAME", "RETAILER", "parse_offer", "reset_cache"]

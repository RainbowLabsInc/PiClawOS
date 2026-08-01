"""
Provider-Registry – fragt alle Quellen parallel und führt sie zusammen.

Grundregel: eine tote Quelle darf die Suche nicht kippen. Deshalb
asyncio.gather mit return_exceptions=True; Ausfälle werden geloggt und
übersprungen, das Ergebnis der anderen zählt.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from piclaw.shopping.providers.base import Offer
from piclaw.shopping.providers.lidl import LidlProvider
from piclaw.shopping.providers.marktguru import MarktguruProvider

log = logging.getLogger("piclaw.shopping.providers")

_PROVIDERS = {
    MarktguruProvider.name: MarktguruProvider,
    LidlProvider.name: LidlProvider,
}

PROVIDER_NAMES = tuple(_PROVIDERS)
DEFAULT_PROVIDERS = PROVIDER_NAMES


def available_providers(names=None) -> list:
    """Instanziiert die gewünschten Provider. Unbekannte Namen werden geloggt."""
    selected = list(names) if names else list(DEFAULT_PROVIDERS)
    out = []
    for name in selected:
        cls = _PROVIDERS.get(name)
        if cls is None:
            log.warning("Unbekannter Angebots-Provider '%s' – übersprungen", name)
            continue
        out.append(cls())
    return out


def dedupe(offers: list[Offer]) -> list[Offer]:
    """Entfernt Doppelte über Händler + Titel + Preis.

    Lidl-Angebote kommen sowohl direkt als auch über marktguru. Die direkte
    Quelle gewinnt, weil sie Grundpreis und Normalpreis mitliefert.
    """
    best: dict[tuple, Offer] = {}
    for offer in offers:
        key = (
            offer.retailer_key or offer.retailer.lower(),
            offer.title.strip().lower(),
            round(offer.price or 0.0, 2),
        )
        current = best.get(key)
        if current is None:
            best[key] = offer
            continue
        # Direkter Händler-Endpoint schlägt Aggregator.
        if current.source == "marktguru" and offer.source != "marktguru":
            best[key] = offer
    return list(best.values())


async def search_all(
    session: aiohttp.ClientSession,
    query: str,
    zip_code: str = "",
    lat: float | None = None,
    lon: float | None = None,
    providers=None,
    limit: int = 24,
    retailer_keys: set[str] | None = None,
    active_only: bool = False,
) -> list[Offer]:
    """Fragt alle Provider parallel und liefert eine sortierte Trefferliste.

    retailer_keys filtert auf Ketten, die es im Umkreis wirklich gibt.
    Angebote ohne erkannten Händler bleiben drin – lieber ein Treffer mit
    unklarer Kette als ein verlorener.
    """
    instances = available_providers(providers)
    if not instances:
        return []

    results = await asyncio.gather(
        *(p.search(session, query, zip_code=zip_code, lat=lat, lon=lon, limit=limit)
          for p in instances),
        return_exceptions=True,
    )

    offers: list[Offer] = []
    for provider, result in zip(instances, results):
        if isinstance(result, BaseException):
            # Provider sollen selbst abfangen; wenn doch etwas durchkommt,
            # ist das ein Bug im Provider – laut loggen, aber nicht abbrechen.
            log.error("Provider '%s' hat geworfen: %s", provider.name, result)
            continue
        offers.extend(result)

    offers = dedupe(offers)

    if active_only:
        offers = [o for o in offers if o.is_active()]
    if retailer_keys:
        offers = [
            o for o in offers
            if not o.retailer_key or o.retailer_key in retailer_keys
        ]

    offers.sort(key=lambda o: (o.price if o.price is not None else float("inf")))
    return offers[:limit]


__all__ = [
    "PROVIDER_NAMES",
    "DEFAULT_PROVIDERS",
    "available_providers",
    "search_all",
    "dedupe",
]

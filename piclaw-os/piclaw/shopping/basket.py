"""
PiClaw OS – Warenkorb-Vergleich

Beantwortet die Frage, die eine Liste einzelner Bestpreise offen lässt:
**In welchem einzelnen Laden ist der ganze Einkauf am günstigsten?**

Es nützt wenig zu wissen, dass Butter bei Lidl und Kaffee bei REWE am
billigsten ist, wenn man dafür zwei Fahrten braucht. Deshalb werden drei
Zahlen nebeneinandergestellt:

* **je Laden** die Summe der dort günstigsten Treffer, plus wie viele
  Artikel er überhaupt führt,
* das **Optimum**, wenn man jeden Artikel dort kauft, wo er am billigsten
  ist (über mehrere Läden verteilt),
* die **Ersparnis**, die dieser Mehraufwand bringt – oft ist sie so klein,
  dass sich die zweite Fahrt nicht lohnt.

Vergleichbarkeit: Läden mit unterschiedlicher Abdeckung sind nicht direkt
vergleichbar. Ein Laden mit 3 von 5 Artikeln ist nicht „billiger" als einer
mit 5 von 5. Deshalb wird primär nach Abdeckung sortiert und die fehlenden
Artikel werden benannt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

from piclaw.shopping.matching import matches_item, normalize_title, retailer_label
from piclaw.shopping.providers import Offer, search_all

log = logging.getLogger("piclaw.shopping.basket")


@dataclass
class Treffer:
    """Der günstigste Fund eines Artikels bei einem Händler."""

    item_id: int
    item_name: str
    price: float
    title: str
    unit_price: float | None = None
    unit_price_text: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "price": self.price,
            "title": self.title,
            "unit_price": self.unit_price,
            "unit_price_text": self.unit_price_text,
        }


@dataclass
class StoreBasket:
    """Der Warenkorb, wie er bei einem Händler aussähe."""

    retailer_key: str
    retailer: str
    treffer: list[Treffer] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    distance_km: float | None = None
    address: str = ""

    @property
    def total(self) -> float:
        return round(sum(t.price for t in self.treffer), 2)

    @property
    def covered(self) -> int:
        return len(self.treffer)

    def to_dict(self) -> dict:
        return {
            "retailer_key": self.retailer_key,
            "retailer": self.retailer,
            "total": self.total,
            "covered": self.covered,
            "missing": self.missing,
            "distance_km": self.distance_km,
            "address": self.address,
            "items": [t.to_dict() for t in self.treffer],
        }


@dataclass
class BasketResult:
    stores: list[StoreBasket] = field(default_factory=list)
    item_count: int = 0
    # Günstigster Preis je Artikel, egal wo – über mehrere Läden verteilt.
    optimum: list[Treffer] = field(default_factory=list)
    optimum_stores: int = 0
    ohne_angebot: list[str] = field(default_factory=list)
    error: str = ""
    # Gesetzt, wenn die Ladenliste leer blieb (Overpass gerade nicht
    # erreichbar). Dann fehlen Entfernungen und der Ketten-Filter – das soll
    # sichtbar sein und nicht wie ein Fehler des Vergleichs wirken.
    hinweis: str = ""

    @property
    def optimum_total(self) -> float:
        return round(sum(t.price for t in self.optimum), 2)

    @property
    def comparable(self) -> int:
        """Artikel, die überhaupt irgendwo im Angebot sind.

        Das ist der ehrliche Nenner für die Abdeckung: ein Laden, der alles
        führt was es gibt, soll nicht als "3 von 4" dastehen, nur weil ein
        Artikel nirgends im Angebot ist.
        """
        return len(self.optimum)

    @property
    def best_single(self) -> StoreBasket | None:
        """Bester Laden für einen Einkauf: erst Abdeckung, dann Preis."""
        if not self.stores:
            return None
        return max(self.stores, key=lambda s: (s.covered, -s.total))

    @property
    def savings(self) -> float:
        """Was der Mehrfach-Einkauf gegenüber dem besten Einzelladen bringt.

        Nur aussagekräftig, wenn der beste Einzelladen alles führt – sonst
        vergleicht man unterschiedliche Warenkörbe.
        """
        einzeln = self.best_single
        if einzeln is None or einzeln.covered < len(self.optimum):
            return 0.0
        return round(einzeln.total - self.optimum_total, 2)

    def to_dict(self) -> dict:
        einzeln = self.best_single
        return {
            "item_count": self.item_count,
            "comparable": self.comparable,
            "stores": [s.to_dict() for s in self.stores],
            "optimum_total": self.optimum_total,
            "optimum_stores": self.optimum_stores,
            "optimum_items": [t.to_dict() for t in self.optimum],
            "best_single": einzeln.to_dict() if einzeln else None,
            "savings": self.savings,
            "ohne_angebot": self.ohne_angebot,
            "error": self.error,
            "hinweis": self.hinweis,
        }


def _als_treffer(item, offer: Offer) -> Treffer:
    return Treffer(
        item_id=item.id,
        item_name=item.name,
        price=float(offer.price or 0.0),
        title=offer.title,
        unit_price=offer.unit_price,
        unit_price_text=offer.unit_price_text,
    )


async def compare(
    session: aiohttp.ClientSession,
    items: list,
    home,
    surroundings,
    cfg=None,
    limit_per_item: int = 30,
) -> BasketResult:
    """Vergleicht den Warenkorb über alle Händler im Umkreis.

    Sucht live, damit das Ergebnis zu dem passt, was `shopping_offers`
    anzeigt – der tägliche Sammellauf wäre bis zu 24 Stunden alt.
    """
    from piclaw.shopping import location

    sc = location._shopping_cfg(cfg)
    ergebnis = BasketResult(item_count=len(items))
    if not items:
        ergebnis.error = "keine Artikel auf der Liste"
        return ergebnis

    retailer_keys = surroundings.retailer_keys or None
    if not retailer_keys:
        ergebnis.hinweis = (
            "Märkte im Umkreis konnten nicht ermittelt werden – ohne "
            "Entfernungen, und es können Ketten dabei sein, die es hier "
            "nicht gibt."
        )
        log.info("Warenkorb ohne Ladenliste – Entfernungen fehlen")
    # retailer_key -> item_id -> bester Treffer
    je_haendler: dict[str, dict[int, Treffer]] = {}
    bestes_je_artikel: dict[int, tuple[str, Treffer]] = {}

    for item in items:
        term = item.search_term
        if not term:
            continue
        try:
            offers = await search_all(
                session, term, zip_code=home.zip_code,
                lat=home.lat, lon=home.lon, providers=sc.providers,
                retailer_keys=retailer_keys, active_only=True,
                limit=limit_per_item,
            )
        except Exception as exc:
            log.exception("Warenkorb: '%s' fehlgeschlagen: %s", term, exc)
            continue

        if item.strict_matching:
            offers = [
                o for o in offers
                if matches_item(normalize_title(o.brand, o.title), term)
            ]
        if item.max_price:
            offers = [o for o in offers
                      if o.price is not None and o.price <= item.max_price]
        if not offers:
            ergebnis.ohne_angebot.append(item.name)
            continue

        for offer in offers:
            if offer.price is None or offer.price <= 0:
                continue
            key = offer.retailer_key
            if not key:
                # Ohne erkannte Kette lässt sich kein Warenkorb zuordnen –
                # der Treffer zählt aber fürs Optimum.
                key = ""
            else:
                bisher = je_haendler.setdefault(key, {}).get(item.id)
                if bisher is None or offer.price < bisher.price:
                    je_haendler[key][item.id] = _als_treffer(item, offer)

            aktuell = bestes_je_artikel.get(item.id)
            if aktuell is None or offer.price < aktuell[1].price:
                bestes_je_artikel[item.id] = (
                    key or offer.retailer, _als_treffer(item, offer)
                )

    if not bestes_je_artikel:
        ergebnis.error = "keine Angebote gefunden"
        return ergebnis

    gefundene_ids = set(bestes_je_artikel)
    namen = {i.id: i.name for i in items}

    for key, treffer_map in je_haendler.items():
        shop = surroundings.nearest(key)
        ergebnis.stores.append(StoreBasket(
            retailer_key=key,
            retailer=retailer_label(key, key),
            treffer=sorted(treffer_map.values(), key=lambda t: t.item_name),
            missing=sorted(namen[i] for i in gefundene_ids - set(treffer_map)),
            distance_km=shop["distance_km"] if shop else None,
            address=shop.get("street", "") if shop else "",
        ))

    # Abdeckung schlägt Preis: 3 von 5 Artikeln sind kein günstigerer Einkauf.
    ergebnis.stores.sort(key=lambda s: (-s.covered, s.total))
    ergebnis.optimum = [t for _k, t in bestes_je_artikel.values()]
    ergebnis.optimum_stores = len({k for k, _t in bestes_je_artikel.values()})
    return ergebnis


__all__ = ["BasketResult", "StoreBasket", "Treffer", "compare"]

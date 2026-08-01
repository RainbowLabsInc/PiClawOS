"""
Gemeinsames Datenmodell der Angebotsquellen.

Die Quellen sind unterschiedlich gebaut: marktguru ist suchgetrieben (Query
rein, Treffer raus), Lidl liefert alle Angebote einer Filiale und wird lokal
gefiltert. Beide liefern hier dieselbe Offer-Liste zurück, damit Sampler,
Tools und Dashboard nur ein Format kennen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import aiohttp


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@dataclass
class Offer:
    """Ein Angebot eines Händlers."""

    title: str = ""
    retailer: str = ""          # Anzeigename, z.B. "REWE Center"
    retailer_key: str = ""      # kanonisch, z.B. "rewe"
    price: float | None = None
    old_price: float | None = None
    unit: str = ""              # Mengen-/Grundpreisangabe als Text
    brand: str = ""
    valid_from: str = ""
    valid_to: str = ""
    source: str = ""            # Provider-Name
    url: str = ""
    image: str = ""

    def is_active(self, now: datetime | None = None) -> bool:
        """True, wenn das Angebot jetzt gilt.

        Ohne Datumsangabe gilt es als aktiv – lieber ein Angebot zu viel als
        eines zu wenig. Wichtig ist der umgekehrte Fall: marktguru liefert
        auch Angebote, die erst nächste Woche starten; die dürfen weder als
        aktueller Preis gemeldet noch in die Preisreihe geschrieben werden.
        """
        now = now or datetime.now(UTC)
        start = _parse_ts(self.valid_from)
        end = _parse_ts(self.valid_to)
        if start and now < start:
            return False
        if end and now > end:
            return False
        return True

    @property
    def savings_pct(self) -> float:
        if not (self.price and self.old_price) or self.old_price <= 0:
            return 0.0
        return max(0.0, (self.old_price - self.price) / self.old_price)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "retailer": self.retailer,
            "retailer_key": self.retailer_key,
            "price": self.price,
            "old_price": self.old_price,
            "unit": self.unit,
            "brand": self.brand,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "source": self.source,
            "url": self.url,
            "image": self.image,
            "active": self.is_active(),
        }


class Provider(Protocol):
    """Schnittstelle einer Angebotsquelle.

    Implementierungen dürfen NICHT werfen. Eine tote Quelle gibt eine leere
    Liste zurück und loggt – der Rest der Suche muss weiterlaufen.
    """

    name: str

    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
        zip_code: str = "",
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 24,
    ) -> list[Offer]:
        ...


__all__ = ["Offer", "Provider"]

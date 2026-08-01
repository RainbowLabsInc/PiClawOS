"""
Angebotsquelle marktguru.de – Aggregator über ~10 Ketten.

Inoffizielle API. Die Zugangsschlüssel stehen in einem JSON-Block auf der
Startseite und werden zur Laufzeit geholt, nicht im Repo abgelegt:

    <script type="application/json">
      {"config":{"apiHostAddress":"api.marktguru.de","apiKey":"…","clientKey":"…"}}

Der Cache folgt dem Muster von _ups_token in tools/parcel_tracking.py: Modul-
Dict mit Ablaufzeit, bei 401 wird verworfen und einmal neu geholt. Ist die
Extraktion kaputt, liefert der Provider eine leere Liste und loggt – wie bei
fehlenden UPS-Credentials, nie eine Exception.

Bekannte Grenze: Komposita finden nichts. "spülmaschinentabs" → 0 Treffer,
"geschirrspül" → 7. Deshalb der Testen-Button im Dashboard.
"""

from __future__ import annotations

import json
import logging
import re
import time

import aiohttp

from piclaw.shopping.matching import normalize_retailer, retailer_label
from piclaw.shopping.providers.base import Offer
from piclaw.shopping.units import (
    refine_size,
    size_from_quantity,
    size_from_reference,
)

log = logging.getLogger("piclaw.shopping.providers.marktguru")

NAME = "marktguru"
HOMEPAGE = "https://www.marktguru.de"
DEFAULT_HOST = "api.marktguru.de"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

# Schlüssel gelten lange; eine Stunde Cache hält die Startseiten-Abrufe klein
# und fängt eine Rotation trotzdem am selben Tag ab.
_CREDENTIAL_TTL = 3600
_credentials: dict = {"api_key": "", "client_key": "", "host": "", "expires_at": 0.0}

_JSON_BLOCK_RE = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.S
)


def reset_credentials() -> None:
    """Verwirft den Schlüssel-Cache (Tests, 401-Behandlung)."""
    _credentials.update({"api_key": "", "client_key": "", "host": "", "expires_at": 0.0})


async def _fetch_credentials(session: aiohttp.ClientSession) -> dict | None:
    """Holt apiKey/clientKey aus dem Config-Block der Startseite."""
    try:
        async with session.get(
            HOMEPAGE, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                log.warning("marktguru: Startseite HTTP %s", resp.status)
                return None
            html = await resp.text()
    except Exception as exc:
        log.warning("marktguru: Startseite nicht erreichbar: %s", exc)
        return None

    for blob in _JSON_BLOCK_RE.findall(html):
        try:
            data = json.loads(blob)
        except (ValueError, TypeError):
            continue
        cfg = data.get("config") if isinstance(data, dict) else None
        if isinstance(cfg, dict) and cfg.get("apiKey") and cfg.get("clientKey"):
            return {
                "api_key": str(cfg["apiKey"]),
                "client_key": str(cfg["clientKey"]),
                "host": str(cfg.get("apiHostAddress") or DEFAULT_HOST),
            }
    log.warning("marktguru: kein Config-Block mit Schlüsseln gefunden – "
                "Seitenstruktur hat sich vermutlich geändert")
    return None


async def _get_credentials(session: aiohttp.ClientSession) -> dict | None:
    if _credentials["api_key"] and time.time() < _credentials["expires_at"]:
        return _credentials
    fresh = await _fetch_credentials(session)
    if not fresh:
        return None
    _credentials.update(fresh)
    _credentials["expires_at"] = time.time() + _CREDENTIAL_TTL
    log.debug("marktguru: Schlüssel geholt (Host %s)", fresh["host"])
    return _credentials


def _price(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _first_dict(value) -> dict:
    """Erstes dict einer Liste, sonst leeres dict.

    Defensiv, weil die Feldformen wechseln: validityDates und advertisers sind
    Listen, images dagegen ein dict. Ein blindes value[0] warf hier KeyError.
    """
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                return entry
    elif isinstance(value, dict):
        return value
    return {}


def parse_offer(raw: dict) -> Offer | None:
    """Wandelt einen marktguru-Treffer in ein Offer. None wenn ohne Preis."""
    if not isinstance(raw, dict):
        return None
    price = _price(raw.get("price"))
    if price is None:
        return None

    brand = ((raw.get("brand") or {}).get("name") or "").strip()
    product = ((raw.get("product") or {}).get("name") or "").strip()
    description = (raw.get("description") or "").strip()
    # Der eigentliche Produktname entsteht erst aus Marke + Produkt;
    # description ist die Mengenangabe ("Gekühlt. Je 250 g").
    title = " ".join(p for p in (brand, product) if p) or description or "Angebot"

    retailer = str(_first_dict(raw.get("advertisers")).get("name") or "").strip()

    validity = _first_dict(raw.get("validityDates"))
    valid_from = str(validity.get("from") or "")
    valid_to = str(validity.get("to") or "")

    # images enthält nur Metadaten (count, aspectRatio), keine URL – die
    # müsste aus mediaHostAddress und Offer-ID gebaut werden. Für Liste und
    # Preisreihe belanglos, deshalb bewusst leer.
    image = ""

    unit_parts = []
    if description:
        unit_parts.append(description)
    ref = _price(raw.get("referencePrice"))
    unit_info = raw.get("unit") or {}
    short_name = str(unit_info.get("shortName") or "")
    if ref and short_name:
        unit_parts.append(f"{ref} €/{short_name}")

    # marktguru liefert den Grundpreis bei praktisch jedem Angebot mit; daraus
    # folgt die Packungsgröße direkt (1,79 € bei 7,16 €/kg ⇒ 250 g).
    unit_size, unit_label = size_from_reference(price, ref, short_name)
    text_size, text_label = size_from_quantity(description)
    if unit_size is None:
        unit_size, unit_label = text_size, text_label
    elif text_label == unit_label:
        # Beide Zahlen sind gerundet; die Textangabe ist die exaktere, wenn
        # sie zur abgeleiteten passt (400,4 g → 400 g).
        unit_size = refine_size(unit_size, text_size)

    return Offer(
        title=title,
        retailer=retailer,
        retailer_key=normalize_retailer(retailer),
        price=price,
        old_price=_price(raw.get("oldPrice")),
        unit=" · ".join(unit_parts),
        unit_size=unit_size,
        unit_label=unit_label,
        brand=brand,
        valid_from=valid_from,
        valid_to=valid_to,
        source=NAME,
        url=str(raw.get("externalUrl") or ""),
        image=image,
    )


def _parse_all(results: list) -> list[Offer]:
    """Parst alle Treffer; ein kaputter Datensatz kippt nicht den Rest.

    Die API ist inoffiziell, Feldformen ändern sich ohne Ankündigung. Genau so
    warf ein images-dict hier einen KeyError und riss die ganze Suche mit.
    """
    offers: list[Offer] = []
    broken = 0
    for raw in results:
        try:
            offer = parse_offer(raw)
        except Exception as exc:
            broken += 1
            log.debug("marktguru: Treffer nicht parsebar (%s)", exc)
            continue
        if offer:
            offers.append(offer)
    if broken:
        log.warning("marktguru: %d von %d Treffern nicht parsebar – "
                    "Antwortformat prüfen", broken, len(results))
    return offers


class MarktguruProvider:
    """Suchgetriebene Quelle: Query rein, Treffer aller Ketten raus."""

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
        if not zip_code:
            log.debug("marktguru: ohne PLZ keine Suche möglich")
            return []

        for attempt in (1, 2):
            creds = await _get_credentials(session)
            if not creds:
                return []
            status, payload = await self._request(session, creds, query, zip_code, limit)
            if status == 401 and attempt == 1:
                log.info("marktguru: 401 – Schlüssel verworfen, hole neuen")
                reset_credentials()
                continue
            if status != 200 or payload is None:
                if status != 401:
                    log.warning("marktguru: Suche HTTP %s", status)
                return []
            results = payload.get("results") or []
            offers = _parse_all(results)
            log.debug("marktguru: '%s' → %d Angebote (von %s Treffern)",
                      query, len(offers), payload.get("totalResults"))
            return offers
        return []

    async def _request(
        self, session: aiohttp.ClientSession, creds: dict,
        query: str, zip_code: str, limit: int,
    ) -> tuple[int, dict | None]:
        url = f"https://{creds['host']}/api/v1/offers/search"
        headers = {
            **HEADERS,
            "x-apikey": creds["api_key"],
            "x-clientkey": creds["client_key"],
        }
        params = {
            "as": "web",
            "limit": str(max(1, min(limit, 50))),
            "offset": "0",
            "q": query,
            "zipCode": zip_code,
        }
        try:
            async with session.get(
                url, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return resp.status, None
                return 200, await resp.json(content_type=None)
        except Exception as exc:
            log.warning("marktguru: Suche fehlgeschlagen: %s", exc)
            return 0, None


__all__ = ["MarktguruProvider", "NAME", "parse_offer", "reset_credentials",
           "retailer_label"]

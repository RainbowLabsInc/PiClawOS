"""
PiClaw OS – Geo-Helfer (OpenStreetMap)

Geocoding via Nominatim und POI-Umkreissuche via Overpass. Ursprünglich lagen
die Geocoding-Funktionen in tools/marketplace.py (Troostwijk-Umkreissuche);
sie stehen jetzt hier, damit auch die Einkaufsliste sie nutzen kann.
marketplace.py behält dünne private Aliase.

Nutzung:
  point = await address_to_coords(session, "Musterweg", "12a", "20095", "Hamburg")
  shops = await find_shops(session, point.lat, point.lon, radius_km=10)

Beide Dienste sind Gemeinschaftsdienste mit Nutzungsregeln. Alle Aufrufe laufen
deshalb durch ein Rate-Gate (siehe _throttle) – nicht entfernen.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field

import aiohttp

log = logging.getLogger("piclaw.tools.geo")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nominatim verlangt einen aussagekräftigen User-Agent (Usage Policy).
USER_AGENT = "PiClaw/1.0 (contact@piclaw.de)"

# Mindestabstand zwischen Aufrufen desselben Dienstes, in Sekunden.
# Nominatim erlaubt 1 req/s, Overpass ist teurer – bewusst großzügiger.
_MIN_INTERVAL = {"nominatim": 1.1, "overpass": 2.0}

# Läden, die für eine Einkaufsliste relevant sind. Reihenfolge egal, wird als
# Regex-Alternative in die Overpass-Query gesetzt.
#
# Aufgenommen wird nur, wofür es auch eine Angebotsquelle gibt – sonst
# entstehen Filialen ohne Preise. `furniture` und `electronics` fehlen
# deshalb bewusst: 2 km um den Hamburger Rathausmarkt liefern sie 43
# Einzelhändler und Möbelboutiquen ohne Prospekt, die gegen MAX_SHOPS
# drücken und echte Märkte verdrängen würden.
DEFAULT_SHOP_TYPES = (
    # Lebensmittel und Drogerie
    "supermarket",
    "convenience",
    "chemist",
    "beverages",
    "butcher",
    "bakery",
    "greengrocer",
    # Baumarkt (OBI, toom, HORNBACH, BAUHAUS, Hagebau, HELLWEG)
    "doityourself",
    "hardware",
    "trade",
    # Tierbedarf und Garten (Fressnapf, DAS FUTTERHAUS, Dehner, Pflanzen-Kölle)
    "pet",
    "garden_centre",
    "agrarian",
    # Non-Food-Discounter (Action, Woolworth, TEDi, Thomas Philipps)
    "variety_store",
)

# Reine Speicher-Obergrenze für find_shops, kein fachlicher Filter.
#
# Die inhaltliche Reduktion macht piclaw/shopping/location.py, weil nur dort
# die Marken bekannt sind. Ein hartes distanzsortiertes Limit an dieser Stelle
# wäre falsch: 5 km um den Hamburger Rathausmarkt liefern 130 Bäckereien, die
# einen weiter entfernten Baumarkt verdrängen würden – obwohl der die einzige
# Filiale seiner Kette im Umkreis ist.
MAX_SHOPS = 2000

# Genauigkeitsklassen von Nominatim, die eine echte Hausadresse bedeuten.
# Alles andere (postcode, road, suburb, city) ist ein Zentroid – als
# Umkreis-Mittelpunkt in Großstädten und Verbandsgemeinden unbrauchbar.
#
# Achtung: addresstype allein reicht NICHT. "Rathausmarkt 1, Hamburg" kommt als
# addresstype='office' zurück, obwohl die Hausnummer sauber getroffen wurde –
# Nominatim benennt das Objekt, nicht die Genauigkeit. Verlässlich ist, ob
# address.house_number im Ergebnis steht; diese Liste ist nur der Zusatzpfad
# für Fälle ohne addressdetails.
EXACT_PRECISIONS = frozenset({"building", "house", "house_number", "address"})

_GEOCODE_CACHE: dict[str, tuple[float, float] | None] = {}
_rate_lock: dict[str, asyncio.Lock] = {}
_last_call: dict[str, float] = {}


@dataclass
class GeoPoint:
    """Ergebnis einer Geocoding-Anfrage inkl. Aussage über die Genauigkeit."""

    lat: float
    lon: float
    precision: str = ""
    display_name: str = ""
    postcode: str = ""
    house_number: str = ""

    @property
    def is_exact(self) -> bool:
        """True nur bei echter Hausadresse, nicht bei Straßen-/PLZ-Zentroid."""
        return bool(self.house_number) or self.precision in EXACT_PRECISIONS

    @property
    def quality(self) -> str:
        """Kurzform für Nutzertexte."""
        if self.is_exact:
            return "Hausnummer"
        if self.precision in ("road", "street"):
            return "nur Straße"
        if self.precision in ("postcode", "city", "town", "village", "suburb"):
            return "nur Ort/PLZ"
        return self.precision or "unbekannt"


@dataclass
class Shop:
    """Ein Laden aus OpenStreetMap."""

    osm_id: str
    name: str
    brand: str
    shop_type: str
    lat: float
    lon: float
    distance_km: float = 0.0
    street: str = ""
    housenumber: str = ""
    city: str = ""
    tags: dict = field(default_factory=dict, repr=False)

    @property
    def label(self) -> str:
        """Anzeigename: Marke bevorzugt, sonst Name."""
        return self.brand or self.name or self.shop_type

    @property
    def address(self) -> str:
        parts = " ".join(p for p in (self.street, self.housenumber) if p)
        return ", ".join(p for p in (parts, self.city) if p)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinienentfernung in km zwischen zwei Koordinatenpaaren (Haversine)."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _throttle(service: str) -> None:
    """Serialisiert Aufrufe und hält den Mindestabstand ein.

    Ohne das feuert eine Schleife über 30 Städte 30 Nominatim-Requests in
    Millisekunden – genau das, was die Usage Policy untersagt.
    """
    lock = _rate_lock.get(service)
    if lock is None:
        lock = _rate_lock[service] = asyncio.Lock()
    min_gap = _MIN_INTERVAL.get(service, 1.0)
    async with lock:
        wait = min_gap - (time.monotonic() - _last_call.get(service, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call[service] = time.monotonic()


async def nominatim_query(
    session: aiohttp.ClientSession, params: dict
) -> tuple[float, float] | None:
    """Ruft Nominatim ab und gibt (lat, lon) zurück oder None bei Fehler."""
    result = await nominatim_lookup(session, params)
    return (result.lat, result.lon) if result else None


async def nominatim_lookup(
    session: aiohttp.ClientSession, params: dict
) -> GeoPoint | None:
    """Wie nominatim_query, gibt aber den vollen GeoPoint inkl. Genauigkeit."""
    await _throttle("nominatim")
    try:
        async with session.get(
            NOMINATIM_URL,
            params={**params, "format": "json", "limit": "1", "addressdetails": "1"},
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                log.debug("Nominatim HTTP %s", resp.status)
                return None
            data = await resp.json(content_type=None)
    except Exception as exc:
        log.debug("Nominatim Fehler: %s", exc)
        return None

    if not data:
        return None
    hit = data[0]
    try:
        lat, lon = float(hit["lat"]), float(hit["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    address = hit.get("address") or {}
    # addresstype benennt das Objekt (z.B. 'office'), nicht die Genauigkeit –
    # die harte Aussage liefert address.house_number.
    precision = hit.get("addresstype") or hit.get("type") or hit.get("class") or ""
    return GeoPoint(
        lat=lat,
        lon=lon,
        precision=str(precision),
        display_name=str(hit.get("display_name") or ""),
        postcode=str(address.get("postcode") or ""),
        house_number=str(address.get("house_number") or ""),
    )


async def plz_to_coords(
    session: aiohttp.ClientSession, plz: str, country: str
) -> tuple[float, float] | None:
    """Geocodiert eine PLZ → (lat, lon). Ergebnis wird prozessweit gecacht."""
    key = f"plz:{country}:{plz}"
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    result = await nominatim_query(session, {"postalcode": plz, "country": country})
    _GEOCODE_CACHE[key] = result
    return result


async def city_to_coords(
    session: aiohttp.ClientSession, city: str, country_code: str
) -> tuple[float, float] | None:
    """Geocodiert einen Stadtnamen → (lat, lon). Ergebnis wird prozessweit gecacht."""
    key = f"city:{country_code.lower()}:{city.lower()}"
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    result = await nominatim_query(session, {"city": city, "country": country_code.lower()})
    _GEOCODE_CACHE[key] = result
    return result


async def address_to_coords(
    session: aiohttp.ClientSession,
    street: str = "",
    house_number: str = "",
    postcode: str = "",
    city: str = "",
    country: str = "de",
) -> GeoPoint | None:
    """Löst eine Hausadresse zu Koordinaten auf.

    Kaskade: strukturierte Suche → freeform → strukturiert ohne Hausnummer.
    Strukturiert zuerst, weil das bei deutschen Adressen deutlich treffsicherer
    ist als ein zusammengebauter q-String.

    Rückgabe enthält immer die Genauigkeitsklasse. Der Aufrufer MUSS
    `is_exact` prüfen – ein stiller Rückfall auf den PLZ-Zentroid macht jede
    Umkreissuche wertlos.
    """
    street = (street or "").strip()
    house_number = (house_number or "").strip()
    postcode = (postcode or "").strip()
    city = (city or "").strip()
    country = (country or "de").strip().lower()

    if not (street or postcode or city):
        return None

    # 1) strukturiert mit Hausnummer
    attempts: list[dict] = []
    if street:
        line = f"{house_number} {street}".strip()
        attempts.append(
            _drop_empty({"street": line, "postalcode": postcode,
                         "city": city, "country": country})
        )
    # 2) freeform
    freeform = ", ".join(p for p in (
        f"{street} {house_number}".strip(),
        f"{postcode} {city}".strip(),
    ) if p)
    if freeform:
        attempts.append({"q": freeform, "countrycodes": country})
    # 3) strukturiert ohne Hausnummer
    if street and house_number:
        attempts.append(
            _drop_empty({"street": street, "postalcode": postcode,
                         "city": city, "country": country})
        )
    # 4) nur PLZ/Ort – bewusst zuletzt, liefert einen Zentroid
    if postcode or city:
        attempts.append(
            _drop_empty({"postalcode": postcode, "city": city, "country": country})
        )

    best: GeoPoint | None = None
    for params in attempts:
        point = await nominatim_lookup(session, params)
        if point is None:
            continue
        if point.is_exact:
            return point
        # Ungenaues Ergebnis merken, aber weitersuchen – vielleicht trifft
        # ein späterer Versuch die Hausnummer doch.
        if best is None:
            best = point
    if best is not None:
        log.debug("Adresse nur ungenau aufgelöst (precision=%s)", best.precision)
    return best


def _drop_empty(params: dict) -> dict:
    return {k: v for k, v in params.items() if v}


async def overpass_query(session: aiohttp.ClientSession, ql: str) -> list[dict]:
    """Führt eine Overpass-QL-Query aus und gibt die Elemente zurück.

    Fehler (Timeout, 429, 504) sind bei einem Gemeinschaftsdienst normal und
    werden zu einer leeren Liste – der Aufrufer arbeitet dann mit dem Cache.
    """
    await _throttle("overpass")
    try:
        async with session.post(
            OVERPASS_URL,
            data={"data": ql},
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                log.warning("Overpass HTTP %s", resp.status)
                return []
            data = await resp.json(content_type=None)
    except Exception as exc:
        log.warning("Overpass Fehler: %s", exc)
        return []
    elements = data.get("elements") if isinstance(data, dict) else None
    return elements or []


def build_shops_query(
    lat: float, lon: float, radius_km: float, shop_types=DEFAULT_SHOP_TYPES
) -> str:
    """Baut die Overpass-QL für Läden im Umkreis.

    `nwr` statt `node`, weil größere Märkte als Way oder Relation gemappt sind;
    `out center` liefert für die einen Mittelpunkt.
    """
    radius_m = max(1, int(round(radius_km * 1000)))
    alternatives = "|".join(shop_types)
    return (
        "[out:json][timeout:25];\n"
        f'nwr["shop"~"^({alternatives})$"](around:{radius_m},{lat:.6f},{lon:.6f});\n'
        "out center tags;"
    )


def parse_shop_element(element: dict, origin_lat: float, origin_lon: float) -> Shop | None:
    """Wandelt ein Overpass-Element in einen Shop um. None wenn unbrauchbar."""
    tags = element.get("tags") or {}
    # Node hat lat/lon direkt, Way/Relation nur über 'center'.
    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None or lon is None:
        center = element.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    name = str(tags.get("name") or "")
    brand = str(tags.get("brand") or tags.get("operator") or "")
    if not (name or brand):
        return None  # namenloser Laden hilft niemandem

    return Shop(
        osm_id=f"{element.get('type', 'node')}/{element.get('id', '')}",
        name=name,
        brand=brand,
        shop_type=str(tags.get("shop") or ""),
        lat=lat,
        lon=lon,
        distance_km=haversine_km(origin_lat, origin_lon, lat, lon),
        street=str(tags.get("addr:street") or ""),
        housenumber=str(tags.get("addr:housenumber") or ""),
        city=str(tags.get("addr:city") or ""),
        tags=tags,
    )


async def find_shops(
    session: aiohttp.ClientSession,
    lat: float,
    lon: float,
    radius_km: float = 10.0,
    shop_types=DEFAULT_SHOP_TYPES,
    max_results: int = MAX_SHOPS,
) -> list[Shop]:
    """Findet Läden im Umkreis, sortiert nach Luftlinie (nächste zuerst).

    In Innenstädten liefert Overpass sehr viele Treffer (2 km um den Hamburger
    Rathausmarkt: 205). Deshalb wird nach dem Sortieren gekappt – die
    nächstgelegenen bleiben, und die sind für eine Einkaufsliste die
    relevanten.
    """
    ql = build_shops_query(lat, lon, radius_km, shop_types)
    elements = await overpass_query(session, ql)
    shops = [
        shop
        for shop in (parse_shop_element(e, lat, lon) for e in elements)
        if shop is not None
    ]
    shops.sort(key=lambda s: s.distance_km)
    if len(shops) > max_results:
        log.info(
            "Overpass: %d Läden gefunden, auf die %d nächsten gekappt",
            len(shops), max_results,
        )
        shops = shops[:max_results]
    else:
        log.info("Overpass: %d Läden im Umkreis von %.1f km", len(shops), radius_km)
    return shops


__all__ = [
    "GeoPoint",
    "Shop",
    "DEFAULT_SHOP_TYPES",
    "EXACT_PRECISIONS",
    "haversine_km",
    "nominatim_query",
    "nominatim_lookup",
    "plz_to_coords",
    "city_to_coords",
    "address_to_coords",
    "overpass_query",
    "build_shops_query",
    "parse_shop_element",
    "find_shops",
]

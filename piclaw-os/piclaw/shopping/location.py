"""
PiClaw OS – Heimatadresse und Läden im Umkreis

Beantwortet zwei Fragen für die Einkaufsliste:
  1. Wo wohne ich genau? (Adresse → Koordinaten, persistent gecacht)
  2. Welche Ketten kann ich von dort aus erreichen? (Overpass, 30 Tage gecacht)

Die Genauigkeit wird immer mitgeliefert und nie stillschweigend verschluckt:
ein PLZ-Zentroid als Umkreis-Mittelpunkt macht die Distanzen wertlos, und das
muss der Nutzer sehen statt es an unplausiblen Kilometerangaben zu erraten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

from piclaw.shopping.matching import normalize_retailer, retailer_label
from piclaw.shopping.store import ShoppingDB, address_hash, get_db
from piclaw.tools import geo

log = logging.getLogger("piclaw.shopping.location")


@dataclass
class Home:
    """Aufgelöster Wohnort."""

    lat: float
    lon: float
    precision: str = ""
    zip_code: str = ""
    source: str = ""      # "config" | "address" | "cache" | "pi-location"
    addr_hash: str = ""

    @property
    def is_exact(self) -> bool:
        return self.precision == "exact" or self.precision in geo.EXACT_PRECISIONS

    @property
    def warning(self) -> str:
        """Hinweistext, wenn die Auflösung ungenau ist. Leer wenn alles gut."""
        if self.is_exact or self.source in ("config", "pi-location"):
            return ""
        if self.precision in ("road", "street"):
            return ("Adresse nur auf Straßenebene aufgelöst – Entfernungen sind "
                    "ungefähr. Hausnummer prüfen.")
        if self.precision in ("postcode", "city", "town", "village", "suburb"):
            return ("Nur PLZ/Ort aufgelöst – der Umkreis liegt um den Ortsmittelpunkt, "
                    "nicht um deine Haustür. Straße und Hausnummer ergänzen.")
        return ""


@dataclass
class Surroundings:
    """Läden im Umkreis plus die daraus abgeleiteten Ketten."""

    shops: list[dict] = field(default_factory=list)
    retailer_keys: set[str] = field(default_factory=set)
    from_cache: bool = False
    # Tatsächlich verwendeter Radius. Wird mitgeführt, damit die Anzeige nicht
    # aus einer zweiten Quelle liest und dann etwas anderes behauptet als
    # gesucht wurde.
    radius_km: float = 0.0

    def nearest(self, retailer_key: str) -> dict | None:
        """Nächste Filiale einer Kette (die Liste ist nach Distanz sortiert)."""
        for shop in self.shops:
            if shop.get("retailer_key") == retailer_key:
                return shop
        return None


def _shopping_cfg(cfg=None):
    """Holt die [shopping]-Sektion, notfalls mit Defaults."""
    if cfg is not None and getattr(cfg, "shopping", None) is not None:
        return cfg.shopping
    try:
        from piclaw.config import ShoppingConfig, load
        loaded = load()
        return getattr(loaded, "shopping", None) or ShoppingConfig()
    except Exception as exc:
        from piclaw.config import ShoppingConfig
        log.debug("Config nicht ladbar (%s) – Shopping-Defaults", exc)
        return ShoppingConfig()


def _user_override(section: str, key: str, fallback):
    """Per-User-Override, falls ein zweiter Account woanders wohnt."""
    try:
        from piclaw.users import get_setting_for_current
        value = get_setting_for_current(section, key, fallback)
        return value if value not in (None, "") else fallback
    except Exception:
        return fallback


def address_parts(cfg=None) -> tuple[str, str, str, str, str]:
    """Adresse aus Config, mit Per-User-Override."""
    sc = _shopping_cfg(cfg)
    return (
        _user_override("shopping", "home_street", sc.home_street),
        _user_override("shopping", "home_house_number", sc.home_house_number),
        _user_override("shopping", "home_zip", sc.home_zip),
        _user_override("shopping", "home_city", sc.home_city),
        _user_override("shopping", "home_country", sc.home_country) or "de",
    )


async def resolve_home(
    session: aiohttp.ClientSession,
    cfg=None,
    db: ShoppingDB | None = None,
    force: bool = False,
) -> Home | None:
    """Ermittelt den Wohnort.

    Reihenfolge:
      1. home_latitude/home_longitude aus der Config (Notnagel, hat Vorrang)
      2. Persistenter Cache zur aktuellen Adresse
      3. Adressauflösung über Nominatim
      4. cfg.location vom Setup-Wizard (Koordinaten ohne PLZ)

    None nur, wenn gar nichts konfiguriert ist.
    """
    sc = _shopping_cfg(cfg)
    db = db or get_db()
    street, house_number, zip_code, city, country = address_parts(cfg)
    ahash = address_hash(street, house_number, zip_code, city, country)

    # 1) explizite Koordinaten
    if sc.home_latitude is not None and sc.home_longitude is not None:
        return Home(
            lat=float(sc.home_latitude), lon=float(sc.home_longitude),
            precision="exact", zip_code=zip_code, source="config", addr_hash=ahash,
        )

    # 2) Cache
    if not force and (street or zip_code or city):
        cached = db.get_home(ahash)
        if cached:
            return Home(
                lat=float(cached["lat"]), lon=float(cached["lon"]),
                precision=str(cached["precision"] or ""),
                zip_code=str(cached["zip"] or zip_code),
                source="cache", addr_hash=ahash,
            )

    # 3) Adressauflösung
    if street or zip_code or city:
        point = await geo.address_to_coords(
            session, street, house_number, zip_code, city, country
        )
        if point:
            home = Home(
                lat=point.lat, lon=point.lon, precision=point.precision,
                zip_code=point.postcode or zip_code, source="address", addr_hash=ahash,
            )
            db.save_home(ahash, home.lat, home.lon, point.precision, home.zip_code)
            # Bewusst OHNE Adresse im Log – das Repo ist public und Logs
            # landen in Support-Ausschnitten.
            log.info("Heimatadresse aufgelöst (precision=%s, exakt=%s)",
                     point.precision, point.is_exact)
            return home
        log.warning("Heimatadresse konnte nicht aufgelöst werden")

    # 4) Wizard-Koordinaten
    location = getattr(cfg, "location", None) if cfg is not None else None
    if location is None:
        try:
            from piclaw.config import load
            location = load().location
        except Exception:
            location = None
    if location and location.latitude is not None and location.longitude is not None:
        return Home(
            lat=float(location.latitude), lon=float(location.longitude),
            precision="exact", zip_code=zip_code, source="pi-location", addr_hash=ahash,
        )

    return None


async def resolve_surroundings(
    session: aiohttp.ClientSession,
    home: Home,
    cfg=None,
    db: ShoppingDB | None = None,
    force: bool = False,
) -> Surroundings:
    """Läden im Umkreis – aus dem Cache oder frisch von Overpass."""
    sc = _shopping_cfg(cfg)
    db = db or get_db()
    radius = float(_user_override("shopping", "radius_km", sc.radius_km) or 10.0)
    radius_key = int(round(radius))

    if not force:
        cached = db.get_stores(home.addr_hash, radius_key, sc.store_cache_days)
        if cached is not None:
            return Surroundings(
                shops=cached,
                retailer_keys={s["retailer_key"] for s in cached if s.get("retailer_key")},
                from_cache=True,
                radius_km=radius,
            )

    shops = await geo.find_shops(session, home.lat, home.lon, radius_km=radius)
    if not shops:
        # Overpass ist ein Gemeinschaftsdienst und antwortet gelegentlich mit
        # 504. Dann lieber einen abgelaufenen Cache als gar nichts.
        stale = db.get_stores(home.addr_hash, radius_key, max_age_days=3650)
        if stale:
            log.warning("Overpass lieferte nichts – nutze veralteten Ladencache")
            return Surroundings(
                shops=stale,
                retailer_keys={s["retailer_key"] for s in stale if s.get("retailer_key")},
                from_cache=True,
                radius_km=radius,
            )
        return Surroundings(radius_km=radius)

    serialised = []
    unknown: set[str] = set()
    for shop in shops:
        key = normalize_retailer(shop.brand) or normalize_retailer(shop.name)
        if not key:
            unknown.add(shop.label)
        serialised.append({
            "osm_id": shop.osm_id,
            "name": shop.name,
            "brand": shop.brand,
            "retailer_key": key,
            "retailer": retailer_label(key, shop.label) if key else shop.label,
            "shop_type": shop.shop_type,
            "distance_km": round(shop.distance_km, 2),
            "street": shop.street,
            "housenumber": shop.housenumber,
            "city": shop.city,
            "lat": shop.lat,
            "lon": shop.lon,
        })

    if unknown:
        # Nicht still verwerfen: so wächst _BRAND_ALIASES mit der Realität.
        log.info("Unbekannte Ladenmarken im Umkreis (%d): %s",
                 len(unknown), ", ".join(sorted(unknown)[:15]))

    db.save_stores(home.addr_hash, radius_key, serialised)
    return Surroundings(
        shops=serialised,
        retailer_keys={s["retailer_key"] for s in serialised if s["retailer_key"]},
        from_cache=False,
        radius_km=radius,
    )


async def resolve(
    session: aiohttp.ClientSession,
    cfg=None,
    db: ShoppingDB | None = None,
    force: bool = False,
) -> tuple[Home | None, Surroundings]:
    """Bequemer Einstieg: Wohnort und Umgebung in einem Rutsch."""
    home = await resolve_home(session, cfg=cfg, db=db, force=force)
    if home is None:
        return None, Surroundings()
    return home, await resolve_surroundings(session, home, cfg=cfg, db=db, force=force)


NOT_CONFIGURED = (
    "📍 Kein Wohnort hinterlegt.\n"
    "Setz ihn mit `shopping_home` (Straße, Hausnummer, PLZ, Ort) – nur mit der "
    "Hausadresse stimmen die Entfernungen zu den Märkten."
)


__all__ = [
    "Home",
    "Surroundings",
    "resolve",
    "resolve_home",
    "resolve_surroundings",
    "address_parts",
    "NOT_CONFIGURED",
]

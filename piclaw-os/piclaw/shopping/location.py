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

import asyncio
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


_ADDRESS_KEYS = (
    "home_street", "home_house_number", "home_zip", "home_city", "home_country",
)


def _toml_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def write_home_address(
    street: str = "", house_number: str = "", zip_code: str = "",
    city: str = "", country: str = "de", radius_km: float | None = None,
) -> None:
    """Schreibt die Adresse in die [shopping]-Sektion der config.toml.

    Bewusst NICHT über config.save(): das schreibt die ganze Datei neu, und
    config.load() injiziert vorher die entschlüsselten Werte aus secrets.enc
    in das Objekt. Auf einer Installation mit `@enc:`-Platzhaltern in der
    config.toml würden diese Platzhalter dadurch durch Klartext-Secrets
    ersetzt. Hier wird deshalb nur die eine Sektion angefasst; alle übrigen
    Zeilen der Datei bleiben Byte für Byte erhalten.

    Vorhandene weitere Keys in [shopping] (radius_km, providers, Schwellen)
    überleben ebenfalls – es werden nur die Adresszeilen ersetzt.
    """
    from piclaw.config import CONFIG_FILE
    from piclaw.fileutils import atomic_write_text, with_file_lock

    neu: dict[str, str] = {
        "home_street": street.strip(),
        "home_house_number": house_number.strip(),
        "home_zip": zip_code.strip(),
        "home_city": city.strip(),
        "home_country": (country or "de").strip().lower(),
    }
    # Explizite Koordinaten würden die neue Adresse aushebeln – rauswerfen.
    entfernen = {"home_latitude", "home_longitude"}
    if radius_km is not None:
        neu["radius_km"] = radius_km

    def _rendern(key: str, value) -> str:
        if isinstance(value, (int, float)):
            return f"{key} = {value}"
        return f'{key} = "{_toml_escape(value)}"'

    def _schreiben() -> None:
        text = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""
        zeilen = text.splitlines()

        out: list[str] = []
        in_shopping = False
        gesehen = False
        geschrieben = False

        for zeile in zeilen:
            stripped = zeile.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_shopping and not geschrieben:
                    out.extend(_rendern(k, v) for k, v in neu.items())
                    geschrieben = True
                in_shopping = stripped == "[shopping]"
                gesehen = gesehen or in_shopping
                out.append(zeile)
                continue
            if in_shopping:
                key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
                if key in neu or key in entfernen:
                    continue  # wird ersetzt bzw. verworfen
                if not geschrieben and stripped and not stripped.startswith("#"):
                    out.extend(_rendern(k, v) for k, v in neu.items())
                    geschrieben = True
            out.append(zeile)

        if in_shopping and not geschrieben:
            out.extend(_rendern(k, v) for k, v in neu.items())
        elif not gesehen:
            if out and out[-1].strip():
                out.append("")
            out.append("[shopping]")
            out.extend(_rendern(k, v) for k, v in neu.items())

        atomic_write_text(CONFIG_FILE, "\n".join(out) + "\n")

    try:
        with with_file_lock(CONFIG_FILE):
            _schreiben()
    except TimeoutError as exc:
        log.error("config.toml gesperrt: %s", exc)
        raise
    # Bewusst ohne die Adresse im Log – das Repo ist öffentlich und Logzeilen
    # landen in Support-Ausschnitten.
    log.info("Heimatadresse in config.toml aktualisiert")


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
            # Nominatim benennt in addresstype das Objekt, nicht die
            # Genauigkeit: "Rathausmarkt 1" kommt als 'office' zurueck, obwohl
            # die Hausnummer traf. Die harte Aussage steckt in
            # GeoPoint.is_exact – hier auf 'exact' normalisieren, sonst ginge
            # sie beim Speichern verloren und die UI meldete faelschlich eine
            # ungenaue Adresse. Bei ungenauen Treffern bleibt die Rohklasse
            # erhalten, weil sie dort die nuetzliche Information ist
            # ('road' vs. 'postcode').
            precision = "exact" if point.is_exact else point.precision
            home = Home(
                lat=point.lat, lon=point.lon, precision=precision,
                zip_code=point.postcode or zip_code, source="address", addr_hash=ahash,
            )
            db.save_home(ahash, home.lat, home.lon, precision, home.zip_code)
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


# Wie viele Filialen je erkannter Kette gespeichert werden. Gebraucht wird
# eigentlich nur die nächste; ein paar mehr schaden nicht und machen die
# Liste im Dashboard brauchbar.
_PRO_KETTE = 3
# Budget für Läden ohne erkannte Kette (Hofläden, Bäckereien, Kioske).
_OHNE_KETTE = 60


def _reduce(shops: list) -> list:
    """Dampft die Ladenliste auf das fachlich Nötige ein.

    Ohne das entscheidet in einer Innenstadt die schiere Zahl der Bäckereien
    darüber, ob ein Baumarkt am Rand des Radius noch in die Liste passt –
    und damit, ob dessen Angebote überhaupt angezeigt werden. Deshalb wird
    **pro Kette** gekappt statt global nach Entfernung.

    Die Liste kommt bereits nach Distanz sortiert an; die Reihenfolge bleibt
    erhalten.
    """
    pro_kette: dict[str, int] = {}
    ohne_kette = 0
    behalten = []
    for shop in shops:
        key = normalize_retailer(shop.brand) or normalize_retailer(shop.name)
        if key:
            if pro_kette.get(key, 0) >= _PRO_KETTE:
                continue
            pro_kette[key] = pro_kette.get(key, 0) + 1
        else:
            if ohne_kette >= _OHNE_KETTE:
                continue
            ohne_kette += 1
        behalten.append(shop)
    if len(behalten) < len(shops):
        log.debug("Ladenliste: %d → %d (max %d je Kette, %d ohne Kette)",
                  len(shops), len(behalten), _PRO_KETTE, _OHNE_KETTE)
    return behalten


# Verhindert, dass parallele Aufrufe (Dashboard lädt Läden, während der
# Warenkorb-Vergleich läuft) beide dieselbe Overpass-Query abfeuern. Der
# zweite wartet und findet den frisch geschriebenen Cache vor. Ohne das
# scheitert unter Last einer der beiden mit 504 – und liefert dann still
# eine leere Ladenliste, also weder Entfernungen noch Ketten-Filter.
_umkreis_locks: dict[str, asyncio.Lock] = {}


def _umkreis_lock(key: str) -> asyncio.Lock:
    lock = _umkreis_locks.get(key)
    if lock is None:
        lock = _umkreis_locks[key] = asyncio.Lock()
    return lock


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

    async with _umkreis_lock(f"{home.addr_hash}:{radius_key}"):
        return await _resolve_surroundings_locked(
            session, home, db, sc, radius, radius_key, force
        )


async def _resolve_surroundings_locked(
    session, home, db, sc, radius, radius_key, force,
) -> Surroundings:
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

    shops = _reduce(shops)

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

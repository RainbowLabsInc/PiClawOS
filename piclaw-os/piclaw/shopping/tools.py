"""
PiClaw OS – Agent-Tools der Einkaufsliste

Nutzung durch den Agent:
  shopping_add(item="Butter", qty="250g", max_price=1.50)
  shopping_list()
  shopping_offers()                  # ganze Liste abgleichen
  shopping_offers(item="Butter")     # nur ein Artikel
  shopping_stores()                  # Märkte im Umkreis
  shopping_home(street="…", house_number="…", zip_code="…", city="…")

Alle Handler geben fertig formatierten deutschen Text zurück und werfen nie –
Fehler werden zu einer "❌ …"-Antwort.
"""

from __future__ import annotations

import logging

import aiohttp

from piclaw.llm.base import ToolDefinition
from piclaw.shopping import analysis, location
from piclaw.shopping.matching import matches_item, normalize_title
from piclaw.shopping.providers import search_all
from piclaw.shopping.store import get_db

log = logging.getLogger("piclaw.shopping.tools")

MAX_LIST = 60


def _current_user_id() -> str | None:
    try:
        from piclaw.agent_context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return None


def _cfg():
    return location._shopping_cfg(None)


def _price(value) -> str:
    return f"{value:.2f} €".replace(".", ",") if value is not None else "—"


def _relevant(offers: list, term: str, strict: bool = True) -> list:
    """Filtert thematische Ausreißer der Provider-Suche.

    Ohne das erscheint unter »Butter« auch »Buttermilch« – siehe
    matching.matches_item. Bei einem selbst gesetzten Suchbegriff wird nicht
    gefiltert (Item.strict_matching).
    """
    if not strict:
        return list(offers)
    return [
        o for o in offers
        if matches_item(normalize_title(o.brand, o.title), term)
    ]


# ── Liste pflegen ────────────────────────────────────────────────────────


async def shopping_add(
    item: str = "", qty: str = "", max_price: float | None = None,
    query: str = "",
) -> str:
    if not item.strip():
        return "❌ Kein Artikel angegeben."
    try:
        db = get_db()
        user_id = _current_user_id()
        existing = db.find_item_by_name(item, owner_id=user_id)
        if existing:
            return f"ℹ️ »{existing.name}« steht schon auf der Liste."
        try:
            max_price = float(max_price) if max_price not in (None, "") else None
        except (TypeError, ValueError):
            max_price = None
        created = db.add_item(item, query=query, qty=qty,
                              max_price=max_price, owner_id=user_id)
        extra = []
        if created.qty:
            extra.append(created.qty)
        if created.max_price:
            extra.append(f"max. {_price(created.max_price)}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return f"🛒 »{created.name}«{suffix} auf die Einkaufsliste gesetzt."
    except Exception as exc:
        log.exception("shopping_add: %s", exc)
        return f"❌ Konnte den Artikel nicht speichern: {exc}"


async def shopping_remove(item: str = "") -> str:
    if not item.strip():
        return "❌ Kein Artikel angegeben."
    try:
        db = get_db()
        user_id = _current_user_id()
        found = db.find_item_by_name(item, owner_id=user_id)
        if not found:
            return f"❓ »{item}« steht nicht auf der Liste."
        db.remove_item(found.id)
        return f"🗑️ »{found.name}« von der Einkaufsliste entfernt."
    except Exception as exc:
        log.exception("shopping_remove: %s", exc)
        return f"❌ Konnte den Artikel nicht entfernen: {exc}"


async def shopping_list() -> str:
    try:
        db = get_db()
        items = db.list_items(owner_id=_current_user_id())
        if not items:
            return "🛒 Die Einkaufsliste ist leer."
        lines = [f"🛒 *Einkaufsliste* ({len(items)})", ""]
        for item in items[:MAX_LIST]:
            details = []
            if item.qty:
                details.append(item.qty)
            if item.max_price:
                details.append(f"max. {_price(item.max_price)}")
            suffix = f" _({', '.join(details)})_" if details else ""
            best = db.best_current(item.id)
            if best:
                suffix += f" — aktuell {_price(best['price'])} bei {best['retailer']}"
            lines.append(f"• {item.name}{suffix}")
        if len(items) > MAX_LIST:
            lines.append(f"… und {len(items) - MAX_LIST} weitere")
        return "\n".join(lines)
    except Exception as exc:
        log.exception("shopping_list: %s", exc)
        return f"❌ Konnte die Liste nicht lesen: {exc}"


# ── Standort ─────────────────────────────────────────────────────────────


async def shopping_home(
    street: str = "", house_number: str = "", zip_code: str = "",
    city: str = "", country: str = "",
) -> str:
    """Zeigt oder setzt die Hausadresse und meldet die Auflösungsgenauigkeit."""
    try:
        from piclaw.config import load

        if any([street, house_number, zip_code, city, country]):
            # Nur die [shopping]-Sektion anfassen, nicht die ganze Datei neu
            # rendern – sonst landen entschlüsselte Secrets im Klartext, wo
            # `@enc:`-Platzhalter standen. Siehe write_home_address().
            alt = location._shopping_cfg(None)
            location.write_home_address(
                street=street or alt.home_street,
                house_number=house_number or alt.home_house_number,
                zip_code=zip_code or alt.home_zip,
                city=city or alt.home_city,
                country=country or alt.home_country,
            )

        cfg = load()
        street_c, nr_c, zip_c, city_c, _ = location.address_parts(cfg)
        if not (street_c or zip_c or city_c):
            return location.NOT_CONFIGURED

        async with aiohttp.ClientSession() as session:
            home = await location.resolve_home(session, cfg=cfg, force=True)
        if home is None:
            return ("❌ Adresse nicht gefunden. Schreibweise prüfen – "
                    "oder Koordinaten direkt in `[shopping] home_latitude/"
                    "home_longitude` eintragen.")

        addr = " ".join(p for p in (street_c, nr_c) if p)
        ort = " ".join(p for p in (zip_c, city_c) if p)
        lines = [
            "📍 *Wohnort*",
            f"{addr}, {ort}" if addr else ort,
            f"Genauigkeit: {'Hausnummer ✅' if home.is_exact else home.precision}",
        ]
        if home.warning:
            lines.append(f"⚠️ {home.warning}")
        return "\n".join(lines)
    except Exception as exc:
        log.exception("shopping_home: %s", exc)
        return f"❌ Konnte den Wohnort nicht setzen: {exc}"


async def shopping_stores(radius_km: float | None = None, refresh: bool = False) -> str:
    try:
        from piclaw.config import load

        cfg = load()
        if radius_km:
            try:
                cfg.shopping.radius_km = float(radius_km)
            except (TypeError, ValueError):
                pass

        async with aiohttp.ClientSession() as session:
            home, surroundings = await location.resolve(
                session, cfg=cfg, force=bool(refresh)
            )
        if home is None:
            return location.NOT_CONFIGURED
        if not surroundings.shops:
            return ("🏪 Keine Läden im Umkreis gefunden. Größerer Radius, oder "
                    "OpenStreetMap war gerade nicht erreichbar – später erneut.")

        lines = [
            f"🏪 *Märkte im Umkreis von {surroundings.radius_km:.0f} km* "
            f"({len(surroundings.shops)})"
        ]
        if home.warning:
            lines.append(f"⚠️ {home.warning}")
        lines.append("")
        for shop in surroundings.shops[:25]:
            addr = ", ".join(p for p in (
                " ".join(x for x in (shop.get("street"), shop.get("housenumber")) if x),
                shop.get("city"),
            ) if p)
            suffix = f" — {addr}" if addr else ""
            lines.append(f"• {shop['distance_km']:.1f} km  {shop['retailer']}{suffix}")
        if len(surroundings.shops) > 25:
            lines.append(f"… und {len(surroundings.shops) - 25} weitere")
        if surroundings.from_cache:
            lines.append("\n_aus dem Zwischenspeicher_")
        return "\n".join(lines)
    except Exception as exc:
        log.exception("shopping_stores: %s", exc)
        return f"❌ Konnte die Märkte nicht ermitteln: {exc}"


# ── Angebotsabgleich ─────────────────────────────────────────────────────


async def shopping_offers(item: str = "") -> str:
    try:
        db = get_db()
        sc = _cfg()
        user_id = _current_user_id()

        if item.strip():
            found = db.find_item_by_name(item, owner_id=user_id)
            items = [found] if found else []
            if not items:
                # Nicht auf der Liste? Trotzdem suchen – das ist die
                # natürlichere Antwort auf "ist X gerade im Angebot?".
                from piclaw.shopping.store import Item
                items = [Item(id=0, name=item.strip())]
        else:
            items = [i for i in db.list_items(owner_id=user_id) if not i.muted]
        if not items:
            return "🛒 Die Einkaufsliste ist leer."

        async with aiohttp.ClientSession() as session:
            home, surroundings = await location.resolve(session)
            if home is None:
                return location.NOT_CONFIGURED
            retailer_keys = surroundings.retailer_keys or None

            blocks: list[str] = []
            for entry in items:
                term = entry.search_term
                if not term:
                    continue
                offers = await search_all(
                    session, term, zip_code=home.zip_code,
                    lat=home.lat, lon=home.lon, providers=sc.providers,
                    retailer_keys=retailer_keys, active_only=True, limit=25,
                )
                offers = _relevant(offers, term, entry.strict_matching)
                if entry.max_price:
                    offers = [o for o in offers
                              if o.price is not None and o.price <= entry.max_price]
                if not offers:
                    continue

                lines = [f"*{entry.name}*"]
                for offer in offers[:5]:
                    shop = surroundings.nearest(offer.retailer_key)
                    entfernung = f" · {shop['distance_km']:.1f} km" if shop else ""
                    alt = (f" ~{_price(offer.old_price)}~"
                           if offer.old_price and offer.old_price > (offer.price or 0)
                           else "")
                    lines.append(
                        f"  {_price(offer.price)}{alt} — {offer.retailer}"
                        f"{entfernung}\n    {offer.title}"
                    )
                if entry.id:
                    hist = db.item_history(entry.id)
                    verdict = analysis.evaluate(
                        hist[:-1] if hist else [],
                        offers[0].price or 0.0,
                        drop_pct=sc.price_drop_pct, baseline_days=sc.baseline_days,
                        min_samples=sc.min_samples, min_span_days=sc.min_span_days,
                    )
                    if verdict.is_drop:
                        lines.append(f"  📉 {verdict.describe()}")
                blocks.append("\n".join(lines))

        if not blocks:
            return ("🔍 Aktuell ist nichts von deiner Liste im Angebot.\n"
                    "_Tipp: zusammengesetzte Wörter finden oft nichts – "
                    "»Geschirrspül« statt »Spülmaschinentabs«._")

        header = "🏷️ *Aktuelle Angebote*"
        if home.warning:
            header += f"\n⚠️ {home.warning}"
        return header + "\n\n" + "\n\n".join(blocks)
    except Exception as exc:
        log.exception("shopping_offers: %s", exc)
        return f"❌ Angebotsabgleich fehlgeschlagen: {exc}"


async def shopping_test(query: str = "") -> str:
    """Prüft einen Suchbegriff live, ohne etwas zu speichern.

    Gegenstück zum Testen-Button im Dashboard: zeigt sofort, ob der Begriff
    überhaupt Treffer liefert – Tippfehler und Komposita fallen so auf, bevor
    der Artikel wochenlang stumm auf der Liste steht.
    """
    if not query.strip():
        return "❌ Kein Suchbegriff angegeben."
    try:
        sc = _cfg()
        async with aiohttp.ClientSession() as session:
            home, surroundings = await location.resolve(session)
            zip_code = home.zip_code if home else ""
            lat = home.lat if home else None
            lon = home.lon if home else None
            raw = await search_all(
                session, query, zip_code=zip_code, lat=lat, lon=lon,
                providers=sc.providers, active_only=True, limit=20,
            )
        offers = _relevant(raw, query)
        if not raw:
            return (f"🔍 »{query}« findet gerade nichts.\n"
                    "Das heißt nicht zwingend Tippfehler – zusammengesetzte "
                    "Wörter funktionieren oft nicht: »Geschirrspül« findet, "
                    "»Spülmaschinentabs« nicht.")

        lines = [f"🔍 »{query}« — {len(offers)} passende Treffer:"]
        for offer in offers[:5]:
            lines.append(f"  {_price(offer.price)} — {offer.retailer}: {offer.title}")

        # Aussortierte mitzeigen: sonst wirkt es wie ein Fehler, wenn zu
        # »Kaffee« keine »Kaffeepads« erscheinen. So sieht man den Grund und
        # kann bei Bedarf einen genaueren Suchbegriff hinterlegen.
        weniger = [o for o in raw if o not in offers]
        if weniger:
            lines.append("")
            lines.append(f"_Als unpassend aussortiert ({len(weniger)}):_")
            for offer in weniger[:3]:
                lines.append(f"  ~{offer.title}~")
            if not offers:
                lines.append("\nPasst davon doch etwas? Dann leg den Artikel mit "
                             "einem genaueren Suchbegriff an.")
        return "\n".join(lines)
    except Exception as exc:
        log.exception("shopping_test: %s", exc)
        return f"❌ Test fehlgeschlagen: {exc}"


# ── Tool-Definitionen ────────────────────────────────────────────────────

TOOL_DEFS: list[ToolDefinition] = [
    ToolDefinition(
        name="shopping_add",
        description=(
            "Setzt einen Artikel auf die Einkaufsliste. Optional mit Menge und "
            "Preisobergrenze. Nutze das bei 'setz X auf die Einkaufsliste', "
            "'ich brauche X', 'kauf X ein'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "Artikelname, z.B. 'Butter'"},
                "qty": {"type": "string", "description": "Menge, z.B. '250g' oder '2 Packungen'"},
                "max_price": {"type": "number", "description": "Preisobergrenze in Euro"},
                "query": {
                    "type": "string",
                    "description": (
                        "Abweichender Suchbegriff für die Angebotssuche. Nur "
                        "nötig, wenn der Artikelname nichts findet."
                    ),
                },
            },
            "required": ["item"],
        },
    ),
    ToolDefinition(
        name="shopping_remove",
        description="Entfernt einen Artikel von der Einkaufsliste.",
        parameters={
            "type": "object",
            "properties": {"item": {"type": "string", "description": "Artikelname"}},
            "required": ["item"],
        },
    ),
    ToolDefinition(
        name="shopping_list",
        description="Zeigt die Einkaufsliste mit den aktuell günstigsten Preisen.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="shopping_offers",
        description=(
            "Prüft, welche Artikel der Einkaufsliste gerade im Angebot sind – "
            "bei Supermärkten in der Umgebung. Ohne Argument die ganze Liste. "
            "Nutze das bei 'was ist im Angebot', 'gibt es Angebote', "
            "'ist X gerade billiger'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "Nur diesen Artikel prüfen. Leer = ganze Liste.",
                }
            },
        },
    ),
    ToolDefinition(
        name="shopping_stores",
        description=(
            "Zeigt Supermärkte und Drogerien im Umkreis des Wohnorts, sortiert "
            "nach Entfernung."
        ),
        parameters={
            "type": "object",
            "properties": {
                "radius_km": {"type": "number", "description": "Umkreis in km"},
                "refresh": {
                    "type": "boolean",
                    "description": "Zwischenspeicher übergehen und neu laden",
                },
            },
        },
    ),
    ToolDefinition(
        name="shopping_home",
        description=(
            "Zeigt oder setzt die Hausadresse für die Umkreissuche und meldet, "
            "wie genau sie aufgelöst wurde. Ohne Argumente nur anzeigen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "street": {"type": "string", "description": "Straße"},
                "house_number": {"type": "string", "description": "Hausnummer"},
                "zip_code": {"type": "string", "description": "Postleitzahl"},
                "city": {"type": "string", "description": "Ort"},
                "country": {"type": "string", "description": "Ländercode, Standard 'de'"},
            },
        },
    ),
    ToolDefinition(
        name="shopping_test",
        description=(
            "Prüft, ob ein Suchbegriff überhaupt Angebote findet, ohne ihn zu "
            "speichern. Gut vor dem Anlegen eines Artikels."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Suchbegriff"}},
            "required": ["query"],
        },
    ),
]


def build_handlers() -> dict:
    async def _add(**kw):
        return await shopping_add(
            item=kw.get("item", ""), qty=kw.get("qty", ""),
            max_price=kw.get("max_price"), query=kw.get("query", ""),
        )

    async def _remove(**kw):
        return await shopping_remove(item=kw.get("item", ""))

    async def _list(**_kw):
        return await shopping_list()

    async def _offers(**kw):
        return await shopping_offers(item=kw.get("item", ""))

    async def _stores(**kw):
        return await shopping_stores(
            radius_km=kw.get("radius_km"), refresh=bool(kw.get("refresh")),
        )

    async def _home(**kw):
        return await shopping_home(
            street=kw.get("street", ""), house_number=kw.get("house_number", ""),
            zip_code=kw.get("zip_code", ""), city=kw.get("city", ""),
            country=kw.get("country", ""),
        )

    async def _test(**kw):
        return await shopping_test(query=kw.get("query", ""))

    async def _sample(**_kw):
        # Nur als direct_tool des Sammel-Sub-Agenten; steht bewusst nicht in
        # TOOL_DEFS, damit das LLM es nicht selbst aufruft.
        from piclaw.shopping.sampler import sample_silent
        return await sample_silent()

    return {
        "shopping_add": _add,
        "shopping_remove": _remove,
        "shopping_list": _list,
        "shopping_offers": _offers,
        "shopping_stores": _stores,
        "shopping_home": _home,
        "shopping_test": _test,
        "shopping_price_sample": _sample,
    }


HANDLERS = build_handlers()

__all__ = ["TOOL_DEFS", "HANDLERS", "build_handlers"]

"""
PiClaw OS – Tägliche Zusammenfassung der Einkaufsliste

Baut die Nachricht, die per Messenger zugestellt wird:

    🛒 Einkaufsliste — Montag, 4. August

    Hackfleisch   3,49 €   Kaufland   1,9 km   (6,98 €/kg)
    Toast         0,89 €   Lidl       1,7 km
    Kaffee        —        nichts im Angebot

    🧮 Ganzer Einkauf: 9,75 € bei Lidl
       Verteilt auf 3 Läden: 8,20 € — spart 1,55 €

Zwei Eigenschaften, die den Unterschied zwischen nützlich und lästig machen:

* **Nur bei Änderung.** Deutsche Prospekte laufen wochenweise; ohne
  Vergleich gegen die letzte Zustellung käme an fünf von sieben Tagen
  dieselbe Nachricht. Dafür wird ein Fingerabdruck des Inhalts gespeichert.
* **Pro Nutzer.** Der Sub-Agent trägt eine owner_id, der Runner setzt daraus
  den Nutzerkontext – jeder sieht nur seine eigene Liste, seine Adresse und
  seinen Zeitplan.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

import aiohttp

from piclaw.shopping import basket, location
from piclaw.shopping.store import get_db

log = logging.getLogger("piclaw.shopping.digest")

SILENT = "__NO_NEW_RESULTS__"

_WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag",
               "Freitag", "Samstag", "Sonntag")
_MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember")


def _preis(value) -> str:
    return f"{value:.2f} €".replace(".", ",") if value is not None else "—"


def _datumszeile(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{_WOCHENTAGE[now.weekday()]}, {now.day}. {_MONATE[now.month - 1]}"


async def build(
    session: aiohttp.ClientSession | None = None,
    db=None,
    user_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Baut die Nachricht. Rückgabe: (text, fingerabdruck).

    Leerer Text heißt: nichts zu melden.
    """
    if session is None:
        async with aiohttp.ClientSession() as own:
            return await build(own, db=db, user_id=user_id, now=now)

    db = db or get_db()
    items = [
        i for i in db.list_items(owner_id=user_id)
        if not i.muted and not i.is_bought()
    ]
    if not items:
        return "", ""

    home, surroundings = await location.resolve(session, db=db)
    if home is None:
        return "", ""

    zeilen: list[str] = [f"🛒 *Einkaufsliste* — {_datumszeile(now)}", ""]
    fingerabdruck: list[str] = []

    for item in items:
        best = db.best_current(item.id)
        if not best:
            zeilen.append(f"• {item.name} — _nichts im Angebot_")
            fingerabdruck.append(f"{item.id}:-")
            continue
        shop = surroundings.nearest(
            next((k for k in surroundings.retailer_keys
                  if k == best["retailer"]), best["retailer"])
        )
        entfernung = f" · {shop['distance_km']:.1f} km" if shop else ""
        grund = f" · {best['unit_price_text']}" if best.get("unit_price_text") else ""
        zeilen.append(
            f"• *{item.name}* {_preis(best['price'])}{grund} — "
            f"{best['retailer']}{entfernung}\n  _{best['title']}_"
        )
        fingerabdruck.append(f"{item.id}:{best['price']}:{best['retailer']}")

    # ── Preisrutsche ────────────────────────────────────────────────
    offen = [a for a in db.pending_alerts()
             if user_id is None or _gehoert(db, a, user_id)]
    if offen:
        zeilen.append("")
        zeilen.append("📉 *Deutlich günstiger als sonst*")
        for alert in offen[:5]:
            zeilen.append(
                f"• {alert['item_name']}: {_preis(alert['price'])} bei "
                f"{alert['retailer']} — sonst {_preis(alert['baseline'])}"
            )
            fingerabdruck.append(f"a{alert['id']}")
        db.mark_alerts_notified([a["id"] for a in offen])

    # ── Warenkorb ───────────────────────────────────────────────────
    korb = await basket.compare(session, items, home, surroundings, db=db)
    bester = korb.best_single
    if bester:
        zusatz = (f" (inkl. {len(bester.geschaetzt)} zum geschätzten Normalpreis)"
                  if bester.geschaetzt else "")
        entfernung = (f" · {bester.distance_km:.1f} km"
                      if bester.distance_km is not None else "")
        zeilen.append("")
        zeilen.append(
            f"🧮 *Ganzer Einkauf:* {_preis(bester.total_full)} bei "
            f"{bester.retailer}{entfernung}{zusatz}"
        )
        fingerabdruck.append(f"korb:{bester.retailer_key}:{bester.total_full}")
        if korb.optimum_stores > 1 and korb.savings > 0:
            zeilen.append(
                f"   Verteilt auf {korb.optimum_stores} Läden: "
                f"{_preis(korb.optimum_total)} — spart {_preis(korb.savings)}"
            )

    # ── Vorschau ────────────────────────────────────────────────────
    vorschau = await _vorschau(session, items, home, surroundings, db)
    if vorschau:
        zeilen.append("")
        zeilen.append("🔜 *Kommt demnächst*")
        zeilen.extend(vorschau)
        fingerabdruck.extend(f"v{z}" for z in vorschau)

    text = "\n".join(zeilen)
    return text, hashlib.sha256("|".join(fingerabdruck).encode()).hexdigest()[:32]


def _gehoert(db, alert: dict, user_id: str) -> bool:
    item = db.get_item(alert.get("item_id") or 0)
    return bool(item and item.owner_id in (None, user_id))


async def _vorschau(session, items, home, surroundings, db) -> list[str]:
    """Angebote, die erst in den nächsten Tagen starten.

    Die Daten liegen ohnehin vor – bisher habe ich sie verworfen. Gerade
    sonntags, wenn die alte Angebotswoche abgelaufen ist, ist das der
    einzige nützliche Inhalt.
    """
    from piclaw.shopping.matching import filter_relevant
    from piclaw.shopping.providers import search_all

    sc = location._shopping_cfg(None)
    zeilen: list[str] = []
    for item in items[:8]:
        term = item.search_term
        if not term:
            continue
        try:
            offers = await search_all(
                session, term, zip_code=home.zip_code,
                lat=home.lat, lon=home.lon, providers=sc.providers,
                retailer_keys=surroundings.retailer_keys or None,
                active_only=False, limit=25,
            )
        except Exception as exc:
            log.debug("Vorschau '%s': %s", term, exc)
            continue
        if item.strict_matching:
            offers = filter_relevant(offers, term)
        kommend = [o for o in offers if o.starts_later and o.price]
        if not kommend:
            continue
        guenstigstes = min(kommend, key=lambda o: o.price)
        # Nur melden, wenn es besser ist als das, was gerade läuft.
        aktuell = db.best_current(item.id)
        if aktuell and guenstigstes.price >= aktuell["price"]:
            continue
        zeilen.append(
            f"• {item.name}: {_preis(guenstigstes.price)} bei "
            f"{guenstigstes.retailer} ab {guenstigstes.starts_on}"
        )
    return zeilen


async def send_digest() -> str:
    """direct_tool-Einstieg des Digest-Sub-Agenten.

    Der Runner setzt den Nutzerkontext aus der owner_id des Sub-Agenten,
    deshalb reicht hier der aktuelle User.
    """
    try:
        from piclaw.agent_context import get_current_user_id

        user_id = get_current_user_id()
        db = get_db()
        text, fingerabdruck = await build(db=db, user_id=user_id)
        if not text:
            return SILENT
        if not db.digest_changed(user_id, fingerabdruck):
            log.debug("Digest unverändert – nicht zugestellt")
            return SILENT
        db.digest_sent(user_id, fingerabdruck)
        return text
    except Exception as exc:
        log.exception("Digest fehlgeschlagen: %s", exc)
        return SILENT


def cron_expression(days: str, time_str: str) -> str:
    """Baut den cron-Ausdruck aus Wochentagen und Uhrzeit.

    days: "1,2,4" (0=Sonntag … 6=Samstag), time_str: "07:00".
    Ungültige Eingaben fallen auf 7 Uhr täglich zurück statt zu werfen –
    ein kaputter Ausdruck würde den Sub-Agenten still nie laufen lassen.
    """
    try:
        stunde, minute = (int(x) for x in str(time_str).split(":", 1))
        if not (0 <= stunde <= 23 and 0 <= minute <= 59):
            raise ValueError(time_str)
    except (ValueError, TypeError):
        log.warning("Ungültige Digest-Uhrzeit %r – nutze 07:00", time_str)
        stunde, minute = 7, 0

    gueltig = sorted({d for d in str(days).split(",")
                      if d.strip().isdigit() and 0 <= int(d) <= 6},
                     key=int)
    tage = ",".join(gueltig) if gueltig else "*"
    return f"cron:{minute} {stunde} * * {tage}"


__all__ = ["build", "send_digest", "cron_expression", "SILENT"]

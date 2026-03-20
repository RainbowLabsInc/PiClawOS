"""
PiClaw OS – Marketplace Crawler Tool
Sucht auf Kleinanzeigen.de, eBay.de und im Web nach Inseraten.
Merkt sich gesehene Inserate und meldet nur neue.

Nutzung durch den Agent:
  marketplace_search(query="Raspberry Pi 5", platforms=["kleinanzeigen", "ebay"],
                     max_price=100, location="Hamburg")
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import aiohttp

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.tools.marketplace")

# Gesehene Inserate werden hier gespeichert (verhindert doppelte Meldungen)
SEEN_FILE = CONFIG_DIR / "marketplace_seen.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── Seen-IDs verwalten ─────────────────────────────────────────────────────────

def _load_seen() -> set:
    try:
        if SEEN_FILE.exists():
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data.get("seen", []))
    except Exception:
        pass
    return set()


def _save_seen(seen: set) -> None:
    try:
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Maximal 10.000 IDs behalten (älteste löschen)
        seen_list = list(seen)[-10000:]
        SEEN_FILE.write_text(
            json.dumps({"seen": seen_list, "updated": datetime.now().isoformat()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        log.debug("Seen-Datei speichern: %s", e)


def _make_id(platform: str, listing_id: str) -> str:
    return f"{platform}:{listing_id}"


def _clean_query(query: str) -> str:
    """Bereinigt den Suchbegriff von Rauschen (PLZ, Radius, Plattformen, Füllwörter)."""
    import re
    # Chat-Präfixe entfernen
    q = re.sub(r"\[.*?\]", " ", query)

    # PLZ (5 Ziffern)
    q = re.sub(r"\b\d{5}\b", " ", q)

    # Radius (z.B. "20km", "20 km")
    q = re.sub(r"\b\d+\s*km\b", " ", q, flags=re.IGNORECASE)

    # Plattformnamen und Domains
    for term in ["kleinanzeigen.de", "ebay.de", "kleinanzeigen", "ebay", ".de"]:
        q = re.sub(re.escape(term), " ", q, flags=re.IGNORECASE)

    # Deutsche Stoppwörter/Rauschen für Marktplatz-Suche
    noise = ["suche", "finde", "such", "find", "schau", "schaue", "durchsuche",
             "zeig", "liste", "was kostet", "preis für", "gibt es", "schnäppchen",
             "angebot", "umkreis", "radius", "einen", "eine", "ein", "mir",
             "dem", "der", "die", "das", "bitte", "im", "in", "um", "von", "bis",
             "nähe", "für", "unter", "euro", "rosengarten", "hamburg", "berlin",
             "nach", "mit", "den", "auf", "mal", "einem", "einer", "münchen",
             "frankfurt", "düsseldorf", "köln", "hannover", "leipzig", "bremen",
             "kaufen", "verkaufen", "preis", "günstig", "billig", "suche", "verkaufe"]

    for word in noise:
        q = re.sub(r"(?i)\b" + re.escape(word) + r"\b", " ", q)

    # "Nähe" auch am Wortende entfernen falls Punkt/Fragezeichen folgt
    q = re.sub(r"(?i)nähe", " ", q)

    # Alle Sonderzeichen entfernen
    q = re.sub(r"[?!.,;:\-_/]", " ", q)

    # Mehrfache Leerzeichen bereinigen
    q = " ".join(q.split()).strip()
    return q


# ── Preis-Parser ───────────────────────────────────────────────────────────────

def _parse_price(text: str) -> Optional[float]:
    """Extrahiert Preis aus Text wie '149 €', '1.299,00 €', 'VB 80 €'"""
    text = text.replace(".", "").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


# ── Kleinanzeigen.de ───────────────────────────────────────────────────────────

async def _search_kleinanzeigen(
    session: aiohttp.ClientSession,
    query: str,
    max_price: Optional[float] = None,
    location: Optional[str] = None,
    max_results: int = 10,
    radius_km: Optional[int] = None,
) -> list[dict]:
    """Sucht auf Kleinanzeigen.de (ehemals eBay Kleinanzeigen)."""
    results = []

    # URL aufbauen mit Radius-Unterstützung
    q = quote_plus(query)
    url = f"https://www.kleinanzeigen.de/s-{q}/k0"
    params = []
    if location:
        loc = quote_plus(location)
        url = f"https://www.kleinanzeigen.de/s-{loc}/{q}/k0"
    if max_price:
        params.append(f"maxPrice={int(max_price)}")
    if radius_km:
        params.append(f"radius={int(radius_km)}")
    if params:
        url += "?" + "&".join(params)

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.debug("Kleinanzeigen HTTP %s", resp.status)
                return []
            html = await resp.text(errors="replace")
    except Exception as e:
        log.debug("Kleinanzeigen Fehler: %s", e)
        return []

    # Inserate parsen
    # Artikel-Blöcke: <article class="aditem ...">
    articles = re.findall(
        r'<article[^>]+data-adid="(\d+)"[^>]*>(.*?)</article>',
        html, re.DOTALL
    )

    for ad_id, content in articles[:max_results]:
        # Titel
        title_match = re.search(
            r'class="[^"]*text-module-begin[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>',
            content, re.DOTALL
        )
        if not title_match:
            title_match = re.search(r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>(.*?)</a>',
                                    content, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""

        # Preis
        price_match = re.search(r'<p[^>]*class="[^"]*aditem-main--middle--price[^"]*"[^>]*>(.*?)</p>',
                                 content, re.DOTALL)
        price_text = re.sub(r'<[^>]+>', '', price_match.group(1)).strip() if price_match else ""
        price = _parse_price(price_text)

        # Ort
        loc_match = re.search(r'<span[^>]*class="[^"]*aditem-main--top--left[^"]*"[^>]*>(.*?)</span>',
                               content, re.DOTALL)
        location_text = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip() if loc_match else ""

        if not title:
            continue

        results.append({
            "id":       ad_id,
            "platform": "kleinanzeigen",
            "title":    title,
            "price":    price,
            "price_text": price_text,
            "location": location_text,
            "url":      f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}",
        })

    log.info("Kleinanzeigen: %d Inserate gefunden für '%s'", len(results), query)
    return results


# ── eBay.de ────────────────────────────────────────────────────────────────────

async def _search_ebay(
    session: aiohttp.ClientSession,
    query: str,
    max_price: Optional[float] = None,
    max_results: int = 10,
) -> list[dict]:
    """Sucht auf eBay.de (Festpreisartikel + Auktionen)."""
    results = []

    q = quote_plus(query)
    url = f"https://www.ebay.de/sch/i.html?_nkw={q}&_sop=15"  # _sop=15 = neueste zuerst
    if max_price:
        url += f"&_udhi={int(max_price)}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.debug("eBay HTTP %s", resp.status)
                return []
            html = await resp.text(errors="replace")
    except Exception as e:
        log.debug("eBay Fehler: %s", e)
        return []

    # eBay Artikel parsen
    items = re.findall(
        r'<li[^>]+data-view="[^"]*mi:1686[^"]*"[^>]*id="item(\d+)"[^>]*>(.*?)</li>',
        html, re.DOTALL
    )
    # Alternativ: s-item Blöcke
    if not items:
        items = re.findall(
            r'<div[^>]+class="[^"]*s-item[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</li>',
            html, re.DOTALL
        )
        items = [(hashlib.md5(c.encode()).hexdigest()[:12], c) for c in items]

    for item_id, content in items[:max_results]:
        # Titel
        title_match = re.search(
            r'<span[^>]+role="heading"[^>]*>(.*?)</span>',
            content, re.DOTALL
        )
        if not title_match:
            title_match = re.search(r'class="[^"]*s-item__title[^"]*"[^>]*>(.*?)</[^>]+>',
                                    content, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
        if not title or "Shop on eBay" in title:
            continue

        # Preis
        price_match = re.search(r'class="[^"]*s-item__price[^"]*"[^>]*>(.*?)</span>',
                                 content, re.DOTALL)
        price_text = re.sub(r'<[^>]+>', '', price_match.group(1)).strip() if price_match else ""
        price = _parse_price(price_text)

        # Link
        link_match = re.search(r'href="(https://www\.ebay\.de/itm/[^"]+)"', content)
        link = link_match.group(1).split("?")[0] if link_match else f"https://www.ebay.de/itm/{item_id}"

        results.append({
            "id":       str(item_id),
            "platform": "ebay",
            "title":    title,
            "price":    price,
            "price_text": price_text,
            "location": "",
            "url":      link,
        })

    log.info("eBay: %d Artikel gefunden für '%s'", len(results), query)
    return results


# ── Freie Websuche ─────────────────────────────────────────────────────────────

async def _search_web(
    session: aiohttp.ClientSession,
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """Sucht via DuckDuckGo nach Inseraten/Angeboten."""
    results = []
    q = quote_plus(f"{query} kaufen angebot")
    url = f"https://html.duckduckgo.com/html/?q={q}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            html = await resp.text(errors="replace")
    except Exception as e:
        log.debug("Websuche Fehler: %s", e)
        return []

    # DDG Ergebnisse parsen
    hits = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )

    for i, (href, title) in enumerate(hits[:max_results]):
        title_clean = re.sub(r'<[^>]+>', '', title).strip()
        snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
        price = _parse_price(snippet)

        results.append({
            "id":       hashlib.md5(href.encode()).hexdigest()[:12],
            "platform": "web",
            "title":    title_clean,
            "price":    price,
            "price_text": f"{price:.0f} €" if price else "",
            "location": "",
            "url":      href,
            "snippet":  snippet,
        })

    log.info("Websuche: %d Treffer für '%s'", len(results), query)
    return results


# ── Haupt-Funktion ─────────────────────────────────────────────────────────────

async def marketplace_search(
    query: str,
    platforms: Optional[list[str]] = None,
    max_price: Optional[float] = None,
    location: Optional[str] = None,
    max_results: int = 10,
    notify_all: bool = True,
    radius_km: Optional[int] = None,
) -> dict:
    """
    Durchsucht Marktplätze nach neuen Inseraten.

    Args:
        query:       Suchbegriff (z.B. "Raspberry Pi 5")
        platforms:   ["kleinanzeigen", "ebay", "web"] – default: alle
        max_price:   Maximaler Preis in Euro
        location:    Ort/PLZ für Kleinanzeigen
        max_results: Max. Ergebnisse pro Plattform
        notify_all:  True = alle melden, False = nur neue (Standard)

    Returns:
        {"new": [...], "total": int, "platforms_searched": [...]}
    """
    if platforms is None:
        platforms = ["kleinanzeigen", "ebay", "web"]

    # Intern bereinigen um Rauschen in der eigentlichen Suche zu vermeiden
    query = _clean_query(query)

    seen = _load_seen() if not notify_all else set()
    all_results = []

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = []
        if "kleinanzeigen" in platforms:
            tasks.append(_search_kleinanzeigen(session, query, max_price, location, max_results, radius_km))
        if "ebay" in platforms:
            tasks.append(_search_ebay(session, query, max_price, max_results))
        if "web" in platforms:
            tasks.append(_search_web(session, query, min(max_results, 5)))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results_list:
            if isinstance(r, list):
                all_results.extend(r)

    # Neue filtern
    new_results = []
    new_seen = set(seen)
    for item in all_results:
        uid = _make_id(item["platform"], item["id"])
        if uid not in new_seen:
            new_results.append(item)
            new_seen.add(uid)

    # Gesehene nur speichern wenn wir NICHT im notify_all Modus sind.
    # Das verhindert, dass eine manuelle Suche spätere Hintergrund-Suchen "stummschaltet".
    if not notify_all:
        _save_seen(new_seen)

    log.info("Marketplace '%s': %d gesamt, %d neu", query, len(all_results), len(new_results))
    return {
        "new":                new_results,
        "total_found":        len(all_results),
        "new_count":          len(new_results),
        "platforms_searched": platforms,
        "query":              query,
        "max_price":          max_price,
        "location":           location,
    }


def format_results(results: dict, mode: str = "text") -> str:
    """Formatiert Ergebnisse. mode='text' für Terminal, 'telegram' für Telegram-Markdown."""
    new = results.get("new", [])
    query = results.get("query", "")
    location = results.get("location", "")
    max_price = results.get("max_price")

    if not new:
        return f"Keine neuen Inserate gefunden für '{query}'."

    loc_str = f" in {location}" if location else ""
    price_str = f" (max. {max_price:.0f} €)" if max_price else ""
    header = f"🛒 {len(new)} Inserate für '{query}'{loc_str}{price_str}\n"
    header += "─" * 50 + "\n"

    lines = [header]
    platform_label = {"kleinanzeigen": "Kleinanzeigen", "ebay": "eBay", "web": "Web"}
    platform_emoji = {"kleinanzeigen": "📌", "ebay": "🛍️", "web": "🌐"}

    for i, item in enumerate(new[:10], 1):
        emoji = platform_emoji.get(item["platform"], "🔗")
        plat  = platform_label.get(item["platform"], item["platform"])
        price = f"  💶 {item['price_text']}" if item.get("price_text") else ""
        loc   = f"  📍 {item['location']}" if item.get("location") else ""
        url   = item.get("url", "")
        # Markdown-Titel bereinigen (Klammern eskapen)
        safe_title = item['title'].replace("[", "\\[").replace("]", "\\]")[:70]

        lines.append(f"{i}. {emoji} [{plat}] {safe_title}")
        if price: lines.append(f"   {price.strip()}")
        if loc:   lines.append(f"   {loc.strip()}")
        if url:   lines.append(f"   🔗 {url}")
        lines.append("")

    if len(new) > 10:
        lines.append(f"... und {len(new) - 10} weitere Inserate.")

    return "\n".join(lines)


def format_results_telegram(results: dict) -> str:
    """Formatiert Ergebnisse als Telegram-Markdown-Nachricht."""
    new = results.get("new", [])
    if not new:
        return f"🔍 Keine neuen Inserate für *{results.get('query', '')}*."

    lines = [
        f"🛒 *{len(new)} neue Inserate* für _{results['query']}_\n"
    ]
    if results.get("max_price"):
        lines[0] += f"(max. {results['max_price']:.0f} €)"

    for item in new[:10]:  # Max 10 pro Nachricht
        platform_emoji = {"kleinanzeigen": "📌", "ebay": "🛍️", "web": "🌐"}.get(
            item["platform"], "🔗"
        )
        # Markdown-Titel bereinigen (Klammern eskapen)
        safe_title = item['title'].replace("[", "\\[").replace("]", "\\]")[:60]

        price_str = f" · {item['price_text']}" if item.get("price_text") else ""
        loc_str   = f" · {item['location']}" if item.get("location") else ""
        lines.append(
            f"{platform_emoji} [{safe_title}]({item['url']})"
            f"{price_str}{loc_str}"
        )

    if len(new) > 10:
        lines.append(f"\n_... und {len(new) - 10} weitere_")
    return "\n".join(lines)

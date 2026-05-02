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
from urllib.parse import quote_plus

import aiohttp

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.tools.marketplace")

# Gesehene Inserate werden hier gespeichert (verhindert doppelte Meldungen)
SEEN_FILE = CONFIG_DIR / "marketplace_seen.json"
# Serialisiert den Read-Modify-Write auf marketplace_seen.json.
# Verhindert Race Conditions wenn mehrere Agenten gleichzeitig laufen.
_SEEN_LOCK: asyncio.Lock | None = None


def _get_seen_lock() -> asyncio.Lock:
    global _SEEN_LOCK
    if _SEEN_LOCK is None:
        _SEEN_LOCK = asyncio.Lock()
    return _SEEN_LOCK

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── Pre-compiled Regular Expressions ──────────────────────────────────────────

# Query Cleaning
RE_CLEAN_CHAT_PREFIX = re.compile(r"\[.*?\]")
RE_CLEAN_PLZ = re.compile(r"(?<!\d)\d{5}(?!\d)")
RE_CLEAN_RADIUS = re.compile(r"\d+\s*km", flags=re.IGNORECASE)
_platform_terms = [
    "kleinanzeigen.de", "ebay.de", "willhaben.at", "egun.de",
    "troostwijkauctions.com", "troostwijk",
    "zoll-auktion.de", "zoll-auktion", "zollauktion",
    "kleinanzeigen", "ebay", "willhaben", "egun", ".de", ".at",
]
_platform_terms.sort(key=len, reverse=True)
RE_CLEAN_PLATFORMS = re.compile(
    r"(?i)(?:" + "|".join(re.escape(term) for term in _platform_terms) + r")"
)

_noise_words = [
    "suche",
    "finde",
    "such",
    "find",
    "schau",
    "schaue",
    "durchsuche",
    "zeig",
    "liste",
    "was kostet",
    "preis für",
    "gibt es",
    "schnäppchen",
    "angebot",
    "umkreis",
    "radius",
    "einen",
    "eine",
    "ein",
    "mir",
    "dem",
    "der",
    "die",
    "das",
    "bitte",
    "im",
    "in",
    "um",
    "von",
    "bis",
    "nähe",
    "für",
    "unter",
    "euro",
    "rosengarten",
    # Österreichische Städte werden NICHT als Noise entfernt –
    # willhaben.at nutzt den Ort im Keyword zur Lokalisierung
    "hamburg",
    "berlin",
    "nach",
    "mit",
    "den",
    "auf",
    "mal",
    "einem",
    "einer",
    "münchen",
    "frankfurt",
    "düsseldorf",
    "köln",
    "hannover",
    "leipzig",
    "bremen",
    "kaufen",
    "verkaufen",
    "preis",
    "günstig",
    "billig",
    "verkaufe",
    "gerade",
    "aktuell",
    "inserate",
    "anzeigen",
]
_noise_words.sort(key=len, reverse=True)
RE_CLEAN_NOISE = re.compile(
    r"(?i)(?:^|(?<=\W))(?:" + "|".join(re.escape(word) for word in _noise_words) + r")(?=\W|$)"
)
RE_CLEAN_SPECIAL_CHARS = re.compile(r"[?!.,;:\-_/]")

# Common Parsing
RE_HTML_TAGS = re.compile(r"<[^>]+>")
RE_PARSE_PRICE = re.compile(r"(\d+(?:\.\d+)?)")

# Kleinanzeigen Parsing
RE_KA_ARTICLES = re.compile(
    r'<article[^>]+data-adid="(\d+)"[^>]*>(.*?)</article>', re.DOTALL
)
RE_KA_TITLE_1 = re.compile(
    r'class="[^"]*text-module-begin[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>', re.DOTALL
)
RE_KA_TITLE_2 = re.compile(
    r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>(.*?)</a>', re.DOTALL
)
RE_KA_PRICE = re.compile(
    r'<p[^>]*class="[^"]*aditem-main--middle--price[^"]*"[^>]*>(.*?)</p>', re.DOTALL
)
RE_KA_LOCATION = re.compile(
    r'<span[^>]*class="[^"]*aditem-main--top--left[^"]*"[^>]*>(.*?)</span>', re.DOTALL
)

# eBay Parsing (neue Struktur ab 2026: data-view=mi:1686 ohne Anführungszeichen, data-listingid)
RE_EBAY_ITEMS_1 = re.compile(
    r'<li[^>]+data-view=mi:1686[^>]+data-listingid=(\d+)[^>]*>(.*?)</li>',
    re.DOTALL,
)
RE_EBAY_ITEMS_2 = re.compile(
    r'<li[^>]+data-listingid=(\d+)[^>]*>(.*?)</li>',
    re.DOTALL,
)
RE_EBAY_TITLE_1 = re.compile(
    r'class=s-card__title[^>]*>.*?<span[^>]*>([^<]+)</span>', re.DOTALL
)
RE_EBAY_TITLE_2 = re.compile(
    r'class="[^"]*s-card__title[^"]*"[^>]*>.*?<span[^>]*>([^<]+)</span>', re.DOTALL
)
RE_EBAY_PRICE = re.compile(
    r's-card__price[^>]*>([^<]+)</span>', re.DOTALL
)
RE_EBAY_LINK = re.compile(
    r'href=(https://(?:www\.)?ebay\.(?:de|com)/itm/\S+?)(?:\s|>|\'|")'
)

# Web Parsing
# ── eGun.de ────────────────────────────────────────────────────────────────────
# eGun nutzt klassisches tabellenbasiertes HTML, ISO-8859-1 Encoding.
# Links: <a href="item.php?id=XXXXX">Titel</a>
# Thumbnail-Links haben leeren Text, Titel-Links haben den Inseratstitel.
RE_EGUN_PRICE = re.compile(
    r"\d[\d.,]+\s*(?:€|EUR|Euro)",
    re.IGNORECASE,
)
RE_EGUN_DATE = re.compile(
    r"(\d{1,2}\s+(?:Tag|Stunde|Minute|Sekunde)e?n?|\d{2}:\d{2})",
    re.IGNORECASE,
)

RE_WEB_HITS = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
RE_WEB_SNIPPETS = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL
)


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
            json.dumps(
                {"seen": seen_list, "updated": datetime.now().isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        log.debug("Seen-Datei speichern: %s", e)


def _make_id(platform: str, listing_id: str) -> str:
    return f"{platform}:{listing_id}"


def _clean_query(query: str) -> str:
    """Bereinigt den Suchbegriff von Rauschen (PLZ, Radius, Plattformen, Füllwörter)."""
    # Chat-Präfixe entfernen
    q = RE_CLEAN_CHAT_PREFIX.sub(" ", query)

    # PLZ (5 Ziffern) - Aggressiver
    q = RE_CLEAN_PLZ.sub(" ", q)

    # Radius (z.B. "20km", "20 km")
    q = RE_CLEAN_RADIUS.sub(" ", q)

    # Plattformnamen und Domains
    q = RE_CLEAN_PLATFORMS.sub(" ", q)

    # Deutsche Stoppwörter/Rauschen für Marktplatz-Suche
    q = RE_CLEAN_NOISE.sub(" ", q)

    # Alle Sonderzeichen entfernen
    q = RE_CLEAN_SPECIAL_CHARS.sub(" ", q)

    # Mehrfache Leerzeichen bereinigen
    q = " ".join(q.split()).strip()
    return q


# ── Preis-Parser ───────────────────────────────────────────────────────────────


def _parse_price(text: str) -> float | None:
    """Extrahiert Preis aus Text wie '149 €', '1.299,00 €', 'VB 80 €'"""
    text = text.replace(".", "").replace(",", ".")
    match = RE_PARSE_PRICE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


# ── Kleinanzeigen.de ───────────────────────────────────────────────────────────


async def _resolve_kleinanzeigen_location_id(
    session: aiohttp.ClientSession,
    location: str,
) -> str | None:
    """Löst PLZ/Ort in die interne Kleinanzeigen Location-ID auf.

    Kleinanzeigen nutzt ein internes URL-Format:
      /s-{PLZ}/{query}/k0l{LOCATION_ID}r{RADIUS}
    Die Location-ID wird über die Ort-Empfehlungs-API aufgelöst.
    """
    try:
        url = f"https://www.kleinanzeigen.de/s-ort-empfehlungen.json?query={quote_plus(location)}"
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
        # Format: {"_0": "Deutschland", "_2811": "21224 Rosengarten"}
        # Den ersten Nicht-_0-Eintrag nehmen (= lokaler Treffer)
        for key, val in data.items():
            if key != "_0" and key.startswith("_"):
                loc_id = key[1:]  # "_2811" → "2811"
                log.debug("Kleinanzeigen Location-ID: %s → %s (%s)", location, loc_id, val)
                return loc_id
    except Exception as e:
        log.debug("Kleinanzeigen Location-ID Fehler: %s", e)
    return None


async def _search_kleinanzeigen(
    session: aiohttp.ClientSession,
    query: str,
    max_price: float | None = None,
    location: str | None = None,
    max_results: int = 10,
    radius_km: int | None = None,
) -> list[dict]:
    """Sucht auf Kleinanzeigen.de (ehemals eBay Kleinanzeigen)."""
    results = []

    # URL aufbauen – Kleinanzeigen nutzt internes Format mit Location-ID
    # Korrekt: /s-{PLZ}/{query}/k0l{LOC_ID}r{RADIUS_KM}
    # Falsch (alt): /s-{location}/{query}/k0?radius=N  (funktioniert nicht)
    q = quote_plus(query)

    if location and radius_km:
        # Location-ID auflösen für korrekte Radius-Suche
        loc_id = await _resolve_kleinanzeigen_location_id(session, location)
        if loc_id:
            loc = quote_plus(location)
            url = f"https://www.kleinanzeigen.de/s-{loc}/{q}/k0l{loc_id}r{int(radius_km)}"
        else:
            # Fallback ohne Location-ID: nur PLZ im Pfad, kein Radius
            log.warning("Kleinanzeigen: Location-ID für '%s' nicht gefunden – kein Radius-Filter", location)
            loc = quote_plus(location)
            url = f"https://www.kleinanzeigen.de/s-{loc}/{q}/k0"
    elif location:
        loc = quote_plus(location)
        url = f"https://www.kleinanzeigen.de/s-{loc}/{q}/k0"
    else:
        url = f"https://www.kleinanzeigen.de/s-{q}/k0"

    # maxPrice als Query-Parameter anhängen (einziger verbleibender QP)
    params = []
    if max_price:
        params.append(f"maxPrice={int(max_price)}")
    if params:
        url += "?" + "&".join(params)

    html = await _fetch_html(url, label="Kleinanzeigen")
    if not html:
        log.warning("Kleinanzeigen: Keine Antwort für '%s'", query)
        return []

    # Inserate parsen
    # Artikel-Blöcke: <article class="aditem ...">
    articles = RE_KA_ARTICLES.findall(html)

    for ad_id, content in articles[:max_results]:
        # Titel
        title_match = RE_KA_TITLE_1.search(content)
        if not title_match:
            title_match = RE_KA_TITLE_2.search(content)
        title = (
            " ".join(RE_HTML_TAGS.sub(" ", title_match.group(1)).split()).strip()
            if title_match
            else ""
        )

        # Preis
        price_match = RE_KA_PRICE.search(content)
        price_text = (
            " ".join(RE_HTML_TAGS.sub(" ", price_match.group(1)).split()).strip()
            if price_match
            else ""
        )
        price = _parse_price(price_text)

        # Ort
        loc_match = RE_KA_LOCATION.search(content)
        location_text = (
            " ".join(RE_HTML_TAGS.sub(" ", loc_match.group(1)).split()).strip()
            if loc_match
            else ""
        )

        if not title:
            continue

        results.append(
            {
                "id": ad_id,
                "platform": "kleinanzeigen",
                "title": title,
                "price": price,
                "price_text": price_text,
                "location": location_text,
                "url": f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}",
            }
        )

    log.info("Kleinanzeigen: %d Inserate gefunden für '%s'", len(results), query)
    return results


# ── eBay.de ────────────────────────────────────────────────────────────────────


async def _fetch_html(url: str, label: str = "web") -> str | None:
    """
    Universelle HTML-Fetch-Kaskade für alle Marktplätze:
      1. Scrapling  – stealth HTTP, kein echter Browser, schnell
      2. aiohttp    – Standard HTTP mit Browser-Headers
      3. Tandem     – echter Headless-Browser (Pi lokal, Port 8765)

    Args:
        url:   Die zu ladende URL
        label: Plattform-Name für Logging (z.B. "eBay", "Kleinanzeigen")
    """
    # 1. Scrapling (stealth HTTP)
    try:
        from scrapling import Fetcher
        fetcher = Fetcher(auto_match=False)
        page = await asyncio.to_thread(
            fetcher.get, url, stealthy_headers=True, follow_redirects=True
        )
        if page and len(str(page.content)) > 500:
            log.debug("%s via Scrapling geholt", label)
            return str(page.content)
    except Exception as e:
        log.debug("Scrapling fehlgeschlagen (%s): %s", label, e)

    # 2. aiohttp mit Browser-Headers
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "DNT": "1",
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    html = await resp.text(errors="replace")
                    if len(html) > 500:
                        log.debug("%s via aiohttp geholt", label)
                        return html
                else:
                    log.debug("%s aiohttp HTTP %s", label, resp.status)
    except Exception as e:
        log.debug("aiohttp fehlgeschlagen (%s): %s", label, e)

    # 3. Tandem Browser (echter Headless-Browser, Pi lokal)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "http://127.0.0.1:8765/navigate",
                json={"url": url},
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    html = data.get("html", "")
                    if len(html) > 500:
                        log.debug("%s via Tandem geholt", label)
                        return html
    except Exception as e:
        log.debug("Tandem nicht verfügbar (%s): %s", label, e)

    log.warning("Alle Fetch-Methoden fehlgeschlagen für %s: %s", label, url)
    return None



async def _search_ebay(
    session: aiohttp.ClientSession,
    query: str,
    max_price: float | None = None,
    max_results: int = 10,
    location: str | None = None,
    radius_km: int | None = None,
) -> list[dict]:
    """Sucht auf eBay.de – nutzt Scrapling → aiohttp → Tandem Kaskade."""
    results = []

    q = quote_plus(query)
    url = f"https://www.ebay.de/sch/i.html?_nkw={q}&_sop=15"
    if max_price:
        url += f"&_udhi={int(max_price)}"
    # PLZ-basierte Umkreissuche: _stpos=PLZ, _sadis=Radius in km
    if location:
        url += f"&_stpos={quote_plus(location)}"
        # eBay unterstützt: 5, 10, 20, 50, 100, 200 km
        if radius_km:
            url += f"&_sadis={int(radius_km)}"

    log.info("eBay URL: %s", url)
    html = await _fetch_html(url, label="eBay")
    if not html:
        log.warning(
            "eBay: Keine Antwort für '%s' (alle Methoden fehlgeschlagen)", query
        )
        return []

    # eBay Artikel parsen (neue Struktur: data-listingid, s-card__title, s-card__price)
    items = RE_EBAY_ITEMS_1.findall(html)
    if not items:
        items = RE_EBAY_ITEMS_2.findall(html)
    if not items:
        log.warning("eBay: Kein Artikel-Muster gefunden – HTML-Struktur geändert?")

    for item_id, content in items:
        if len(results) >= max_results:
            break

        # Titel
        title_match = RE_EBAY_TITLE_1.search(content)
        if not title_match:
            title_match = RE_EBAY_TITLE_2.search(content)
        title = (
            " ".join(RE_HTML_TAGS.sub(" ", title_match.group(1)).split()).strip()
            if title_match
            else ""
        )
        if not title or "Shop on eBay" in title or "Anzeige" in title:
            continue

        # Preis
        price_match = RE_EBAY_PRICE.search(content)
        price_text = (
            " ".join(RE_HTML_TAGS.sub(" ", price_match.group(1)).split()).strip()
            if price_match
            else ""
        )
        price = _parse_price(price_text)

        # Link – eBay nutzt ebay.com/itm/ oder ebay.de/itm/ ohne Anführungszeichen
        link_match = RE_EBAY_LINK.search(content)
        if link_match:
            link = link_match.group(1).split("?")[0]
            # Normalisieren auf ebay.de
            link = link.replace("ebay.com/itm/", "ebay.de/itm/")
        else:
            link = f"https://www.ebay.de/itm/{item_id}"

        results.append(
            {
                "id": str(item_id),
                "platform": "ebay",
                "title": title,
                "price": price,
                "price_text": price_text,
                "location": "",
                "url": link,
            }
        )

    log.info("eBay: %d Artikel gefunden für '%s'", len(results), query)
    return results


# ── eGun.de ────────────────────────────────────────────────────────────────────


async def _search_egun(
    session: aiohttp.ClientSession,
    query: str,
    max_price: float | None = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Sucht auf eGun.de – Marktplatz für Jäger, Schützen und Angler.

    HTML-Struktur (tabellenbasiert, ISO-8859-1):
      - Jedes Inserat hat ZWEI Links auf item.php?id=XXXXX:
        1. Thumbnail-Link (leerer Link-Text)
        2. Titel-Link (enthält den Anzeigentitel)
      - TDs in der TR: [Titel, Preis, Stück/Gebote, Restzeit]
    """
    results: list[dict] = []
    q = quote_plus(query)

    url = (
        "https://www.egun.de/market/list_items.php"
        f"?mode=qry&plusdescr=off&wheremode=and&query={q}&quick=1"
        "&order=date&asdes=desc"
    )
    if max_price:
        url += f"&maxpr={int(max_price)}"

    # eGun liefert ISO-8859-1 – explizit decodieren statt _fetch_html zu nutzen
    html = None
    try:
        egun_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Referer": "https://www.egun.de/",
        }
        async with session.get(
            url, headers=egun_headers, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status == 200:
                raw = await resp.read()
                html = raw.decode("latin-1", errors="replace")
                log.debug("eGun: HTTP 200, %d Bytes", len(html))
            else:
                log.warning("eGun: HTTP %s für '%s'", resp.status, query)
    except Exception as e:
        log.warning("eGun: Fetch-Fehler: %s", e)

    if not html:
        return []

    # ── Parsen ────────────────────────────────────────────────────────────
    # Thumbnail-Links haben leeren Text, Titel-Links haben Text.
    # Muster: <a href="item.php?id=ID">Titel</a>
    item_link_re = re.compile(
        r'<a\s[^>]*href="[^"]*item\.php\?id=(\d+)[^"]*"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    seen_ids: set[str] = set()

    for m in item_link_re.finditer(html):
        item_id = m.group(1)
        link_text = RE_HTML_TAGS.sub("", m.group(2)).strip()

        # Thumbnail-Links überspringen (leerer Text)
        if not link_text or len(link_text) < 4:
            continue
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        # Preis aus den nächsten ~400 Zeichen nach diesem Link
        segment = html[m.end() : m.end() + 400]
        price_match = RE_EGUN_PRICE.search(segment)
        price_text = price_match.group(0).strip() if price_match else ""
        price = _parse_price(price_text) if price_text else None

        # Restzeit / Datum
        date_match = RE_EGUN_DATE.search(segment)
        date_str = date_match.group(1) if date_match else ""

        results.append({
            "id": item_id,
            "platform": "egun",
            "title": link_text,
            "price": price,
            "price_text": price_text,
            "location": date_str,
            "url": f"https://www.egun.de/market/item.php?id={item_id}",
        })

        if len(results) >= max_results:
            break

    log.info("eGun: %d Inserate gefunden für '%s'", len(results), query)
    return results


# ── Troostwijk.com ─────────────────────────────────────────────────────────────
#
# Live-Debugging ergab drei Fehler in der alten Implementierung:
#   1. Domain war troostwijk.com → korrekt: troostwijkauctions.com
#   2. Pfad war /de/a/ → korrekt: /de/l/
#   3. Suchparameter war q= → korrekt: searchTerm=
#      (q= liefert immer 0 Ergebnisse; searchTerm= liefert 131+)
#
# Datenquelle: /_next/data/{buildId}/de/search.json?searchTerm=X&countries=DE
# Lot-ID:      A\d+-\d+-\d+  (z.B. A7-44764-172, A1-44837-40)
# Pagination:  &page=2, &page=3 ...  (20 Lots pro Seite)
# Lot-URL:     /de/l/{urlSlug}

_TW_BASE = "https://www.troostwijkauctions.com"
_TW_BUILD_ID_CACHE: dict[str, str] = {}
_TW_BUILD_ID_LOCK: asyncio.Lock | None = None  # lazy-init (loop muss bereits laufen)

_TW_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "application/json, text/html, */*;q=0.8",
    "Referer": "https://www.troostwijkauctions.com/de",
}


async def _tw_get_build_id(session: aiohttp.ClientSession) -> str | None:
    """
    Holt die aktuelle Next.js BuildId aus der Troostwijk-Hauptseite.
    Gecacht bis das Programm neu startet (ändert sich nur bei Deployments).
    Bei 404-Antwort wird der Cache geleert damit beim nächsten Aufruf frisch geholt wird.
    Lock verhindert dass mehrere parallele Monitore gleichzeitig fetchen.
    """
    global _TW_BUILD_ID_LOCK
    if _TW_BUILD_ID_LOCK is None:
        _TW_BUILD_ID_LOCK = asyncio.Lock()

    # Schnellpfad ohne Lock (cache hit)
    cached = _TW_BUILD_ID_CACHE.get("twk")
    if cached:
        return cached

    # Kritischer Abschnitt: nur ein Fetch zur selben Zeit
    async with _TW_BUILD_ID_LOCK:
        # Nochmals prüfen – anderer Task hat ggf. inzwischen befüllt
        cached = _TW_BUILD_ID_CACHE.get("twk")
        if cached:
            return cached
        try:
            async with session.get(
                f"{_TW_BASE}/de",
                headers=_TW_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            m = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
            if m:
                bid = m.group(1)
                _TW_BUILD_ID_CACHE["twk"] = bid
                log.debug("Troostwijk BuildId: %s", bid)
                return bid
        except Exception as exc:
            log.debug("Troostwijk BuildId Fehler: %s", exc)
    return None


async def _search_troostwijk(
    session: aiohttp.ClientSession,
    query: str,
    location: str = "",
    country: str = "DE",
    max_price: float | None = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Sucht auf troostwijkauctions.com via Next.js Data-API.

    Korrekte API:
        GET /_next/data/{buildId}/de/search.json?searchTerm=QUERY&countries=DE&page=N
        → pageProps.lots[]  (20 pro Seite)
        → pageProps.searchTotalSize

    Lot-Felder: id (UUID), displayId (A7-44764-172), title, urlSlug,
                location.city, currentBidAmount.cents, endDate (Unix-TS),
                biddingStatus
    """
    results: list[dict] = []

    build_id = await _tw_get_build_id(session)
    if not build_id:
        log.warning("Troostwijk: BuildId nicht verfügbar")
        return []

    encoded_q = quote_plus(query)
    pages_needed = max(1, (max_results + 19) // 20)

    for page in range(1, pages_needed + 1):
        api_url = (
            f"{_TW_BASE}/_next/data/{build_id}/de/search.json"
            f"?searchTerm={encoded_q}&countries={country}&page={page}"
        )
        try:
            async with session.get(
                api_url,
                headers=_TW_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 404:
                    # BuildId veraltet → Cache leeren
                    _TW_BUILD_ID_CACHE.clear()
                    log.warning("Troostwijk: BuildId veraltet (404) – bitte erneut versuchen")
                    break
                if resp.status != 200:
                    log.warning("Troostwijk: HTTP %s für Seite %d", resp.status, page)
                    break
                data = await resp.json(content_type=None)
        except Exception as exc:
            log.warning("Troostwijk Fetch Fehler Seite %d: %s", page, exc)
            break

        page_props = data.get("pageProps", {})
        lots = page_props.get("lots", [])
        if not lots:
            log.debug("Troostwijk: Keine Lots auf Seite %d", page)
            break

        for lot in lots:
            if len(results) >= max_results:
                break

            # Preis: Cents → Euro
            bid_data = lot.get("currentBidAmount") or {}
            bid_cents = bid_data.get("cents")
            price = bid_cents / 100.0 if bid_cents else None

            # Preisfilter
            if max_price is not None and price is not None and price > max_price:
                continue

            # URL aus urlSlug
            url_slug = lot.get("urlSlug", "")
            lot_url = f"{_TW_BASE}/de/l/{url_slug}" if url_slug else ""

            # Standort
            loc = lot.get("location") or {}
            city = loc.get("city", "")
            cc = loc.get("countryCode", "").upper()
            location_str = f"{city}, {cc}".strip(", ") if city or cc else ""

            # Enddatum
            end_ts = lot.get("endDate")
            from datetime import datetime as _dt
            end_str = _dt.fromtimestamp(end_ts).strftime("%d.%m.%Y %H:%M") if end_ts else ""

            results.append({
                "id":         lot.get("displayId") or lot.get("id", ""),
                "platform":   "troostwijk",
                "title":      (lot.get("title") or "")[:100],
                "price":      price,
                "price_text": f"{price:.0f} \u20ac" if price else "",
                "location":   location_str,
                "url":        lot_url,
                "end_date":   end_str,
                "status":     lot.get("biddingStatus", ""),
            })

        total = page_props.get("searchTotalSize", 0)
        log.debug("Troostwijk Seite %d/%d: %d Lots (gesamt: %d)",
                  page, pages_needed, len(lots), total)

        if len(lots) < 20:
            break  # letzte Seite

    log.info("Troostwijk: %d Lots für '%s'", len(results), query)
    return results


# ── Geocoding-Hilfsfunktionen (Nominatim/OSM) ────────────────────────────────

_GEOCODE_CACHE: dict[str, tuple[float, float] | None] = {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinienentfernung in km zwischen zwei Koordinatenpaaren (Haversine)."""
    import math
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _nominatim_query(
    session: aiohttp.ClientSession, params: dict
) -> tuple[float, float] | None:
    """Ruft Nominatim ab und gibt (lat, lon) zurück oder None bei Fehler."""
    try:
        async with session.get(
            "https://nominatim.openstreetmap.org/search",
            params={**params, "format": "json", "limit": "1"},
            headers={"User-Agent": "PiClaw/1.0 (contact@piclaw.de)"},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as exc:
        log.debug("Nominatim Fehler: %s", exc)
    return None


async def _plz_to_coords(
    session: aiohttp.ClientSession, plz: str, country: str
) -> tuple[float, float] | None:
    """Geocodiert eine PLZ → (lat, lon). Ergebnis wird prozessweit gecacht."""
    key = f"plz:{country}:{plz}"
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    result = await _nominatim_query(session, {"postalcode": plz, "country": country})
    _GEOCODE_CACHE[key] = result
    return result


async def _city_to_coords(
    session: aiohttp.ClientSession, city: str, country_code: str
) -> tuple[float, float] | None:
    """Geocodiert einen Stadtnamen → (lat, lon). Ergebnis wird prozessweit gecacht."""
    key = f"city:{country_code.lower()}:{city.lower()}"
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    result = await _nominatim_query(session, {"city": city, "country": country_code.lower()})
    _GEOCODE_CACHE[key] = result
    return result


async def _search_troostwijk_auctions(
    session: aiohttp.ClientSession,
    country: str = "de",
    city_filter: str | None = None,
    max_results: int = 24,
    plz: str | None = None,
    radius_km: int | None = None,
) -> list[dict]:
    """
    Sucht auf troostwijkauctions.com nach Auktions-Events (nicht einzelne Lose).

    Anders als _search_troostwijk() (die nach Artikeln sucht) überwacht diese
    Funktion ganze Auktionsveranstaltungen und meldet neue Events.

    API: /_next/data/{buildId}/de/auctions.json?countries={country}&page={page}
    Rückgabe: Auktionen mit Name, Losmenge, Start/Ende, URL.

    Standort-Filter (Priorität):
      1. PLZ + Radius → Geocoding + Haversine-Distanzberechnung gegen
         collectionDays[].city jeder Auktion.
      2. city_filter → Teilstring-Matching im Auktionsnamen UND in
         collectionDays[].city (Fallback ohne Geocoding).
    """
    build_id = await _tw_get_build_id(session)
    if not build_id:
        log.warning("Troostwijk Auctions: BuildId nicht verfügbar")
        return []

    country_lc = (country or "de").lower()
    results: list[dict] = []
    page = 1

    # ── Radius-Modus: PLZ → Koordinaten auflösen ──────────────────────
    origin_coords: tuple[float, float] | None = None
    if plz and radius_km:
        origin_coords = await _plz_to_coords(session, plz, country_lc)
        if not origin_coords:
            if not city_filter:
                log.warning(
                    "Troostwijk Radius: PLZ %s/%s nicht geocodierbar, kein city_filter – "
                    "überspringe Lauf um ungefiltertes Ergebnis zu vermeiden",
                    country_lc, plz,
                )
                return []
            log.warning(
                "Troostwijk Radius: PLZ %s/%s konnte nicht geocodiert werden – "
                "Fallback auf city_filter",
                country_lc, plz,
            )
        else:
            log.info(
                "Troostwijk Radius: PLZ %s → (%.4f, %.4f), Radius %d km",
                plz, origin_coords[0], origin_coords[1], radius_km,
            )

    # Beim Radius-Modus mehr Seiten laden, da viele Auktionen ausgefiltert werden
    max_pages = 10 if origin_coords else 5

    while len(results) < max_results and page <= max_pages:
        api_url = (
            f"{_TW_BASE}/_next/data/{build_id}/de/auctions.json"
            f"?countries={country_lc}&page={page}"
        )
        try:
            async with session.get(
                api_url,
                headers=_TW_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 404:
                    _TW_BUILD_ID_CACHE.clear()
                    log.warning("Troostwijk Auctions: BuildId veraltet (404) – Cache geleert")
                    break
                if resp.status != 200:
                    log.warning("Troostwijk Auctions: HTTP %s Seite %d", resp.status, page)
                    break
                data = await resp.json(content_type=None)
        except Exception as exc:
            log.warning("Troostwijk Auctions Fetch Fehler Seite %d: %s", page, exc)
            break

        page_props = data.get("pageProps", {})
        list_data = page_props.get("listData") or {}
        total = page_props.get("totalSize", 0)

        # listData kann dict (keyed by UUID), list oder leer sein
        if isinstance(list_data, dict):
            auctions = list(list_data.values())
        elif isinstance(list_data, list):
            auctions = list_data
        else:
            log.warning("Troostwijk Auctions: unbekanntes listData-Format auf Seite %d: %s", page, type(list_data))
            break

        if not auctions:
            log.debug("Troostwijk Auctions: Keine Auktionen auf Seite %d (total=%d)", page, total)
            break

        for auction in auctions:
            if len(results) >= max_results:
                break

            name = (auction.get("name") or "").strip()
            collection_days = auction.get("collectionDays") or []

            # ── Standort-Filterung ────────────────────────────────────
            auction_city = ""
            auction_cc = ""
            distance_km: float | None = None

            # Primär: Stadt aus collectionDays extrahieren
            for cd in collection_days:
                if cd.get("city"):
                    auction_city = cd["city"]
                    auction_cc = (cd.get("countryCode") or country_lc).upper()
                    break

            # MODUS 1: Radius-Filter (PLZ + Radius gegeben + Origin geocodiert)
            if origin_coords and radius_km:
                if not auction_city:
                    # Keine Stadt in collectionDays → kann Entfernung nicht prüfen
                    # Nur aufnehmen wenn auch city_filter matched (Name-Check)
                    if city_filter and city_filter.lower() in name.lower():
                        pass  # Name-Match als Fallback
                    else:
                        continue  # Keine Standortinfo → überspringen

                if auction_city:
                    # Stadt → Koordinaten auflösen
                    auction_coords = await _city_to_coords(
                        session, auction_city, auction_cc or country_lc
                    )
                    if auction_coords:
                        distance_km = _haversine_km(
                            origin_coords[0], origin_coords[1],
                            auction_coords[0], auction_coords[1],
                        )
                        if distance_km > radius_km:
                            log.debug(
                                "Troostwijk Radius: '%s' in %s → %.0f km (> %d km) – gefiltert",
                                name[:50], auction_city, distance_km, radius_km,
                            )
                            continue
                        log.debug(
                            "Troostwijk Radius: '%s' in %s → %.0f km ✓",
                            name[:50], auction_city, distance_km,
                        )
                    else:
                        # Stadt konnte nicht geocodiert werden → Name-Fallback
                        log.debug(
                            "Troostwijk Radius: '%s' – Stadt '%s' nicht geocodierbar",
                            name[:50], auction_city,
                        )
                        continue

            # MODUS 2: Stadt-Filter (string matching, bisheriges Verhalten)
            elif city_filter:
                city_lower = city_filter.lower()
                name_match = city_lower in name.lower()
                collection_match = any(
                    city_lower in (cd.get("city") or "").lower()
                    for cd in collection_days
                )
                if not name_match and not collection_match:
                    continue

            # ── Ergebnis aufbauen ─────────────────────────────────────
            display_id = auction.get("displayId", "")
            url_slug = auction.get("urlSlug", "")
            auction_url = f"{_TW_BASE}/de/a/{url_slug}" if url_slug else ""

            start_ts = auction.get("startDate")
            end_ts = auction.get("endDate") or auction.get("minEndDate")
            from datetime import datetime as _dt
            start_str = _dt.fromtimestamp(start_ts).strftime("%d.%m.%Y") if start_ts else ""
            end_str   = _dt.fromtimestamp(end_ts).strftime("%d.%m.%Y %H:%M") if end_ts else ""

            lot_count = auction.get("lotCount", 0)
            status    = auction.get("biddingStatus", "")

            # Standort-String für Anzeige
            if auction_city:
                location_str = f"{auction_city}, {auction_cc}" if auction_cc else auction_city
            elif city_filter:
                location_str = city_filter
            else:
                location_str = country.upper()

            # Distanz anhängen wenn berechnet
            if distance_km is not None:
                location_str += f" ({distance_km:.0f} km)"

            results.append({
                "id":         display_id,
                "platform":   "troostwijk_auctions",
                "title":      name[:120],
                "price":      None,
                "price_text": f"{lot_count} Lose" if lot_count else "",
                "location":   location_str,
                "url":        auction_url,
                "start_date": start_str,
                "end_date":   end_str,
                "status":     status,
                "lot_count":  lot_count,
            })

        log.debug(
            "Troostwijk Auctions Seite %d: %d Auktionen (gesamt: %d, gefiltert: %d)",
            page, len(auctions), total, len(results),
        )

        # Letzte Seite oder genug Ergebnisse
        if len(auctions) < 24 or (total and len(results) >= total):
            break
        page += 1

    log.info(
        "Troostwijk Auctions: %d Auktionen gefunden (Land=%s, Stadt=%s)",
        len(results), country, city_filter or "alle",
    )
    return results


# ── Willhaben Standort-Mapping (areaId) ──────────────────────────────────────
# Willhaben nutzt interne areaIds für den Standortfilter im webapi-Endpoint.
# Bundesland-IDs: 100er-Schritte. Bezirks/Stadt-IDs: Bundesland + 2 Ziffern.

_WH_AREA_IDS: dict[str, str] = {
    # Bundesländer
    "wien":              "100",
    "vienna":            "100",
    "niederösterreich":  "200",
    "niederoesterreich": "200",
    "niederosterreich":  "200",
    "lower austria":     "200",
    "burgenland":        "300",
    "oberösterreich":    "400",
    "oberoesterreich":   "400",
    "oberosterreich":    "400",
    "upper austria":     "400",
    "salzburg":          "500",
    "steiermark":        "600",
    "styria":            "600",
    "kärnten":           "700",
    "kaernten":          "700",
    "carinthia":         "700",
    "tirol":             "800",
    "tyrol":             "800",
    "vorarlberg":        "900",
    # Städte / Bezirke
    "graz":              "601",
    "graz-umgebung":     "602",
    "deutschlandsberg":  "603",
    "leibnitz":          "610",
    "leoben":            "604",
    "bruck an der mur":  "605",
    "kapfenberg":        "605",
    "weiz":              "614",
    "linz":              "401",
    "wels":              "404",
    "steyr":             "411",
    "salzburg stadt":    "501",
    "salzburg city":     "501",
    "innsbruck":         "801",
    "innsbruck land":    "803",
    "klagenfurt":        "701",
    "villach":           "703",
    "st. pölten":        "202",
    "st pölten":         "202",
    "st. poelten":       "202",
    "wiener neustadt":   "216",
    "krems":             "206",
    "eisenstadt":        "301",
    "bregenz":           "901",
    "dornbirn":          "902",
    "feldkirch":         "903",
}


def _resolve_willhaben_location(location: str | None) -> str | None:
    """
    Gibt die Willhaben areaId für einen Standort zurück.
    Beispiele:
      "Graz"       → "601"
      "Steiermark" → "600"
      "Wien"       → "100"
    Unbekannte Orte: None (österreichweit suchen).
    """
    if not location:
        return None
    key = location.strip().lower()
    # Direkter Treffer
    if key in _WH_AREA_IDS:
        return _WH_AREA_IDS[key]
    # Teilstring-Treffer (z.B. "Graz, Österreich" → "graz" → "601")
    for k, v in sorted(_WH_AREA_IDS.items(), key=lambda x: len(x[0]), reverse=True):
        if k in key:
            return v
    return None


async def _fetch_willhaben_area_id(location: str) -> str | None:
    """
    Ermittelt die echte areaId von Willhaben für einen Standort,
    indem die Willhaben-Suchseite über Scrapling geladen und der
    API-Request aus dem Netzwerk-Traffic extrahiert wird.
    Fallback: statisches Mapping.
    """
    try:
        from scrapling import Fetcher
        search_url = f"https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=test&areaId=0&location={location}"
        fetcher = Fetcher(auto_match=False)
        page = await asyncio.to_thread(
            fetcher.get, search_url, stealthy_headers=True, follow_redirects=True
        )
        if page:
            import re
            # Suche nach areaId in der API-URL oder im Page-State
            match = re.search(r'"areaId"\s*:\s*"?(\d+)"?', str(page.content))
            if match:
                log.debug("Willhaben areaId via Scrapling: %s → %s", location, match.group(1))
                return match.group(1)
    except Exception as e:
        log.debug("Scrapling areaId-Lookup fehlgeschlagen: %s", e)
    return None


async def _parse_willhaben_html(url: str, max_results: int, max_price: float | None) -> list[dict]:
    """
    HTML-Fallback für Willhaben wenn die JSON-API nicht antwortet.
    Nutzt _fetch_html Kaskade (Scrapling → aiohttp → Tandem).
    """
    import re as _re
    html = await _fetch_html(url, label="Willhaben-HTML")
    if not html:
        return []

    results = []
    # Willhaben HTML: Inserate sind in <article data-testid="advert-listitem">
    # oder alternativ in Script-Tags als JSON (Next.js __NEXT_DATA__)
    # Ansatz 1: __NEXT_DATA__ JSON aus Script-Tag
    next_data_match = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.DOTALL)
    if next_data_match:
        try:
            import json as _json
            nd = _json.loads(next_data_match.group(1))
            # Pfad: props.pageProps.searchResult.advertSummaryList.advertSummary
            adverts = (nd.get("props", {})
                         .get("pageProps", {})
                         .get("searchResult", {})
                         .get("advertSummaryList", {})
                         .get("advertSummary", []))
            def _attr(item, name):
                for a in item.get("attributes", {}).get("attribute", []):
                    if a.get("name") == name:
                        v = a.get("values", [])
                        return v[0] if v else ""
                return ""
            for item in adverts:
                if len(results) >= max_results:
                    break
                title = _attr(item, "HEADING")
                price_text = _attr(item, "PRICE_FOR_DISPLAY") or _attr(item, "PRICE")
                location_text = _attr(item, "LOCATION")
                seo_url = _attr(item, "SEO_URL")
                price = _parse_price(price_text)
                if max_price and price and price > max_price:
                    continue
                if not title:
                    continue
                item_id = str(item.get("id", ""))
                link = (f"https://www.willhaben.at/iad/{seo_url.lstrip('/')}"
                        if seo_url else
                        f"https://www.willhaben.at/iad/kaufen-und-verkaufen/d/{item_id}")
                results.append({
                    "id": item_id, "platform": "willhaben",
                    "title": title, "price": price, "price_text": price_text,
                    "location": location_text, "url": link,
                })
            if results:
                log.info("Willhaben HTML-Fallback (__NEXT_DATA__): %d Inserate", len(results))
                return results
        except Exception as e:
            log.debug("Willhaben __NEXT_DATA__ Parse-Fehler: %s", e)

    log.warning("Willhaben HTML-Fallback: Kein parse-bares Format gefunden")
    return results


async def _search_willhaben(
    session: aiohttp.ClientSession,
    query: str,
    max_price: float | None = None,
    max_results: int = 10,
    location: str | None = None,
    radius_km: int | None = None,
) -> list[dict]:
    """Sucht auf willhaben.at via JSON-API (mit Session-Cookie)."""
    results = []

    WH_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "de-AT,de;q=0.9",
        "x-wh-client": "api@willhaben.at;responsive_web;server;1.0.0;desktop",
        "Referer": "https://www.willhaben.at/iad/kaufen-und-verkaufen",
        "DNT": "1",
    }

    # Schritt 1: Session-Cookie holen (ohne Cookie → HTTP 500)
    try:
        async with aiohttp.ClientSession() as wh_session:
            try:
                async with wh_session.get(
                    "https://www.willhaben.at/iad/kaufen-und-verkaufen",
                    headers={"User-Agent": WH_HEADERS["User-Agent"]},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    log.debug("Willhaben Cookie-Fetch: HTTP %s", resp.status)
            except Exception as e:
                log.debug("Willhaben Cookie-Fetch Fehler: %s", e)

            # Schritt 2: API-Aufruf mit Session (Cookies werden automatisch mitgeschickt)
            params = {
                "keyword": query,
                "rows": str(max_results),
                "isNavigation": "true",
                "sort": "1",  # Neueste zuerst
            }
            if max_price:
                params["PRICE_TO"] = str(int(max_price))
            # Willhaben nutzt areaId als Query-Parameter für Standortfilter
            # 1. Statisches Mapping (schnell, die meisten Städte)
            _wh_area_id = _resolve_willhaben_location(location)
            # 2. Dynamisch via Scrapling falls unbekannter Ort
            if not _wh_area_id and location:
                _wh_area_id = await _fetch_willhaben_area_id(location)
            if _wh_area_id:
                params["areaId"] = _wh_area_id
                log.debug("Willhaben Standortfilter: %s → areaId=%s", location, _wh_area_id)
            elif location:
                log.debug("Willhaben: Unbekannter Ort '%s' – österreichweit", location)
            url = "https://www.willhaben.at/webapi/iad/search/atz/seo/kaufen-und-verkaufen/marktplatz"

            try:
                async with wh_session.get(
                    url,
                    params=params,
                    headers=WH_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        log.debug("Willhaben API HTTP %s – versuche HTML-Fallback", resp.status)
                        # Fallback: HTML-Seite via _fetch_html Kaskade
                        from urllib.parse import urlencode
                        fallback_url = (
                            f"https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz"
                            f"?{urlencode(params)}"
                        )
                        return await _parse_willhaben_html(fallback_url, max_results, max_price)
                    data = await resp.json(content_type=None)
            except Exception as e:
                log.debug("Willhaben API Fehler: %s – versuche HTML-Fallback", e)
                from urllib.parse import urlencode
                fallback_url = (
                    f"https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz"
                    f"?{urlencode(params)}"
                )
                return await _parse_willhaben_html(fallback_url, max_results, max_price)
    except Exception as e:
        log.debug("Willhaben Session Fehler: %s", e)
        return []

    # JSON parsen: advertSummaryList.advertSummary[]
    adverts = data.get("advertSummaryList", {}).get("advertSummary", [])

    def _attr(item: dict, name: str) -> str:
        for a in item.get("attributes", {}).get("attribute", []):
            if a.get("name") == name:
                vals = a.get("values", [])
                return vals[0] if vals else ""
        return ""

    for item in adverts:
        if len(results) >= max_results:
            break

        item_id = str(item.get("id", ""))
        if not item_id:
            continue

        title = _attr(item, "HEADING")
        price_text = _attr(item, "PRICE_FOR_DISPLAY") or _attr(item, "PRICE")
        location_text = _attr(item, "LOCATION")
        seo_url = _attr(item, "SEO_URL")
        price = _parse_price(price_text)

        if max_price and price and price > max_price:
            continue
        if not title:
            continue

        # Link aus SEO_URL oder Fallback
        if seo_url:
            link = f"https://www.willhaben.at/iad/{seo_url.lstrip('/')}"
        else:
            link = f"https://www.willhaben.at/iad/kaufen-und-verkaufen/d/{item_id}"

        results.append(
            {
                "id": item_id,
                "platform": "willhaben",
                "title": title,
                "price": price,
                "price_text": price_text,
                "location": location_text,
                "url": link,
            }
        )

    log.info("Willhaben: %d Inserate gefunden für '%s'", len(results), query)
    return results


# ── Zoll-Auktion.de ────────────────────────────────────────────────────────────
#
# Das Auktionshaus von Bund, Ländern und Gemeinden.
# Behörden versteigern hier Fahrzeuge, Elektronik, Werkzeuge, etc.
#
# Suchseite: /auktion/auktionsuebersicht.php?searchstring=X&plz=PLZ&umkreis=RADIUS
#   Umkreis-Werte: 20, 50, 100, 250, 500 (nativ unterstützt!)
#   Preis-Filter:  preis_bis=MAXPRICE
#   Sortierung:    sortierfeld=enddatum  sortierrichtung=asc
#
# Produkt-URL: /auktion/produkt/SLUG/ID  (ID = numerisch, z.B. 953552)
# Standort in Ergebnissen: "PLZ Ort" (z.B. "44801 Bochum")

_ZA_BASE = "https://www.zoll-auktion.de"

# Pre-compiled regex patterns for Zoll-Auktion parsing
RE_ZA_PRODUCT_LINK = re.compile(
    r'<a[^>]+href="[^"]*?/produkt/([^"]+?)/(\d+)"[^>]*(?:title="([^"]*)")?[^>]*>',
    re.DOTALL | re.IGNORECASE,
)
RE_ZA_PRICE = re.compile(
    r"([\d.,]+)\s*EUR",
    re.IGNORECASE,
)
RE_ZA_LOCATION = re.compile(
    r"(\d{5})\s+([A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\s\-]+)",
)
RE_ZA_RESTZEIT = re.compile(
    r"(?:noch\s+)?((?:\d+\s+Tag[e]?\s+)?\d+\s+Std\.\s+\d+\s+Min\.)",
    re.IGNORECASE,
)
RE_ZA_GEBOTE = re.compile(r"(\d+)\s+Gebot", re.IGNORECASE)

# Zoll-Auktion Umkreis → nächster unterstützter Wert
_ZA_RADII = [20, 50, 100, 250, 500]


def _za_nearest_radius(km: int) -> int:
    """Rundet auf den nächstgrößeren von Zoll-Auktion unterstützten Radius."""
    for r in _ZA_RADII:
        if km <= r:
            return r
    return 500


async def _search_zoll_auktion(
    session: aiohttp.ClientSession,
    query: str,
    max_price: float | None = None,
    max_results: int = 10,
    location: str | None = None,
    radius_km: int | None = None,
) -> list[dict]:
    """
    Sucht auf zoll-auktion.de – Versteigerungen der öffentlichen Hand.

    Unterstützt native PLZ + Umkreis-Suche (20/50/100/250/500 km).
    """
    results: list[dict] = []

    q = quote_plus(query)
    url = (
        f"{_ZA_BASE}/auktion/auktionsuebersicht.php"
        f"?searchstring={q}&kategorie=&submit=Suchen"
        f"&sortierfeld=enddatum&sortierrichtung=asc"
    )

    # PLZ + Umkreis (nativ unterstützt!)
    if location and re.fullmatch(r"\d{5}", location.strip()):
        url += f"&plz={location.strip()}"
        if radius_km:
            url += f"&umkreis={_za_nearest_radius(radius_km)}"

    # Preisfilter
    if max_price:
        url += f"&preis_bis={int(max_price)}"

    log.info("Zoll-Auktion URL: %s", url)
    html = await _fetch_html(url, label="Zoll-Auktion")
    if not html:
        log.warning("Zoll-Auktion: Keine Antwort für '%s'", query)
        return []

    # ── Ergebnisse parsen ─────────────────────────────────────────────
    # Strategie: Produkt-Links finden (href="...produkt/SLUG/ID"),
    # dann umgebenden Text für Preis, Ort, Restzeit parsen.
    seen_ids: set[str] = set()

    for m in RE_ZA_PRODUCT_LINK.finditer(html):
        slug = m.group(1)
        item_id = m.group(2)
        title_attr = m.group(3) or ""

        # Deduplizieren (jedes Inserat hat mehrere Links – Bild + Titel)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        # Titel aus title-Attribut oder Link-Text
        title = RE_HTML_TAGS.sub("", title_attr).strip()
        if not title or len(title) < 4:
            # Fallback: Link-Inhalt
            link_end = html.find("</a>", m.end())
            if link_end > 0:
                link_text = RE_HTML_TAGS.sub("", html[m.end():link_end]).strip()
                if len(link_text) > 4:
                    title = link_text
        if not title or len(title) < 4:
            continue

        # Kontext: 800 Zeichen nach dem Link für Preis/Ort/Restzeit
        segment = html[m.start():m.start() + 1500]

        # Preis
        price_match = RE_ZA_PRICE.search(segment)
        price_text = price_match.group(0).strip() if price_match else ""
        price = _parse_price(price_text) if price_text else None

        # Preisfilter (serverseitig ist bereits gefiltert, aber sicherheitshalber)
        if max_price and price and price > max_price:
            continue

        # Standort (PLZ + Ort)
        loc_match = RE_ZA_LOCATION.search(segment)
        location_str = (
            f"{loc_match.group(1)} {loc_match.group(2).strip()}"
            if loc_match else ""
        )

        # Restzeit
        rest_match = RE_ZA_RESTZEIT.search(segment)
        restzeit = rest_match.group(1).strip() if rest_match else ""

        # Gebote
        gebote_match = RE_ZA_GEBOTE.search(segment)
        gebote = int(gebote_match.group(1)) if gebote_match else 0

        results.append({
            "id":         item_id,
            "platform":   "zoll_auktion",
            "title":      title[:120],
            "price":      price,
            "price_text": price_text,
            "location":   location_str,
            "url":        f"{_ZA_BASE}/auktion/produkt/{slug}/{item_id}",
            "restzeit":   restzeit,
            "gebote":     gebote,
        })

        if len(results) >= max_results:
            break

    log.info("Zoll-Auktion: %d Inserate gefunden für '%s'", len(results), query)
    return results


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
    hits = RE_WEB_HITS.findall(html)
    snippets = RE_WEB_SNIPPETS.findall(html)

    for i, (href, title) in enumerate(hits[:max_results]):
        title_clean = RE_HTML_TAGS.sub("", title).strip()
        snippet = RE_HTML_TAGS.sub("", snippets[i]).strip() if i < len(snippets) else ""
        price = _parse_price(snippet)

        results.append(
            {
                "id": hashlib.md5(href.encode()).hexdigest()[:12],
                "platform": "web",
                "title": title_clean,
                "price": price,
                "price_text": f"{price:.0f} €" if price else "",
                "location": "",
                "url": href,
                "snippet": snippet,
            }
        )

    log.info("Websuche: %d Treffer für '%s'", len(results), query)
    return results


# ── Haupt-Funktion ─────────────────────────────────────────────────────────────


async def marketplace_search(
    query: str,
    platforms: list[str] | None = None,
    max_price: float | None = None,
    location: str | None = None,
    max_results: int = 10,
    notify_all: bool = True,
    radius_km: int | None = None,
    country: str = "de",
) -> dict:
    """
    Durchsucht Marktplätze nach neuen Inseraten.

    Args:
        query:       Suchbegriff (z.B. "Raspberry Pi 5")
        platforms:   ["kleinanzeigen", "ebay", "web"] – default: alle
        max_price:   Maximaler Preis in Euro
        location:    Ort/PLZ für Kleinanzeigen; bei troostwijk_auctions: Stadtname-Filter
        max_results: Max. Ergebnisse pro Plattform
        notify_all:  True = alle melden, False = nur neue (Standard)
        country:     ISO-Ländercode für troostwijk_auctions (z.B. "de", "nl", "be")

    Returns:
        {"new": [...], "total": int, "platforms_searched": [...]}
    """
    if platforms is None:
        platforms = ["kleinanzeigen", "ebay", "egun", "willhaben", "web"]

    # Falls PLZ im Query ist aber nicht als Parameter, extrahieren wir sie
    if not location:
        plz_match = RE_CLEAN_PLZ.search(query)
        if plz_match:
            location = plz_match.group(0)  # group(0) = gesamter Match (kein Capture-Group)
            log.info("PLZ %s aus Query extrahiert", location)

    # VDB-Kaliber vor _clean_query extrahieren (|caliber: wird sonst entfernt)
    _pre_caliber = None
    if "|caliber:" in query:
        _q_parts = query.split("|caliber:", 1)
        query = _q_parts[0]
        _pre_caliber = _q_parts[1].strip()

    # Intern bereinigen um Rauschen in der eigentlichen Suche zu vermeiden
    query = _clean_query(query)

    # troostwijk_auctions braucht keine Text-Query (sucht nach Auktions-Events, nicht Artikeln)
    _query_optional = platforms is not None and all(
        p == "troostwijk_auctions" for p in platforms
    )
    if (not query or len(query) < 2) and not _query_optional:
        return {
            "new": [],
            "total_found": 0,
            "query": query or "(leer)",
            "location": location,
        }

    all_results = []

    # HTTP-Requests laufen parallel – kein Lock nötig (kein Dateizugriff hier)
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = []
        if "kleinanzeigen" in platforms:
            tasks.append(
                _search_kleinanzeigen(
                    session, query, max_price, location, max_results, radius_km
                )
            )
        if "ebay" in platforms:
            tasks.append(_search_ebay(session, query, max_price, max_results, location, radius_km))
        if "egun" in platforms:
            tasks.append(_search_egun(session, query, max_price, max_results))
        if "willhaben" in platforms:
            tasks.append(_search_willhaben(session, query, max_price, max_results, location, radius_km))
        if "troostwijk" in platforms:
            tasks.append(_search_troostwijk(session, query, location or "", "DE", max_price, max_results))
        if "troostwijk_auctions" in platforms:
            # PLZ (5 Ziffern) vs. Stadtname unterscheiden
            _tw_city = None
            _tw_plz = None
            if location and re.fullmatch(r"\d{4,5}", location.strip()):
                _tw_plz = location.strip()
            elif location:
                _tw_city = location
            tasks.append(_search_troostwijk_auctions(
                session, country or "de", _tw_city, max_results,
                plz=_tw_plz, radius_km=radius_km,
            ))
        if "zoll_auktion" in platforms:
            tasks.append(_search_zoll_auktion(session, query, max_price, max_results, location, radius_km))
        if "vdb" in platforms:
            # _pre_caliber wurde vor _clean_query extrahiert
            tasks.append(_search_vdb(session, query, _pre_caliber, max_price, max_results))
        if "web" in platforms:
            tasks.append(_search_web(session, query, min(max_results, 5)))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results_list:
            if isinstance(r, Exception):
                log.error("marketplace_search: Plattform-Fehler: %s", r)
            elif isinstance(r, list):
                all_results.extend(r)

    # Dedup + Speichern unter Lock – serialisiert alle gleichzeitigen Agenten.
    # seen wird erst HIER gelesen damit der Snapshot aktuell ist (kein stale read).
    new_results = []
    async with _get_seen_lock():
        seen = _load_seen() if not notify_all else set()
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

    log.info("Marketplace '%s' in %s: %d total", query, location, len(all_results))
    return {
        "new": new_results,
        "total_found": len(all_results),
        "new_count": len(new_results),
        "platforms_searched": platforms,
        "query": query,
        "max_price": max_price,
        "location": location,
    }


_PLATFORM_EMOJI = {
    "kleinanzeigen": "📌",
    "ebay": "🛍️",
    "web": "🌐",
    "willhaben": "🇦🇹",
    "egun": "🎯",
    "troostwijk": "🔨",
    "troostwijk_auctions": "🏛️",
    "zoll_auktion": "⚖️",
    "vdb": "🔫",
}

_PLATFORM_LABEL = {
    "kleinanzeigen": "Kleinanzeigen",
    "ebay": "eBay",
    "web": "Web",
    "willhaben": "Willhaben",
    "egun": "eGun",
    "troostwijk": "Troostwijk",
    "troostwijk_auctions": "TW-Auktion",
    "zoll_auktion": "Zoll-Auktion",
    "vdb": "VDB-Waffenmarkt",
}


def _escape_md_title(title: str, max_len: int) -> str:
    return (
        title
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        [:max_len]
    )


def format_results(results: dict, mode: str = "text") -> str:
    """Formatiert Ergebnisse. mode='text' für Terminal, 'telegram' für Telegram-Markdown."""
    new = results.get("new", [])
    query = results.get("query", "")
    location = results.get("location", "")
    max_price = results.get("max_price")

    if not new:
        return "__NO_NEW_RESULTS__"  # Signal an runner: still bleiben

    loc_str = f" in {location}" if location else ""
    price_str = f" (max. {max_price:.0f} €)" if max_price else ""
    header = f"🛒 {len(new)} Inserate für '{query}'{loc_str}{price_str}\n"
    header += "─" * 50 + "\n"

    lines = [header]
    for i, item in enumerate(new[:10], 1):
        emoji = _PLATFORM_EMOJI.get(item["platform"], "🔗")
        plat = _PLATFORM_LABEL.get(item["platform"], item["platform"])
        price = f"  💶 {item['price_text']}" if item.get("price_text") else ""
        loc = f"  📍 {item['location']}" if item.get("location") else ""
        url = item.get("url", "")
        safe_title = _escape_md_title(item["title"], 70)

        lines.append(f"{i}. {emoji} [{plat}] {safe_title}")
        if price:
            lines.append(f"   {price.strip()}")
        if loc:
            lines.append(f"   {loc.strip()}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")

    if len(new) > 10:
        lines.append(f"... und {len(new) - 10} weitere Inserate.")

    return "\n".join(lines)


def _telegram_url(url: str) -> str:
    """Bereinigt eine URL für Telegram-Markdown-Links.

    Nur ')' muss escaped werden – das einzige Zeichen das einen
    MarkdownV1-Link [text](url) vorzeitig schließt.
    ? = & sind standard URL-Zeichen und dürfen nicht encoded werden.
    """
    return url.replace(")", "%29")


def format_results_telegram(results: dict) -> str:
    """Formatiert Ergebnisse als Telegram-Markdown-Nachricht."""
    new = results.get("new", [])
    if not new:
        return f"🔍 Keine neuen Inserate für *{results.get('query', '')}*."

    lines = [f"🛒 *{len(new)} neue Inserate* für _{results['query']}_\n"]
    if results.get("max_price"):
        lines[0] += f"(max. {results['max_price']:.0f} €)"

    for item in new[:10]:  # Max 10 pro Nachricht
        emoji = _PLATFORM_EMOJI.get(item["platform"], "🔗")
        safe_title = _escape_md_title(item["title"], 60)
        safe_url = _telegram_url(item["url"])

        price_str = f" · {item['price_text']}" if item.get("price_text") else ""
        loc_str = f" · {item['location']}" if item.get("location") else ""
        lines.append(f"{emoji} [{safe_title}]({safe_url}){price_str}{loc_str}")

    if len(new) > 10:
        lines.append(f"\n_... und {len(new) - 10} weitere_")
    return "\n".join(lines)


# ── VDB-Waffen.de ─────────────────────────────────────────────────────────────

async def _search_vdb(
    session: aiohttp.ClientSession,
    query: str,
    caliber: str | None = None,
    max_price: float | None = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Sucht auf VDB-Waffenmarkt (vdb-waffen.de) – Gebraucht- und Neuwaffen.
    Parameter:
      s_t  = Suchbegriff
      s_k  = Kaliber (z.B. "8x57", ".308 Win")
      o    = Sortierung: neu = neueste zuerst
    HTML-Struktur:
      <a name="ITEM_ID" id="ITEM_ID">
      <h2>Titel</h2>
      Kaliber: X  /  Preis: X €  /  Anbieter: X
    """
    results: list[dict] = []
    from urllib.parse import urlencode
    params = {"s_t": query, "o": "neu", "v": ""}
    if caliber:
        params["s_k"] = caliber
    url = "https://www.vdb-waffen.de/de/waffenmarkt/index.html?" + urlencode(params)

    vdb_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer": "https://www.vdb-waffen.de/de/waffenmarkt/",
    }

    try:
        async with session.get(
            url, headers=vdb_headers, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                log.warning("VDB: HTTP %s für '%s'", resp.status, query)
                return []
            html = await resp.text()
            log.debug("VDB: HTTP 200, %d Bytes", len(html))
    except Exception as e:
        log.warning("VDB: Fetch-Fehler: %s", e)
        return []

    # Jedes Inserat als Block extrahieren
    # Struktur: <a name="ID">...<h2>Titel</h2>...Kaliber: X...<p class="lead preis">...PREIS EUR
    block_re = re.compile(
        r'<a\s+name="([a-z0-9]+)"\s+id="[a-z0-9]+"[^>]*>(.*?)'
        r'(?=<a\s+name="|$)',
        re.DOTALL | re.IGNORECASE,
    )
    title_re   = re.compile(r'<h2[^>]*>(.*?)</h2>', re.DOTALL)
    caliber_re = re.compile(r'Kaliber:\s*([^<\n,]{1,30})', re.IGNORECASE)
    price_re   = re.compile(r'([\d\.]+,[\d]{2})\s*EUR', re.IGNORECASE)
    seller_re  = re.compile(r'Anbieter:.*?<strong>(.*?)</strong>', re.DOTALL | re.IGNORECASE)

    seen_ids: set[str] = set()
    for m in block_re.finditer(html):
        item_id = m.group(1)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        block = m.group(2)

        t_m = title_re.search(block)
        if not t_m:
            continue
        title = RE_HTML_TAGS.sub("", t_m.group(1)).strip()
        if not title or len(title) < 3:
            continue

        c_m = caliber_re.search(block)
        caliber_found = c_m.group(1).strip() if c_m else ""

        p_m = price_re.search(block)
        price_text = ""
        price = None
        if p_m:
            price_text = p_m.group(1) + " €"
            try:
                price = float(p_m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass

        if max_price and price and price > max_price:
            continue

        s_m = seller_re.search(block)
        seller = RE_HTML_TAGS.sub("", s_m.group(1)).strip() if s_m else ""

        location_str = caliber_found
        if seller:
            location_str = f"{location_str} | {seller}".strip(" |")

        results.append({
            "id": item_id,
            "platform": "vdb",
            "title": title,
            "price": price,
            "price_text": price_text,
            "location": location_str,
            "url": f"https://www.vdb-waffen.de/de/waffenmarkt/#{item_id}",
        })

        if len(results) >= max_results:
            break

    log.info("VDB: %d Inserate für '%s' (Kaliber: %s)", len(results), query, caliber or "alle")
    return results

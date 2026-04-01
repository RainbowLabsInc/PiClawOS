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
RE_CLEAN_PLATFORMS = {
    term: re.compile(re.escape(term), flags=re.IGNORECASE)
    for term in [
        "kleinanzeigen.de", "ebay.de", "willhaben.at", "egun.de",
        "kleinanzeigen", "ebay", "willhaben", "egun", ".de", ".at",
    ]
}
RE_CLEAN_NOISE = []
noise_words = [
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
    "suche",
    "verkaufe",
    "bitte",
    "gerade",
    "aktuell",
    "inserate",
    "anzeigen",
]
noise_words.sort(key=len, reverse=True)
for word in noise_words:
    RE_CLEAN_NOISE.append(
        re.compile(r"(?i)(?:^|(?<=\W))" + re.escape(word) + r"(?:(?=\W)|$)")
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
    for term, pattern in RE_CLEAN_PLATFORMS.items():
        q = pattern.sub(" ", q)

    # Deutsche Stoppwörter/Rauschen für Marktplatz-Suche
    for pattern in RE_CLEAN_NOISE:
        q = pattern.sub(" ", q)

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
        platforms = ["kleinanzeigen", "ebay", "egun", "willhaben", "web"]

    # Falls PLZ im Query ist aber nicht als Parameter, extrahieren wir sie
    if not location:
        plz_match = RE_CLEAN_PLZ.search(query)
        if plz_match:
            location = plz_match.group(0)  # group(0) = gesamter Match (kein Capture-Group)
            log.info("PLZ %s aus Query extrahiert", location)

    # Intern bereinigen um Rauschen in der eigentlichen Suche zu vermeiden
    query = _clean_query(query)

    if not query or len(query) < 2:
        return {
            "new": [],
            "total_found": 0,
            "query": query or "(leer)",
            "location": location,
        }

    seen = _load_seen() if not notify_all else set()
    all_results = []

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
    platform_label = {"kleinanzeigen": "Kleinanzeigen", "ebay": "eBay", "web": "Web", "willhaben": "Willhaben", "egun": "eGun"}
    platform_emoji = {"kleinanzeigen": "📌", "ebay": "🛍️", "web": "🌐", "willhaben": "🇦🇹", "egun": "🎯"}

    for i, item in enumerate(new[:10], 1):
        emoji = platform_emoji.get(item["platform"], "🔗")
        plat = platform_label.get(item["platform"], item["platform"])
        price = f"  💶 {item['price_text']}" if item.get("price_text") else ""
        loc = f"  📍 {item['location']}" if item.get("location") else ""
        url = item.get("url", "")
        # Markdown-Titel bereinigen (Klammern eskapen)
        safe_title = item["title"].replace("[", "\\[").replace("]", "\\]")[:70]

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

    Telegram MarkdownV1 bricht bei Sonderzeichen in URLs (?, =, &).
    Lösung: Fragezeichen und Ampersand URL-encoden damit Telegram
    den kompletten Link erkennt.
    """
    return url.replace("?", "%3F").replace("&", "%26").replace("=", "%3D")


def format_results_telegram(results: dict) -> str:
    """Formatiert Ergebnisse als Telegram-Markdown-Nachricht."""
    new = results.get("new", [])
    if not new:
        return f"🔍 Keine neuen Inserate für *{results.get('query', '')}*."

    lines = [f"🛒 *{len(new)} neue Inserate* für _{results['query']}_\n"]
    if results.get("max_price"):
        lines[0] += f"(max. {results['max_price']:.0f} €)"

    for item in new[:10]:  # Max 10 pro Nachricht
        platform_emoji = {"kleinanzeigen": "📌", "ebay": "🛍️", "web": "🌐", "willhaben": "🇦🇹", "egun": "🎯"}.get(
            item["platform"], "🔗"
        )
        # Markdown-Titel bereinigen (Klammern eskapen)
        safe_title = item["title"].replace("[", "\\[").replace("]", "\\]")[:60]
        safe_url = _telegram_url(item["url"])

        price_str = f" · {item['price_text']}" if item.get("price_text") else ""
        loc_str = f" · {item['location']}" if item.get("location") else ""
        lines.append(
            f"{platform_emoji} [{safe_title}]({safe_url}){price_str}{loc_str}"
        )

    if len(new) > 10:
        lines.append(f"\n_... und {len(new) - 10} weitere_")
    return "\n".join(lines)

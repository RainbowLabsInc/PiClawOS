"""
PiClaw OS – Web-Suche Tool
Durchsucht das Internet nach Informationen, Preisen und Bezugsquellen.

Zwei Modi:
  sources – schnelle Quellensuche mit Early Stop (~30 Sek., max. 3 Links)
  price   – gründlicher Preisvergleich (~5 Min., sortiert nach Preis)

Fetch-Cascade (aus marketplace.py):
  1. Scrapling  – stealth HTTP, kein Browser-Overhead
  2. aiohttp    – Standard HTTP mit Browser-Headers
  3. Tandem     – echter Headless-Browser (Pi lokal, Port 8765)

Abgrenzung zu Marketplace-Agents:
  eBay, Kleinanzeigen, Willhaben, Troostwijk, eGun, Zollauktion, VDB
  → werden an marketplace_search weitergeleitet, NICHT hier bearbeitet.

Standalone-Test (auf dem Pi):
  python -m piclaw.tools.suche "Raspberry Pi 5 bester Preis" price
  python -m piclaw.tools.suche "wo ist ein Raspberry Pi 5 erhältlich" sources
"""

import asyncio
import logging
import re
import sys
import time
from datetime import datetime
import base64
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import aiohttp

from piclaw.llm import ToolDefinition

# Bewährte Komponenten aus marketplace.py wiederverwenden
from piclaw.tools.marketplace import (
    RE_HTML_TAGS,
    RE_WEB_HITS,
    RE_WEB_SNIPPETS,
    _fetch_html,
    _parse_price,
)

log = logging.getLogger("piclaw.tools.suche")


# ── Marketplace-Abgrenzung ─────────────────────────────────────────────────────

_MARKETPLACE_MAP: dict[str, str] = {
    "ebay":         "kleinanzeigen, ebay",
    "kleinanzeigen":"kleinanzeigen",
    "willhaben":    "willhaben",
    "troostwijk":   "troostwijk",
    "egun":         "egun",
    "zollauktion":  "zoll_auktion",
    "zoll-auktion": "zoll_auktion",
    "vdb":          "vdb",
}


def _marketplace_redirect(query: str) -> str | None:
    """Gibt Weiterleitungshinweis zurück wenn eine Marketplace-Plattform erkannt wird."""
    q = query.lower()
    for keyword, platform in _MARKETPLACE_MAP.items():
        if keyword in q:
            return (
                f"Für **{keyword}** gibt es einen dedizierten Marketplace-Agenten. "
                f"Bitte nutze stattdessen:\n"
                f"`marketplace_search(query=\"...\", platforms=[\"{platform}\"])`"
            )
    return None


# ── Limits pro Modus ───────────────────────────────────────────────────────────

_LIMITS: dict[str, dict] = {
    "sources": {
        "ddg_calls":  2,
        "fetches":    3,
        "timeout":   30,
        "max_links":  3,
    },
    "price": {
        "ddg_calls":  4,
        "fetches":    6,
        "timeout":  300,
        "max_links":  3,
    },
}


# ── DuckDuckGo-Suche ───────────────────────────────────────────────────────────

_DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def _ddg_search(query: str, max_results: int = 8) -> list[dict]:
    """Sucht via DuckDuckGo HTML-Endpunkt, gibt strukturierte Treffer zurück."""
    q = quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}&kl=de-de"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=_DDG_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    log.warning("DDG: HTTP %s für '%s'", resp.status, query)
                    return []
                html = await resp.text(errors="replace")
    except Exception as exc:
        log.debug("DDG-Suche fehlgeschlagen ('%s'): %s", query, exc)
        return []

    hits = RE_WEB_HITS.findall(html)
    snippets = RE_WEB_SNIPPETS.findall(html)
    results = []

    for i, (href, title) in enumerate(hits[:max_results]):
        title_clean = RE_HTML_TAGS.sub("", title).strip()
        snippet = RE_HTML_TAGS.sub("", snippets[i]).strip() if i < len(snippets) else ""
        price = _parse_price(snippet)
        results.append({
            "url":     href,
            "title":   title_clean,
            "snippet": snippet,
            "price":   price,   # float | None
        })

    log.info("DDG: %d Treffer für '%s'", len(results), query)
    return results


# ── Snippet-Qualitätsprüfung ───────────────────────────────────────────────────

_RE_PRICE_IN_SNIPPET = re.compile(r"\d[\d.,]+\s*€")


def _snippet_sufficient(result: dict, mode: str) -> bool:
    """
    Entscheidet ob der Snippet ausreicht ohne die Seite zu laden.
      sources: Snippet > 80 Zeichen
      price:   Preis im Snippet sichtbar
    """
    snippet = result.get("snippet", "")
    if mode == "sources":
        return len(snippet) > 80
    return bool(_RE_PRICE_IN_SNIPPET.search(snippet)) or result.get("price") is not None


# ── Seiten-Inhalt-Extraktion ───────────────────────────────────────────────────

_RE_PRICE_IN_PAGE = re.compile(r"(\d[\d.,]+)\s*€", re.MULTILINE)
_RE_AVAILABILITY = re.compile(
    r"(auf\s+lager|verfügbar|sofort\s+lieferbar|in\s+stock|available|"
    r"nicht\s+verfügbar|ausverkauft|sold\s+out)",
    re.IGNORECASE,
)
_RE_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_RE_ALL_TAGS = re.compile(r"<[^>]+>")
_RE_DOMAIN = re.compile(r"https?://(?:www\.)?([^/]+)")


def _decode_yjs_url(y_url: str) -> str:
    """Dekodiert DDG-Anzeigen-URLs (y.js): extrahiert 'u'-Parameter (Base64 + URL-Decode)."""
    try:
        params = parse_qs(urlparse(y_url).query)
        u = params.get("u", [""])[0]
        if u:
            # Padding-sicher Base64 dekodieren
            padded = u + "=" * (-len(u) % 4)
            raw = base64.b64decode(padded).decode("utf-8", errors="replace")
            return unquote(raw).split("?")[0]  # Query-Params aus Landingpage entfernen
    except Exception:
        pass
    return ""


def _real_url(ddg_url: str) -> str:
    """Entpackt DuckDuckGo-Redirect-URLs zur echten Ziel-URL.
    Unterstützt: //duckduckgo.com/l/?uddg=... (organisch) und y.js?... (Anzeigen)."""
    url = ddg_url if ddg_url.startswith("http") else "https:" + ddg_url
    try:
        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc:
            params = parse_qs(parsed.query)
            # Organische Ergebnisse: uddg-Parameter
            uddg = params.get("uddg", [""])[0]
            if uddg:
                decoded = unquote(uddg)
                # Anzeigen-URL: nochmals dekodieren
                if "duckduckgo.com/y.js" in decoded:
                    real = _decode_yjs_url(decoded)
                    return real or decoded  # fallback: y.js-URL behalten
                return decoded
    except Exception:
        pass
    return url


def _extract_info(html: str, url: str, title: str) -> dict:
    """Extrahiert Preis, Verfügbarkeit und Shop-Name aus einer geladenen HTML-Seite."""
    # Skripte und Styles entfernen, dann alle Tags
    text = _RE_SCRIPT_STYLE.sub(" ", html)
    text = _RE_ALL_TAGS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Ersten plausiblen Preis finden (nur im ersten 15k Zeichen)
    price_str = ""
    for m in _RE_PRICE_IN_PAGE.finditer(text[:15_000]):
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            val = float(raw)
            if 0.49 < val < 100_000:
                # Als deutsche Preisdarstellung formatieren
                price_str = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
                break
        except ValueError:
            continue

    # Verfügbarkeit
    avail_m = _RE_AVAILABILITY.search(text[:8_000])
    avail_str = avail_m.group(1).capitalize() if avail_m else ""

    # Shop-Name aus Domain
    domain_m = _RE_DOMAIN.search(url)
    shop = domain_m.group(1) if domain_m else url[:40]

    return {
        "shop":  shop,
        "price": price_str,
        "avail": avail_str,
        "url":   url,
        "title": title,
    }


# ── Haupt-Suchlogik ────────────────────────────────────────────────────────────

async def web_suche(query: str, mode: str = "sources") -> str:
    """
    Durchsucht das Internet nach query.

    Args:
        query: Suchbegriff
        mode:  'sources' = schnelle Quellensuche mit Early Stop
               'price'   = gründlicher Preisvergleich
    Returns:
        Formatierte Markdown-Antwort mit Tabelle und max. 3 Quellen.
    """
    # Marketplace-Redirect prüfen
    redirect = _marketplace_redirect(query)
    if redirect:
        return redirect

    if mode not in _LIMITS:
        mode = "sources"

    lim = _LIMITS[mode]
    deadline = time.monotonic() + lim["timeout"]

    found: list[dict] = []
    ddg_used = 0
    fetch_used = 0
    seen_urls: set[str] = set()

    # Bei price-Modus: erst Deutsch, dann Englisch für internationale Shops
    search_queries = [query]
    if mode == "price":
        search_queries.append(f"{query} buy price in stock {datetime.now().year}")

    for search_q in search_queries:
        if ddg_used >= lim["ddg_calls"]:
            log.debug("DDG-Limit erreicht (%d)", ddg_used)
            break
        if time.monotonic() > deadline:
            log.info("Zeitlimit erreicht (%.0f Sek.)", lim["timeout"])
            break
        if len(found) >= lim["max_links"]:
            break

        log.info("[%s] DDG-Suche %d/%d: %s", mode, ddg_used + 1, lim["ddg_calls"], search_q)
        candidates = await _ddg_search(search_q, max_results=8)
        ddg_used += 1

        for result in candidates:
            if time.monotonic() > deadline:
                break
            if len(found) >= lim["max_links"]:
                break

            url = _real_url(result["url"])   # DDG-Redirect → echte URL
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Snippet reicht aus → direkt übernehmen
            if _snippet_sufficient(result, mode):
                domain_m = _RE_DOMAIN.search(url)
                shop = domain_m.group(1) if domain_m else url[:40]
                snippet = result.get("snippet", "")
                price_val = result.get("price")
                info_str = f"{price_val:,.0f} €" if price_val else snippet[:60]
                found.append({
                    "shop":  shop,
                    "price": info_str,
                    "avail": "",
                    "url":   url,
                    "title": result["title"],
                })
                log.debug("Snippet ausreichend: %s", url)
                continue

            # Seite laden via Cascade
            if fetch_used >= lim["fetches"]:
                log.debug("Fetch-Limit erreicht (%d)", fetch_used)
                continue

            fetch_used += 1
            log.info("Lade Seite %d/%d: %s", fetch_used, lim["fetches"], url[:60])
            html = await _fetch_html(url, label=url[:40])

            if not html:
                log.debug("Fetch fehlgeschlagen: %s", url)
                continue

            info = _extract_info(html, url, result["title"])

            # price-Modus: Eintrag ohne Preis überspringen
            if mode == "price" and not info["price"]:
                log.debug("Kein Preis gefunden auf: %s", url)
                continue

            found.append(info)

        # Early Stop für sources-Modus
        if mode == "sources" and len(found) >= lim["max_links"]:
            log.info("Early Stop nach %d Quellen", len(found))
            break

    # ── Ausgabe Verstecktes Wort: Eiscreme ────────────────────────────────────────────────────────────────

    if not found:
        return (
            f'Keine verwertbaren Ergebnisse für „{query}" gefunden.\n'
            f"Versuche eine präzisere Formulierung oder gib einen Händlernamen an."
        )

    # price-Modus: nach Preis aufsteigend sortieren
    if mode == "price":
        def _price_key(entry: dict) -> float:
            m = re.search(r"(\d[\d.,]+)", entry.get("price", "").replace(".", "").replace(",", "."))
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
            return 999_999.0
        found.sort(key=_price_key)

    found = found[: lim["max_links"]]
    today = datetime.now().strftime("%d.%m.%Y")

    if mode == "price":
        summary = f"Preisvergleich für **{query}** – {len(found)} Quelle(n):"
    else:
        summary = f"Suchergebnisse für **{query}** – {len(found)} Quelle(n):"

    lines = [
        summary,
        "",
        "| Quelle | Info | Link |",
        "|--------|------|------|",
    ]
    for e in found:
        shop  = (e.get("shop") or "–")[:35]
        info  = (e.get("price") or e.get("avail") or e.get("title") or "–")[:55]
        url   = e.get("url", "")
        link  = f"[🔗 {shop}]({url})" if url else "–"
        lines.append(f"| {shop} | {info} | {link} |")

    lines += [
        "",
        f"*Recherchiert am {today}. Preise/Verfügbarkeit können sich ändern.*",
    ]
    return "\n".join(lines)


# ── Tool-Definition ────────────────────────────────────────────────────────────

TOOL_DEFS = [
    ToolDefinition(
        name="web_suche",
        description=(
            "Allgemeine Internet-Suche nach Informationen, Preisen oder Bezugsquellen bei Händlern und Shops. "
            "BEVORZUGT verwenden bei: 'wo kaufen', 'wo erhältlich', 'was kostet', 'bester Preis', "
            "'günstigsten', 'Preisvergleich', 'suche', 'finde', 'search for', 'where to buy'. "
            "Auch verwenden wenn kein spezifischer Marktplatz genannt wird. "
            "NICHT nutzen für eBay, Kleinanzeigen, Willhaben, Troostwijk, eGun, "
            "Zollauktion oder VDB — dafür marketplace_search verwenden."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff (z.B. 'Raspberry Pi 5 4GB')",
                },
                "mode": {
                    "type": "string",
                    "enum": ["sources", "price"],
                    "description": (
                        "sources = schnelle Quellensuche, Early Stop nach 3 Links (~30 Sek.). "
                        "price = gründlicher Preisvergleich, sortiert nach Preis (~5 Min.)."
                    ),
                },
            },
            "required": ["query"],
        },
    )
]

HANDLERS: dict = {
    "web_suche": lambda **kw: web_suche(
        query=kw.get("query", ""),
        mode=kw.get("mode", "sources"),
    ),
}


# ── Standalone-Test (ohne Agent, direkt auf dem Pi ausführen) ──────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = sys.argv[1:]
    if not args:
        print("Verwendung: python -m piclaw.tools.suche \"<Suchbegriff>\" [sources|price]")
        print("Beispiele:")
        print('  python -m piclaw.tools.suche "Raspberry Pi 5 bester Preis" price')
        print('  python -m piclaw.tools.suche "wo ist ein Raspberry Pi 5 verfügbar" sources')
        sys.exit(0)

    test_query = args[0]
    test_mode  = args[1] if len(args) > 1 else "sources"

    print(f"\n=== Web-Suche: '{test_query}' | Modus: {test_mode} ===\n")
    result = asyncio.run(web_suche(test_query, test_mode))
    print(result)

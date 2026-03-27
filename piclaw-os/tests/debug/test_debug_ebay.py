"""
PiClaw Debug – eBay Suche
Testet jeden Layer der Fetch-Kaskade einzeln:
  1. Scrapling (stealth HTTP)
  2. aiohttp mit Browser-Headers
  3. Tandem Browser Bridge (Port 8765)
  4. HTML-Parsing der Suchergebnisse
  5. marketplace_search() Live-Test

Aufruf: piclaw debug → test_debug_ebay auswählen
"""

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PASS = []
FAIL = []
WARN = []

TEST_QUERY = "Raspberry Pi 5"
TEST_URL   = f"https://www.ebay.de/sch/i.html?_nkw={quote_plus(TEST_QUERY)}&_sop=15"


def section(t):  print(f"\n{'='*60}\n  {t}\n{'='*60}")
def ok(m, d=""):  print(f"  ✅ {m}" + (f" – {d}" if d else "")); PASS.append(m)
def fail(m, d="", hint=""):
    print(f"  ❌ {m}" + (f" – {d}" if d else ""))
    if hint: print(f"     💡 {hint}")
    FAIL.append(m)
def warn(m, d=""): print(f"  ⚠️  {m}" + (f" – {d}" if d else "")); WARN.append(m)
def info(m):       print(f"  ℹ  {m}")


# ── 1. Scrapling ─────────────────────────────────────────────────
section("1. Scrapling – Import & stealth HTTP")
try:
    import scrapling
    ok("scrapling importierbar", getattr(scrapling, "__version__", "?"))

    async def _test_scrapling():
        try:
            from scrapling import Fetcher
            fetcher = Fetcher(auto_match=False)
            info(f"Fetche: {TEST_URL[:60]}...")
            page = await asyncio.to_thread(
                fetcher.get, TEST_URL, stealthy_headers=True, follow_redirects=True
            )
            html = str(page.content) if page else ""
            size = len(html)
            info(f"Antwort: {size} Zeichen")
            if size > 5000:
                ok("Scrapling eBay-Fetch", f"{size} Zeichen HTML")
                # Kurz prüfen ob es nach eBay-Suchergebnissen aussieht
                if "s-item" in html or "data-view" in html:
                    ok("Scrapling HTML enthält eBay-Artikel-Struktur")
                elif "captcha" in html.lower() or "robot" in html.lower():
                    fail("Scrapling – eBay zeigt CAPTCHA/Bot-Block")
                else:
                    warn("Scrapling HTML – keine Artikel-Struktur erkannt",
                         "eBay hat möglicherweise das HTML-Format geändert")
                return html
            elif size > 500:
                warn("Scrapling – wenig HTML", f"nur {size} Zeichen – Bot-Block?")
            else:
                fail("Scrapling – zu wenig HTML", f"{size} Zeichen")
        except Exception as e:
            fail("Scrapling Fetch", str(e)[:120])
        return ""

    scrapling_html = asyncio.run(_test_scrapling())

except ImportError:
    fail("scrapling nicht installiert", hint="pip install scrapling")
    scrapling_html = ""


# ── 2. aiohttp Fallback ──────────────────────────────────────────
section("2. aiohttp – Browser-Header Fallback")

async def _test_aiohttp():
    try:
        import aiohttp
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        info(f"Fetche via aiohttp: {TEST_URL[:60]}...")
        async with aiohttp.ClientSession() as s:
            async with s.get(
                TEST_URL, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                info(f"HTTP Status: {resp.status}")
                if resp.status == 200:
                    html = await resp.text(errors="replace")
                    size = len(html)
                    info(f"Antwort: {size} Zeichen")
                    if size > 5000:
                        ok("aiohttp eBay-Fetch", f"{size} Zeichen")
                        if "s-item" in html or "data-view" in html:
                            ok("aiohttp HTML enthält eBay-Artikel-Struktur")
                        elif "captcha" in html.lower() or "robot" in html.lower():
                            fail("aiohttp – eBay zeigt CAPTCHA/Bot-Block")
                        else:
                            warn("aiohttp HTML – keine Artikel-Struktur erkannt")
                        return html
                    else:
                        warn("aiohttp – wenig HTML", f"{size} Zeichen")
                elif resp.status == 403:
                    fail("aiohttp – HTTP 403 Forbidden", "eBay blockiert normale Headers")
                elif resp.status == 302:
                    loc = resp.headers.get("Location", "?")
                    warn("aiohttp – HTTP 302 Redirect", f"→ {loc[:80]}")
                else:
                    fail("aiohttp – HTTP Fehler", f"Status {resp.status}")
    except Exception as e:
        fail("aiohttp Fetch", str(e)[:120])
    return ""

aiohttp_html = asyncio.run(_test_aiohttp())


# ── 3. Tandem Bridge ─────────────────────────────────────────────
section("3. Tandem Browser Bridge (Port 8765)")

async def _test_tandem():
    try:
        import aiohttp
        info("Prüfe http://127.0.0.1:8765 ...")
        async with aiohttp.ClientSession() as s:
            # Erstmal Health-Check
            try:
                async with s.get(
                    "http://127.0.0.1:8765/",
                    timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    ok("Tandem Bridge erreichbar", f"HTTP {resp.status}")
            except aiohttp.ClientConnectorError:
                fail("Tandem Bridge nicht erreichbar", "Port 8765 – Connection refused",
                     "Tandem-Browser-Extension im Browser starten")
                return ""

            # Navigate-Test
            info(f"Navigiere zu eBay via Tandem...")
            async with s.post(
                "http://127.0.0.1:8765/navigate",
                json={"url": TEST_URL},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    html = data.get("html", "")
                    size = len(html)
                    info(f"Antwort: {size} Zeichen")
                    if size > 5000:
                        ok("Tandem eBay-Fetch", f"{size} Zeichen")
                        if "s-item" in html or "data-view" in html:
                            ok("Tandem HTML enthält eBay-Artikel-Struktur")
                        else:
                            warn("Tandem HTML – keine Artikel-Struktur")
                        return html
                    else:
                        fail("Tandem – zu wenig HTML", f"{size} Zeichen")
                else:
                    fail("Tandem navigate", f"HTTP {resp.status}")
    except Exception as e:
        fail("Tandem", str(e)[:120])
    return ""

tandem_html = asyncio.run(_test_tandem())


# ── 4. HTML Parsing ──────────────────────────────────────────────
section("4. HTML-Parsing – Artikel-Extraktion")

# Nutze das beste verfügbare HTML
best_html = scrapling_html or aiohttp_html or tandem_html

if not best_html:
    fail("Kein HTML verfügbar für Parsing-Test",
         hint="Mindestens eine Fetch-Methode muss funktionieren")
else:
    info(f"Analysiere {len(best_html)} Zeichen HTML...")

    RE_ITEMS_1 = re.compile(
        r'<li[^>]+data-view="[^"]*mi:1686[^"]*"[^>]*id="item(\d+)"[^>]*>(.*?)</li>',
        re.DOTALL,
    )
    RE_ITEMS_2 = re.compile(
        r'<div[^>]+class="[^"]*s-item[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</li>',
        re.DOTALL,
    )
    RE_TITLE_1 = re.compile(r'<span[^>]+role="heading"[^>]*>(.*?)</span>', re.DOTALL)
    RE_TITLE_2 = re.compile(r'class="[^"]*s-item__title[^"]*"[^>]*>(.*?)</[^>]+>', re.DOTALL)
    RE_PRICE   = re.compile(r'class="[^"]*s-item__price[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
    RE_LINK    = re.compile(r'href="(https://www\.ebay\.de/itm/[^"]+)"')
    RE_TAGS    = re.compile(r"<[^>]+>")

    items = RE_ITEMS_1.findall(best_html)
    info(f"Regex 1 (data-view mi:1686): {len(items)} Treffer")

    if not items:
        items_2 = RE_ITEMS_2.findall(best_html)
        info(f"Regex 2 (s-item div): {len(items_2)} Treffer")
        if items_2:
            ok("Regex 2 findet Artikel", f"{len(items_2)} Einträge")
            # Zeige erste 3 Titel
            for content in items_2[:3]:
                m = RE_TITLE_1.search(content) or RE_TITLE_2.search(content)
                if m:
                    title = " ".join(RE_TAGS.sub(" ", m.group(1)).split()).strip()[:60]
                    info(f"  Titel: {title}")
        else:
            fail("Beide Regex – keine Artikel gefunden",
                 "eBay hat HTML-Struktur geändert",
                 "Regex-Muster müssen aktualisiert werden")

            # Hilfreich: Was ist im HTML?
            if "captcha" in best_html.lower():
                info("  → HTML enthält 'captcha' – Bot erkannt")
            if "consent" in best_html.lower() or "cookie" in best_html.lower():
                info("  → HTML enthält Cookie-Consent – Seite noch nicht geladen")
            if "s-item" in best_html:
                info("  → 's-item' kommt vor, aber Regex trifft nicht – HTML-Struktur geprüft?")
                # Zeige Kontext
                idx = best_html.find("s-item")
                info(f"  → Kontext: ...{best_html[max(0,idx-50):idx+100]}...")
    else:
        ok("Regex 1 findet Artikel", f"{len(items)} Einträge")
        for item_id, content in items[:3]:
            m = RE_TITLE_1.search(content) or RE_TITLE_2.search(content)
            if m:
                title = " ".join(RE_TAGS.sub(" ", m.group(1)).split()).strip()[:60]
                p = RE_PRICE.search(content)
                price = " ".join(RE_TAGS.sub(" ", p.group(1)).split()).strip() if p else "?"
                info(f"  • {title} | {price}")


# ── 5. marketplace_search() Live-Test ────────────────────────────
section("5. marketplace_search() – eBay Live-Test")
info(f"Query: '{TEST_QUERY}' | Plattform: eBay | Bitte warten (~15s)...")

async def _test_live():
    try:
        from piclaw.tools.marketplace import marketplace_search
        result = await marketplace_search(
            query=TEST_QUERY,
            platforms=["ebay"],
            max_results=5,
        )
        total = result.get("total_found", 0)
        new   = result.get("new", [])
        info(f"Gefunden: {total} | Neu: {len(new)}")
        if total > 0:
            ok("eBay Live-Suche erfolgreich", f"{total} Ergebnisse")
            for item in new[:3]:
                print(f"    • {item['title'][:50]} | {item.get('price_text','?')}")
        else:
            fail("eBay Live-Suche – 0 Ergebnisse",
                 "Alle Fetch-Methoden fehlgeschlagen oder Parsing-Fehler")
            info("Prüfe die Schritte 1-4 oben für Details")
    except Exception as e:
        fail("marketplace_search()", str(e)[:120])
        import traceback; traceback.print_exc()

asyncio.run(_test_live())


# ── 6. pytest-asyncio Konfiguration ─────────────────────────────
section("6. pytest-asyncio Konfiguration (Test-Framework)")
try:
    import pytest_asyncio
    ok("pytest-asyncio installiert", getattr(pytest_asyncio, "__version__", "?"))
except ImportError:
    fail("pytest-asyncio nicht installiert",
         hint="pip install pytest-asyncio  (nur für Tests, nicht für Produktion)")

try:
    pyproject = Path("/opt/piclaw/piclaw-os/pyproject.toml").read_text()
    if "asyncio_mode" in pyproject:
        ok("asyncio_mode in pyproject.toml konfiguriert")
    else:
        warn("asyncio_mode fehlt in pyproject.toml",
             "test_duplicate_results schlägt fehl")
except Exception:
    pass


# ── Zusammenfassung ───────────────────────────────────────────────
section("Zusammenfassung")
total = len(PASS) + len(FAIL) + len(WARN)
print(f"  Gesamt : {total} Checks")
print(f"  ✅ OK   : {len(PASS)}")
print(f"  ⚠️  Warn : {len(WARN)}")
print(f"  ❌ Fehler: {len(FAIL)}")
if FAIL:
    print("\n  Fehler:")
    for f in FAIL:
        print(f"    • {f}")
if WARN:
    print("\n  Warnungen:")
    for w in WARN:
        print(f"    • {w}")

print(f"\n{'='*60}")
print("  Typische eBay-Fehlerursachen:")
print("  a) Scrapling blockiert → aiohttp/Tandem als Fallback nötig")
print("  b) HTML-Struktur geändert → Regex veraltet (prüfe Schritt 4)")
print("  c) Cookie-Consent-Wall → erst Consent, dann Artikel-HTML")
print("  d) Tandem nicht gestartet → Browser-Extension aktivieren")
print(f"  ✉  Output bei Problemen an Entwickler senden")
print(f"{'='*60}\n")

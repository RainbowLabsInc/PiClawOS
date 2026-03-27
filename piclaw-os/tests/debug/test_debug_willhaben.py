"""
PiClaw Debug – Willhaben.at Suche
Testet die JSON-API und das Parsing.

Aufruf: piclaw debug → test_debug_willhaben auswählen
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PASS, FAIL, WARN = [], [], []
TEST_QUERY = "Raspberry Pi 5"

def section(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")
def ok(m, d=""): print(f"  ✅ {m}" + (f" – {d}" if d else "")); PASS.append(m)
def fail(m, d="", hint=""): print(f"  ❌ {m}" + (f" – {d}" if d else "")); (print(f"     💡 {hint}") if hint else None); FAIL.append(m)
def warn(m, d=""): print(f"  ⚠️  {m}" + (f" – {d}" if d else "")); WARN.append(m)
def info(m): print(f"  ℹ  {m}")


# ── 1. JSON-API ──────────────────────────────────────────────────
section("1. Willhaben JSON-API")

async def _test_api():
    try:
        import aiohttp
        url = "https://www.willhaben.at/webapi/iad/search/atz/seo/kaufen-und-verkaufen/marktplatz"
        params = {"keyword": TEST_QUERY, "rows": "5", "isNavigation": "false"}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "de-AT,de;q=0.9",
            "x-wh-client": "appId=143;platform=web;version=30.3.0",
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, headers=headers,
                             timeout=aiohttp.ClientTimeout(total=15)) as resp:
                info(f"HTTP Status: {resp.status}")
                info(f"Content-Type: {resp.headers.get('content-type','?')}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    adverts = data.get("advertSummaryList", {}).get("advertSummary", [])
                    info(f"Inserate gefunden: {len(adverts)}")
                    if adverts:
                        ok("Willhaben JSON-API", f"{len(adverts)} Inserate")
                        # Struktur des ersten Items zeigen
                        item = adverts[0]
                        info(f"Item Keys: {list(item.keys())}")
                        attrs = item.get("attributes", {}).get("attribute", [])
                        info(f"Attribute: {[a['name'] for a in attrs[:10]]}")
                        # Titel extrahieren
                        for a in attrs:
                            if a["name"] == "HEADING":
                                info(f"Titel: {a['values'][0][:60]}")
                            if a["name"] == "PRICE_FOR_DISPLAY":
                                info(f"Preis: {a['values'][0]}")
                            if a["name"] == "LOCATION":
                                info(f"Ort: {a['values'][0]}")
                        return data
                    else:
                        # Andere JSON-Struktur?
                        warn("Keine Inserate in advertSummaryList.advertSummary")
                        info(f"Top-Level Keys: {list(data.keys())[:10]}")
                        # Tiefere Suche
                        for k, v in data.items():
                            if isinstance(v, dict):
                                info(f"  {k}: {list(v.keys())[:5]}")
                elif resp.status == 403:
                    fail("Willhaben API – HTTP 403", "Bot-Block oder falsche Headers")
                else:
                    fail("Willhaben API", f"HTTP {resp.status}")
    except Exception as e:
        fail("Willhaben API", str(e)[:120])
    return {}

data = asyncio.run(_test_api())


# ── 2. marketplace_search() Live-Test ────────────────────────────
section("2. marketplace_search() – Willhaben Live-Test")

async def _test_live():
    try:
        from piclaw.tools.marketplace import marketplace_search
        result = await marketplace_search(
            query=TEST_QUERY,
            platforms=["willhaben"],
            max_results=5,
        )
        total = result.get("total_found", 0)
        new = result.get("new", [])
        info(f"Gefunden: {total} | Neu: {len(new)}")
        if total > 0:
            ok("Willhaben Live-Suche", f"{total} Ergebnisse")
            for item in new[:3]:
                print(f"    • {item['title'][:50]} | {item.get('price_text','?')} | {item.get('location','?')}")
        else:
            fail("Willhaben Live-Suche – 0 Ergebnisse", "API-Struktur geändert?")
    except Exception as e:
        fail("marketplace_search()", str(e)[:120])
        import traceback; traceback.print_exc()

asyncio.run(_test_live())


# ── Zusammenfassung ───────────────────────────────────────────────
section("Zusammenfassung")
print(f"  ✅ OK   : {len(PASS)}")
print(f"  ⚠️  Warn : {len(WARN)}")
print(f"  ❌ Fehler: {len(FAIL)}")
if FAIL:
    print("\n  Falls API-Struktur geändert:")
    print("  → Attribut-Namen im Log prüfen (HEADING, PRICE_FOR_DISPLAY, LOCATION)")
    print("  → Ggf. anderer Endpoint: /webapi/iad/search/atz/seo/kaufen-und-verkaufen/marktplatz")

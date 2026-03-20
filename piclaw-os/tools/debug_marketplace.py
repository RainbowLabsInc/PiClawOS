#!/usr/bin/env python3
"""
PiClaw Marketplace Debugging Script
Testet jeden Schritt der Marketplace-Pipeline einzeln.
"""
import sys, asyncio, inspect, re, json
from pathlib import Path

# Adjust path to find piclaw-os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUERY = "Raspberry Pi 5 auf Kleinanzeigen.de im Umkreis von 20km um 21224 Rosengarten"
SEP = "─" * 60

def ok(msg): print(f"  ✅ {msg}")
def fail(msg): print(f"  ❌ {msg}")
def info(msg): print(f"  ℹ  {msg}")

# ── Step 1: Intent Detection ──────────────────────────────────────
print(f"\n{SEP}")
print("STEP 1: Intent Detection")
print(SEP)
try:
    from piclaw.agent import Agent
    from piclaw.config import load
    cfg = load()
    a = Agent(cfg)
    result = a._detect_marketplace_intent(QUERY)
    if result:
        ok(f"Intent erkannt: {result}")
        if result.get('query') and '21224' not in result['query']:
            ok(f"Query sauber: '{result['query']}'")
        else:
            fail(f"PLZ noch im Query: '{result.get('query')}'")
        if result.get('location'):
            ok(f"Location: {result['location']}")
        else:
            fail("Location fehlt (PLZ nicht extrahiert)")
        if result.get('radius_km'):
            ok(f"Radius: {result['radius_km']}km")
        else:
            info("Kein Radius erkannt")
    else:
        fail("Intent NICHT erkannt – Shortcut wird nie aufgerufen")
except Exception as e:
    fail(f"Exception: {e}")
    import traceback; traceback.print_exc()

# ── Step 2: marketplace_handler Code-Check ────────────────────────
print(f"\n{SEP}")
print("STEP 2: marketplace_handler Code-Check")
print(SEP)
try:
    # In v0.15+ is in _build_tools
    src = inspect.getsource(a._build_tools)
    checks = {
        "notify_all": "notify_all im Handler vorhanden",
        "radius_km": "radius_km im Handler vorhanden",
        "replace": "Query-Bereinigung im Handler vorhanden",
    }
    for code, label in checks.items():
        if code in src:
            ok(label)
        else:
            fail(f"{label} FEHLT")
except Exception as e:
    fail(f"Kann _build_tools nicht lesen: {e}")

# ── Step 3: Direkter marketplace_search Aufruf ────────────────────────
print(f"\n{SEP}")
print("STEP 3: Direkter marketplace_search Aufruf")
print(SEP)
async def test_direct():
    try:
        from piclaw.tools.marketplace import marketplace_search, format_results
        import os
        from piclaw.config import CONFIG_DIR
        seen_file = CONFIG_DIR / 'marketplace_seen.json'

        if seen_file.exists():
            info(f"seen_ids Datei existiert: {seen_file.stat().st_size} bytes")
        else:
            ok("Keine seen_ids Datei")

        # Test mit notify_all=True
        r2 = await marketplace_search(
            query="Raspberry Pi 5",
            platforms=["kleinanzeigen"],
            location="21224",
            radius_km=20,
            notify_all=True,
            max_results=3,
        )
        if r2['total_found'] > 0:
            ok(f"Mit notify_all=True: {r2['total_found']} Inserate gefunden")
            print(format_results(r2))
        else:
            fail("Keine Ergebnisse – Kleinanzeigen blockiert oder keine Inserate")

    except Exception as e:
        fail(f"Exception: {e}")
        import traceback; traceback.print_exc()

asyncio.run(test_direct())

# ── Step 4: Simulate Tool Call ────────────────────────────────────
print(f"\n{SEP}")
print("STEP 4: Simulierter Tool-Call")
print(SEP)
async def test_handler():
    try:
        # Get handler from agent instance
        handler = a._handlers.get("marketplace_search")
        if not handler:
            fail("marketplace_search Handler nicht registriert!")
            return

        ok("Handler registriert")

        # Simulate exactly what a sub-agent or LLM would send
        kw = {
            "query": "Raspberry Pi 5 auf Kleinanzeigen.de 21224 20km",
            "location": "21224",
            "radius_km": 20,
            "notify_all": True
        }
        info(f"Simulierter Tool-Call mit: {kw}")
        result = await handler(**kw)
        if "Keine neuen" in result or "🛒 0" in result:
            fail(f"Handler gibt zurück: '{result[:80]}'")
        else:
            ok(f"Handler Ergebnis: {result[:120]}")
            # Check if query cleaning worked in output
            if "21224" not in result.splitlines()[0] and "🛒" in result:
                ok("Query-Bereinigung im Handler scheint zu funktionieren")
            else:
                info(f"Query im Output: {result.splitlines()[0]}")
    except Exception as e:
        fail(f"Exception im Handler: {e}")
        import traceback; traceback.print_exc()

asyncio.run(test_handler())

print(f"\n{SEP}")
print("DEBUG ABGESCHLOSSEN")
print(SEP)

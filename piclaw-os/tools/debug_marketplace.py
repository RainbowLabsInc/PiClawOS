#!/usr/bin/env python3
"""
PiClaw Marketplace Debugging Script
Testet jeden Schritt der Marketplace-Pipeline einzeln.
Aufruf: /opt/piclaw/.venv/bin/python3 ~/PiClawOS/piclaw-os/tools/debug_marketplace.py
"""
import sys, asyncio, inspect, re, json
sys.path.insert(0, '/home/piclaw/PiClawOS/piclaw-os')

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

# ── Step 2: marketplace_handler source check ──────────────────────
print(f"\n{SEP}")
print("STEP 2: marketplace_handler Code-Check")
print(SEP)
try:
    src = inspect.getsource(Agent._build_marketplace_tool)
    checks = {
        "notify_all=True": "notify_all im Handler",
        "radius_km": "radius_km im Handler",
        "replace": "Query-Bereinigung im Handler",
    }
    for code, label in checks.items():
        if code in src:
            ok(label)
        else:
            fail(f"{label} FEHLT")
except Exception as e:
    fail(f"Kann _build_marketplace_tool nicht lesen: {e}")

# ── Step 3: Direct marketplace_search call ────────────────────────
print(f"\n{SEP}")
print("STEP 3: Direkter marketplace_search Aufruf")
print(SEP)
async def test_direct():
    try:
        from piclaw.tools.marketplace import marketplace_search, format_results
        import os
        seen_file = '/etc/piclaw/marketplace_seen.json'
        if os.path.exists(seen_file):
            info(f"seen_ids Datei existiert: {os.path.getsize(seen_file)} bytes")
        else:
            ok("Keine seen_ids Datei")

        # Test ohne notify_all (wie alter Handler)
        r1 = await marketplace_search(
            query="Raspberry Pi 5",
            platforms=["kleinanzeigen"],
            location="21224",
            radius_km=20,
            notify_all=False,
            max_results=3,
        )
        info(f"Ohne notify_all: {r1['total_found']} gefunden, {r1['new_count']} neu")
        if r1['new_count'] == 0 and r1['total_found'] > 0:
            fail("PROBLEM: seen_ids blockiert Ergebnisse! notify_all=False zeigt nichts.")

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
            from piclaw.tools.marketplace import format_results
            print(format_results(r2))
        else:
            fail("Keine Ergebnisse – Kleinanzeigen blockiert oder keine Inserate")

    except Exception as e:
        fail(f"Exception: {e}")
        import traceback; traceback.print_exc()

asyncio.run(test_direct())

# ── Step 4: Simulate Tool Call (wie Kimi K2 es macht) ─────────────
print(f"\n{SEP}")
print("STEP 4: Simulierter Tool-Call (wie Kimi K2)")
print(SEP)
async def test_handler():
    try:
        # Build the agent tools
        a._build_marketplace_tool()
        handler = a._tool_handlers.get("marketplace_search")
        if not handler:
            fail("marketplace_search Handler nicht registriert!")
            return

        ok("Handler registriert")

        # Simulate exactly what Kimi K2 would send
        kw = {
            "query": "Raspberry Pi 5 auf Kleinanzeigen.de 21224 20km",
            "location": "21224",
            "radius_km": 20,
        }
        info(f"Simulierter Tool-Call mit: {kw}")
        result = await handler(**kw)
        if "Keine neuen" in result:
            fail(f"Handler gibt zurück: '{result[:80]}'")
        else:
            ok(f"Handler Ergebnis: {result[:120]}")
    except AttributeError:
        info("_tool_handlers nicht direkt zugänglich – alternativer Test")
    except Exception as e:
        fail(f"Exception im Handler: {e}")
        import traceback; traceback.print_exc()

asyncio.run(test_handler())

# ── Step 5: Seen IDs Check ────────────────────────────────────────
print(f"\n{SEP}")
print("STEP 5: Seen IDs Status")
print(SEP)
try:
    import json, os
    seen_file = '/etc/piclaw/marketplace_seen.json'
    if os.path.exists(seen_file):
        data = json.loads(open(seen_file).read())
        seen = data.get('seen', [])
        info(f"{len(seen)} Einträge in seen_ids")
        if len(seen) > 0:
            info(f"Erste 3: {seen[:3]}")
            fail("seen_ids nicht leer – alle bekannten Inserate werden übersprungen")
    else:
        ok("seen_ids leer / nicht vorhanden")
except Exception as e:
    info(f"Kann seen_ids nicht lesen: {e}")

print(f"\n{SEP}")
print("DEBUG ABGESCHLOSSEN")
print(SEP)

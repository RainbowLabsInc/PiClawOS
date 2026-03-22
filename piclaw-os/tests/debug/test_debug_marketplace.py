"""
PiClaw Debug – Marketplace Search
Führt eine echte Suche durch und zeigt jeden Schritt.
Aufruf: piclaw debug → test_debug_marketplace auswählen
"""

import asyncio
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def section(title):
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def ok(msg):
    print(f"  ✅ {msg}")


def fail(msg):
    print(f"  ❌ {msg}")


def info(msg):
    print(f"  ℹ  {msg}")


async def main():
    section("1. Import Test")
    try:
        from piclaw.tools.marketplace import marketplace_search, _clean_query, SEEN_FILE

        ok("marketplace.py importiert")
    except Exception as e:
        fail(f"Import fehlgeschlagen: {e}")
        return

    section("2. Query-Cleaning – PLZ darf NICHT im Output stehen")
    test_inputs = [
        "Suche Raspberry Pi 5 auf Kleinanzeigen im Umkreis von 30km um 21224",
        "[you] Suche Raspberry Pi 5 auf Kleinanzeigen.de im Umkreis von 30km um 21224",
        "raspberry pi 5 21224 30km kleinanzeigen",
        "Raspberry Pi 5",
    ]
    for raw in test_inputs:
        cleaned = _clean_query(raw)
        plz_in_clean = bool(re.search(r"(?<!\d)\d{5}(?!\d)", cleaned))
        icon = "❌ PLZ noch drin!" if plz_in_clean else "✅"
        print(f"  {icon}")
        print(f"    Input:  {raw[:70]}")
        print(f"    Output: '{cleaned}'\n")

    section("3. Intent Detection")
    try:
        from piclaw.config import load
        from piclaw.agent import Agent

        agent = Agent(load())
        for msg in [
            "Suche Raspberry Pi 5 auf Kleinanzeigen im Umkreis von 30km um 21224",
            "Raspberry Pi 5 kaufen",
        ]:
            r = agent._detect_marketplace_intent(msg)
            print(f"  Input:  {msg[:65]}")
            if r:
                q, plz, rad = (
                    r.get("query", ""),
                    r.get("location", ""),
                    r.get("radius_km", ""),
                )
                icon = "❌ PLZ im Query!" if plz and plz in q else "✅"
                print(f"  {icon} query='{q}' | location={plz} | radius={rad}km")
            else:
                print("  ❌ Intent nicht erkannt")
            print()
    except Exception as e:
        fail(f"Intent detection: {e}")

    section("4. Live-Suche Kleinanzeigen (PLZ 21224, 30km)")
    print("  Bitte warten (~5-10s)...\n")
    try:
        result = await marketplace_search(
            query="Raspberry Pi 5",
            platforms=["kleinanzeigen"],
            location="21224",
            radius_km=30,
            max_results=5,
            notify_all=True,
        )
        total = result.get("total_found", 0)
        q_sent = result.get("query", "")
        loc = result.get("location", "")
        info(f"Query an API: '{q_sent}' | Location: '{loc}'")
        info(f"Gefunden: {total}")
        if total > 0:
            ok(f"{total} Inserate – Bug behoben!")
            for item in result.get("new", [])[:3]:
                print(
                    f"    • {item['title'][:50]} | {item.get('price_text', '?')} | {item.get('location', '?')}"
                )
        else:
            fail("0 Inserate – Bug möglicherweise noch aktiv")
            info("Mögliche Ursachen:")
            info("  a) PLZ noch im Query (sieh Schritt 2)")
            info("  b) Kleinanzeigen blockiert Request (Bot-Schutz)")
            info("  c) Radius/PLZ-Parameter nicht korrekt in URL")
    except Exception as e:
        fail(f"Live-Suche: {e}")
        import traceback

        traceback.print_exc()

    section("5. SEEN_FILE")
    info(f"Pfad: {SEEN_FILE}")
    if SEEN_FILE.exists():
        import json

        d = json.loads(SEEN_FILE.read_text())
        info(
            f"Gespeicherte IDs: {len(d.get('seen', []))} | Aktualisiert: {d.get('updated', '?')}"
        )
    else:
        info("Noch keine seen-Datei (normale Erstinstallation)")

    print(f"\n{'=' * 60}")
    print("  ✉  Output komplett an Entwickler senden")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())

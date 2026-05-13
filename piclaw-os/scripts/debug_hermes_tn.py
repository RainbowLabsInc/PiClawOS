"""
Debug-Skript für den Hermes-Tracking-Endpoint.

Aufruf:
    python scripts/debug_hermes_tn.py <TRACKING-NUMMER>

Ziel: bei echten Hermes-Sendungen Roh-JSON-Response und den daraus von
`_query_hermes()` abgeleiteten Status nebeneinander sehen, um das
`_HERMES_PROGRESS_STATUS`-Mapping (Heuristik aus erstem Sniff) gegen reale
Daten zu validieren.

Pfad auf Pi: `/opt/piclaw/.venv/bin/python /opt/piclaw/piclaw-os/scripts/debug_hermes_tn.py <TN>`
"""
import asyncio
import json
import logging
import sys
from urllib.parse import quote_plus

import aiohttp

# Damit `from piclaw...` auch funktioniert wenn das Skript direkt aufgerufen wird.
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from piclaw.tools.parcel_tracking import (
    HEADERS,
    _HERMES_PROGRESS_STATUS,
    _query_hermes,
)

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")


async def fetch_raw(tracking_number: str) -> dict | list | None:
    """Roher GET, ohne Filterung – zeigt was Hermes wirklich zurückgibt."""
    url = f"https://api.my-deliveries.de/tnt/v2/shipments/search/{quote_plus(tracking_number)}"
    headers = {
        **HEADERS,
        "Accept": "application/json",
        "Origin": "https://www.myhermes.de",
        "Referer": "https://www.myhermes.de/",
        "x-language": "de",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            print(f"\n=== RAW REQUEST ===\nURL: {url}\nHTTP {resp.status}")
            try:
                data = await resp.json(content_type=None)
            except Exception as e:
                text = await resp.text()
                print(f"JSON-Parse fehlgeschlagen: {e}\nBody (first 500 chars):\n{text[:500]}")
                return None
            return data


def heuristic_match(status_text: str) -> str:
    """Spiegelt die Heuristik aus parcel_tracking.py:481-492 – zeigt welcher
    Branch greifen würde, wenn `progress.current` fehlt."""
    s_low = (status_text or "").lower()
    if "zugestellt" in s_low or "ausgehändigt" in s_low:
        return "delivered"
    if "in zustellung" in s_low or "ausgeliefert" in s_low:
        return "out_for_delivery"
    if "abholbereit" in s_low or "paketshop" in s_low:
        return "ready_for_pickup"
    if "rücksendung" in s_low or "retoure" in s_low:
        return "returned"
    return "in_transit"


async def main(tn: str) -> None:
    print(f"Hermes-Debug für TN: {tn}")
    print(f"Mapping: {_HERMES_PROGRESS_STATUS}")

    raw = await fetch_raw(tn)
    print("\n=== RAW JSON ===")
    print(json.dumps(raw, indent=2, ensure_ascii=False))

    if not raw:
        print("\nKein verwertbarer Response.")
        return

    shipments = raw if isinstance(raw, list) else raw.get("shipments", [])
    if not shipments:
        print("\nKeine shipments im Response.")
        return

    sh = shipments[0]
    progress = sh.get("progress", {}) or {}
    current = progress.get("current")
    status_obj = progress.get("status")
    status_text = (status_obj or {}).get("text", "") if isinstance(status_obj, dict) else ""
    status_text = status_text or sh.get("status", "")

    print("\n=== EXTRAKTION ===")
    print(f"progress.current       = {current!r}")
    print(f"progress.status.text   = {status_text!r}")
    print(f"status (top-level)     = {sh.get('status')!r}")
    print(f"Mapping-Lookup         = {_HERMES_PROGRESS_STATUS.get(current)!r}")
    print(f"Heuristik (Fallback)   = {heuristic_match(status_text)!r}")

    print("\n=== _query_hermes() Ergebnis ===")
    parsed = await _query_hermes(tn)
    print(json.dumps(parsed, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/debug_hermes_tn.py <TRACKING-NUMMER>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

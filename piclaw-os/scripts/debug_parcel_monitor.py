"""
Debug-Skript für `parcel_monitor_check()` und das Event-Change-Mapping.

Aufruf:
    python scripts/debug_parcel_monitor.py            # alle Pakete checken
    python scripts/debug_parcel_monitor.py <TN>       # nur ein Paket im Detail

Ohne TN: ruft `parcel_monitor_check()` einmal auf — die INFO-Logs der Funktion
zeigen für jedes Paket alt/neu/Änderungs-Flags. Persistierte parcels.json
wird nach dem Run nochmal gedumpt.

Mit TN: ruft `track_single()` direkt auf und stellt das Live-Ergebnis dem
gespeicherten Stand gegenüber. Berechnet zusätzlich was die patched Logik
`events_changed` ergeben würde.

Pfad auf Pi: `/opt/piclaw/.venv/bin/python /opt/piclaw/piclaw-os/scripts/debug_parcel_monitor.py [TN]`
"""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from piclaw.tools.parcel_tracking import (
    _latest_event_ts,
    _load_parcels,
    parcel_monitor_check,
    track_single,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def detail(tn: str) -> None:
    data = _load_parcels()
    stored = data["parcels"].get(tn)
    if not stored:
        print(f"❌ TN {tn} nicht in parcels.json")
        return

    print("=== Gespeichert (parcels.json) ===")
    print(json.dumps(stored, indent=2, ensure_ascii=False, default=str))

    print("\n=== Live ===")
    live = await track_single(tn, stored.get("carrier", "auto"))
    print(json.dumps(live, indent=2, ensure_ascii=False, default=str))

    print("\n=== Change-Detection (was die gepatched Logik sehen würde) ===")
    old_status = stored.get("status", "unknown")
    new_status = live.get("status", "unknown")
    old_events = stored.get("events", [])
    new_events = live.get("events", [])[:5]
    print(f"status_changed  = {new_status != old_status and new_status != 'unknown'}")
    print(f"  old_status    = {old_status!r}")
    print(f"  new_status    = {new_status!r}")
    print(f"events_changed  = {_latest_event_ts(new_events) > _latest_event_ts(old_events) or len(new_events) > len(old_events)}")
    print(f"  old_latest_ts = {_latest_event_ts(old_events)!r}")
    print(f"  new_latest_ts = {_latest_event_ts(new_events)!r}")
    print(f"  count         = {len(old_events)} → {len(new_events)}")


async def all_parcels() -> None:
    print("=== parcel_monitor_check() startet ===\n")
    result = await parcel_monitor_check()
    print("\n=== Rückgabe ===")
    print(repr(result))
    print("\n=== parcels.json nach Run ===")
    data = _load_parcels()
    for tn, p in data["parcels"].items():
        print(f"  {tn}: status={p.get('status')!r} status_text={p.get('status_text', '')[:60]!r} "
              f"events={len(p.get('events', []))} inbox_msg_id={'yes' if p.get('inbox_message_id') else 'no'}")


def main() -> None:
    if len(sys.argv) > 1:
        asyncio.run(detail(sys.argv[1]))
    else:
        asyncio.run(all_parcels())


if __name__ == "__main__":
    main()

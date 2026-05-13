"""
Backfill `inbox_thread_id` / `inbox_message_id` / `inbox_id` für Pakete die
vor Patch D-1 importiert wurden (also keine Mail-Referenz tragen).

Hintergrund: bis zum Patch der das Inbox-Cleanup eingeführt hat, persistierte
`_scan_agentmail_inbox()` keine Referenz auf die ursprüngliche Versand-Mail.
Damit greift weder der Inline-Hard-Delete in `parcel_monitor_check()` noch
der Safety-Net-Sub-Agent `Inbox_Cleanup_Pakete` für diese alten Pakete —
ihre Versand-Mails bleiben ewig in der AgentMail-Inbox liegen.

Dieses Skript füllt die Felder einmalig nach, indem es:
  1. Aus parcels.json alle Pakete extrahiert, die `inbox_thread_id` fehlt
     und noch nicht `delivered` sind.
  2. Die letzten N Mails aus der AgentMail-Inbox holt, deren Body durch die
     vorhandene `extract_tracking_numbers()` jagt.
  3. Bei einem TN-Match: nimmt die ÄLTESTE Mail (= Original-Versand-Bestätigung,
     nicht spätere Reminder) und backfillt die drei Felder.

Default ist Dry-Run — `--apply` schreibt erst wirklich.

Aufruf:
    python scripts/backfill_inbox_refs.py           # dry-run
    python scripts/backfill_inbox_refs.py --apply   # schreibt
"""
import argparse
import asyncio
import logging
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backfill_inbox_refs")

from piclaw.config import load as load_cfg
from piclaw.tools.parcel_tracking import (
    _load_parcels,
    _save_parcels,
    extract_tracking_numbers,
)


SCAN_LIMIT = 50  # Anzahl letzter Mails die wir durchsuchen


async def _collect_inbox_messages(client: Any, inbox_id: str) -> list[dict]:
    """Lädt die letzten SCAN_LIMIT Mails inkl. Body + thread_id."""
    msgs_res = await client.inboxes.messages.list(inbox_id=inbox_id, limit=SCAN_LIMIT)
    out = []
    for m in msgs_res.messages:
        msg_id = getattr(m, "message_id", None)
        thread_id = getattr(m, "thread_id", None)
        if not msg_id:
            continue
        try:
            full = await client.inboxes.messages.get(inbox_id=inbox_id, message_id=msg_id)
        except Exception as e:
            log.warning("  konnte msg %s nicht laden: %s", msg_id, e)
            continue
        body = ""
        if getattr(full, "extracted_text", None):
            body = full.extracted_text
        elif getattr(full, "text", None):
            body = full.text
        elif getattr(full, "extracted_html", None):
            body = re.sub(r"<[^>]+>", " ", full.extracted_html)
        subject = getattr(full, "subject", None) or getattr(m, "subject", None) or ""
        html_body = getattr(full, "html", None) or ""
        full_text = f"{subject}\n{body}\n{html_body}"
        out.append({
            "message_id": msg_id,
            "thread_id": getattr(full, "thread_id", None) or thread_id,
            "created_at": getattr(m, "created_at", None),
            "subject": subject or "(no subject)",
            "full_text": full_text,
        })
    return out


def _find_targets(data: dict) -> list[str]:
    """TNs die ein Backfill brauchen: nicht delivered und ohne thread_id."""
    targets = []
    for tn, p in data["parcels"].items():
        if p.get("status") == "delivered":
            continue
        if p.get("inbox_thread_id"):
            continue
        targets.append(tn)
    return targets


def _match_messages_to_targets(messages: list[dict], targets: list[str]) -> dict[str, dict]:
    """Pro Target-TN die älteste Mail finden, in der sie vorkommt."""
    # message_idx[tn] = liste von matches sortiert nach created_at
    found: dict[str, list[dict]] = {tn: [] for tn in targets}
    for msg in messages:
        for hit in extract_tracking_numbers(msg["full_text"]):
            tn = hit["tracking_number"]
            if tn in found:
                found[tn].append(msg)
    # Pro Target: älteste Mail nehmen
    result = {}
    for tn, matches in found.items():
        if not matches:
            continue
        oldest = min(matches, key=lambda m: m["created_at"] or "")
        result[tn] = oldest
    return result


async def main(apply: bool) -> int:
    cfg = load_cfg()
    if not cfg.agentmail.api_key or not cfg.agentmail.inbox_id:
        log.error("AgentMail nicht konfiguriert (api_key/inbox_id fehlt).")
        return 1

    data = _load_parcels()
    targets = _find_targets(data)
    if not targets:
        log.info("Keine Pakete brauchen ein Backfill (alle haben thread_id oder sind delivered).")
        return 0

    log.info("Targets für Backfill: %d Paket(e)", len(targets))
    for tn in targets:
        log.info("  → %s", tn)

    try:
        from agentmail import AsyncAgentMail
    except ImportError:
        log.error("agentmail package nicht installiert.")
        return 1

    client = AsyncAgentMail(api_key=cfg.agentmail.api_key)
    log.info("Scanne die letzten %d Mails aus Inbox %s …", SCAN_LIMIT, cfg.agentmail.inbox_id)
    try:
        messages = await _collect_inbox_messages(client, cfg.agentmail.inbox_id)
    except Exception as e:
        log.error("AgentMail Inbox-Scan fehlgeschlagen: %s", e)
        return 1

    log.info("Lade %d Mails, suche TN-Matches …", len(messages))
    matches = _match_messages_to_targets(messages, targets)

    log.info("")
    log.info("=== Match-Ergebnis ===")
    for tn in targets:
        m = matches.get(tn)
        if not m:
            log.warning("  %s : KEIN MATCH in den letzten %d Mails", tn, SCAN_LIMIT)
            continue
        log.info(
            "  %s ← thread=%s msg_id=%s (subject=%r created=%s)",
            tn, m["thread_id"], m["message_id"], m["subject"][:50], m["created_at"],
        )

    if not matches:
        log.info("Nichts zu schreiben.")
        return 0

    if not apply:
        log.info("")
        log.info("Dry-Run abgeschlossen. Mit --apply schreiben.")
        return 0

    # Apply: parcels.json frisch laden (Race-safe), Felder ergänzen, speichern
    log.info("")
    log.info("=== Apply ===")
    data = _load_parcels()
    written = 0
    for tn, m in matches.items():
        if tn not in data["parcels"]:
            log.warning("  %s: ist nicht mehr in parcels.json — skip", tn)
            continue
        if data["parcels"][tn].get("inbox_thread_id"):
            log.info("  %s: hat schon thread_id (race mit anderem Schreiber?) — skip", tn)
            continue
        data["parcels"][tn]["inbox_thread_id"] = m["thread_id"]
        data["parcels"][tn]["inbox_message_id"] = m["message_id"]
        data["parcels"][tn]["inbox_id"] = cfg.agentmail.inbox_id
        log.info("  %s: backfilled", tn)
        written += 1
    if written:
        _save_parcels(data)
        log.info("%d Paket(e) ge-backfillt.", written)
    else:
        log.info("Nichts geschrieben.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Tatsächlich schreiben (default ist dry-run)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(apply=args.apply)))

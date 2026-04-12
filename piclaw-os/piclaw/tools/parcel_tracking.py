"""
PiClaw OS – Paket-Tracking Tool
Verfolgt Pakete über DHL, Hermes, DPD, GLS, UPS via Parcello + DHL API.
Benachrichtigt via Telegram bei Statusänderungen.

Nutzung durch den Agent:
  parcel_add(tracking_number="00340434161094042557", label="Amazon Bestellung")
  parcel_status()
  parcel_remove(tracking_number="00340434161094042557")

Nutzung als Direct-Tool (Sub-Agent Monitor_Pakete):
  direct_tool="parcel_monitor"  →  prüft alle aktiven Pakete, meldet Änderungen
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import aiohttp

from piclaw.config import CONFIG_DIR
from piclaw.llm import ToolDefinition as _TD

log = logging.getLogger("piclaw.tools.parcel_tracking")

# ── Storage ──────────────────────────────────────────────────────────────────

PARCELS_FILE = CONFIG_DIR / "parcels.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Carrier Detection ────────────────────────────────────────────────────────

# Regex-Muster für automatische Carrier-Erkennung
CARRIER_PATTERNS = [
    # DHL Deutschland: 00-Prefix (12-20 Stellen) oder JJD/JVGL
    (re.compile(r"^00\d{10,18}$"), "dhl"),
    (re.compile(r"^JJD\d{12,18}$", re.IGNORECASE), "dhl"),
    (re.compile(r"^JVGL\d{10,16}$", re.IGNORECASE), "dhl"),
    # DHL Express / International (10-stellig)
    (re.compile(r"^\d{10}$"), "dhl"),
    # UPS: 1Z + 16 alphanumerisch
    (re.compile(r"^1Z[A-Z0-9]{16}$", re.IGNORECASE), "ups"),
    # Hermes: 14-16 Stellen
    (re.compile(r"^\d{14,16}$"), "hermes"),
    # DPD: 14 Stellen, oft mit 01-Prefix
    (re.compile(r"^01\d{12}$"), "dpd"),
    (re.compile(r"^\d{14}$"), "dpd"),
    # GLS: 11-12 Stellen
    (re.compile(r"^\d{11,12}$"), "gls"),
    # Amazon Logistics: TBA
    (re.compile(r"^TBA\d{10,14}$", re.IGNORECASE), "amazon"),
    # FedEx: 12 oder 15 Stellen
    (re.compile(r"^\d{12}$"), "fedex"),
    (re.compile(r"^\d{15}$"), "fedex"),
]

# Regex zum Extrahieren von Trackingnummern aus E-Mails/Nachrichten
RE_TRACKING_NUMBERS = re.compile(
    r"(?:^|\s|:\s*)"  # Anfang oder nach Leerzeichen/Doppelpunkt
    r"("
    r"1Z[A-Z0-9]{16}"  # UPS
    r"|00\d{10,18}"  # DHL
    r"|JJD\d{12,18}"  # DHL
    r"|JVGL\d{10,16}"  # DHL
    r"|TBA\d{10,14}"  # Amazon
    r"|\d{10,20}"  # Generisch (DHL/Hermes/DPD/GLS/FedEx)
    r")",
    re.IGNORECASE,
)

# Carrier-Anzeigenamen
CARRIER_NAMES = {
    "dhl": "DHL",
    "hermes": "Hermes",
    "dpd": "DPD",
    "gls": "GLS",
    "ups": "UPS",
    "amazon": "Amazon Logistics",
    "fedex": "FedEx",
    "unknown": "Unbekannt",
}

# Status-Emojis für Telegram
STATUS_EMOJI = {
    "pending": "📋",
    "in_transit": "📦",
    "out_for_delivery": "🚚",
    "delivered": "✅",
    "exception": "⚠️",
    "returned": "↩️",
    "unknown": "❓",
}

# Status-Texte Deutsch
STATUS_TEXT_DE = {
    "pending": "Angekündigt",
    "in_transit": "Unterwegs",
    "out_for_delivery": "In Zustellung",
    "delivered": "Zugestellt",
    "exception": "Problem",
    "returned": "Rücksendung",
    "unknown": "Unbekannt",
}


def detect_carrier(tracking_number: str) -> str:
    """Erkennt den Carrier anhand der Trackingnummer."""
    tn = tracking_number.strip().replace(" ", "")
    for pattern, carrier in CARRIER_PATTERNS:
        if pattern.match(tn):
            return carrier
    return "unknown"


def extract_tracking_numbers(text: str) -> list[dict]:
    """Extrahiert Trackingnummern aus einem Text (E-Mail, Nachricht etc.)."""
    matches = RE_TRACKING_NUMBERS.findall(text)
    results = []
    seen = set()
    for tn in matches:
        tn = tn.strip()
        if len(tn) < 10 or tn in seen:
            continue
        seen.add(tn)
        carrier = detect_carrier(tn)
        results.append({"tracking_number": tn, "carrier": carrier})
    return results


# ── Storage Management ───────────────────────────────────────────────────────

def _load_parcels() -> dict:
    """Lädt alle verfolgten Pakete aus parcels.json."""
    if PARCELS_FILE.exists():
        try:
            return json.loads(PARCELS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("parcels.json Lesefehler: %s", e)
    return {"parcels": {}, "archive": {}}


def _save_parcels(data: dict) -> None:
    """Speichert die Paketdaten."""
    PARCELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARCELS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _archive_delivered(data: dict, days: int = 7) -> int:
    """Verschiebt zugestellte Pakete nach X Tagen ins Archiv."""
    now = time.time()
    to_archive = []
    for tn, p in data["parcels"].items():
        if p.get("status") == "delivered":
            delivered_at = p.get("delivered_at", p.get("updated_at", 0))
            if now - delivered_at > days * 86400:
                to_archive.append(tn)

    for tn in to_archive:
        data["archive"][tn] = data["parcels"].pop(tn)

    if to_archive:
        _save_parcels(data)
        log.info("Archiviert: %d zugestellte Pakete", len(to_archive))
    return len(to_archive)


# ── Parcello Scraping ────────────────────────────────────────────────────────

async def _query_parcello(
    tracking_number: str,
    session: aiohttp.ClientSession | None = None,
) -> dict | None:
    """
    Fragt Parcello nach Tracking-Status + Zustellprognose.
    Parcello liefert Status UND geschätztes Zustellfenster.
    """
    url = f"https://www.parcello.org/app/track/{quote_plus(tracking_number)}"

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("Parcello HTTP %d für %s", resp.status, tracking_number)
                return None
            html = await resp.text()
    except Exception as e:
        log.warning("Parcello Fehler für %s: %s", tracking_number, e)
        return None
    finally:
        if close_session:
            await session.close()

    # Parcello liefert eine SPA — wir parsen die initiale JSON-Daten
    # die im HTML eingebettet sind (meist als __NUXT_DATA__ oder ähnlich)
    result = {"source": "parcello", "raw_status": None, "events": []}

    # Versuche JSON-Daten aus dem HTML zu extrahieren
    # Parcello verwendet verschiedene Muster für eingebettete Daten
    json_patterns = [
        re.compile(r'window\.__NUXT__\s*=\s*({.+?})\s*;?\s*</script>', re.DOTALL),
        re.compile(r'"trackingData"\s*:\s*({.+?})\s*[,}]', re.DOTALL),
        re.compile(r'"shipment"\s*:\s*({.+?})\s*[,}]', re.DOTALL),
    ]

    for pattern in json_patterns:
        m = pattern.search(html)
        if m:
            try:
                data = json.loads(m.group(1))
                result["raw_data"] = data
                break
            except json.JSONDecodeError:
                continue

    # Fallback: Suche nach Status-Indikatoren im HTML
    status_map = {
        "zugestellt": "delivered",
        "delivered": "delivered",
        "in zustellung": "out_for_delivery",
        "out for delivery": "out_for_delivery",
        "unterwegs": "in_transit",
        "in transit": "in_transit",
        "transit": "in_transit",
        "angekündigt": "pending",
        "elektronisch angekündigt": "pending",
        "information received": "pending",
        "problem": "exception",
        "exception": "exception",
        "rücksendung": "returned",
        "return": "returned",
    }

    html_lower = html.lower()
    for keyword, status in status_map.items():
        if keyword in html_lower:
            result["raw_status"] = status
            break

    # Zustellprognose extrahieren (Parcello's Hauptfeature)
    # Format: "voraussichtlich zwischen HH:MM und HH:MM"
    time_pattern = re.compile(
        r"(?:voraussichtlich|ankunft|lieferung)\s+.*?"
        r"(\d{1,2}[:.]\d{2})\s*(?:und|bis|-)\s*(\d{1,2}[:.]\d{2})",
        re.IGNORECASE,
    )
    m = time_pattern.search(html)
    if m:
        result["eta_from"] = m.group(1).replace(".", ":")
        result["eta_to"] = m.group(2).replace(".", ":")

    # Datum extrahieren
    date_pattern = re.compile(
        r"(?:am|lieferung)\s+(\d{1,2})\.\s*(\w+)\.?\s*(\d{4})?",
        re.IGNORECASE,
    )
    m = date_pattern.search(html)
    if m:
        result["eta_date"] = m.group(0).strip()

    return result if result.get("raw_status") or result.get("eta_from") else None


# ── DHL Unified Tracking API ────────────────────────────────────────────────

async def _query_dhl(
    tracking_number: str,
    api_key: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> dict | None:
    """
    Fragt die DHL Shipment Tracking Unified API ab.
    Benötigt DHL API Key (kostenlos von developer.dhl.com).
    Fällt zurück auf öffentliches Tracking ohne Key.
    """
    if not api_key:
        # Lade API Key aus Config
        try:
            import tomllib
            cfg_path = CONFIG_DIR / "config.toml"
            if cfg_path.exists():
                cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
                api_key = cfg.get("parcel_tracking", {}).get("dhl_api_key")
        except Exception:
            pass

    if not api_key:
        log.debug("Kein DHL API Key konfiguriert – überspringe DHL API")
        return None

    url = "https://api-eu.dhl.com/track/shipments"
    params = {"trackingNumber": tracking_number}
    headers = {
        "DHL-API-Key": api_key,
        "Accept": "application/json",
    }

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(
            url, params=params, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                log.warning("DHL API HTTP %d für %s", resp.status, tracking_number)
                return None
            data = await resp.json()
    except Exception as e:
        log.warning("DHL API Fehler für %s: %s", tracking_number, e)
        return None
    finally:
        if close_session:
            await session.close()

    shipments = data.get("shipments", [])
    if not shipments:
        return None

    ship = shipments[0]
    status = ship.get("status", {})

    # DHL Status-Mapping
    dhl_status_map = {
        "pre-transit": "pending",
        "transit": "in_transit",
        "delivered": "delivered",
        "failure": "exception",
        "unknown": "unknown",
    }

    # Events extrahieren
    events = []
    for ev in ship.get("events", []):
        events.append({
            "timestamp": ev.get("timestamp", ""),
            "location": ev.get("location", {}).get("address", {}).get("addressLocality", ""),
            "description": ev.get("description", ""),
            "status_code": ev.get("statusCode", ""),
        })

    # Zustellzeitprognose von DHL
    eta = ship.get("estimatedTimeOfDelivery")
    eta_str = None
    if eta:
        eta_str = eta.get("estimatedFrom") or eta.get("date")

    result = {
        "source": "dhl_api",
        "raw_status": dhl_status_map.get(
            status.get("statusCode", "unknown"), "unknown"
        ),
        "status_text": status.get("status", ""),
        "status_detail": status.get("description", ""),
        "events": events,
        "eta": eta_str,
        "service": ship.get("service", ""),
    }

    return result


# ── Combined Tracking ────────────────────────────────────────────────────────

async def track_single(tracking_number: str, carrier: str = "auto") -> dict:
    """
    Trackt ein einzelnes Paket über alle verfügbaren Quellen.
    Kombiniert Parcello (Prognose) + DHL API (Details).
    """
    tn = tracking_number.strip().replace(" ", "")
    if carrier == "auto":
        carrier = detect_carrier(tn)

    result = {
        "tracking_number": tn,
        "carrier": carrier,
        "carrier_name": CARRIER_NAMES.get(carrier, carrier),
        "status": "unknown",
        "status_text": "",
        "events": [],
        "eta": None,
        "eta_window": None,
        "checked_at": datetime.now().isoformat(),
    }

    async with aiohttp.ClientSession() as session:
        # Parallelabfrage: Parcello + DHL (falls DHL-Paket)
        tasks = [_query_parcello(tn, session)]
        if carrier == "dhl":
            tasks.append(_query_dhl(tn, session=session))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    parcello_result = results[0] if not isinstance(results[0], Exception) else None
    dhl_result = results[1] if len(results) > 1 and not isinstance(results[1], Exception) else None

    # DHL API hat Vorrang bei Status + Events (genauer)
    if dhl_result and dhl_result.get("raw_status"):
        result["status"] = dhl_result["raw_status"]
        result["status_text"] = dhl_result.get("status_detail", "")
        result["events"] = dhl_result.get("events", [])
        if dhl_result.get("eta"):
            result["eta"] = dhl_result["eta"]

    # Parcello hat Vorrang bei Zustellfenster (genauer)
    if parcello_result:
        if not result["status"] or result["status"] == "unknown":
            result["status"] = parcello_result.get("raw_status", "unknown")
        if parcello_result.get("eta_from"):
            result["eta_window"] = {
                "from": parcello_result["eta_from"],
                "to": parcello_result.get("eta_to", ""),
                "date": parcello_result.get("eta_date", ""),
            }

    result["status_emoji"] = STATUS_EMOJI.get(result["status"], "❓")
    result["status_de"] = STATUS_TEXT_DE.get(result["status"], "Unbekannt")

    return result


# ── Public API ───────────────────────────────────────────────────────────────

async def parcel_add(
    tracking_number: str,
    label: str = "",
    carrier: str = "auto",
) -> str:
    """Fügt ein Paket zur Verfolgung hinzu."""
    tn = tracking_number.strip().replace(" ", "")
    if len(tn) < 10:
        return "❌ Ungültige Trackingnummer (zu kurz)."

    if carrier == "auto":
        carrier = detect_carrier(tn)

    data = _load_parcels()
    if tn in data["parcels"]:
        return f"ℹ️ Paket {tn} wird bereits verfolgt."

    # Ersten Status abrufen
    status = await track_single(tn, carrier)

    data["parcels"][tn] = {
        "tracking_number": tn,
        "carrier": carrier,
        "carrier_name": CARRIER_NAMES.get(carrier, carrier),
        "label": label or "",
        "status": status.get("status", "unknown"),
        "status_text": status.get("status_text", ""),
        "eta_window": status.get("eta_window"),
        "events": status.get("events", [])[:5],  # Nur die letzten 5 Events
        "added_at": time.time(),
        "updated_at": time.time(),
    }
    _save_parcels(data)

    carrier_name = CARRIER_NAMES.get(carrier, carrier)
    emoji = STATUS_EMOJI.get(status.get("status", "unknown"), "📦")
    eta_str = ""
    if status.get("eta_window"):
        w = status["eta_window"]
        eta_str = f"\n🕐 Prognose: {w.get('date', 'heute')} {w['from']}–{w.get('to', '')}"

    label_str = f" ({label})" if label else ""
    return (
        f"{emoji} Paket hinzugefügt: {carrier_name} {tn}{label_str}\n"
        f"Status: {STATUS_TEXT_DE.get(status.get('status', 'unknown'), 'Unbekannt')}"
        f"{eta_str}"
    )


async def parcel_status(tracking_number: str | None = None) -> str:
    """Zeigt den Status aller (oder eines bestimmten) Pakete."""
    data = _load_parcels()

    if not data["parcels"]:
        return "📭 Keine Pakete in Verfolgung. Sende mir eine Trackingnummer!"

    if tracking_number:
        tn = tracking_number.strip().replace(" ", "")
        p = data["parcels"].get(tn)
        if not p:
            return f"❌ Paket {tn} nicht gefunden."

        # Aktuellen Status holen
        status = await track_single(tn, p.get("carrier", "auto"))
        return _format_single_status(p, status)

    # Alle Pakete
    lines = [f"📦 *{len(data['parcels'])} Paket(e) in Verfolgung:*\n"]
    for tn, p in data["parcels"].items():
        emoji = STATUS_EMOJI.get(p.get("status", "unknown"), "❓")
        carrier = p.get("carrier_name", "?")
        label = f" – {p['label']}" if p.get("label") else ""
        status_de = STATUS_TEXT_DE.get(p.get("status", "unknown"), "?")
        eta = ""
        if p.get("eta_window"):
            w = p["eta_window"]
            eta = f" (ca. {w.get('from', '')}–{w.get('to', '')})"
        lines.append(f"{emoji} *{carrier}*{label}: {status_de}{eta}")
        lines.append(f"   `{tn}`")

    return "\n".join(lines)


async def parcel_remove(tracking_number: str) -> str:
    """Entfernt ein Paket aus der Verfolgung."""
    tn = tracking_number.strip().replace(" ", "")
    data = _load_parcels()
    if tn not in data["parcels"]:
        return f"❌ Paket {tn} nicht gefunden."

    removed = data["parcels"].pop(tn)
    data["archive"][tn] = removed
    _save_parcels(data)

    label = f" ({removed.get('label', '')})" if removed.get("label") else ""
    return f"🗑️ Paket {tn}{label} aus Verfolgung entfernt."


async def parcel_extract_and_add(text: str) -> str:
    """
    Extrahiert Trackingnummern aus einem Text (E-Mail, Nachricht)
    und fügt sie automatisch zur Verfolgung hinzu.
    """
    found = extract_tracking_numbers(text)
    if not found:
        return "❌ Keine Trackingnummern im Text erkannt."

    results = []
    for item in found:
        result = await parcel_add(
            tracking_number=item["tracking_number"],
            carrier=item["carrier"],
        )
        results.append(result)

    return "\n\n".join(results)


# ── Monitor (Direct Tool für Sub-Agent) ──────────────────────────────────────

async def _scan_agentmail_inbox() -> list[str]:
    """
    Scannt die AgentMail-Inbox auf neue E-Mails mit Trackingnummern.
    Gibt Liste von Benachrichtigungen zurück (neue Pakete die hinzugefügt wurden).
    """
    try:
        import tomllib
        cfg_path = CONFIG_DIR / "config.toml"
        if not cfg_path.exists():
            return []
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        api_key = cfg.get("agentmail", {}).get("api_key", "")
        inbox_id = cfg.get("agentmail", {}).get("inbox_id", "")
        if not api_key or not inbox_id:
            return []
    except Exception:
        return []

    try:
        from agentmail import AsyncAgentMail
    except ImportError:
        return []

    # Letzten gescannten Zeitpunkt laden
    data = _load_parcels()
    last_scan = data.get("_inbox_last_scan", 0)

    try:
        client = AsyncAgentMail(api_key=api_key)
        msgs_res = await client.inboxes.messages.list(inbox_id=inbox_id, limit=10)
    except Exception as e:
        log.warning("AgentMail Inbox-Scan fehlgeschlagen: %s", e)
        return []

    if not msgs_res.messages:
        return []

    notifications = []
    new_last_scan = last_scan

    for msg in msgs_res.messages:
        # Zeitstempel des Messages prüfen
        msg_time = getattr(msg, "created_at", None)
        if msg_time:
            # ISO-String zu Unix-Timestamp
            try:
                from datetime import datetime as _dt
                if isinstance(msg_time, str):
                    # Versuche ISO-Format zu parsen
                    ts = _dt.fromisoformat(msg_time.replace("Z", "+00:00")).timestamp()
                else:
                    ts = float(msg_time)
                if ts <= last_scan:
                    continue  # Bereits verarbeitet
                new_last_scan = max(new_last_scan, ts)
            except Exception:
                pass  # Wenn Timestamp nicht parsbar → trotzdem verarbeiten

        # Text aus E-Mail extrahieren
        body = ""
        if hasattr(msg, "extracted_text") and msg.extracted_text:
            body = msg.extracted_text
        elif hasattr(msg, "text") and msg.text:
            body = msg.text
        subject = getattr(msg, "subject", "") or ""
        from_addr = getattr(msg, "from_address", "") or ""

        full_text = f"{subject}\n{body}"

        # Trackingnummern extrahieren
        found = extract_tracking_numbers(full_text)
        if not found:
            continue

        log.info(
            "AgentMail: %d Trackingnummer(n) in E-Mail von %s gefunden",
            len(found), from_addr,
        )

        for item in found:
            tn = item["tracking_number"]
            if tn in data["parcels"]:
                continue  # Bereits verfolgt

            # Label aus Betreff extrahieren
            label = subject[:50] if subject else f"via {from_addr}"

            try:
                result = await parcel_add(
                    tracking_number=tn,
                    label=label,
                    carrier=item["carrier"],
                )
                notifications.append(f"📧 {result}")
            except Exception as e:
                log.warning("Auto-Add für %s fehlgeschlagen: %s", tn, e)

    # Letzten Scan-Zeitpunkt aktualisieren
    if new_last_scan > last_scan:
        data = _load_parcels()  # Neu laden (parcel_add hat gespeichert)
        data["_inbox_last_scan"] = new_last_scan
        _save_parcels(data)

    return notifications


async def parcel_monitor_check() -> str:
    """
    Prüft alle aktiven Pakete auf Statusänderungen.
    Scannt auch die AgentMail-Inbox auf neue Trackingnummern.
    Wird vom Sub-Agent Monitor_Pakete als direct_tool aufgerufen.
    Gibt nur geänderte Pakete zurück (für Telegram-Benachrichtigung).
    """
    # 1. AgentMail-Inbox auf neue Versandbestätigungen scannen
    inbox_notifications = []
    try:
        inbox_notifications = await _scan_agentmail_inbox()
    except Exception as e:
        log.warning("AgentMail Inbox-Scan Fehler: %s", e)

    # 2. Alle aktiven Pakete auf Statusänderungen prüfen
    data = _load_parcels()
    if not data["parcels"]:
        return "__NO_NEW_RESULTS__"

    # Zugestellte Pakete archivieren
    _archive_delivered(data)

    changes = []

    for tn, p in list(data["parcels"].items()):
        old_status = p.get("status", "unknown")

        try:
            new = await track_single(tn, p.get("carrier", "auto"))
        except Exception as e:
            log.warning("Tracking-Fehler für %s: %s", tn, e)
            continue

        new_status = new.get("status", "unknown")

        # Status geändert?
        status_changed = new_status != old_status and new_status != "unknown"

        # ETA-Fenster neu/geändert?
        eta_changed = (
            new.get("eta_window") and
            new.get("eta_window") != p.get("eta_window")
        )

        if status_changed or eta_changed:
            # Update speichern
            p["status"] = new_status
            p["status_text"] = new.get("status_text", "")
            p["eta_window"] = new.get("eta_window")
            p["events"] = new.get("events", [])[:5]
            p["updated_at"] = time.time()
            if new_status == "delivered":
                p["delivered_at"] = time.time()

            changes.append(_format_change_telegram(p, old_status, new_status, eta_changed))

    _save_parcels(data)

    # Inbox-Funde + Statusänderungen zusammenführen
    all_notifications = inbox_notifications + changes

    if not all_notifications:
        return "__NO_NEW_RESULTS__"

    return "\n\n".join(all_notifications)


# ── Formatierung ─────────────────────────────────────────────────────────────

def _format_single_status(parcel: dict, live: dict) -> str:
    """Formatiert den detaillierten Status eines Pakets."""
    emoji = STATUS_EMOJI.get(live.get("status", "unknown"), "❓")
    carrier = parcel.get("carrier_name", "?")
    label = f" – {parcel['label']}" if parcel.get("label") else ""
    status_de = STATUS_TEXT_DE.get(live.get("status", "unknown"), "?")
    tn = parcel.get("tracking_number", "?")

    lines = [
        f"{emoji} *{carrier}*{label}",
        f"Status: *{status_de}*",
        f"Tracking: `{tn}`",
    ]

    if live.get("status_text"):
        lines.append(f"Details: {live['status_text']}")

    if live.get("eta_window"):
        w = live["eta_window"]
        lines.append(f"🕐 Prognose: {w.get('date', 'heute')} {w['from']}–{w.get('to', '')}")
    elif live.get("eta"):
        lines.append(f"🕐 Voraussichtlich: {live['eta']}")

    # Letzte Events
    events = live.get("events", [])[:3]
    if events:
        lines.append("\nLetzte Stationen:")
        for ev in events:
            loc = ev.get("location", "")
            desc = ev.get("description", "")
            ts = ev.get("timestamp", "")[:16].replace("T", " ")
            loc_str = f" ({loc})" if loc else ""
            lines.append(f"  • {ts} {desc}{loc_str}")

    return "\n".join(lines)


def _format_change_telegram(parcel: dict, old_status: str, new_status: str, eta_changed: bool) -> str:
    """Formatiert eine Statusänderung für Telegram-Benachrichtigung."""
    emoji = STATUS_EMOJI.get(new_status, "📦")
    carrier = parcel.get("carrier_name", "?")
    label = f" – {parcel.get('label', '')}" if parcel.get("label") else ""
    status_de = STATUS_TEXT_DE.get(new_status, "?")
    tn = parcel.get("tracking_number", "?")

    lines = [f"{emoji} *{carrier}*{label}: {status_de}"]

    if parcel.get("status_text"):
        lines.append(parcel["status_text"])

    if parcel.get("eta_window"):
        w = parcel["eta_window"]
        lines.append(f"🕐 {w.get('date', 'Heute')} {w['from']}–{w.get('to', '')}")

    lines.append(f"`{tn}`")

    return "\n".join(lines)


def format_parcels_telegram(data: dict) -> str:
    """Formatiert alle Pakete für Telegram."""
    parcels = data.get("parcels", {})
    if not parcels:
        return "📭 Keine Pakete in Verfolgung."

    lines = [f"📦 *{len(parcels)} Paket(e):*"]
    for tn, p in parcels.items():
        emoji = STATUS_EMOJI.get(p.get("status", "unknown"), "❓")
        carrier = p.get("carrier_name", "?")
        label = f" – {p['label']}" if p.get("label") else ""
        status_de = STATUS_TEXT_DE.get(p.get("status", "unknown"), "?")
        lines.append(f"{emoji} {carrier}{label}: {status_de} `{tn}`")

    return "\n".join(lines)


# ── Tool Definitions ─────────────────────────────────────────────────────────

TOOL_DEFS = [
    _TD(
        name="parcel_add",
        description=(
            "Fügt ein Paket zur Sendungsverfolgung hinzu. "
            "Erkennt den Carrier (DHL, Hermes, DPD, GLS, UPS) automatisch. "
            "Nutze dies wenn der User eine Trackingnummer schickt."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "Die Sendungsnummer / Tracking-ID",
                },
                "label": {
                    "type": "string",
                    "description": "Optionale Bezeichnung (z.B. 'Amazon Bestellung', 'Zalando')",
                },
            },
            "required": ["tracking_number"],
        },
    ),
    _TD(
        name="parcel_status",
        description=(
            "Zeigt den Status aller verfolgten Pakete oder eines bestimmten Pakets. "
            "Nutze dies bei Fragen wie 'Wo ist mein Paket?' oder 'Pakete'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "Optional: spezifische Trackingnummer. Ohne = alle Pakete.",
                },
            },
        },
    ),
    _TD(
        name="parcel_remove",
        description="Entfernt ein Paket aus der Sendungsverfolgung.",
        parameters={
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "Die Sendungsnummer die entfernt werden soll.",
                },
            },
            "required": ["tracking_number"],
        },
    ),
    _TD(
        name="parcel_extract",
        description=(
            "Extrahiert Trackingnummern aus einem Text (z.B. weitergeleitete "
            "Versandbestätigung, E-Mail-Body) und fügt sie automatisch hinzu."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Der Text der Trackingnummern enthält.",
                },
            },
            "required": ["text"],
        },
    ),
]


def build_handlers() -> dict:
    """Erstellt die Handler-Map für die Agent-Tool-Registrierung."""
    async def _add(**kw):
        return await parcel_add(
            tracking_number=kw.get("tracking_number", ""),
            label=kw.get("label", ""),
        )

    async def _status(**kw):
        return await parcel_status(
            tracking_number=kw.get("tracking_number"),
        )

    async def _remove(**kw):
        return await parcel_remove(
            tracking_number=kw.get("tracking_number", ""),
        )

    async def _extract(**kw):
        return await parcel_extract_and_add(
            text=kw.get("text", ""),
        )

    return {
        "parcel_add": _add,
        "parcel_status": _status,
        "parcel_remove": _remove,
        "parcel_extract": _extract,
    }


HANDLERS = build_handlers()

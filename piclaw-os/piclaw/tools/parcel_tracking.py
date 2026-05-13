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

# Regex zum Extrahieren von Trackingnummern aus E-Mails/Nachrichten.
# WICHTIG: Bewusst spezifisch — die generische `\d{10,20}` Variante hat zu viele
# False-Positives (Bestellnummern, Datums-IDs wie "20260427084422" matchen sonst).
# Nur bekannt-präfixe oder klar tracking-kontextbezogene Zahlen werden hier
# erfasst. Generische Hermes/DPD-/GLS-IDs ohne Präfix kommen nur durch wenn
# der Kontext "Sendungsnummer:" / "Tracking:" / "TrackID=" voraus geht.
RE_TRACKING_NUMBERS = re.compile(
    r"(?:"
    # Mit eindeutigem Präfix — Position egal
    r"(?:^|\s|[=?&/])(1Z[A-Z0-9]{16})"          # UPS
    r"|(?:^|\s|[=?&/])(00\d{18})"                # DHL (genau 20 stellig)
    r"|(?:^|\s|[=?&/])(JJD\d{12,18})"            # DHL
    r"|(?:^|\s|[=?&/])(JVGL\d{10,16})"           # DHL
    r"|(?:^|\s|[=?&/])(TBA\d{10,14})"            # Amazon
    # Kontext-erforderlich: nur wenn ein Tracking-Schlüsselwort direkt vorausgeht
    r"|(?:Sendung(?:s(?:nummer|verfolgung))?|Trackingnummer|Track(?:ing)?[\-\.]?(?:ID|Nr|Number)|TrackID|Versandnummer|Paketnummer|barcode|piececode)"
    r"[\s:=]*"
    r"(\d{10,20}|H[A-Z0-9]{10,20})"
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
    """Extrahiert Trackingnummern aus einem Text (E-Mail, Nachricht etc.).

    Bewusst konservativ: Generische Zahlen ohne Präfix (Hermes/DPD/GLS) werden
    nur erfasst wenn ein Schlüsselwort wie "Trackingnummer:" oder "TrackID="
    direkt vorausgeht. Sonst gäbe es zu viele False-Positives durch
    Bestellnummern und Datums-IDs.
    """
    # HTML-Link-Texte zusätzlich extrahieren (<a href="...">NUMMER</a>)
    import re as _re
    link_texts = _re.findall(r'<a[^>]+>([^<]{8,30})</a>', text)
    if link_texts:
        text = text + "\n" + "\n".join(link_texts)
    matches = RE_TRACKING_NUMBERS.findall(text)
    results = []
    seen = set()
    for groups in matches:
        # findall mit mehreren Capture-Groups liefert Tuples — wir nehmen die
        # erste nicht-leere Gruppe.
        if isinstance(groups, tuple):
            tn = next((g for g in groups if g), "")
        else:
            tn = groups
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


def _latest_event_ts(events: list[dict]) -> str:
    """Größter ISO-Timestamp aus einer Event-Liste (lexikographischer Vergleich
    funktioniert für ISO-8601). Leer wenn keine Events."""
    return max((e.get("timestamp", "") for e in events), default="")


async def _archive_inbox_message(parcel: dict) -> bool:
    """Markiert die Versand-Mail eines Pakets in AgentMail mit Label "archived".

    AgentMail hat kein hard-delete für Messages — Label-Update ist der offizielle
    Weg ([SDK: messages.update]). Bei Erfolg wird inbox_message_id aus dem
    parcel-Datensatz entfernt damit nicht erneut versucht wird.

    Returns True wenn die Mail wirklich archiviert wurde, False sonst
    (keine ID, kein API-Key, oder API-Fehler).
    """
    msg_id = parcel.get("inbox_message_id")
    inbox_id = parcel.get("inbox_id")
    if not msg_id or not inbox_id:
        return False
    try:
        from piclaw.config import load as _load_cfg
        from agentmail import AsyncAgentMail
        cfg = _load_cfg()
        if not cfg.agentmail.api_key:
            return False
        client = AsyncAgentMail(api_key=cfg.agentmail.api_key)
        await client.inboxes.messages.update(
            inbox_id=inbox_id,
            message_id=msg_id,
            add_labels=["archived"],
        )
        log.info(
            "AgentMail-Mail archiviert: %s in %s (Paket %s)",
            msg_id, inbox_id, parcel.get("tracking_number"),
        )
        # ID raus damit Safety-Net-Sub-Agent nicht nochmal versucht
        parcel.pop("inbox_message_id", None)
        return True
    except Exception as e:
        log.warning(
            "AgentMail-Archive fehlgeschlagen für %s (msg=%s): %s",
            parcel.get("tracking_number"), msg_id, e,
        )
        return False


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
    # WICHTIG: Keywords müssen spezifisch genug sein um nicht auf SPA-Boilerplate
    # zu matchen. "transit" allein matched z.B. immer (Meta-Tags, JS-Strings) →
    # falsche "in_transit"-Reports auch wenn Paket längst zugestellt ist.
    status_map = {
        "zugestellt": "delivered",
        "successfully delivered": "delivered",
        "in zustellung": "out_for_delivery",
        "out for delivery": "out_for_delivery",
        "unterwegs": "in_transit",
        "in transit": "in_transit",
        "elektronisch angekündigt": "pending",
        "information received": "pending",
        "rücksendung": "returned",
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


# ── DHL Public XHR (no auth) ────────────────────────────────────────────────

# DHL iconId → interner Status. Aus dhl.de/int-verfolgen/data/search Response.
# 1 = elektronisch angekündigt, 2-3 = unterwegs, 4 = Zustellfahrzeug, 5 = zugestellt
_DHL_ICON_STATUS = {
    "1": "pending",
    "2": "in_transit",
    "3": "in_transit",
    "4": "out_for_delivery",
    "5": "delivered",
}


async def _query_dhl_public(
    tracking_number: str,
    session: aiohttp.ClientSession | None = None,
) -> dict | None:
    """
    Fragt den öffentlichen DHL JSON-XHR-Endpoint ab (gleicher den dhl.de
    selbst nutzt). Kein API-Key nötig, dafür undokumentiert/best-effort.
    """
    url = (
        "https://www.dhl.de/int-verfolgen/data/search"
        f"?piececode={quote_plus(tracking_number)}&language=de"
    )
    headers = {**HEADERS, "Accept": "application/json"}

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(
            url, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                log.warning("DHL public HTTP %d für %s", resp.status, tracking_number)
                return None
            data = await resp.json(content_type=None)
    except Exception as e:
        log.warning("DHL public Fehler für %s: %s", tracking_number, e)
        return None
    finally:
        if close_session:
            await session.close()

    sendungen = data.get("sendungen") or []
    if not sendungen:
        return None

    s = sendungen[0]
    details = (s.get("sendungsdetails") or {}).get("sendungsverlauf") or {}
    if not details:
        return None

    icon_id = str(details.get("iconId", ""))
    status_text = details.get("status", "")
    fortschritt = details.get("fortschritt")
    max_fortschritt = details.get("maximalFortschritt")

    # Heuristik: iconId vorrangig, dann fortschritt, dann Statustext
    raw_status = _DHL_ICON_STATUS.get(icon_id)
    if not raw_status:
        if fortschritt and max_fortschritt and fortschritt == max_fortschritt:
            raw_status = "delivered"
        elif "zugestellt" in status_text.lower() or "erfolgreich" in status_text.lower():
            raw_status = "delivered"
        elif "rücksendung" in status_text.lower() or "retoure" in status_text.lower():
            raw_status = "returned"
        elif "problem" in status_text.lower():
            raw_status = "exception"
        else:
            raw_status = "in_transit"

    # Events normalisieren
    events = []
    for ev in details.get("events", []) or []:
        events.append({
            "timestamp": ev.get("datum", ""),
            "location": ev.get("ort", "") or "",
            "description": ev.get("status", ""),
        })

    return {
        "source": "dhl_public",
        "raw_status": raw_status,
        "status_text": status_text,
        "events": events,
        "current_event_at": details.get("datumAktuellerStatus", ""),
        "progress": (
            f"{fortschritt}/{max_fortschritt}"
            if fortschritt is not None and max_fortschritt is not None
            else None
        ),
    }


# ── Hermes Public XHR (no auth) ─────────────────────────────────────────────

# Hermes status-progress mapping. Die Hermes-API liefert eine numerische
# `progress.current` zwischen 0 und 5 plus `progress.status.text`.
# Empirisch ermittelt aus echten Hermes-Responses:
#   0/1 = elektronisch angekündigt (label printed)
#   2   = abgeholt / im Hub
#   3   = im Transport
#   4   = in Zustellung (Fahrer hat Paket)
#   5   = zugestellt
_HERMES_PROGRESS_STATUS = {
    0: "pending",
    1: "pending",
    2: "in_transit",
    3: "in_transit",
    4: "out_for_delivery",
    5: "delivered",
}


async def _query_hermes(
    tracking_number: str,
    session: aiohttp.ClientSession | None = None,
) -> dict | None:
    """
    Fragt den öffentlichen Hermes-XHR-Endpoint ab (gleicher den myhermes.de
    selbst nutzt, ermittelt via Browser-Network-Sniff).
    Kein API-Key, aber spezifischer x-language Header zwingend.
    """
    url = f"https://api.my-deliveries.de/tnt/v2/shipments/search/{quote_plus(tracking_number)}"
    headers = {
        **HEADERS,
        "Accept": "application/json",
        "Origin": "https://www.myhermes.de",
        "Referer": "https://www.myhermes.de/",
        "x-language": "de",
    }

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(
            url, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 404:
                # TN nicht im Hermes-System (häufig falsch extrahierte Order-IDs)
                log.debug("Hermes 404 für %s — TN nicht bekannt", tracking_number)
                return None
            if resp.status != 200:
                log.warning("Hermes HTTP %d für %s", resp.status, tracking_number)
                return None
            data = await resp.json(content_type=None)
    except Exception as e:
        log.warning("Hermes Fehler für %s: %s", tracking_number, e)
        return None
    finally:
        if close_session:
            await session.close()

    # Hermes-Response: list of shipments oder dict mit shipments
    shipments = data if isinstance(data, list) else data.get("shipments", [])
    if not shipments:
        return None

    sh = shipments[0]
    progress = sh.get("progress", {}) or {}
    current = progress.get("current")
    status_text = (progress.get("status") or {}).get("text", "") if isinstance(progress.get("status"), dict) else ""
    status_text = status_text or sh.get("status", "")

    # Status mapping: numerischer Fortschritt + Heuristik aus Statustext
    raw_status = _HERMES_PROGRESS_STATUS.get(current) if current is not None else None
    if not raw_status:
        s_low = status_text.lower()
        if "zugestellt" in s_low or "ausgehändigt" in s_low:
            raw_status = "delivered"
        elif "in zustellung" in s_low or "ausgeliefert" in s_low:
            raw_status = "out_for_delivery"
        elif "abholbereit" in s_low or "paketshop" in s_low:
            raw_status = "ready_for_pickup"
        elif "rücksendung" in s_low or "retoure" in s_low:
            raw_status = "returned"
        else:
            raw_status = "in_transit"

    # Events extrahieren (Hermes nennt sie events oder history)
    events = []
    raw_events = sh.get("events") or sh.get("history") or []
    for ev in raw_events:
        events.append({
            "timestamp": ev.get("timestamp") or ev.get("date") or "",
            "location": ev.get("location") or ev.get("place") or "",
            "description": ev.get("text") or ev.get("description") or ev.get("status", ""),
        })

    return {
        "source": "hermes_public",
        "raw_status": raw_status,
        "status_text": status_text,
        "events": events,
        "progress": f"{current}/5" if current is not None else None,
    }


# ── DPD / GLS via Scrapling (Anti-Bot-Bypass) ──────────────────────────────
#
# DPD und GLS rendern ihre Tracking-Daten als JSON-Response hinter dem SPA-
# Frontend. Direkter aiohttp-Call wird oft von Cloudflare/Anti-Bot-Layern
# geblockt — daher Scrapling, das im Repo schon für Marketplace-Scraping
# eingesetzt wird (Pattern: marketplace.py:_fetch_html). Tier 1 ist der
# leichtgewichtige stealth-HTTP-Fetcher; falls der nicht durchkommt fällt
# es auf StealthyFetcher (Camoufox-basiert, voller Headless-Browser) zurück.

# DPD Lifecycle-Status-Codes (`_eventCode` / numerischer State im
# parcellifecycle-Objekt). Mapping aus echten Responses ableitbar; Heuristik
# parallel zu Hermes/DHL.
_DPD_STATUS_MAP = {
    "ACCEPTED": "in_transit",
    "PICKEDUP": "in_transit",
    "ATSENDDEPOT": "in_transit",
    "ATDELIVERYDEPOT": "in_transit",
    "ONROAD": "in_transit",
    "OUTFORDELIVERY": "out_for_delivery",
    "DELIVERED": "delivered",
    "PICKUPBYCONSIGNEE": "delivered",
    "RETURNINPROGRESS": "returned",
    "RETURNED": "returned",
    "EXCEPTION": "exception",
    "PROBLEM": "exception",
}


async def _scrapling_get_json(url: str, label: str) -> dict | None:
    """Holt JSON via Scrapling. Versucht erst stealth-HTTP, fällt zurück auf
    Headless-Browser bei Anti-Bot-Block. Pattern adaptiert aus
    marketplace._fetch_html (wo es seit Monaten produktiv läuft).

    Returns:
        Dict mit JSON-Daten, oder Dict mit Key "_html" wenn nur HTML kam,
        oder None bei vollständigem Fehlschlag.
    """
    # Tier 1: Plain Fetcher mit stealth-Headers — schnell, kein Browser
    try:
        from scrapling import Fetcher
        fetcher = Fetcher()
        page = await asyncio.to_thread(
            fetcher.get, url,
            stealthy_headers=True, follow_redirects=True, timeout=20,
        )
        if page and getattr(page, "status", None) == 200:
            text = str(page.html_content)
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                # Body ist HTML statt JSON — wahrscheinlich Anti-Bot-Wall.
                # In Tier 2 weiter.
                pass
    except Exception as e:
        log.debug("%s: Scrapling-Fetcher Tier1 Fehler: %s", label, e)

    # Tier 2: StealthyFetcher (Chromium-basierter Browser mit Stealth-Mode +
    # Cloudflare-Bypass). fetch() ist ein @classmethod — direkt auf der Klasse
    # aufrufen, kein Instance-Setup nötig.
    try:
        from scrapling import StealthyFetcher
        page = await asyncio.to_thread(
            StealthyFetcher.fetch, url,
            headless=True,
            network_idle=True,
            solve_cloudflare=True,   # DPD/GLS sitzen oft hinter Cloudflare
            timeout=30000,
        )
        if page and getattr(page, "status", None) == 200:
            text = str(page.html_content)
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                # Browser-Render lieferte HTML — Caller soll selbst entscheiden
                # ob er den DOM nach eingebetteten JSON-Blobs durchsucht.
                return {"_html": text}
    except Exception as e:
        log.warning("%s: Scrapling StealthyFetcher Tier2 Fehler: %s", label, e)

    return None


def _parse_dpd_response(data: dict) -> dict | None:
    """Extrahiert Status + Events aus DPD parcellifecycle-Response."""
    # Struktur typischerweise: {"parcellifecycle": {"statusInfo": [{...}, ...]}}
    # oder {"parcelLifeCycleData": {"scanInfo": {"scanList": [...]}}}.
    # Wir akzeptieren beide Formate.
    lifecycle = (
        data.get("parcellifecycle")
        or data.get("parcelLifeCycleData")
        or {}
    )
    status_infos = (
        lifecycle.get("statusInfo")
        or (lifecycle.get("scanInfo") or {}).get("scanList")
        or []
    )
    if not status_infos:
        return None

    events = []
    raw_status = "in_transit"
    status_text = ""

    for entry in status_infos:
        # Verschiedene Feldnamen je nach API-Version
        code = (
            entry.get("status")
            or entry.get("statusCode")
            or entry.get("scanType", {}).get("code", "")
            if isinstance(entry.get("scanType"), dict)
            else entry.get("statusCode", "")
        )
        code_str = str(code).upper()
        text = (
            entry.get("description", {}).get("content", "")
            if isinstance(entry.get("description"), dict)
            else (entry.get("description") or entry.get("statusText") or "")
        )
        ts = (
            entry.get("date")
            or entry.get("timestamp")
            or entry.get("scanTimestamp", "")
        )
        loc = (
            entry.get("location", {}).get("city", "")
            if isinstance(entry.get("location"), dict)
            else (entry.get("location") or "")
        )

        events.append({
            "timestamp": ts,
            "location": loc,
            "description": text,
        })

        # Aktuellster (= erster) Status bestimmt das Mapping
        if not status_text:
            mapped = _DPD_STATUS_MAP.get(code_str)
            if mapped:
                raw_status = mapped
            elif "zugestellt" in text.lower() or "delivered" in text.lower():
                raw_status = "delivered"
            elif "zustellung" in text.lower() or "out for delivery" in text.lower():
                raw_status = "out_for_delivery"
            status_text = text

    return {
        "source": "dpd_scrapling",
        "raw_status": raw_status,
        "status_text": status_text,
        "events": events,
    }


def _parse_gls_response(data: dict) -> dict | None:
    """Extrahiert Status + Events aus GLS rstt001-Response."""
    # GLS-Format: {"tuStatus": [{"history": [...], "progressBar": {"statusInfo": "..."}}]}
    tu_status = data.get("tuStatus") or []
    if not tu_status:
        return None

    tu = tu_status[0]
    history = tu.get("history") or []
    progress = tu.get("progressBar") or {}
    status_info = progress.get("statusInfo") or progress.get("statusText") or ""
    progress_value = progress.get("statusBar") or progress.get("statusValue")

    events = []
    for entry in history:
        events.append({
            "timestamp": (
                f"{entry.get('date', '')} {entry.get('time', '')}".strip()
            ),
            "location": entry.get("address", {}).get("city", "")
            if isinstance(entry.get("address"), dict)
            else (entry.get("location") or ""),
            "description": entry.get("evtDscr") or entry.get("description") or "",
        })

    # Status-Heuristik aus statusInfo + numerischem progress
    raw_status = "in_transit"
    s_low = status_info.lower()
    if "delivered" in s_low or "zugestellt" in s_low:
        raw_status = "delivered"
    elif "out for delivery" in s_low or "zustellung" in s_low:
        raw_status = "out_for_delivery"
    elif "preadvice" in s_low or "angekündigt" in s_low or "data received" in s_low:
        raw_status = "pending"
    elif "exception" in s_low or "problem" in s_low:
        raw_status = "exception"
    elif "return" in s_low or "rücksendung" in s_low:
        raw_status = "returned"

    return {
        "source": "gls_scrapling",
        "raw_status": raw_status,
        "status_text": status_info,
        "events": events,
        "progress": (
            f"{progress_value}/5" if progress_value is not None else None
        ),
    }


async def _query_dpd(
    tracking_number: str,
    session: aiohttp.ClientSession | None = None,  # ungenutzt – Scrapling hat eigene Sessions
) -> dict | None:
    """Fragt DPD über Scrapling ab (REST-API direkt, Browser-Fallback)."""
    api_url = (
        "https://tracking.dpd.de/rest/plc/de_DE/"
        f"{quote_plus(tracking_number)}"
    )
    label = f"DPD {tracking_number}"
    data = await _scrapling_get_json(api_url, label)
    if not data or "_html" in data:
        log.warning("DPD %s: keine JSON-Antwort über Scrapling", tracking_number)
        return None
    parsed = _parse_dpd_response(data)
    if parsed is None:
        log.warning("DPD %s: Response nicht parsbar — Felder geändert?", tracking_number)
    return parsed


async def _query_gls(
    tracking_number: str,
    session: aiohttp.ClientSession | None = None,
) -> dict | None:
    """Fragt GLS über Scrapling ab."""
    api_url = (
        "https://gls-group.com/app/service/open/rest/DE/de/rstt001"
        f"?match={quote_plus(tracking_number)}"
    )
    label = f"GLS {tracking_number}"
    data = await _scrapling_get_json(api_url, label)
    if not data or "_html" in data:
        log.warning("GLS %s: keine JSON-Antwort über Scrapling", tracking_number)
        return None
    parsed = _parse_gls_response(data)
    if parsed is None:
        log.warning("GLS %s: Response nicht parsbar — Felder geändert?", tracking_number)
    return parsed


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

    Quellen-Priorität:
      1. DHL Public XHR (für DHL-Pakete) – kein Auth, echte Events
      2. DHL Unified API (für DHL-Pakete) – falls API-Key konfiguriert, als Backup
      3. Hermes Public XHR (für Hermes-Pakete) – kein Auth, echte Events
      4. DPD/GLS via Scrapling (Anti-Bot-Bypass für blockierte Carrier)
      5. Parcello-Scraping – Zustellfenster + Fallback für unbekannte Carrier
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

    # Dict-basiertes Slot-Mapping — vermeidet die alte None-Index-Padding-Logik
    # und macht das Hinzufügen weiterer Carrier trivial.
    async with aiohttp.ClientSession() as session:
        slots: dict[str, asyncio.Future | None] = {
            "parcello": _query_parcello(tn, session),
        }
        if carrier == "dhl":
            slots["dhl_public"] = _query_dhl_public(tn, session=session)
            slots["dhl_api"] = _query_dhl(tn, session=session)
        elif carrier == "hermes":
            slots["hermes"] = _query_hermes(tn, session=session)
        elif carrier == "dpd":
            slots["dpd"] = _query_dpd(tn)
        elif carrier == "gls":
            slots["gls"] = _query_gls(tn)

        keys = list(slots.keys())
        gathered = await asyncio.gather(
            *(slots[k] for k in keys), return_exceptions=True
        )
        results = dict(zip(keys, gathered))

    def _ok(r):
        return r if r and not isinstance(r, Exception) else None

    parcello_result = _ok(results.get("parcello"))
    dhl_public_result = _ok(results.get("dhl_public"))
    dhl_api_result = _ok(results.get("dhl_api"))
    hermes_result = _ok(results.get("hermes"))
    dpd_result = _ok(results.get("dpd"))
    gls_result = _ok(results.get("gls"))

    # Carrier-spezifische primäre Quelle
    primary = dhl_public_result or hermes_result or dpd_result or gls_result
    if primary and primary.get("raw_status"):
        result["status"] = primary["raw_status"]
        result["status_text"] = primary.get("status_text", "")
        result["events"] = primary.get("events", [])

    # DHL Unified API als Backup für DHL
    if dhl_api_result and dhl_api_result.get("raw_status"):
        if not result["events"]:
            result["events"] = dhl_api_result.get("events", [])
        if not result["status"] or result["status"] == "unknown":
            result["status"] = dhl_api_result["raw_status"]
            result["status_text"] = dhl_api_result.get("status_detail", "")
        if dhl_api_result.get("eta"):
            result["eta"] = dhl_api_result["eta"]

    # Parcello: Zustellfenster (genauer) + Fallback für unbekannte Carrier
    if parcello_result:
        if not result["status"] or result["status"] == "unknown":
            result["status"] = parcello_result.get("raw_status", "unknown")
        if parcello_result.get("eta_from"):
            result["eta_window"] = {
                "from": parcello_result["eta_from"],
                "to": parcello_result.get("eta_to", ""),
                "date": parcello_result.get("eta_date", ""),
            }

    # Wenn KEIN Quellen-Ergebnis nutzbar war: das ist ein Datenproblem,
    # nicht "kein Status-Change". Loggen damit der User es im journal sieht.
    if result["status"] == "unknown" and not result["events"]:
        log.warning(
            "Tracking %s (%s): keine Daten aus Carrier-API/Parcello — "
            "TN evtl. ungültig oder Carrier-Endpoint defekt", tn, carrier,
        )

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
            # ISO-String oder datetime zu Unix-Timestamp
            try:
                from datetime import datetime as _dt
                if isinstance(msg_time, str):
                    ts = _dt.fromisoformat(msg_time.replace("Z", "+00:00")).timestamp()
                elif isinstance(msg_time, _dt):
                    ts = msg_time.timestamp()
                else:
                    ts = float(msg_time)
                if ts <= last_scan:
                    continue  # Bereits verarbeitet
                new_last_scan = max(new_last_scan, ts)
            except Exception:
                pass  # Wenn Timestamp nicht parsbar → trotzdem verarbeiten

        # Vollen Message-Body via get() laden (list() gibt keinen Body zurück)
        msg_id = getattr(msg, "message_id", None)
        full_msg = msg
        if msg_id:
            try:
                full_msg = await client.inboxes.messages.get(
                    inbox_id=inbox_id, message_id=msg_id
                )
            except Exception as e:
                log.warning("AgentMail get() fehlgeschlagen für %s: %s", msg_id, e)

        body = ""
        if getattr(full_msg, "extracted_text", None):
            body = full_msg.extracted_text
        elif getattr(full_msg, "text", None):
            body = full_msg.text
        elif getattr(full_msg, "extracted_html", None):
            # HTML-Fallback: Tags entfernen
            body = re.sub(r"<[^>]+>", " ", full_msg.extracted_html)
        subject = getattr(full_msg, "subject", "") or getattr(msg, "subject", "") or ""
        from_addr = getattr(full_msg, "from_", "") or ""

        html_body = getattr(full_msg, "html", None) or ""
        full_text = f"{subject}\n{body}\n{html_body}"

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
                # Origin-Mail-Referenz mitnehmen für späteren Auto-Archive
                # nach Zustellung. parcel_add hat parcels.json schon gespeichert,
                # also frisch laden und nachreichen.
                if msg_id:
                    d_after = _load_parcels()
                    if tn in d_after["parcels"]:
                        d_after["parcels"][tn]["inbox_message_id"] = msg_id
                        d_after["parcels"][tn]["inbox_id"] = inbox_id
                        _save_parcels(d_after)
                notifications.append(f"📧 {result}")
            except Exception as e:
                log.warning("Auto-Add für %s fehlgeschlagen: %s", tn, e)

    # Letzten Scan-Zeitpunkt aktualisieren
    if new_last_scan > last_scan:
        data = _load_parcels()  # Neu laden (parcel_add hat gespeichert)
        data["_inbox_last_scan"] = new_last_scan
        _save_parcels(data)

    return notifications


async def parcel_inbox_import(silent_when_empty: bool = False) -> str:
    """
    Scannt die AgentMail-Inbox einmalig nach neuen Versandbestätigungen und
    fügt gefundene Trackingnummern zur Verfolgung hinzu.

    Bewusst NICHT Teil von parcel_monitor_check — der Inbox-Scan ist netzwerk-
    abhängig und hat unter Boot-Stress den ganzen Sub-Agent blockiert (sogar
    asyncio.wait_for griff nicht). Status-Updates müssen jederzeit durchlaufen,
    Inbox-Imports sind on-demand vom Nutzer oder über separate Routine.

    Args:
        silent_when_empty: Wenn True und keine neuen TNs gefunden, Rückgabe
            des Silent-Tokens "__NO_NEW_RESULTS__" statt freundlichem Text.
            Wird vom Sub-Agent Inbox_Scan_Pakete genutzt um den Telegram-
            Channel nicht alle 6h mit "📭 nichts neues" zu spammen.

    Tool-Name: parcel_inbox_import
    Beispiel-Aufruf vom Agent: "Scanne meine Mails nach neuen Tracking-Nummern"
    """
    try:
        notifications = await _scan_agentmail_inbox()
    except Exception as e:
        log.warning("AgentMail Inbox-Scan Fehler: %s", e)
        return f"❌ Inbox-Scan fehlgeschlagen: {e}"

    if not notifications:
        if silent_when_empty:
            return "__NO_NEW_RESULTS__"
        return "📭 Keine neuen Trackingnummern in der Inbox gefunden."

    return "📬 Neue Pakete aus E-Mails:\n\n" + "\n\n".join(notifications)


async def parcel_inbox_import_silent() -> str:
    """Silent-Variante für den Sub-Agent Inbox_Scan_Pakete (kein Spam bei leerer Inbox)."""
    return await parcel_inbox_import(silent_when_empty=True)


async def parcel_inbox_cleanup() -> str:
    """Safety-Net-Routine: archiviert AgentMail-Versand-Mails zugestellter
    Pakete die noch eine `inbox_message_id` tragen.

    Primärer Cleanup passiert inline in `parcel_monitor_check()` beim
    Statuswechsel auf delivered — diese Routine fängt Migrations-Lücke
    (alte Pakete vor Patch D), API-Fehler und Pi-Downtime ab.

    Grace-Period: 3 Tage nach `delivered_at`, damit der User Zeit hat die
    Mail noch zu sehen falls er will.

    Tool-Name: parcel_inbox_cleanup
    Wird vom Sub-Agent Inbox_Cleanup_Pakete als direct_tool aufgerufen.
    """
    data = _load_parcels()
    archived = 0
    grace = 3 * 86400  # 3 Tage
    now = time.time()

    for tn, p in data["parcels"].items():
        if p.get("status") != "delivered":
            continue
        if not p.get("inbox_message_id"):
            continue
        delivered_at = p.get("delivered_at", 0)
        if now - delivered_at < grace:
            continue
        if await _archive_inbox_message(p):
            archived += 1

    if archived:
        _save_parcels(data)

    if archived == 0:
        return "__NO_NEW_RESULTS__"
    return f"🧹 Inbox-Cleanup: {archived} Versand-Mail(s) archiviert."


async def parcel_monitor_check() -> str:
    """
    Prüft alle aktiven Pakete auf Statusänderungen.
    Wird vom Sub-Agent Monitor_Pakete als direct_tool aufgerufen.
    Gibt nur geänderte Pakete zurück (für Telegram-Benachrichtigung).

    Hinweis: Der Inbox-Scan ist NICHT mehr Teil dieses Checks. Er lief vorher
    bei jedem 30-min-Cycle gegen AgentMail und blockierte beim Pi-Boot-Stress
    den ganzen Sub-Agent. Stattdessen wird die Inbox via parcel_inbox_import
    on-demand gescannt (entweder durch User-Anfrage oder separates Schedule).
    """
    # Alle aktiven Pakete auf Statusänderungen prüfen
    data = _load_parcels()
    if not data["parcels"]:
        return "__NO_NEW_RESULTS__"

    # Zugestellte Pakete archivieren
    _archive_delivered(data)

    changes = []

    for tn, p in list(data["parcels"].items()):
        old_status = p.get("status", "unknown")
        old_status_text = p.get("status_text", "")
        old_events = p.get("events", [])

        try:
            new = await track_single(tn, p.get("carrier", "auto"))
        except Exception as e:
            log.warning("Tracking-Fehler für %s: %s", tn, e)
            continue

        new_status = new.get("status", "unknown")
        new_events = new.get("events", [])[:5]

        # Status geändert? (Top-Level: pending/in_transit/out_for_delivery/delivered)
        status_changed = new_status != old_status and new_status != "unknown"

        # ETA-Fenster neu/geändert?
        eta_changed = (
            new.get("eta_window") and
            new.get("eta_window") != p.get("eta_window")
        )

        # Neue Sendungs-Etappe? DHL bewegt Pakete durch viele Sub-Stationen
        # innerhalb desselben raw_status (z.B. "Vorbereitung Weitertransport"
        # bleibt in_transit). Vergleich per neuesten Event-Timestamp.
        events_changed = (
            _latest_event_ts(new_events) > _latest_event_ts(old_events)
            or len(new_events) > len(old_events)
        )

        # Diagnose-Log: eine Zeile pro Paket pro Check, damit der Pfad
        # selbst-erklärend wird (vorher war stiller Pfad ohne Spur in Logs)
        log.info(
            "parcel_monitor %s: old=%s/%r → new=%s/%r events=%d→%d "
            "status_changed=%s events_changed=%s eta_changed=%s",
            tn, old_status, old_status_text,
            new_status, new.get("status_text", ""),
            len(old_events), len(new_events),
            status_changed, events_changed, eta_changed,
        )

        if status_changed or eta_changed or events_changed:
            # Persistenz: Events + status_text werden IMMER aktualisiert sobald
            # sich was bewegt — auch wenn raw_status gleich bleibt. Sonst
            # zeigt /paket beim User veralteten Stand.
            if status_changed:
                p["status"] = new_status
            p["status_text"] = new.get("status_text", "")
            p["eta_window"] = new.get("eta_window")
            p["events"] = new_events
            p["updated_at"] = time.time()

            if new_status == "delivered" and old_status != "delivered":
                p["delivered_at"] = time.time()
                # Inline-Archive der Versand-Mail in AgentMail (Cleanup)
                await _archive_inbox_message(p)

            changes.append(_format_change_telegram(p, old_status, new_status, eta_changed))

    _save_parcels(data)

    if not changes:
        return "__NO_NEW_RESULTS__"

    return "\n\n".join(changes)


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
    _TD(
        name="parcel_inbox_import",
        description=(
            "Scannt die AgentMail-Inbox auf neue Versandbestätigungen und fügt "
            "gefundene Trackingnummern zur Verfolgung hinzu. Nutze dies wenn "
            "der User sagt 'Scanne meine Mails nach Paketen' oder 'Gibt es "
            "neue Pakete in der Mail-Inbox'. Läuft NICHT mehr automatisch im "
            "Monitor-Cycle (war Quelle eines Boot-Hangs)."
        ),
        parameters={"type": "object", "properties": {}},
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

    async def _inbox_import(**kw):
        return await parcel_inbox_import()

    async def _inbox_import_silent(**kw):
        return await parcel_inbox_import_silent()

    async def _inbox_cleanup(**kw):
        return await parcel_inbox_cleanup()

    return {
        "parcel_add": _add,
        "parcel_status": _status,
        "parcel_remove": _remove,
        "parcel_extract": _extract,
        "parcel_inbox_import": _inbox_import,
        # Nicht in TOOL_DEFS — interner Handler nur für Sub-Agent direct_tool
        "parcel_inbox_import_silent": _inbox_import_silent,
        "parcel_inbox_cleanup": _inbox_cleanup,
    }


HANDLERS = build_handlers()

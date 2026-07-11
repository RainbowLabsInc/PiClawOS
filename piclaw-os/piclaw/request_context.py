"""
PiClaw OS – Request Context
============================
Pro Eingangs-Request eine kurze UUID, die in einer ContextVar liegt und
von allen Sub-Systemen (Classifier, Router, Memory, Tools) gelesen werden
kann, um ihre Log-Zeilen und ihre Telemetrie-Events zu korrelieren.

Eingangspunkte (wo new_request_id() gesetzt wird):
  * FastAPI-Middleware           – jeder HTTP-Request bekommt eine ID
  * WebSocket-Loop               – jede Chat-Iteration bekommt eine ID
  * TelegramAdapter._handle_message
  * DiscordAdapter on_message
  * WhatsApp/Threema-Webhook-Handler (via API-Middleware bereits abgedeckt)

Konsumenten:
  * logging.LogRecord (via ContextFilter in logging_setup.py)
  * metrics.routing_events (via record_routing_event in metrics.py)
  * /api/trace/{request_id} (zeigt die zusammengehörigen Events)

Wenn nichts gesetzt ist: get_request_id() liefert "" (Falsy) – Konsumenten
können das ignorieren oder einen Default einsetzen. Damit ist die ganze
Mechanik nicht-invasiv: existierender Code, der request_id nicht kennt,
funktioniert unverändert.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

# Default leerer String macht Konsumenten-Checks bequem (`if rid:`).
_request_id: ContextVar[str] = ContextVar("piclaw_request_id", default="")


def new_request_id() -> str:
    """Erzeugt eine neue kurze Request-ID (8 hex chars).

    8 chars sind 32 Bits – Kollisionsrisiko ist bei den paar hundert
    parallelen Requests, die ein Pi handelt, vernachlässigbar.
    """
    return uuid.uuid4().hex[:8]


def set_request_id(rid: str) -> object:
    """Setzt die Request-ID im aktuellen Context und gibt das Reset-Token
    zurück. Nur benötigt, wenn man den Scope manuell verwalten will;
    sonst lieber `request_scope()` als Context Manager benutzen.
    """
    return _request_id.set(rid)


def reset_request_id(token: object) -> None:
    """Setzt die Request-ID auf den Wert vor `set_request_id()` zurück."""
    _request_id.reset(token)


def get_request_id() -> str:
    """Liefert die aktuelle Request-ID, oder "" wenn keine gesetzt ist."""
    return _request_id.get()


@contextmanager
def request_scope(rid: str | None = None) -> Iterator[str]:
    """Kontext-Manager: setzt eine Request-ID für die Dauer des `with`-Blocks
    und restauriert den vorigen Wert beim Verlassen.

    Beispiel:
        with request_scope() as rid:
            log.info("incoming")  # bekommt rid via ContextFilter
            await process(...)

    Wenn `rid` None ist, wird automatisch eine neue generiert.
    """
    if not rid:
        rid = new_request_id()
    token = _request_id.set(rid)
    try:
        yield rid
    finally:
        _request_id.reset(token)

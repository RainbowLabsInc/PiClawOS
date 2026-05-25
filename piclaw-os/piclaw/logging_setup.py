"""
PiClaw OS – Logging-Setup
==========================
Strukturiertes Logging mit Request-ID-Korrelation.

Aktivierung:
  Default                       → Text-Format wie gehabt, plus [rid=xxxxxxxx]
                                  Prefix sobald eine Request-ID gesetzt ist.
  PICLAW_LOG_FORMAT=json        → JSON-Lines, ein Objekt pro Zeile.

Felder in jeder Log-Zeile:
  ts          – ISO-Timestamp
  level       – DEBUG/INFO/WARNING/ERROR/CRITICAL
  logger      – Logger-Name (z.B. piclaw.llm.multirouter)
  msg         – formatierte Nachricht
  request_id  – aktuelle ContextVar (leer wenn nichts gesetzt)
  + alle `extra={}`-Felder die der Caller mitgibt

Migration: bestehender Code verwendet weiterhin log.info("..."),
log.warning("...") etc. – nichts muss umgestellt werden. Der
ContextFilter packt request_id automatisch dran.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

from piclaw.request_context import get_request_id

# Felder, die wir aus dem LogRecord NICHT in den JSON-Output dumpen,
# weil sie entweder redundant sind oder den Payload aufblähen.
_STD_FIELDS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class ContextFilter(logging.Filter):
    """Hängt request_id (und ggf. weitere ContextVars) an jeden LogRecord.

    Per Filter statt LoggerAdapter, damit es global wirkt – jeder
    `logging.getLogger("piclaw.x")` profitiert ohne Code-Änderung.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Schreibt jede Log-Zeile als JSON-Objekt (eine Zeile pro Record)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", "")
        if rid:
            payload["request_id"] = rid
        # `extra={}`-Felder mit aufnehmen (alles was nicht zu den
        # Standard-LogRecord-Attributen gehört)
        for key, value in record.__dict__.items():
            if key in _STD_FIELDS or key.startswith("_"):
                continue
            if key == "request_id":
                continue  # schon oben
            # Nicht-JSON-serialisierbare Werte überspringen (statt fallen)
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Default Text-Formatter, optional mit [rid=xxxxxxxx] Prefix."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        rid = getattr(record, "request_id", "")
        if rid:
            return f"{base}  [rid={rid}]"
        return base


def configure_logging(level: int = logging.INFO) -> None:
    """Initialisiert das Root-Logging.

    Idempotent: kann mehrfach aufgerufen werden (entfernt vorherige Handler).
    Wird einmal von api.lifespan und einmal von daemon.run aufgerufen.
    """
    fmt_mode = os.environ.get("PICLAW_LOG_FORMAT", "text").strip().lower()

    handler = logging.StreamHandler(sys.stderr)
    if fmt_mode == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    # Vorherige Handler entfernen, damit konsekutive Calls (api↔daemon ggf.
    # beide via lifespan + import side-effects) keine Duplikate produzieren.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

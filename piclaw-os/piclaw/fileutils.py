"""
PiClaw OS – File Utilities
===========================
Atomares Schreiben von Dateien: verhindert halb-geschriebene Configs
bei Stromausfall, vollem Speicher oder Kernel-Panik.

Strategie: write temp → fsync → rename (atomar auf POSIX/Linux)
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("piclaw.fileutils")


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Schreibt Text atomar:  tmp → fsync → rename.
    Wirft OSError bei Fehler (volles Dateisystem, fehlende Rechte, etc.)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Temporäre Datei im selben Verzeichnis (wichtig für atomares rename)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())  # Sicherstellen dass Kernel-Buffer geflusht
        os.replace(tmp_path, path)  # Atomar: altes File wird direkt ersetzt
    except Exception:
        # Aufräumen falls rename fehlschlug
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Schreibt JSON atomar. Wirft OSError oder json.JSONEncodeError."""
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))


def safe_write_text(path: Path, content: str, *, label: str = "") -> bool:
    """
    Wie atomic_write_text, aber loggt Fehler statt Exception zu werfen.
    Gibt True zurück bei Erfolg, False bei Fehler.
    Für nicht-kritische Writes (Logs, Cache).
    """
    try:
        atomic_write_text(path, content)
        return True
    except OSError as e:
        log.error("Disk-Write fehlgeschlagen%s: %s", f" ({label})" if label else "", e)
        return False


def safe_write_json(path: Path, data: Any, *, label: str = "") -> bool:
    """Wie safe_write_text für JSON."""
    try:
        atomic_write_json(path, data)
        return True
    except (OSError, TypeError, ValueError) as e:
        log.error("JSON-Write fehlgeschlagen%s: %s", f" ({label})" if label else "", e)
        return False

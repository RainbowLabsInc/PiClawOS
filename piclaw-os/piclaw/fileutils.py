"""
PiClaw OS – File Utilities
===========================
Atomares Schreiben von Dateien: verhindert halb-geschriebene Configs
bei Stromausfall, vollem Speicher oder Kernel-Panik.

Strategie: write temp → fsync → rename (atomar auf POSIX/Linux)

Zusätzlich: with_file_lock() für Read-Modify-Write-Zyklen über mehrere
Prozesse hinweg (API ↔ Daemon teilen sich Registry-Files).
"""

import json
import logging
import os
import sys
import tempfile
import time
from contextlib import contextmanager
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


# ── Cross-process file locking ────────────────────────────────────

@contextmanager
def with_file_lock(path: Path, timeout: float = 10.0):
    """Acquire an exclusive cross-process lock for read-modify-write cycles.

    The lock is a `<path>.lock` sentinel next to the target file, held via
    fcntl.flock. On Windows we no-op (dev only – production runs on Linux).

    Use it to wrap the entire read-merge-write sequence on shared
    registries (sub-agents, LLM backends, routines, users) that the API
    and the Daemon both mutate. Without it, two writers can run their
    own merge against stale on-disk content and the last-writer-wins
    pattern can silently drop a concurrent change.

    Raises TimeoutError if the lock can't be acquired within `timeout`.
    """
    path = Path(path)

    if sys.platform == "win32":
        # No-op on Windows – piclaw runs on Linux in production.
        # Local dev on Windows is single-process so the race doesn't matter.
        yield
        return

    import fcntl  # POSIX-only import

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start > timeout:
                    raise TimeoutError(
                        f"with_file_lock: could not acquire {lock_path} "
                        f"within {timeout:.1f}s – another writer is stuck?"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

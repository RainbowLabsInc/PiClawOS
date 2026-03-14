"""
PiClaw OS – Backup & Restore (v0.10)

Sichert und stellt wieder her:
  - /etc/piclaw/config.toml
  - /etc/piclaw/SOUL.md
  - /etc/piclaw/subagents.json
  - /etc/piclaw/sensors.json
  - /etc/piclaw/llm_registry.json
  - Memory-Datenbank (QMD)
  - Metriken-Datenbank (optional)

Ziele:
  - Lokaler USB-Stick:  /media/*/piclaw-backup/
  - Lokales Verzeichnis: /var/lib/piclaw/backups/
  - (Erweiterbar: S3, Nextcloud, SFTP)

CLI:
  piclaw backup          → Backup erstellen
  piclaw backup list     → Backups auflisten
  piclaw backup restore  → Neuestes Backup wiederherstellen
  piclaw backup restore --file backup.tar.gz → Spezifisches Backup
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

_SECS_PER_DAY = 86_400  # Sekunden pro Tag


logger = logging.getLogger(__name__)

CONFIG_DIR    = Path("/etc/piclaw")
BACKUP_DIR    = Path("/var/lib/piclaw/backups")
BACKUP_PREFIX = "piclaw-backup"
MAX_BACKUPS   = 10   # älteste werden automatisch gelöscht


# ── Was wird gesichert ────────────────────────────────────────────
BACKUP_TARGETS = [
    CONFIG_DIR / "config.toml",
    CONFIG_DIR / "SOUL.md",
    CONFIG_DIR / "subagents.json",
    CONFIG_DIR / "sensors.json",
    CONFIG_DIR / "llm_registry.json",
    CONFIG_DIR / "watchdog.toml",
]

BACKUP_OPTIONAL = [
    CONFIG_DIR / "metrics.db",
    CONFIG_DIR / "memory",        # QMD Verzeichnis
]


# ── Metadaten ─────────────────────────────────────────────────────
class BackupInfo(NamedTuple):
    path: Path
    ts: int
    size_kb: float
    version: str
    files: int

    @property
    def datetime_str(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    @property
    def age_str(self) -> str:
        age_s = int(time.time()) - self.ts
        if age_s < 60:
            return f"vor {age_s}s"
        if age_s < 3600:
            return f"vor {age_s // 60}min"
        if age_s < _SECS_PER_DAY:
            return f"vor {age_s // 3600}h"
        return f"vor {age_s // _SECS_PER_DAY}d"


def _write_manifest(manifest_path: Path, info: dict) -> None:
    from piclaw.fileutils import atomic_write_json
    atomic_write_json(manifest_path, info)


def _read_manifest(tar_path: Path) -> dict:
    try:
        with tarfile.open(tar_path, "r:gz", encoding="utf-8") as tar:
            member = tar.getmember("manifest.json")
            f = tar.extractfile(member)
            if f:
                return json.loads(f.read())
    except Exception as _e:
        log.debug("manifest read: %s", _e)
    return {}


# ── Backup erstellen ──────────────────────────────────────────────

async def create_backup(
    include_metrics: bool = False,
    output_dir: Path | None = None,
    note: str = "",
) -> Path:
    """
    Erstellt ein komprimiertes Backup-Archiv.
    Gibt den Pfad zur .tar.gz Datei zurück.
    """
    out_dir = Path(output_dir) if output_dir else BACKUP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{BACKUP_PREFIX}_{dt}.tar.gz"
    output_path = out_dir / filename

    # Sammle Dateien
    files_to_backup: list[tuple[Path, str]] = []  # (source, arcname)

    for target in BACKUP_TARGETS:
        if target.exists():
            files_to_backup.append((target, f"config/{target.name}"))

    if include_metrics:
        for opt in BACKUP_OPTIONAL:
            if opt.exists():
                if opt.is_dir():
                    for f in opt.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(CONFIG_DIR)
                            files_to_backup.append((f, f"config/{rel}"))
                else:
                    files_to_backup.append((opt, f"config/{opt.name}"))

    # Erstelle Manifest
    manifest = {
        "version": "0.10.0",
        "ts": ts,
        "datetime": dt,
        "hostname": os.uname().nodename,
        "note": note,
        "files": [arc for _, arc in files_to_backup],
        "include_metrics": include_metrics,
    }

    # Archiv bauen (in Thread, da I/O-intensiv)
    def _build():
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, manifest)

            with tarfile.open(output_path, "w:gz", compresslevel=6, encoding="utf-8") as tar:
                tar.add(manifest_path, arcname="manifest.json")
                for source, arcname in files_to_backup:
                    try:
                        tar.add(source, arcname=arcname)
                    except PermissionError:
                        logger.warning("Backup: Kein Zugriff auf %s (übersprungen)", source)

        return output_path

    result = await asyncio.to_thread(_build)
    size_kb = round(result.stat().st_size / 1024, 1)
    logger.info("Backup erstellt: %s (%s KB, %d Dateien)", result.name, size_kb, len(files_to_backup))

    # USB-Stick Kopie
    await _copy_to_usb(result)

    # Alte Backups aufräumen
    await _cleanup_old_backups(out_dir)

    return result


async def _copy_to_usb(backup_path: Path) -> bool:
    """Kopiert Backup auf angeschlossenen USB-Stick (falls vorhanden)."""
    def _find_usb() -> Path | None:
        for base in [Path("/media"), Path("/mnt")]:
            if not base.exists():
                continue
            for user_dir in base.iterdir():
                for mount in (user_dir.iterdir() if user_dir.is_dir() else [user_dir]):
                    if mount.is_mount() and not str(mount).endswith("boot"):
                        return mount
        return None

    def _copy():
        usb = _find_usb()
        if usb is None:
            return False
        usb_dest = usb / "piclaw-backup"
        usb_dest.mkdir(exist_ok=True)
        shutil.copy2(backup_path, usb_dest / backup_path.name)
        logger.info("Backup auf USB-Stick kopiert: %s", usb_dest)
        return True

    try:
        return await asyncio.to_thread(_copy)
    except Exception as e:
        logger.debug("USB-Kopie fehlgeschlagen: %s", e)
        return False


async def _cleanup_old_backups(out_dir: Path) -> None:
    """Löscht überzählige alte Backups."""
    def _clean():
        backups = sorted(out_dir.glob(f"{BACKUP_PREFIX}_*.tar.gz"), key=lambda p: p.stat().st_mtime)
        while len(backups) > MAX_BACKUPS:
            old = backups.pop(0)
            old.unlink()
            logger.info("Altes Backup gelöscht: %s", old.name)

    await asyncio.to_thread(_clean)


# ── Backups auflisten ─────────────────────────────────────────────

def list_backups(search_dirs: list[Path] | None = None) -> list[BackupInfo]:
    """Listet alle gefundenen Backups auf, neueste zuerst."""
    dirs = search_dirs or [BACKUP_DIR]

    # Auch USB-Sticks durchsuchen
    for base in [Path("/media"), Path("/mnt")]:
        if base.exists():
            for p in base.rglob("piclaw-backup"):
                if p.is_dir():
                    dirs.append(p)

    infos: list[BackupInfo] = []
    seen: set[str] = set()

    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob(f"{BACKUP_PREFIX}_*.tar.gz"), reverse=True):
            key = f.name
            if key in seen:
                continue
            seen.add(key)
            manifest = _read_manifest(f)
            infos.append(BackupInfo(
                path=f,
                ts=manifest.get("ts", int(f.stat().st_mtime)),
                size_kb=round(f.stat().st_size / 1024, 1),
                version=manifest.get("version", "?"),
                files=len(manifest.get("files", [])),
            ))

    return sorted(infos, key=lambda i: i.ts, reverse=True)


# ── Restore ───────────────────────────────────────────────────────

async def restore_backup(
    backup_path: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Stellt ein Backup wieder her.
    Bei dry_run=True wird nur angezeigt was gemacht würde.
    """
    # Neuestes Backup finden wenn kein Pfad angegeben
    if backup_path is None:
        backups = list_backups()
        if not backups:
            return {"ok": False, "error": "Keine Backups gefunden."}
        backup_path = backups[0].path

    if not backup_path.exists():
        return {"ok": False, "error": f"Backup nicht gefunden: {backup_path}"}

    manifest = _read_manifest(backup_path)
    restored: list[str] = []
    errors: list[str] = []

    def _restore():
        with tarfile.open(backup_path, "r:gz", encoding="utf-8") as tar:
            for member in tar.getmembers():
                if member.name == "manifest.json":
                    continue
                if not member.name.startswith("config/"):
                    continue

                rel_name = member.name[len("config/"):]
                dest = CONFIG_DIR / rel_name

                if dry_run:
                    restored.append(str(dest))
                    continue

                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    f = tar.extractfile(member)
                    if f:
                        content = f.read()
                        # Sicherheitskopie der aktuellen Datei
                        if dest.exists():
                            dest.rename(dest.with_suffix(dest.suffix + ".bak"))
                        dest.write_bytes(content)
                        restored.append(str(dest))
                except Exception as e:
                    errors.append(f"{rel_name}: {e}")

    await asyncio.to_thread(_restore)

    logger.info("Restore %s: %d Dateien, %d Fehler",
                "(DRY RUN) " if dry_run else "", len(restored), len(errors))

    return {
        "ok": len(errors) == 0,
        "backup": backup_path.name,
        "backup_ts": manifest.get("datetime", "?"),
        "restored": restored,
        "errors": errors,
        "dry_run": dry_run,
    }


# ── CLI-Hilfsfunktionen ───────────────────────────────────────────

def format_backup_list(backups: list[BackupInfo]) -> str:
    if not backups:
        return "  Keine Backups gefunden.\n  Erstelle eines mit: piclaw backup"

    lines = [f"  {'#':<3} {'Datum':<22} {'Größe':>8}  {'Dateien':>8}  {'Alter':<12}  Pfad"]
    lines.append("  " + "─" * 80)
    for i, b in enumerate(backups):
        lines.append(
            f"  {i+1:<3} {b.datetime_str:<22} {b.size_kb:>7.0f}KB  {b.files:>8}  {b.age_str:<12}  {b.path.name}"
        )
    return "\n".join(lines)
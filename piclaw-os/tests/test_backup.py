"""Tests für piclaw.backup – Backup & Restore."""

import asyncio
import json
import tarfile
import time
from pathlib import Path

import pytest

from piclaw.backup import (
    BackupInfo,
    _read_manifest,
    _write_manifest,
    create_backup,
    list_backups,
    restore_backup,
    format_backup_list,
    BACKUP_PREFIX,
)


@pytest.fixture
def fake_config_dir(tmp_path):
    """Erstellt eine temporäre Konfigurationsstruktur."""
    config_dir = tmp_path / "etc" / "piclaw"
    config_dir.mkdir(parents=True)

    (config_dir / "config.toml").write_text('[agent]\nname = "TestPiClaw"\n')
    (config_dir / "SOUL.md").write_text("# Test Soul\nIch bin ein Test-Agent.\n")
    (config_dir / "subagents.json").write_text(json.dumps([]))
    (config_dir / "sensors.json").write_text(json.dumps({}))

    return config_dir


@pytest.fixture
def backup_dir(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return d


# ── Manifest ──────────────────────────────────────────────────────


def test_write_read_manifest(tmp_path):
    manifest = {"version": "0.10.0", "ts": 12345, "files": ["a", "b"]}
    path = tmp_path / "manifest.json"
    _write_manifest(path, manifest)
    assert path.exists()
    result = json.loads(path.read_text())
    assert result["version"] == "0.10.0"
    assert result["ts"] == 12345


def test_read_manifest_from_tar(tmp_path):
    # Erstelle ein minimales .tar.gz mit manifest.json
    tar_path = tmp_path / "test.tar.gz"
    manifest = {"version": "0.10.0", "ts": 99999, "files": []}
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, manifest)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(manifest_path, arcname="manifest.json")
    result = _read_manifest(tar_path)
    assert result["ts"] == 99999


def test_read_manifest_missing(tmp_path):
    tar_path = tmp_path / "empty.tar.gz"
    with tarfile.open(tar_path, "w:gz"):
        pass
    result = _read_manifest(tar_path)
    assert result == {}


# ── BackupInfo ────────────────────────────────────────────────────


def test_backup_info_datetime_str():
    info = BackupInfo(
        path=Path("/tmp/test.tar.gz"),
        ts=1700000000,
        size_kb=42.5,
        version="0.10.0",
        files=5,
    )
    assert "2023" in info.datetime_str  # Unix 1700000000 ist 2023
    assert "UTC" in info.datetime_str


def test_backup_info_age_str():
    now = int(time.time())
    # 30 Sekunden alt
    info = BackupInfo(Path("/x"), now - 30, 10.0, "0.10.0", 3)
    assert "s" in info.age_str

    # 5 Minuten alt
    info2 = BackupInfo(Path("/x"), now - 300, 10.0, "0.10.0", 3)
    assert "min" in info2.age_str

    # 2 Stunden alt
    info3 = BackupInfo(Path("/x"), now - 7200, 10.0, "0.10.0", 3)
    assert "h" in info3.age_str

    # 3 Tage alt
    info4 = BackupInfo(Path("/x"), now - 3 * 86400, 10.0, "0.10.0", 3)
    assert "d" in info4.age_str


# ── create_backup ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_backup_basic(tmp_path, monkeypatch):
    """Backup erstellen – minimale Konfiguration."""
    # Monkeypatch CONFIG_DIR und BACKUP_DIR
    import piclaw.backup as backup_mod

    config_dir = tmp_path / "etc" / "piclaw"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('[agent]\nname="Test"\n')
    (config_dir / "SOUL.md").write_text("# Soul\n")

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(
        backup_mod,
        "BACKUP_TARGETS",
        [
            config_dir / "config.toml",
            config_dir / "SOUL.md",
        ],
    )

    result = await create_backup(output_dir=backup_dir, note="test backup")

    assert result.exists()
    assert result.suffix == ".gz"
    assert BACKUP_PREFIX in result.name

    # Manifest prüfen
    manifest = _read_manifest(result)
    assert manifest["version"] == "0.10.0"
    assert manifest["note"] == "test backup"
    assert len(manifest["files"]) >= 1


@pytest.mark.asyncio
async def test_create_backup_size(tmp_path, monkeypatch):
    """Backup-Datei sollte > 0 Bytes sein."""
    import piclaw.backup as backup_mod

    config_dir = tmp_path / "etc" / "piclaw"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("test = true\n")
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backup_mod, "BACKUP_TARGETS", [config_dir / "config.toml"])

    result = await create_backup(output_dir=backup_dir)
    assert result.stat().st_size > 0


# ── list_backups ─────────────────────────────────────────────────


def test_list_backups_empty(tmp_path):
    result = list_backups([tmp_path])
    assert result == []


def test_list_backups_sorted(tmp_path):
    """Neueste Backups zuerst."""
    for i, ts in enumerate([1000, 3000, 2000]):
        dt = "20231001_120000"
        p = tmp_path / f"{BACKUP_PREFIX}_{dt}_{i}.tar.gz"
        manifest = {"ts": ts, "version": "0.10.0", "files": []}
        manifest_file = tmp_path / "manifest.json"
        _write_manifest(manifest_file, manifest)
        with tarfile.open(p, "w:gz") as tar:
            tar.add(manifest_file, arcname="manifest.json")

    backups = list_backups([tmp_path])
    assert len(backups) == 3
    # Neueste zuerst
    assert backups[0].ts >= backups[1].ts >= backups[2].ts


# ── restore_backup ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_dry_run(tmp_path, monkeypatch):
    """Dry-Run sollte nichts schreiben."""
    import piclaw.backup as backup_mod

    config_dir = tmp_path / "etc" / "piclaw"
    config_dir.mkdir(parents=True)
    original_content = '[agent]\nname="Original"\n'
    (config_dir / "config.toml").write_text(original_content)

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backup_mod, "BACKUP_TARGETS", [config_dir / "config.toml"])

    # Backup erstellen
    backup_path = await create_backup(output_dir=backup_dir)

    # Config verändern
    (config_dir / "config.toml").write_text('[agent]\nname="Changed"\n')

    # Dry-Run
    result = await restore_backup(backup_path=backup_path, dry_run=True)
    assert result["dry_run"] is True
    assert result["ok"] is True

    # Datei sollte unverändert sein
    content = (config_dir / "config.toml").read_text()
    assert "Changed" in content


@pytest.mark.asyncio
async def test_restore_no_backups(tmp_path):
    result = await restore_backup(backup_path=None)
    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_restore_missing_file():
    result = await restore_backup(backup_path=Path("/nonexistent/backup.tar.gz"))
    assert result["ok"] is False


# ── format_backup_list ───────────────────────────────────────────


def test_format_backup_list_empty():
    output = format_backup_list([])
    assert "Keine Backups" in output
    assert "piclaw backup" in output


def test_format_backup_list_with_entries():
    now = int(time.time())
    backups = [
        BackupInfo(Path("/tmp/b1.tar.gz"), now - 3600, 42.0, "0.10.0", 5),
        BackupInfo(Path("/tmp/b2.tar.gz"), now - 7200, 38.5, "0.9.0", 4),
    ]
    output = format_backup_list(backups)
    assert "b1.tar.gz" in output
    assert "b2.tar.gz" in output
    assert "42" in output

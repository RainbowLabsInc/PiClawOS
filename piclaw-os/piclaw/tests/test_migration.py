"""
Phase 6 — Tests für das Migrations-Skript.

Wir importieren `scripts.migrate_to_multiuser` und testen die einzelnen
Funktionen isoliert in tmp_path-Sandboxen.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


# scripts/ ist nicht im Package-Pfad — wir laden das Modul über importlib.
@pytest.fixture(scope="module")
def migrate_mod():
    import importlib.util
    here = Path(__file__).resolve().parent
    script = here.parent.parent / "scripts" / "migrate_to_multiuser.py"
    spec = importlib.util.spec_from_file_location("migrate_to_multiuser", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_to_multiuser"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture
def sandbox(tmp_path):
    """Minimaler Pre-Multi-User-State in tmp_path."""
    (tmp_path / "config.toml").write_text(
        '[telegram]\n'
        'token = "12345:test"\n'
        'chat_id = "8764333284"\n\n'
        '[api]\n'
        'secret_key = "legacy-token-abc"\n',
        encoding="utf-8",
    )
    return tmp_path


# ── preflight ────────────────────────────────────────────────────


def test_preflight_ok(migrate_mod, sandbox):
    info = migrate_mod.preflight(sandbox)
    assert info["chat_id"] == "8764333284"
    assert info["secret_key"] == "legacy-token-abc"


def test_preflight_fails_without_chat_id(migrate_mod, tmp_path):
    (tmp_path / "config.toml").write_text(
        '[telegram]\ntoken = "x"\nchat_id = ""\n\n[api]\nsecret_key = "y"\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="chat_id ist leer"):
        migrate_mod.preflight(tmp_path)


def test_preflight_fails_without_secret_key(migrate_mod, tmp_path):
    (tmp_path / "config.toml").write_text(
        '[telegram]\ntoken = "x"\nchat_id = "111"\n\n[api]\nsecret_key = ""\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="secret_key ist leer"):
        migrate_mod.preflight(tmp_path)


def test_preflight_fails_if_already_migrated(migrate_mod, sandbox):
    (sandbox / "users.json").write_text(
        json.dumps([{"id": "x", "name": "y", "role": "admin"}]),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="bereits.*Admin"):
        migrate_mod.preflight(sandbox)


def test_preflight_fails_without_config_file(migrate_mod, tmp_path):
    with pytest.raises(RuntimeError, match="config.toml nicht gefunden"):
        migrate_mod.preflight(tmp_path)


# ── backup ────────────────────────────────────────────────────────


def test_backup_creates_tarball(migrate_mod, sandbox):
    (sandbox / "parcels.json").write_text('{"parcels":{}}', encoding="utf-8")
    tarball = migrate_mod.make_backup(sandbox)
    assert tarball.exists()
    assert tarball.suffix == ".gz"
    assert "pre-multiuser" in tarball.name
    assert tarball.parent.name == "backups"


def test_backup_only_includes_existing_files(migrate_mod, sandbox):
    import tarfile
    # Keine parcels.json — Backup sollte nur config.toml haben
    tarball = migrate_mod.make_backup(sandbox)
    with tarfile.open(tarball) as t:
        names = t.getnames()
    assert "config.toml" in names
    assert "parcels.json" not in names


# ── tag_parcels ───────────────────────────────────────────────────


def test_tag_parcels_only_untagged(migrate_mod, tmp_path):
    p = tmp_path / "parcels.json"
    p.write_text(json.dumps({
        "parcels": {
            "A": {"tracking_number": "A"},
            "B": {"tracking_number": "B", "owner_id": "existing"},
        },
        "archive": {"OLD": {"tracking_number": "OLD"}},
    }), encoding="utf-8")
    p_count, a_count = migrate_mod.tag_parcels(tmp_path, "patrick-id")
    assert p_count == 1
    assert a_count == 1
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["parcels"]["A"]["owner_id"] == "patrick-id"
    assert data["parcels"]["B"]["owner_id"] == "existing"  # nicht überschrieben
    assert data["archive"]["OLD"]["owner_id"] == "patrick-id"


def test_tag_parcels_no_file(migrate_mod, tmp_path):
    assert migrate_mod.tag_parcels(tmp_path, "x") == (0, 0)


# ── tag_routines ──────────────────────────────────────────────────


def test_tag_routines_preserves_system(migrate_mod, tmp_path):
    p = tmp_path / "routines.json"
    p.write_text(json.dumps([
        {"id": "morning", "action": "briefing"},
        {"id": "temp_check", "action": "direct_check"},
        {"id": "network_check", "action": "direct_check"},
    ]), encoding="utf-8")
    user_n, sys_n = migrate_mod.tag_routines(tmp_path, "patrick-id")
    assert user_n == 1  # morning
    assert sys_n == 2   # temp_check + network_check
    data = json.loads(p.read_text(encoding="utf-8"))
    routines_by_id = {r["id"]: r for r in data}
    assert routines_by_id["morning"]["owner_id"] == "patrick-id"
    assert routines_by_id["temp_check"].get("owner_id") is None
    assert routines_by_id["network_check"].get("owner_id") is None


# ── tag_subagents ─────────────────────────────────────────────────


def test_tag_subagents_list_format(migrate_mod, tmp_path):
    """List-Format (Test-Fixtures, vermutlich auch alte Pi-Installationen)."""
    p = tmp_path / "subagents.json"
    p.write_text(json.dumps([
        {"id": "a", "name": "Monitor"},
        {"id": "b", "name": "Other", "owner_id": "existing"},
    ]), encoding="utf-8")
    count = migrate_mod.tag_subagents(tmp_path, "patrick-id")
    assert count == 1  # nur 'a'
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data[0]["owner_id"] == "patrick-id"
    assert data[1]["owner_id"] == "existing"


def test_tag_subagents_dict_format(migrate_mod, tmp_path):
    """Dict-Format {id: def} — das echte Pi-Format aus sa_registry._save."""
    p = tmp_path / "subagents.json"
    p.write_text(json.dumps({
        "cbe61af9": {"name": "CronJob_0715", "mission": "x"},
        "abcd1234": {"name": "Monitor_Pakete", "owner_id": "existing"},
    }), encoding="utf-8")
    count = migrate_mod.tag_subagents(tmp_path, "patrick-id")
    assert count == 1
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["cbe61af9"]["owner_id"] == "patrick-id"
    assert data["abcd1234"]["owner_id"] == "existing"


def test_tag_subagents_unknown_format(migrate_mod, tmp_path):
    """Unbekannter Top-Level-Typ → 0, kein Crash."""
    p = tmp_path / "subagents.json"
    p.write_text(json.dumps("not a list or dict"), encoding="utf-8")
    assert migrate_mod.tag_subagents(tmp_path, "x") == 0


# ── tag_jobs_db ───────────────────────────────────────────────────


def test_tag_jobs_db_creates_column_and_tags(migrate_mod, tmp_path):
    db = tmp_path / "ipc" / "jobs.db"
    db.parent.mkdir()
    con = sqlite3.connect(str(db))
    # Altes Schema OHNE owner_user_id
    con.execute("""CREATE TABLE jobs (
        id TEXT PRIMARY KEY, query TEXT, urls TEXT, mode TEXT, cron TEXT,
        interval_sec INTEGER, max_depth INTEGER, max_pages INTEGER,
        timeout_sec INTEGER, until_pattern TEXT, notify_chat TEXT,
        created_at TEXT, status TEXT, last_run TEXT, run_count INTEGER,
        last_result TEXT, error TEXT, stopped_at TEXT)""")
    con.execute("INSERT INTO jobs (id) VALUES ('j1'), ('j2')")
    con.commit()
    con.close()

    count = migrate_mod.tag_jobs_db(tmp_path, "patrick-id")
    assert count == 2

    con = sqlite3.connect(str(db))
    cols = [r[1] for r in con.execute("PRAGMA table_info(jobs)").fetchall()]
    assert "owner_user_id" in cols
    rows = con.execute("SELECT id, owner_user_id FROM jobs").fetchall()
    con.close()
    assert {(r[0], r[1]) for r in rows} == {("j1", "patrick-id"), ("j2", "patrick-id")}


def test_tag_jobs_db_no_file(migrate_mod, tmp_path):
    assert migrate_mod.tag_jobs_db(tmp_path, "x") == 0


# ── move_memory ────────────────────────────────────────────────────


def test_move_memory(migrate_mod, tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# old", encoding="utf-8")
    (mem / "memory").mkdir()
    (mem / "memory" / "2026-05-01.md").write_text("day", encoding="utf-8")
    (mem / "sessions").mkdir()
    (mem / "sessions" / "s1.jsonl").write_text("{}", encoding="utf-8")

    main_m, daily_m, sess_m = migrate_mod.move_memory(tmp_path, "uid")
    assert (main_m, daily_m, sess_m) == (1, 1, 1)

    target = tmp_path / "users" / "uid" / "memory"
    assert (target / "MEMORY.md").exists()
    assert (target / "memory" / "2026-05-01.md").exists()
    assert (target / "sessions" / "s1.jsonl").exists()
    # Source-Files sind weg
    assert not (mem / "MEMORY.md").exists()


def test_move_memory_no_dir(migrate_mod, tmp_path):
    assert migrate_mod.move_memory(tmp_path, "x") == (0, 0, 0)


# ── Full Integration ──────────────────────────────────────────────


def test_full_migration_e2e(migrate_mod, sandbox):
    """E2E: aus sandbox einen vollständig migrierten Stand machen."""
    # Daten vorbereiten
    (sandbox / "parcels.json").write_text(json.dumps({
        "parcels": {"X1": {"tracking_number": "X1"}},
        "archive": {},
    }), encoding="utf-8")
    (sandbox / "routines.json").write_text(json.dumps([
        {"id": "morning", "action": "briefing"},
        {"id": "temp_check", "action": "direct_check"},
    ]), encoding="utf-8")
    (sandbox / "subagents.json").write_text(json.dumps([
        {"id": "a", "name": "M"},
    ]), encoding="utf-8")
    (sandbox / "memory").mkdir()
    (sandbox / "memory" / "MEMORY.md").write_text("old", encoding="utf-8")

    stats = migrate_mod.run_migration(sandbox, admin_name="patrick")

    # Verify
    users = json.loads((sandbox / "users.json").read_text(encoding="utf-8"))
    assert len(users) == 1
    admin = users[0]
    assert admin["name"] == "patrick"
    assert admin["role"] == "admin"
    assert admin["web_token"] == "legacy-token-abc"  # Legacy bleibt
    assert admin["telegram_chat_id"] == "8764333284"

    parcels = json.loads((sandbox / "parcels.json").read_text(encoding="utf-8"))
    assert parcels["parcels"]["X1"]["owner_id"] == admin["id"]

    routines = json.loads((sandbox / "routines.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in routines}
    assert by_id["morning"]["owner_id"] == admin["id"]
    assert by_id["temp_check"].get("owner_id") is None

    assert (sandbox / "users" / admin["id"] / "memory" / "MEMORY.md").exists()

    assert stats["admin_id"] == admin["id"]


def test_migration_idempotent(migrate_mod, sandbox):
    """Zweiter Aufruf muss preflight-Error werfen."""
    migrate_mod.run_migration(sandbox, admin_name="patrick")
    with pytest.raises(RuntimeError, match="bereits.*Admin"):
        migrate_mod.run_migration(sandbox, admin_name="patrick")

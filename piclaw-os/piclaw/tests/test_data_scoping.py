"""
Phase 4 — Daten-Scoping Tests.

Deckt ab:
  - parcels: owner_id wird beim Add gesetzt, Status filtert, Remove respektiert Ownership
  - routines: Routine.visible_to + RoutineRegistry-Filter
  - subagents: SubAgentDef.visible_to + list_all/list_enabled Filter
  - memory: per-User-Pfade vs. globale (Legacy) Pfade
  - ipc.jobs: owner_user_id-Spalte + Filter
"""

from __future__ import annotations

import pytest

from piclaw.agent_context import user_scope, current_user


# ── Parcels ──────────────────────────────────────────────────────


@pytest.fixture
def parcels_file(tmp_path, monkeypatch):
    """parcels.json in tmp_path mappen statt CONFIG_DIR/parcels.json."""
    import piclaw.tools.parcel_tracking as pt
    monkeypatch.setattr(pt, "PARCELS_FILE", tmp_path / "parcels.json")
    return tmp_path / "parcels.json"


@pytest.mark.asyncio
async def test_parcel_add_sets_owner_id(parcels_file, monkeypatch):
    import piclaw.tools.parcel_tracking as pt
    async def fake_track_single(tn, carrier):
        return {"status": "in_transit", "status_text": "On the way", "events": []}
    monkeypatch.setattr(pt, "track_single", fake_track_single)

    with user_scope("anna-id"):
        await pt.parcel_add("1234567890")

    data = pt._load_parcels()
    assert data["parcels"]["1234567890"]["owner_id"] == "anna-id"


@pytest.mark.asyncio
async def test_parcel_status_filters_by_user(parcels_file, monkeypatch):
    import piclaw.tools.parcel_tracking as pt
    async def fake_track_single(tn, carrier):
        return {"status": "in_transit", "status_text": "OK", "events": []}
    monkeypatch.setattr(pt, "track_single", fake_track_single)

    with user_scope("anna-id"):
        await pt.parcel_add("1111111111")
    with user_scope("patrick-id"):
        await pt.parcel_add("2222222222")

    # Anna sieht nur ihr Paket
    with user_scope("anna-id"):
        text = await pt.parcel_status()
    assert "1111111111" in text
    assert "2222222222" not in text

    # Patrick sieht nur sein Paket
    with user_scope("patrick-id"):
        text = await pt.parcel_status()
    assert "2222222222" in text
    assert "1111111111" not in text


@pytest.mark.asyncio
async def test_parcel_remove_only_own(parcels_file, monkeypatch):
    import piclaw.tools.parcel_tracking as pt
    async def fake_track_single(tn, carrier):
        return {"status": "in_transit", "status_text": "OK", "events": []}
    monkeypatch.setattr(pt, "track_single", fake_track_single)

    with user_scope("anna-id"):
        await pt.parcel_add("1111111111")

    # Patrick versucht Annas Paket zu löschen → "nicht gefunden"
    with user_scope("patrick-id"):
        result = await pt.parcel_remove("1111111111")
    assert "nicht gefunden" in result.lower()
    # Paket existiert weiterhin
    assert "1111111111" in pt._load_parcels()["parcels"]


@pytest.mark.asyncio
async def test_parcel_add_collision_with_other_owner(parcels_file, monkeypatch):
    import piclaw.tools.parcel_tracking as pt
    async def fake_track_single(tn, carrier):
        return {"status": "in_transit", "status_text": "OK", "events": []}
    monkeypatch.setattr(pt, "track_single", fake_track_single)

    with user_scope("anna-id"):
        await pt.parcel_add("1111111111")
    with user_scope("patrick-id"):
        result = await pt.parcel_add("1111111111")
    assert "anderen" in result.lower() or "already" in result.lower() or "❌" in result


@pytest.mark.asyncio
async def test_parcel_legacy_no_user_sees_all(parcels_file, monkeypatch):
    """user_id=None → System-/Legacy-Sicht: sieht alle Pakete."""
    import piclaw.tools.parcel_tracking as pt
    async def fake_track_single(tn, carrier):
        return {"status": "in_transit", "status_text": "OK", "events": []}
    monkeypatch.setattr(pt, "track_single", fake_track_single)

    with user_scope("anna-id"):
        await pt.parcel_add("1111111111")
    with user_scope("patrick-id"):
        await pt.parcel_add("2222222222")

    # Ohne user_scope → ContextVar default None → globale Sicht
    text = await pt.parcel_status()
    assert "1111111111" in text and "2222222222" in text


# ── Routines ─────────────────────────────────────────────────────


def test_routine_visible_to():
    from piclaw.routines import Routine
    sys_r = Routine(id="s", name="Temp", enabled=True, cron="* * * * *",
                    action="direct_check", params={}, owner_id=None)
    anna_r = Routine(id="a", name="Morning", enabled=True, cron="0 7 * * *",
                     action="briefing", params={}, owner_id="anna")
    # user_id=None (Admin/Scheduler) sieht alles
    assert sys_r.visible_to(None)
    assert anna_r.visible_to(None)
    # Patrick sieht System + eigene, nicht Annas
    assert sys_r.visible_to("patrick")
    assert not anna_r.visible_to("patrick")
    # Anna sieht ihre eigene
    assert anna_r.visible_to("anna")


def test_routine_registry_filter(tmp_path):
    from piclaw.routines import Routine, RoutineRegistry
    reg = RoutineRegistry(tmp_path / "routines.json")
    # Defaults sind alle System (owner_id=None)
    # Wir hängen eine User-spezifische dran
    anna_r = Routine(id="anna_brief", name="Anna Morning", enabled=True,
                     cron="0 7 * * *", action="briefing", params={},
                     owner_id="anna")
    reg.add(anna_r)
    all_for_anna = reg.all("anna")
    names = [r.id for r in all_for_anna]
    assert "anna_brief" in names
    # System-Defaults (temp_check etc.) auch sichtbar
    assert any(r.is_system for r in all_for_anna)
    # Patrick sieht NICHT Annas Routine
    all_for_patrick = reg.all("patrick")
    assert "anna_brief" not in [r.id for r in all_for_patrick]


def test_routine_registry_enabled_filter(tmp_path):
    from piclaw.routines import Routine, RoutineRegistry
    reg = RoutineRegistry(tmp_path / "routines.json")
    # Defaults sind enabled=False → enabled() für jeden User leer
    assert reg.enabled("anna") == []
    # Anna enabled-Routine hinzufuegen
    anna_r = Routine(id="anna_brief", name="Anna", enabled=True,
                     cron="0 7 * * *", action="briefing", params={},
                     owner_id="anna")
    reg.add(anna_r)
    assert [r.id for r in reg.enabled("anna")] == ["anna_brief"]
    assert reg.enabled("patrick") == []


# ── SubAgents ────────────────────────────────────────────────────


def test_subagent_visible_to():
    from piclaw.agents.sa_registry import SubAgentDef
    sys_sa = SubAgentDef(name="SysMon", description="", mission="",
                        tools=[], owner_id=None)
    user_sa = SubAgentDef(name="AnnaBot", description="", mission="",
                         tools=[], owner_id="anna")
    assert sys_sa.visible_to("patrick")  # System → für alle
    assert not user_sa.visible_to("patrick")  # Annas → nicht für Patrick
    assert user_sa.visible_to("anna")
    # user_id=None sieht alles
    assert sys_sa.visible_to(None)
    assert user_sa.visible_to(None)


def test_subagent_registry_list_filter(tmp_path, monkeypatch):
    from piclaw.agents import sa_registry
    monkeypatch.setattr(sa_registry, "SA_REGISTRY_FILE", tmp_path / "subagents.json")
    reg = sa_registry.SubAgentRegistry()

    sys_sa = sa_registry.SubAgentDef(
        name="SysMon", description="", mission="", tools=[], owner_id=None
    )
    anna_sa = sa_registry.SubAgentDef(
        name="AnnaBot", description="", mission="", tools=[], owner_id="anna"
    )
    reg.add(sys_sa)
    reg.add(anna_sa)

    assert {a.name for a in reg.list_all(None)} == {"SysMon", "AnnaBot"}
    assert {a.name for a in reg.list_all("anna")} == {"SysMon", "AnnaBot"}
    assert {a.name for a in reg.list_all("patrick")} == {"SysMon"}


# ── Memory ───────────────────────────────────────────────────────


def test_memory_per_user_paths(tmp_path, monkeypatch):
    from piclaw import users as users_mod
    from piclaw.memory import store

    # users/<id>/-Tree in tmp_path mappen
    monkeypatch.setattr(users_mod, "USERS_DIR", tmp_path / "users")

    # System-Memory (kein User-Kontext) → globale Pfade
    monkeypatch.setattr(store, "MEMORY_ROOT", tmp_path / "global_memory")
    monkeypatch.setattr(store, "MEMORY_MAIN", tmp_path / "global_memory" / "MEMORY.md")
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "global_memory" / "memory")
    monkeypatch.setattr(store, "SESSIONS_DIR", tmp_path / "global_memory" / "sessions")
    monkeypatch.setattr(store, "WORKSPACE_DIR", tmp_path / "global_memory" / "workspace")
    monkeypatch.setattr(store, "CONTEXT_FILE", tmp_path / "global_memory" / "context.md")

    # Ohne user_id → global
    store.write_fact("globaler fakt")
    assert "globaler fakt" in store.read_memory_main()

    # Mit user_id=anna → ~/users/anna/memory/
    store.write_fact("annas fakt", user_id="anna")
    anna_main = tmp_path / "users" / "anna" / "memory" / "MEMORY.md"
    assert anna_main.exists()
    assert "annas fakt" in anna_main.read_text(encoding="utf-8")

    # Anna's Fact ist NICHT in global memory
    assert "annas fakt" not in store.read_memory_main()


def test_memory_via_contextvar(tmp_path, monkeypatch):
    """Wenn user_id nicht explizit übergeben → ContextVar."""
    from piclaw import users as users_mod
    from piclaw.memory import store
    monkeypatch.setattr(users_mod, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(store, "MEMORY_ROOT", tmp_path / "global_memory")
    monkeypatch.setattr(store, "MEMORY_MAIN", tmp_path / "global_memory" / "MEMORY.md")
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "global_memory" / "memory")
    monkeypatch.setattr(store, "SESSIONS_DIR", tmp_path / "global_memory" / "sessions")
    monkeypatch.setattr(store, "WORKSPACE_DIR", tmp_path / "global_memory" / "workspace")
    monkeypatch.setattr(store, "CONTEXT_FILE", tmp_path / "global_memory" / "context.md")

    with user_scope("via-contextvar"):
        store.write_daily_note("hallo")

    path = tmp_path / "users" / "via-contextvar" / "memory" / "memory"
    files = list(path.glob("*.md")) if path.exists() else []
    assert len(files) == 1
    assert "hallo" in files[0].read_text(encoding="utf-8")


# ── IPC jobs.db ──────────────────────────────────────────────────


def test_jobs_db_owner_user_id_field(tmp_path, monkeypatch):
    from piclaw.agents import ipc
    monkeypatch.setattr(ipc, "JOBS_DB", tmp_path / "jobs.db")
    monkeypatch.setattr(ipc, "IPC_DIR", tmp_path)

    job_anna = ipc.CrawlJob(query="anna search", owner_user_id="anna-id")
    job_pat = ipc.CrawlJob(query="patrick search", owner_user_id="patrick-id")
    job_sys = ipc.CrawlJob(query="legacy", owner_user_id="")
    ipc.write_job(job_anna)
    ipc.write_job(job_pat)
    ipc.write_job(job_sys)

    # Alle: 3
    assert len(ipc.list_jobs()) == 3
    # Filter owner=anna: nur anna
    only_anna = ipc.list_jobs(owner_user_id="anna-id")
    assert len(only_anna) == 1 and only_anna[0].query == "anna search"
    # Filter owner='': nur System
    only_sys = ipc.list_jobs(owner_user_id="")
    assert len(only_sys) == 1 and only_sys[0].query == "legacy"


def test_jobs_db_migration_adds_column(tmp_path, monkeypatch):
    """Alte DB ohne owner_user_id-Spalte → ALTER TABLE fügt sie hinzu."""
    import sqlite3
    from piclaw.agents import ipc
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(ipc, "JOBS_DB", db_path)
    monkeypatch.setattr(ipc, "IPC_DIR", tmp_path)

    # DB im alten Schema anlegen (ohne owner_user_id)
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, query TEXT, urls TEXT, mode TEXT, cron TEXT,
            interval_sec INTEGER, max_depth INTEGER, max_pages INTEGER,
            timeout_sec INTEGER, until_pattern TEXT, notify_chat TEXT,
            created_at TEXT, status TEXT, last_run TEXT, run_count INTEGER,
            last_result TEXT, error TEXT, stopped_at TEXT
        )
    """)
    con.commit()
    con.close()

    # init_jobs_db sollte die Migration durchführen
    ipc.init_jobs_db()

    con = sqlite3.connect(str(db_path))
    cols = [r[1] for r in con.execute("PRAGMA table_info(jobs)").fetchall()]
    con.close()
    assert "owner_user_id" in cols


# ── agent_context (ContextVar selbst) ─────────────────────────────


def test_user_scope_sets_and_resets():
    from piclaw.agent_context import current_user, user_scope
    assert current_user.get() is None
    with user_scope("anna"):
        assert current_user.get() == "anna"
    assert current_user.get() is None


def test_user_scope_nested():
    from piclaw.agent_context import current_user, user_scope
    with user_scope("anna"):
        with user_scope("patrick"):
            assert current_user.get() == "patrick"
        assert current_user.get() == "anna"
    assert current_user.get() is None

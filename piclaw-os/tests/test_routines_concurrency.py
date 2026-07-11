"""
Regressionstests für das Cross-Process-Hardening der RoutineRegistry.

Szenario: api-Prozess (Routine-Tools) und Daemon (ProactiveRunner.mark_ran)
schreiben dieselbe routines.json. Vor dem _atomic_modify-Umbau schrieb jeder
Writer seinen kompletten (ggf. veralteten) In-Memory-Stand zurück – ein
mark_ran konnte eine parallel angelegte Routine verschwinden lassen.

Zwei Registry-Instanzen auf derselben Datei simulieren die zwei Prozesse.
"""

from piclaw.routines import DEFAULT_ROUTINES, RoutineRegistry


def _registry_pair(tmp_path):
    path = tmp_path / "routines.json"
    return RoutineRegistry(path), RoutineRegistry(path), path


def test_concurrent_create_and_mark_ran_both_survive(tmp_path):
    reg_api, reg_daemon, path = _registry_pair(tmp_path)

    # "API-Prozess" legt eine neue Routine an …
    custom = reg_api.create_custom(
        name="Kaffee-Erinnerung",
        cron="0 9 * * *",
        action="notify",
        params={"message": "Kaffee!"},
    )

    # … der "Daemon" (mit veraltetem In-Memory-Stand von vor dem Create)
    # markiert eine Default-Routine als gelaufen.
    reg_daemon.mark_ran("morning_briefing")

    # Frische dritte Instanz = was wirklich auf Platte steht.
    fresh = RoutineRegistry(path)
    assert fresh.get(custom.id) is not None, "create_custom wurde von mark_ran überschrieben"
    mb = fresh.get("morning_briefing")
    assert mb is not None
    assert mb.run_count == 1
    assert mb.last_run != ""


def test_concurrent_enable_and_remove_no_lost_update(tmp_path):
    reg_a, reg_b, path = _registry_pair(tmp_path)

    custom = reg_a.create_custom(
        name="Wegwerf-Routine", cron="0 0 * * *", action="notify", params={},
    )
    # B (stale) aktiviert eine Default-Routine, A entfernt danach die eigene.
    assert reg_b.enable("temp_check") is True
    assert reg_a.remove(custom.id) is True

    fresh = RoutineRegistry(path)
    assert fresh.get(custom.id) is None
    assert fresh.get("temp_check").enabled is True


def test_mark_ran_on_parallel_deleted_routine_is_noop(tmp_path):
    reg_a, reg_b, path = _registry_pair(tmp_path)

    custom = reg_a.create_custom(
        name="Kurzlebig", cron="0 0 * * *", action="notify", params={},
    )
    reg_b._load()  # B kennt die Routine
    assert reg_a.remove(custom.id) is True

    # B versucht mark_ran auf die inzwischen gelöschte Routine → darf sie
    # nicht wiederbeleben.
    reg_b.mark_ran(custom.id)
    fresh = RoutineRegistry(path)
    assert fresh.get(custom.id) is None


def test_corrupt_file_is_quarantined_not_overwritten(tmp_path):
    path = tmp_path / "routines.json"
    corrupt_content = '{"das ist": kein gültiges json'
    path.write_text(corrupt_content, encoding="utf-8")

    reg = RoutineRegistry(path)

    # Original wurde in Quarantäne verschoben, nicht überschrieben
    quarantined = list(tmp_path.glob("routines.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content
    assert not path.exists()

    # Defaults sind im Speicher aktiv
    assert {r.id for r in reg.all()} == {d["id"] for d in DEFAULT_ROUTINES}

    # Nächste Mutation persistiert Defaults + Änderung
    reg.enable("temp_check")
    fresh = RoutineRegistry(path)
    assert fresh.get("temp_check").enabled is True


def test_load_never_writes_on_missing_file(tmp_path):
    path = tmp_path / "routines.json"
    RoutineRegistry(path)
    # Reines Konstruieren/Lesen legt keine Datei an (erst eine Mutation)
    assert not path.exists()

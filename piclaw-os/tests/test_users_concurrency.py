"""
Regressionstests für das Cross-Process-Hardening der UserRegistry.

Writer: API-Endpoints, Telegram-Registrierung und cli_users (separater
Prozess). Vorher: atomic_write ohne Lock/Re-Read → der langsamste Writer
überschrieb die User der anderen. Korrupte users.json leerte die Registry
und der nächste Save zerstörte die Datei endgültig.
"""

from piclaw.users import UserRegistry


def test_concurrent_registrations_both_survive(tmp_path):
    path = tmp_path / "users.json"
    reg_api = UserRegistry(path)
    reg_cli = UserRegistry(path)

    admin = reg_api.register_pending("Patrick", "111")  # erster User → admin
    reg_cli.add_user(name="Anna", telegram_chat_id="222")

    fresh = UserRegistry(path)
    assert fresh.find_by_chat_id("111") is not None, "CLI-Writer hat API-User überschrieben"
    assert fresh.find_by_chat_id("222") is not None
    assert admin.is_admin


def test_stale_instance_mutation_does_not_lose_other_users(tmp_path):
    path = tmp_path / "users.json"
    reg_a = UserRegistry(path)
    reg_b = UserRegistry(path)  # lädt leeren Stand

    reg_a.register_pending("Patrick", "111")
    # reg_b ist stale (kennt Patrick nicht) und legt einen weiteren User an
    reg_b.register_pending("Anna", "222")

    fresh = UserRegistry(path)
    assert len(fresh.all()) == 2


def test_external_reference_stays_valid_after_reload(tmp_path):
    """API-Handler halten User-Objekte über Mutationen hinweg – das
    In-Place-Reconcile muss diese Referenzen aktuell halten."""
    path = tmp_path / "users.json"
    reg = UserRegistry(path)

    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "inbox_id", "inbox-1")

    # Die ursprünglich gehaltene Referenz sieht die Änderung
    assert u.overrides["agentmail"]["inbox_id"] == "inbox-1"


def test_corrupt_users_file_quarantined_not_wiped(tmp_path):
    path = tmp_path / "users.json"
    reg = UserRegistry(path)
    reg.register_pending("Patrick", "111")

    corrupt_content = '[{"id": kaputt'
    path.write_text(corrupt_content, encoding="utf-8")

    # Neue Instanz (z.B. CLI-Aufruf) trifft auf die korrupte Datei
    reg2 = UserRegistry(path)
    assert reg2.all() == []

    quarantined = list(tmp_path.glob("users.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content
    # Die korrupte Datei liegt nicht mehr am Originalpfad → ein späterer
    # Save kann die geretteten Daten nicht mehr überschreiben
    assert not path.exists()

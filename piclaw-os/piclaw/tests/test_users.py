"""
Tests fuer piclaw.users — User-Registry, Token-Lookup, Pending-Flow.

Wir vermeiden den Modul-Singleton (registry()/find_by_*) und instanziieren
UserRegistry direkt mit einem tmp_path, damit jeder Test isoliert bleibt.
"""

from __future__ import annotations

import json

import pytest

from piclaw.users import UserRegistry, User


@pytest.fixture
def reg(tmp_path):
    return UserRegistry(tmp_path / "users.json")


# ── Erste Registrierung wird Admin (selbst-Bootstrap) ─────────────


def test_first_pending_becomes_admin(reg):
    u = reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert u.role == "admin"
    assert u.is_admin
    assert reg.has_admin()


def test_second_pending_stays_pending(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    anna = reg.register_pending(name="Anna", telegram_chat_id="222")
    assert anna.role == "pending"
    assert not anna.is_active


def test_register_pending_is_idempotent_per_chat_id(reg):
    a = reg.register_pending(name="Patrick", telegram_chat_id="111")
    b = reg.register_pending(name="Patrick Duplicate", telegram_chat_id="111")
    assert a.id == b.id
    assert len(reg.all()) == 1


# ── Approve ──────────────────────────────────────────────────────


def test_approve_pending_moves_to_user(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")  # admin
    anna = reg.register_pending(name="Anna", telegram_chat_id="222")
    approved = reg.approve(anna.id)
    assert approved is not None
    assert approved.role == "user"
    assert approved.is_active


def test_approve_by_name(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    reg.register_pending(name="Anna", telegram_chat_id="222")
    approved = reg.approve("Anna")
    assert approved is not None and approved.role == "user"


def test_approve_unknown_returns_none(reg):
    assert reg.approve("nonexistent") is None


def test_approve_already_user_is_noop(reg):
    admin = reg.register_pending(name="Patrick", telegram_chat_id="111")
    result = reg.approve(admin.id)
    # admin bleibt admin, kein Rolle-Wechsel
    assert result.role == "admin"


# ── Token-Lookup (Auth) ──────────────────────────────────────────


def test_find_by_token_returns_active_user(reg):
    admin = reg.register_pending(name="Patrick", telegram_chat_id="111")
    found = reg.find_by_token(admin.web_token)
    assert found is not None and found.id == admin.id


def test_find_by_token_rejects_pending(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")  # admin
    anna = reg.register_pending(name="Anna", telegram_chat_id="222")
    assert anna.role == "pending"
    # Pending darf sich NICHT mit seinem Token einloggen
    assert reg.find_by_token(anna.web_token) is None


def test_find_by_token_rejects_empty(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert reg.find_by_token("") is None
    assert reg.find_by_token(None) is None  # type: ignore[arg-type]


def test_find_by_token_rejects_unknown(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert reg.find_by_token("definitely-not-a-real-token") is None


def test_tokens_are_unique_per_user(reg):
    a = reg.register_pending(name="Patrick", telegram_chat_id="111")
    reg.approve(reg.register_pending(name="Anna", telegram_chat_id="222").id)
    b = reg.find_by_chat_id("222")
    assert a.web_token != b.web_token


# ── Find-by-* ────────────────────────────────────────────────────


def test_find_by_chat_id(reg):
    u = reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert reg.find_by_chat_id("111").id == u.id
    # auch wenn caller einen int reinsteckt
    assert reg.find_by_chat_id(111).id == u.id  # type: ignore[arg-type]
    assert reg.find_by_chat_id("999") is None


def test_find_by_id(reg):
    u = reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert reg.find_by_id(u.id).id == u.id
    assert reg.find_by_id("nope") is None


def test_find_by_name_case_insensitive(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert reg.find_by_name("patrick").name == "Patrick"
    assert reg.find_by_name("PATRICK").name == "Patrick"


# ── Persistence (Round-Trip via Disk) ────────────────────────────


def test_persist_and_reload(tmp_path):
    path = tmp_path / "users.json"
    r1 = UserRegistry(path)
    admin = r1.register_pending(name="Patrick", telegram_chat_id="111")
    anna = r1.register_pending(name="Anna", telegram_chat_id="222")
    r1.approve(anna.id)

    r2 = UserRegistry(path)
    assert len(r2.all()) == 2
    again_admin = r2.find_by_id(admin.id)
    again_anna  = r2.find_by_id(anna.id)
    assert again_admin.role == "admin"
    assert again_anna.role == "user"
    assert again_admin.web_token == admin.web_token  # Token uebersteht Reload


def test_corrupt_json_yields_empty_registry(tmp_path, caplog):
    path = tmp_path / "users.json"
    path.write_text("NOT VALID JSON", encoding="utf-8")
    r = UserRegistry(path)
    assert r.all() == []


def test_save_writes_valid_json(tmp_path):
    path = tmp_path / "users.json"
    r = UserRegistry(path)
    r.register_pending(name="Patrick", telegram_chat_id="111")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["name"] == "Patrick"
    assert data[0]["role"] == "admin"


# ── Revoke / Letzten-Admin-Schutz ────────────────────────────────


def test_revoke_removes_user(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    anna = reg.register_pending(name="Anna", telegram_chat_id="222")
    reg.approve(anna.id)
    assert reg.revoke(anna.id) is True
    assert reg.find_by_id(anna.id) is None


def test_revoke_last_admin_refused(reg):
    admin = reg.register_pending(name="Patrick", telegram_chat_id="111")
    assert reg.revoke(admin.id) is False
    assert reg.find_by_id(admin.id) is not None


def test_revoke_admin_ok_if_other_admin_exists(reg):
    a1 = reg.register_pending(name="Patrick", telegram_chat_id="111")
    a2_pending = reg.register_pending(name="Anna", telegram_chat_id="222")
    reg.set_role(a2_pending.id, "admin")
    assert reg.revoke(a1.id) is True


def test_demote_last_admin_refused(reg):
    admin = reg.register_pending(name="Patrick", telegram_chat_id="111")
    # try to demote — should stay admin
    result = reg.set_role(admin.id, "user")
    assert result.role == "admin"


# ── Bootstrap-Admin (Migration) ──────────────────────────────────


def test_bootstrap_admin_with_existing_token(reg):
    legacy_token = "legacy-token-from-config-toml"
    admin = reg.bootstrap_admin(
        name="Patrick",
        telegram_chat_id="111",
        web_token=legacy_token,
    )
    assert admin.role == "admin"
    assert admin.web_token == legacy_token
    assert reg.find_by_token(legacy_token).id == admin.id


def test_bootstrap_admin_refuses_if_admin_exists(reg):
    reg.register_pending(name="Patrick", telegram_chat_id="111")
    with pytest.raises(RuntimeError):
        reg.bootstrap_admin(name="Other", telegram_chat_id="222", web_token="x")


# ── User-Pfade ───────────────────────────────────────────────────


def test_user_path_and_ensure_dirs(tmp_path, monkeypatch):
    # CONFIG_DIR und USERS_DIR sind beim Import gebunden — wir patchen das Modul
    # direkt, damit ensure_user_dirs in tmp_path schreibt.
    import piclaw.users as users_mod
    monkeypatch.setattr(users_mod, "USERS_DIR", tmp_path / "users")

    p = users_mod.user_path("abc123", "parcels.json")
    assert p == tmp_path / "users" / "abc123" / "parcels.json"
    assert not p.exists()  # user_path() legt nichts an

    base = users_mod.ensure_user_dirs("abc123")
    assert base.exists()
    assert (base / "memory" / "sessions").is_dir()


# ── User-Dataclass ───────────────────────────────────────────────


def test_user_dataclass_round_trip():
    u = User(
        id="abc",
        name="Test",
        telegram_chat_id="111",
        role="user",
        web_token="tok",
        created_at="2026-05-17T19:00:00+00:00",
    )
    d = u.to_dict()
    assert User.from_dict(d) == u


def test_user_from_dict_ignores_unknown_fields():
    u = User.from_dict({
        "id": "abc",
        "name": "Test",
        "telegram_chat_id": "111",
        "role": "user",
        "web_token": "tok",
        "created_at": "2026-05-17T19:00:00+00:00",
        "obsolete_field": "ignored",
    })
    assert u.name == "Test"

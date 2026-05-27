"""
Phase 5.7 — Tests für User.overrides + get_setting / set_override / clear_override.
"""

from __future__ import annotations

import pytest

from piclaw import users as users_mod
from piclaw.users import UserRegistry, User
from piclaw.agent_context import user_scope


@pytest.fixture
def reg(tmp_path, monkeypatch):
    r = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", r)
    return r


# ── Dataclass / Persistence ───────────────────────────────────────


def test_user_default_overrides_empty():
    u = User(
        id="abc", name="x", telegram_chat_id="1", role="user",
        web_token="t", created_at="2026-01-01",
    )
    assert u.overrides == {}


def test_user_dataclass_round_trip_with_overrides():
    u = User(
        id="abc", name="x", telegram_chat_id="1", role="user",
        web_token="t", created_at="2026-01-01",
        overrides={"homeassistant": {"token": "abc"}},
    )
    d = u.to_dict()
    assert d["overrides"] == {"homeassistant": {"token": "abc"}}
    again = User.from_dict(d)
    assert again == u


# ── set_override / get_override ───────────────────────────────────


def test_set_override_creates_section(reg):
    u = reg.register_pending("Patrick", "111")
    assert reg.set_override(u.id, "homeassistant", "token", "HA-token") is True
    assert reg.get_override(u.id, "homeassistant", "token") == "HA-token"


def test_set_override_multiple_keys_same_section(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    reg.set_override(u.id, "agentmail", "inbox_id", "inbox-123")
    assert u.overrides["agentmail"] == {"email_address": "p@a.to", "inbox_id": "inbox-123"}


def test_set_override_value_none_removes_key(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    reg.set_override(u.id, "agentmail", "inbox_id", "inbox-123")
    # None entfernt den einen Key
    reg.set_override(u.id, "agentmail", "email_address", None)
    assert "email_address" not in u.overrides["agentmail"]
    assert u.overrides["agentmail"]["inbox_id"] == "inbox-123"


def test_set_override_last_key_in_section_removes_section(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    reg.set_override(u.id, "agentmail", "email_address", None)
    assert "agentmail" not in u.overrides


def test_set_override_unknown_user(reg):
    assert reg.set_override("ghost-id", "homeassistant", "token", "x") is False


def test_get_override_returns_none_if_missing(reg):
    u = reg.register_pending("Patrick", "111")
    assert reg.get_override(u.id, "homeassistant", "token") is None


# ── clear_override ────────────────────────────────────────────────


def test_clear_override_specific_key(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    reg.set_override(u.id, "agentmail", "inbox_id", "inbox-123")
    assert reg.clear_override(u.id, "agentmail", "email_address") is True
    assert "email_address" not in u.overrides["agentmail"]
    assert u.overrides["agentmail"]["inbox_id"] == "inbox-123"


def test_clear_override_entire_section(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "x")
    reg.set_override(u.id, "homeassistant", "base_url", "http://...")
    assert reg.clear_override(u.id, "homeassistant") is True
    assert "homeassistant" not in u.overrides


def test_clear_override_missing_section(reg):
    u = reg.register_pending("Patrick", "111")
    assert reg.clear_override(u.id, "homeassistant") is False


# ── Persistence Round-Trip ────────────────────────────────────────


def test_overrides_persist_across_reload(tmp_path):
    path = tmp_path / "users.json"
    r1 = UserRegistry(path)
    u = r1.register_pending("Patrick", "111")
    r1.set_override(u.id, "homeassistant", "token", "HA-token-123")
    r1.set_override(u.id, "agentmail", "email_address", "p@a.to")

    r2 = UserRegistry(path)
    again = r2.find_by_id(u.id)
    assert again.overrides["homeassistant"]["token"] == "HA-token-123"
    assert again.overrides["agentmail"]["email_address"] == "p@a.to"


# ── get_setting (Modul-Funktion) ───────────────────────────────────


def test_get_setting_returns_fallback_when_no_user(reg):
    assert users_mod.get_setting(None, "homeassistant", "token", fallback="GLOBAL") == "GLOBAL"


def test_get_setting_returns_override_when_set(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "USER-TOKEN")
    assert users_mod.get_setting(u.id, "homeassistant", "token", fallback="GLOBAL") == "USER-TOKEN"


def test_get_setting_falls_back_when_no_override(reg):
    u = reg.register_pending("Patrick", "111")
    assert users_mod.get_setting(u.id, "homeassistant", "token", fallback="GLOBAL") == "GLOBAL"


def test_get_setting_for_current_via_contextvar(reg):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    with user_scope(u.id):
        assert users_mod.get_setting_for_current("agentmail", "email_address", "DEF") == "p@a.to"
    # Außerhalb des scopes → fallback
    assert users_mod.get_setting_for_current("agentmail", "email_address", "DEF") == "DEF"

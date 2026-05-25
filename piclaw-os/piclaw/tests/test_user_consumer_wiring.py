"""
Phase 5.8 — Tests für Consumer-Wiring: HA-Client + AgentMail-Inbox
honorieren Per-User-Overrides.
"""

from __future__ import annotations

import pytest

from piclaw import users as users_mod
from piclaw.users import UserRegistry
from piclaw.agent_context import user_scope


@pytest.fixture(autouse=True)
def reg(tmp_path, monkeypatch):
    r = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", r)
    return r


# ── HomeAssistant get_client() ────────────────────────────────────


@pytest.fixture
def ha_global_client(monkeypatch):
    """Globaler HA-Client mit Default-Config; user-cache leeren."""
    from piclaw.tools import homeassistant as ha
    monkeypatch.setattr(ha, "_user_clients", {})
    global_cfg = ha.HAConfig(
        url="http://global.local:8123", token="GLOBAL-TOK", verify_ssl=False
    )
    global_client = ha.HomeAssistantClient(global_cfg)
    monkeypatch.setattr(ha, "_client", global_client)
    return global_client


def test_get_client_returns_global_when_no_user_context(ha_global_client):
    from piclaw.tools import homeassistant as ha
    # Kein user_scope → ContextVar None → global
    assert ha.get_client() is ha_global_client


def test_get_client_returns_global_when_user_has_no_override(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    with user_scope(u.id):
        assert ha.get_client() is ha_global_client


def test_get_client_returns_user_specific_when_token_override(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "USER-TOK")
    with user_scope(u.id):
        client = ha.get_client()
    assert client is not ha_global_client
    assert client.cfg.token == "USER-TOK"
    # URL fällt auf global zurück
    assert client.cfg.url == "http://global.local:8123"


def test_get_client_returns_user_specific_when_url_override(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "url", "http://anna.local:8123")
    with user_scope(u.id):
        client = ha.get_client()
    assert client is not ha_global_client
    assert client.cfg.url == "http://anna.local:8123"
    assert client.cfg.token == "GLOBAL-TOK"  # token fällt zurück


def test_get_client_url_strips_trailing_slash(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "url", "http://anna.local:8123/")
    with user_scope(u.id):
        client = ha.get_client()
    assert client.cfg.url == "http://anna.local:8123"


def test_get_client_returns_none_when_no_token_anywhere(reg, monkeypatch):
    from piclaw.tools import homeassistant as ha
    monkeypatch.setattr(ha, "_client", None)
    monkeypatch.setattr(ha, "_user_clients", {})
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "url", "http://x.local:8123")
    # nur url-Override, kein Token → globaler Token leer → None
    with user_scope(u.id):
        assert ha.get_client() is None


def test_get_client_cache_is_reused(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "USER-TOK")
    with user_scope(u.id):
        c1 = ha.get_client()
        c2 = ha.get_client()
    assert c1 is c2


def test_get_client_cache_invalidates_on_override_change(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "USER-TOK-1")
    with user_scope(u.id):
        c1 = ha.get_client()
        # Override ändern
        reg.set_override(u.id, "homeassistant", "token", "USER-TOK-2")
        c2 = ha.get_client()
    assert c1 is not c2
    assert c1.cfg.token == "USER-TOK-1"
    assert c2.cfg.token == "USER-TOK-2"


def test_clear_user_client_cache_all(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "USER-TOK")
    with user_scope(u.id):
        c1 = ha.get_client()
    ha.clear_user_client_cache()
    with user_scope(u.id):
        c2 = ha.get_client()
    assert c1 is not c2  # nach clear: neuer Client


def test_clear_user_client_cache_per_user(ha_global_client, reg):
    from piclaw.tools import homeassistant as ha
    u1 = reg.register_pending("Patrick", "111")
    u2 = reg.register_pending("Anna", "222")
    reg.approve(u2.id)
    reg.set_override(u1.id, "homeassistant", "token", "P-TOK")
    reg.set_override(u2.id, "homeassistant", "token", "A-TOK")
    with user_scope(u1.id):
        p1 = ha.get_client()
    with user_scope(u2.id):
        a1 = ha.get_client()
    ha.clear_user_client_cache(u1.id)
    with user_scope(u1.id):
        p2 = ha.get_client()
    with user_scope(u2.id):
        a2 = ha.get_client()
    assert p1 is not p2          # Patrick wurde invalidiert
    assert a1 is a2              # Anna bleibt gecached


def test_get_client_global_remains_unchanged_for_other_users(ha_global_client, reg):
    """Wenn Patrick einen Override hat, sieht ein anderer User ohne Override
    weiterhin den globalen Client."""
    from piclaw.tools import homeassistant as ha
    p = reg.register_pending("Patrick", "111")
    a = reg.register_pending("Anna", "222")
    reg.approve(a.id)
    reg.set_override(p.id, "homeassistant", "token", "P-ONLY")
    with user_scope(a.id):
        assert ha.get_client() is ha_global_client

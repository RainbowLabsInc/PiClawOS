"""
Tests fuer piclaw.auth — Pro-User-Token + Legacy-Fallback + Admin-Gate.

Wir bauen eine winzige FastAPI-App mit den drei Dependencies und nutzen
TestClient (httpx). Der UserRegistry-Singleton wird pro Test ueber tmp_path
isoliert, der Legacy-Token wird vor jedem Test geleert.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from piclaw import auth as auth_mod
from piclaw import users as users_mod
from piclaw.users import UserRegistry, User


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()

    @app.get("/auth")
    async def needs_auth(user: User = Depends(auth_mod.require_auth)):
        return {"id": user.id, "role": user.role, "name": user.name}

    @app.get("/admin")
    async def needs_admin(user: User = Depends(auth_mod.require_admin)):
        return {"id": user.id, "role": user.role}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Frischer UserRegistry pro Test, Singleton-Reset, leerer Legacy-Token."""
    reg = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", reg)
    # Rate-Limit-State zwischen Tests zuruecksetzen
    auth_mod._fail_counts.clear()
    auth_mod._lockout_until.clear()
    auth_mod._legacy_token = ""
    yield reg
    auth_mod._legacy_token = ""


# ── Pro-User-Token akzeptiert ────────────────────────────────────


def test_admin_token_works(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")  # admin (first user)
    r = client.get("/auth", headers={"Authorization": f"Bearer {admin.web_token}"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert r.json()["name"] == "Patrick"


def test_user_token_works_after_approval(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")  # pending
    isolated_registry.approve(anna.id)
    r = client.get("/auth", headers={"Authorization": f"Bearer {anna.web_token}"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"


def test_pending_token_rejected(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")  # still pending
    r = client.get("/auth", headers={"Authorization": f"Bearer {anna.web_token}"})
    assert r.status_code == 401


# ── Token im Query-Param (WebSocket-Pfad) ────────────────────────


def test_query_param_token_works(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.get(f"/auth?token={admin.web_token}")
    assert r.status_code == 200


# ── Legacy-Token-Fallback ────────────────────────────────────────


def test_legacy_token_works_when_no_users(client):
    """Vor der Migration: kein Admin im Registry, Legacy-Token gilt."""
    auth_mod.set_token("legacy-secret-12345")
    r = client.get("/auth", headers={"Authorization": "Bearer legacy-secret-12345"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "legacy-admin"
    assert body["role"] == "admin"


def test_legacy_token_rejected_once_admin_exists(client, isolated_registry):
    """Sobald ein echter Admin existiert, ist Legacy tot."""
    auth_mod.set_token("legacy-secret-12345")
    isolated_registry.register_pending("Patrick", "111")  # echter Admin entsteht
    r = client.get("/auth", headers={"Authorization": "Bearer legacy-secret-12345"})
    assert r.status_code == 401


def test_legacy_token_rejected_if_not_set(client):
    r = client.get("/auth", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 401


# ── Bootstrap-Admin behält Legacy-Token als web_token ─────────────


def test_bootstrap_admin_keeps_legacy_token(client, isolated_registry):
    """Migration: bootstrap_admin uebernimmt den Legacy-Token als web_token.
    Alte Clients koennen mit demselben Token weiterarbeiten."""
    legacy = "legacy-secret-12345"
    auth_mod.set_token(legacy)
    isolated_registry.bootstrap_admin(
        name="Patrick",
        telegram_chat_id="111",
        web_token=legacy,
    )
    r = client.get("/auth", headers={"Authorization": f"Bearer {legacy}"})
    assert r.status_code == 200
    # Nun aber als ECHTER User, nicht als legacy-admin
    assert r.json()["id"] != "legacy-admin"
    assert r.json()["name"] == "Patrick"


# ── Fehlende oder ungültige Tokens ───────────────────────────────


def test_missing_token_401(client):
    assert client.get("/auth").status_code == 401


def test_wrong_token_401(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")
    r = client.get("/auth", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_wrong_scheme_401(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    # "Basic" statt "Bearer"
    r = client.get("/auth", headers={"Authorization": f"Basic {admin.web_token}"})
    assert r.status_code == 401


# ── Admin-Gate ───────────────────────────────────────────────────


def test_admin_endpoint_accepts_admin(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.get("/admin", headers={"Authorization": f"Bearer {admin.web_token}"})
    assert r.status_code == 200


def test_admin_endpoint_rejects_user(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    r = client.get("/admin", headers={"Authorization": f"Bearer {anna.web_token}"})
    assert r.status_code == 403


def test_admin_endpoint_rejects_unauthenticated(client):
    assert client.get("/admin").status_code == 401


def test_admin_endpoint_accepts_legacy_admin(client):
    """Legacy-Token gilt als Admin-aequivalent (Single-User-Mode)."""
    auth_mod.set_token("legacy-secret")
    r = client.get("/admin", headers={"Authorization": "Bearer legacy-secret"})
    assert r.status_code == 200


# ── Rate-Limiting (Schutz bleibt erhalten) ────────────────────────


def test_rate_limit_locks_after_10_fails(client, isolated_registry):
    # 10 fehlerhafte Tries → 11. ist 429
    for _ in range(10):
        client.get("/auth", headers={"Authorization": "Bearer wrong"})
    r = client.get("/auth", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 429
    assert "Try again" in r.json().get("detail", "")


def test_rate_limit_resets_on_success(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    # 5 Fails
    for _ in range(5):
        client.get("/auth", headers={"Authorization": "Bearer wrong"})
    # Erfolgreicher Login resettet
    r = client.get("/auth", headers={"Authorization": f"Bearer {admin.web_token}"})
    assert r.status_code == 200
    # Danach wieder volle 10 Fails moeglich – wir prüfen nur dass es nicht lockt
    r2 = client.get("/auth", headers={"Authorization": "Bearer wrong"})
    assert r2.status_code == 401  # nicht 429


# ── mark_seen-Bookkeeping (nicht-blockierend) ────────────────────


def test_successful_auth_updates_last_seen(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    assert admin.last_seen == ""
    client.get("/auth", headers={"Authorization": f"Bearer {admin.web_token}"})
    assert admin.last_seen != ""

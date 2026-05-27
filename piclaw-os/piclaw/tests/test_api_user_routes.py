"""
Phase 5 — API-Endpoints für User-Management & Admin-Gates.

Wir testen die /api/whoami, /api/users*-Endpoints isoliert über eine
Mini-FastAPI-App, die nur die User-Management-Routen registriert (keine
Agent/Hub-Abhängigkeiten).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient

from piclaw import auth as auth_mod
from piclaw import users as users_mod
from piclaw.users import UserRegistry, User
from piclaw.auth import require_auth, require_admin


@pytest.fixture
def app() -> FastAPI:
    """Mini-App, mirror der relevanten api.py-Routen."""
    app = FastAPI()

    def _user_to_dict(u: User) -> dict:
        return {
            "id": u.id, "name": u.name, "role": u.role,
            "telegram_chat_id": u.telegram_chat_id,
            "created_at": u.created_at, "last_seen": u.last_seen,
        }

    @app.get("/api/whoami")
    async def whoami(user: User = Depends(require_auth)):
        return {
            "id": user.id, "name": user.name, "role": user.role,
            "is_admin": user.is_admin,
        }

    @app.get("/api/users")
    async def list_users(_: User = Depends(require_admin)):
        return {"users": [_user_to_dict(u) for u in users_mod.registry().active()]}

    @app.get("/api/users/pending")
    async def list_pending(_: User = Depends(require_admin)):
        return {"pending": [_user_to_dict(u) for u in users_mod.registry().pending()]}

    @app.post("/api/users/{id_or_name}/approve")
    async def approve(id_or_name: str, _: User = Depends(require_admin)):
        u = users_mod.registry().approve(id_or_name)
        if u is None:
            raise HTTPException(404, f"User '{id_or_name}' not found")
        return {"approved": True, "user": _user_to_dict(u)}

    @app.post("/api/users/{id_or_name}/revoke")
    async def revoke(id_or_name: str, _: User = Depends(require_admin)):
        reg = users_mod.registry()
        target = reg.find_by_id(id_or_name) or reg.find_by_name(id_or_name)
        if target is None:
            raise HTTPException(404, f"User '{id_or_name}' not found")
        if not reg.revoke(target.id):
            raise HTTPException(409, "Cannot revoke last admin")
        return {"revoked": True, "name": target.name}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    reg = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", reg)
    auth_mod._fail_counts.clear()
    auth_mod._lockout_until.clear()
    auth_mod._legacy_token = ""
    yield reg


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ── /api/whoami ──────────────────────────────────────────────────


def test_whoami_unauth(client):
    assert client.get("/api/whoami").status_code == 401


def test_whoami_admin(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.get("/api/whoami", headers=_hdr(admin.web_token))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Patrick"
    assert body["is_admin"] is True


def test_whoami_user(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    r = client.get("/api/whoami", headers=_hdr(anna.web_token))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Anna"
    assert body["is_admin"] is False


# ── /api/users ───────────────────────────────────────────────────


def test_list_users_requires_admin(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    # Anna ist nur user, kein admin
    assert client.get("/api/users", headers=_hdr(anna.web_token)).status_code == 403


def test_list_users_as_admin(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    r = client.get("/api/users", headers=_hdr(admin.web_token))
    assert r.status_code == 200
    names = {u["name"] for u in r.json()["users"]}
    assert names == {"Patrick", "Anna"}


def test_list_users_omits_tokens(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.get("/api/users", headers=_hdr(admin.web_token))
    body = r.json()
    assert "web_token" not in body["users"][0]


def test_list_pending(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")  # admin
    isolated_registry.register_pending("Anna", "222")  # pending
    r = client.get("/api/users/pending", headers=_hdr(admin.web_token))
    assert r.status_code == 200
    names = {u["name"] for u in r.json()["pending"]}
    assert names == {"Anna"}


# ── /api/users/{id}/approve ──────────────────────────────────────


def test_approve_as_admin(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    anna = isolated_registry.register_pending("Anna", "222")
    r = client.post(f"/api/users/{anna.id}/approve", headers=_hdr(admin.web_token))
    assert r.status_code == 200
    assert r.json()["approved"] is True
    assert isolated_registry.find_by_id(anna.id).role == "user"


def test_approve_by_name(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    isolated_registry.register_pending("Anna", "222")
    r = client.post("/api/users/Anna/approve", headers=_hdr(admin.web_token))
    assert r.status_code == 200


def test_approve_unknown(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.post("/api/users/ghost/approve", headers=_hdr(admin.web_token))
    assert r.status_code == 404


def test_approve_requires_admin(client, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    eve = isolated_registry.register_pending("Eve", "333")
    r = client.post(f"/api/users/{eve.id}/approve", headers=_hdr(anna.web_token))
    assert r.status_code == 403


# ── /api/users/{id}/revoke ───────────────────────────────────────


def test_revoke_user(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    r = client.post(f"/api/users/{anna.id}/revoke", headers=_hdr(admin.web_token))
    assert r.status_code == 200
    assert isolated_registry.find_by_id(anna.id) is None


def test_revoke_last_admin_returns_409(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.post(f"/api/users/{admin.id}/revoke", headers=_hdr(admin.web_token))
    assert r.status_code == 409


def test_revoke_unknown_returns_404(client, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    r = client.post("/api/users/ghost/revoke", headers=_hdr(admin.web_token))
    assert r.status_code == 404

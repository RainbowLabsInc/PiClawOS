"""
Tests for piclaw.auth – token generation, verification, FastAPI dependencies.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends
from piclaw import auth


@pytest.fixture(autouse=True)
def reset_token():
    """Reset module-level token before every test."""
    original = auth._token
    yield
    auth._token = original


class TestTokenGeneration:
    def test_generate_token_length(self):
        token = auth.generate_token()
        # token_urlsafe(32) produces 43-char base64url string
        assert len(token) >= 40

    def test_generate_token_unique(self):
        tokens = {auth.generate_token() for _ in range(100)}
        assert len(tokens) == 100  # all unique

    def test_generate_token_urlsafe(self):
        token = auth.generate_token()
        # Should only contain URL-safe chars
        import re

        assert re.match(r"^[A-Za-z0-9\-_]+$", token)


class TestVerification:
    def test_verify_correct_token(self):
        auth.set_token("my-secret-token")
        assert auth.verify("my-secret-token") is True

    def test_verify_wrong_token(self):
        auth.set_token("correct-token")
        assert auth.verify("wrong-token") is False

    def test_verify_empty_candidate(self):
        auth.set_token("some-token")
        assert auth.verify("") is False

    def test_verify_empty_stored(self):
        auth.set_token("")
        assert auth.verify("any-token") is False

    def test_verify_both_empty(self):
        auth.set_token("")
        assert auth.verify("") is False

    def test_set_and_get(self):
        auth.set_token("test-abc-123")
        assert auth.get_token() == "test-abc-123"

    def test_timing_safe(self):
        """verify() uses secrets.compare_digest – ensure it's called (not ==)."""
        import secrets

        auth.set_token("token")
        with patch("secrets.compare_digest", return_value=True) as mock:
            auth.verify("token")
            mock.assert_called_once()


class TestRequireAuthDependency:
    """Integration tests using FastAPI TestClient."""

    @pytest.fixture
    def app(self):
        _app = FastAPI()

        @_app.get("/protected")
        async def protected(token: str = Depends(auth.require_auth)):
            return {"ok": True}

        @_app.get("/health")
        async def health():
            return {"status": "ok"}

        return _app

    @pytest.fixture
    def client(self, app):
        return TestClient(app, raise_server_exceptions=True)

    def test_no_token_returns_401(self, client):
        auth.set_token("secret")
        r = client.get("/protected")
        assert r.status_code == 401

    def test_wrong_token_returns_401(self, client):
        auth.set_token("secret")
        r = client.get("/protected", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_correct_bearer_token(self, client):
        auth.set_token("secret")
        r = client.get("/protected", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_correct_query_param_token(self, client):
        auth.set_token("secret")
        r = client.get("/protected?token=secret")
        assert r.status_code == 200

    def test_unprotected_route_no_auth(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_malformed_bearer_scheme(self, client):
        """'Basic token' is not Bearer – should 401."""
        auth.set_token("secret")
        r = client.get("/protected", headers={"Authorization": "Basic secret"})
        assert r.status_code == 401

    def test_empty_token_module_level(self, client):
        """If no token configured at all, should 401."""
        auth.set_token("")
        r = client.get("/protected", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

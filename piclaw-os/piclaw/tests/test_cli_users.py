"""
Tests fuer piclaw.cli_users — Subcommands der `piclaw user`-CLI.
"""

from __future__ import annotations

import pytest

from piclaw import users as users_mod
from piclaw.users import UserRegistry
from piclaw.cli_users import cmd_user


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    reg = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", reg)
    return reg


def run(args: list[str], capsys) -> tuple[int, str]:
    """Helper: Subcommand ausführen und (rc, captured_stdout) zurückgeben."""
    rc = cmd_user(args)
    out = capsys.readouterr().out
    return rc, out


# ── help / unbekannt ─────────────────────────────────────────────


def test_no_args_prints_help(capsys):
    rc, out = run([], capsys)
    assert rc == 0
    assert "Subcommands" in out


def test_help_flag(capsys):
    rc, out = run(["help"], capsys)
    assert rc == 0
    assert "Subcommands" in out


def test_unknown_subcommand(capsys):
    rc, out = run(["xyz"], capsys)
    assert rc == 1
    assert "Unbekanntes" in out


# ── list / pending ───────────────────────────────────────────────


def test_list_empty(capsys, isolated_registry):
    rc, out = run(["list"], capsys)
    assert rc == 0
    assert "Keine" in out


def test_list_shows_admin_and_user(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    rc, out = run(["list"], capsys)
    assert rc == 0
    assert "Patrick" in out and "admin" in out
    assert "Anna" in out
    assert "★" in out  # Admin-Marker


def test_pending_lists_waiting(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    isolated_registry.register_pending("Anna", "222")  # pending
    rc, out = run(["pending"], capsys)
    assert rc == 0
    assert "Anna" in out
    assert "Patrick" not in out  # admin ist nicht pending


def test_pending_empty(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")
    rc, out = run(["pending"], capsys)
    assert rc == 0
    assert "keine" in out.lower()


# ── show ─────────────────────────────────────────────────────────


def test_show_existing_user(capsys, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    rc, out = run(["show", "Patrick"], capsys)
    assert rc == 0
    assert "Patrick" in out
    assert admin.id in out
    assert "admin" in out
    assert "111" in out


def test_show_by_id(capsys, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    rc, out = run(["show", admin.id], capsys)
    assert rc == 0
    assert "Patrick" in out


def test_show_missing_arg(capsys):
    rc, out = run(["show"], capsys)
    assert rc == 1
    assert "Usage" in out


def test_show_unknown_user(capsys):
    rc, out = run(["show", "ghost"], capsys)
    assert rc == 1


# ── approve / revoke ─────────────────────────────────────────────


def test_approve_pending(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    isolated_registry.register_pending("Anna", "222")  # pending
    rc, out = run(["approve", "Anna"], capsys)
    assert rc == 0
    assert "aktiviert" in out.lower()
    assert isolated_registry.find_by_name("Anna").role == "user"


def test_approve_unknown(capsys, isolated_registry):
    rc, out = run(["approve", "ghost"], capsys)
    assert rc == 1


def test_revoke_user(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    rc, out = run(["revoke", "Anna"], capsys)
    assert rc == 0
    assert "entfernt" in out.lower()
    assert isolated_registry.find_by_name("Anna") is None


def test_revoke_last_admin_blocked(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")
    rc, out = run(["revoke", "Patrick"], capsys)
    assert rc == 1
    assert isolated_registry.find_by_name("Patrick") is not None


# ── promote / demote ─────────────────────────────────────────────


def test_promote_user_to_admin(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)
    rc, out = run(["promote", "Anna"], capsys)
    assert rc == 0
    assert "admin" in out.lower()
    assert isolated_registry.find_by_name("Anna").role == "admin"


def test_demote_last_admin_blocked(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    rc, out = run(["demote", "Patrick"], capsys)
    assert rc == 1
    assert isolated_registry.find_by_name("Patrick").role == "admin"


def test_demote_admin_when_another_exists(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.set_role(anna.id, "admin")
    rc, out = run(["demote", "Anna"], capsys)
    assert rc == 0
    assert isolated_registry.find_by_name("Anna").role == "user"


# ── add ──────────────────────────────────────────────────────────


def test_add_user_minimal(capsys, isolated_registry):
    rc, out = run(["add", "Bob", "--telegram", "555"], capsys)
    assert rc == 0
    u = isolated_registry.find_by_name("Bob")
    assert u is not None
    assert u.role == "user"
    assert u.telegram_chat_id == "555"
    # web_token wird im Output gezeigt
    assert u.web_token in out


def test_add_admin_role(capsys, isolated_registry):
    rc, out = run(["add", "Boss", "--telegram", "777", "--role", "admin"], capsys)
    assert rc == 0
    assert isolated_registry.find_by_name("Boss").role == "admin"


def test_add_without_telegram_fails(capsys, isolated_registry):
    rc, out = run(["add", "Bob"], capsys)
    assert rc == 1
    assert "--telegram" in out


def test_add_duplicate_chat_id(capsys, isolated_registry):
    isolated_registry.register_pending("Patrick", "111")
    rc, out = run(["add", "Anna", "--telegram", "111"], capsys)
    assert rc == 1
    assert "bereits" in out.lower()


def test_add_with_equals_syntax(capsys, isolated_registry):
    rc, out = run(["add", "Bob", "--telegram=555", "--role=admin"], capsys)
    assert rc == 0
    u = isolated_registry.find_by_name("Bob")
    assert u.role == "admin" and u.telegram_chat_id == "555"


# ── token ────────────────────────────────────────────────────────


def test_token_shows(capsys, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    rc, out = run(["token", "Patrick"], capsys)
    assert rc == 0
    assert admin.web_token in out


def test_token_regenerate(capsys, isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    old = admin.web_token
    rc, out = run(["token", "Patrick", "--regenerate"], capsys)
    assert rc == 0
    new_token = isolated_registry.find_by_name("Patrick").web_token
    assert new_token != old
    assert new_token in out
    assert "regeneriert" in out.lower()


def test_token_unknown_user(capsys):
    rc, out = run(["token", "ghost"], capsys)
    assert rc == 1

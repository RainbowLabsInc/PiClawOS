"""
Phase 5.5 — Tests für wizard_users (interaktiver Setup-Flow).

Wir patchen `input()` mit einer Sequenz und prüfen, dass die UserRegistry
nach Abschluss den erwarteten Zustand hat.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from piclaw import users as users_mod
from piclaw.users import UserRegistry, User


@pytest.fixture
def reg(tmp_path, monkeypatch):
    r = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", r)
    return r


def _patch_input(monkeypatch, sequence: list[str]):
    """Ersetzt builtins.input mit einer FIFO-Liste."""
    seq = iter(sequence)

    def fake_input(prompt=""):
        try:
            return next(seq)
        except StopIteration:
            raise EOFError("no more inputs in test sequence")

    monkeypatch.setattr(builtins, "input", fake_input)


def _state(cfg=None) -> SimpleNamespace:
    """Mini-Wizard-State."""
    s = SimpleNamespace()
    s.cfg = cfg or SimpleNamespace(api=SimpleNamespace(secret_key="legacy123"))
    s.mark = lambda *a, **k: None
    return s


# ── Hauptmenü: Exit-Pfad ──────────────────────────────────────────


def test_main_menu_exits_with_zero(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    _patch_input(monkeypatch, ["0"])
    step_user_management(_state(), 1, 1)
    out = capsys.readouterr().out
    assert "Fertig" in out


def test_main_menu_invalid_then_exit(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    _patch_input(monkeypatch, ["9", "0"])
    step_user_management(_state(), 1, 1)
    out = capsys.readouterr().out
    assert "Unbekannte Auswahl" in out
    assert "Fertig" in out


# ── Approve-Flow ─────────────────────────────────────────────────


def test_approve_pending_user_via_menu(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")  # admin
    reg.register_pending("Anna", "222")  # pending
    _patch_input(monkeypatch, ["1", "1", "0"])
    step_user_management(_state(), 1, 1)
    assert reg.find_by_name("Anna").role == "user"
    out = capsys.readouterr().out
    assert "Anna" in out and "user" in out


def test_approve_menu_no_pending(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["1", "0"])
    step_user_management(_state(), 1, 1)
    out = capsys.readouterr().out
    assert "Keine wartenden" in out


def test_approve_menu_back(reg, monkeypatch):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    reg.register_pending("Anna", "222")
    _patch_input(monkeypatch, ["1", "0", "0"])  # menu→approve→back→exit
    step_user_management(_state(), 1, 1)
    assert reg.find_by_name("Anna").role == "pending"


# ── Add-Flow ─────────────────────────────────────────────────────


def test_add_user_via_menu(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")  # admin
    _patch_input(monkeypatch, ["2", "Bob", "9999", "user", "0"])
    step_user_management(_state(), 1, 1)
    bob = reg.find_by_name("Bob")
    assert bob is not None and bob.role == "user" and bob.telegram_chat_id == "9999"


def test_add_admin_via_menu(reg, monkeypatch):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["2", "Boss", "7777", "admin", "0"])
    step_user_management(_state(), 1, 1)
    assert reg.find_by_name("Boss").role == "admin"


def test_add_aborts_on_empty_name(reg, monkeypatch):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["2", "", "0"])
    step_user_management(_state(), 1, 1)
    assert len(reg.all()) == 1


def test_add_aborts_on_empty_chat_id(reg, monkeypatch):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["2", "Bob", "", "0"])
    step_user_management(_state(), 1, 1)
    assert len(reg.all()) == 1


def test_add_duplicate_chat_id_shows_error(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["2", "Anna", "111", "user", "0"])
    step_user_management(_state(), 1, 1)
    out = capsys.readouterr().out
    assert "bereits" in out


# ── Token-Flow ───────────────────────────────────────────────────


def test_token_shows_and_keeps(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    admin = reg.register_pending("Patrick", "111")
    old_token = admin.web_token
    _patch_input(monkeypatch, ["3", "1", "n", "0"])  # menu→token→user1→nicht regen→exit
    step_user_management(_state(), 1, 1)
    out = capsys.readouterr().out
    assert old_token in out
    assert reg.find_by_name("Patrick").web_token == old_token  # unverändert


def test_token_regenerate(reg, monkeypatch):
    from piclaw.wizard_users import step_user_management
    admin = reg.register_pending("Patrick", "111")
    old_token = admin.web_token
    _patch_input(monkeypatch, ["3", "1", "j", "0"])
    step_user_management(_state(), 1, 1)
    new_token = reg.find_by_name("Patrick").web_token
    assert new_token != old_token


# ── Revoke-Flow ──────────────────────────────────────────────────


def test_revoke_user_via_menu(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")  # admin
    anna = reg.register_pending("Anna", "222")
    reg.approve(anna.id)
    # menu→revoke→user2 (Anna)→confirm→exit
    _patch_input(monkeypatch, ["4", "2", "j", "0"])
    step_user_management(_state(), 1, 1)
    assert reg.find_by_name("Anna") is None
    out = capsys.readouterr().out
    assert "entfernt" in out.lower()


def test_revoke_last_admin_blocked(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["4", "1", "j", "0"])
    step_user_management(_state(), 1, 1)
    out = capsys.readouterr().out
    assert "❌" in out or "letzter" in out.lower()
    assert reg.find_by_name("Patrick") is not None


def test_revoke_cancels_on_no(reg, monkeypatch):
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    anna = reg.register_pending("Anna", "222")
    reg.approve(anna.id)
    _patch_input(monkeypatch, ["4", "2", "n", "0"])
    step_user_management(_state(), 1, 1)
    assert reg.find_by_name("Anna") is not None  # nicht entfernt


# ── offer_bootstrap_admin ────────────────────────────────────────


def test_bootstrap_admin_creates_admin(reg, monkeypatch, capsys):
    from piclaw.wizard_users import offer_bootstrap_admin
    cfg = SimpleNamespace(api=SimpleNamespace(secret_key="legacy123"))
    _patch_input(monkeypatch, ["j", "Patrick"])
    assert offer_bootstrap_admin(cfg, "8888") is True
    u = reg.find_by_chat_id("8888")
    assert u is not None and u.is_admin
    assert u.web_token == "legacy123"  # alter Token weiterverwendet


def test_bootstrap_admin_idempotent(reg, monkeypatch):
    from piclaw.wizard_users import offer_bootstrap_admin
    reg.register_pending("Patrick", "111")  # admin existiert bereits
    cfg = SimpleNamespace(api=SimpleNamespace(secret_key="legacy123"))
    # Sollte direkt False zurückgeben, ohne Input zu konsumieren
    _patch_input(monkeypatch, [])
    assert offer_bootstrap_admin(cfg, "8888") is False


def test_bootstrap_admin_user_says_no(reg, monkeypatch):
    from piclaw.wizard_users import offer_bootstrap_admin
    cfg = SimpleNamespace(api=SimpleNamespace(secret_key="legacy123"))
    _patch_input(monkeypatch, ["n"])
    assert offer_bootstrap_admin(cfg, "8888") is False
    assert reg.find_by_chat_id("8888") is None


def test_bootstrap_admin_generates_token_if_missing(reg, monkeypatch):
    from piclaw.wizard_users import offer_bootstrap_admin
    cfg = SimpleNamespace(api=SimpleNamespace(secret_key=""))
    # Mock save_cfg um Dateisystem nicht anzufassen
    monkeypatch.setattr("piclaw.config.save", lambda c: None)
    _patch_input(monkeypatch, ["j", "Patrick"])
    assert offer_bootstrap_admin(cfg, "8888") is True
    # secret_key wurde gesetzt
    assert cfg.api.secret_key != ""
    # User hat den gleichen Token
    assert reg.find_by_chat_id("8888").web_token == cfg.api.secret_key

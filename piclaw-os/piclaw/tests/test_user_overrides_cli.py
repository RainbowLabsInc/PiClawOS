"""
Phase 5.7 — Tests für CLI- und Wizard-Pfade rund um Per-User-Overrides.
"""

from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from piclaw import users as users_mod
from piclaw.users import UserRegistry
from piclaw.cli_users import cmd_user


@pytest.fixture(autouse=True)
def reg(tmp_path, monkeypatch):
    r = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", r)
    return r


def run(args, capsys) -> tuple[int, str]:
    rc = cmd_user(args)
    return rc, capsys.readouterr().out


# ── piclaw user set ──────────────────────────────────────────────


def test_set_creates_override(reg, capsys):
    u = reg.register_pending("Patrick", "111")
    rc, out = run(["set", "Patrick", "homeassistant.token", "HA-secret"], capsys)
    assert rc == 0
    assert reg.get_override(u.id, "homeassistant", "token") == "HA-secret"
    assert "Patrick" in out and "homeassistant.token" in out


def test_set_parses_int(reg, capsys):
    u = reg.register_pending("Patrick", "111")
    rc, _ = run(["set", "Patrick", "discord.user_id", "123456789"], capsys)
    assert rc == 0
    assert reg.get_override(u.id, "discord", "user_id") == 123456789


def test_set_parses_bool(reg, capsys):
    u = reg.register_pending("Patrick", "111")
    rc, _ = run(["set", "Patrick", "homeassistant.verify_ssl", "true"], capsys)
    assert rc == 0
    assert reg.get_override(u.id, "homeassistant", "verify_ssl") is True


def test_set_requires_dot_in_path(reg, capsys):
    reg.register_pending("Patrick", "111")
    rc, out = run(["set", "Patrick", "homeassistant", "HA-secret"], capsys)
    assert rc == 1
    assert "section>.<key>" in out


def test_set_unknown_user(reg, capsys):
    rc, _ = run(["set", "ghost", "homeassistant.token", "x"], capsys)
    assert rc == 1


def test_set_multi_word_value(reg, capsys):
    """Werte mit Leerzeichen werden zusammengefügt (z.B. URLs/Emails)."""
    u = reg.register_pending("Patrick", "111")
    rc, _ = run(["set", "Patrick", "agentmail.email_address", "anna foo bar"], capsys)
    assert rc == 0
    assert reg.get_override(u.id, "agentmail", "email_address") == "anna foo bar"


# ── piclaw user clear ────────────────────────────────────────────


def test_clear_single_key(reg, capsys):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "x")
    reg.set_override(u.id, "homeassistant", "url", "http://...")
    rc, out = run(["clear", "Patrick", "homeassistant.token"], capsys)
    assert rc == 0
    assert reg.get_override(u.id, "homeassistant", "token") is None
    assert reg.get_override(u.id, "homeassistant", "url") == "http://..."


def test_clear_entire_section(reg, capsys):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "x")
    reg.set_override(u.id, "homeassistant", "url", "http://...")
    rc, _ = run(["clear", "Patrick", "homeassistant"], capsys)
    assert rc == 0
    assert "homeassistant" not in u.overrides


def test_clear_unknown(reg, capsys):
    reg.register_pending("Patrick", "111")
    rc, out = run(["clear", "Patrick", "homeassistant"], capsys)
    assert rc == 1
    assert "Kein Override" in out


# ── piclaw user settings ─────────────────────────────────────────


def test_settings_empty(reg, capsys):
    reg.register_pending("Patrick", "111")
    rc, out = run(["settings", "Patrick"], capsys)
    assert rc == 0
    assert "Keine Overrides" in out


def test_settings_lists_all(reg, capsys):
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "HA-secret-12345")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    rc, out = run(["settings", "Patrick"], capsys)
    assert rc == 0
    assert "[homeassistant]" in out
    assert "[agentmail]" in out
    assert "p@a.to" in out
    # Token wird maskiert
    assert "HA-secret-12345" not in out


def test_settings_unknown_user(reg, capsys):
    rc, _ = run(["settings", "ghost"], capsys)
    assert rc == 1


# ── Wizard Menüpunkt [5] ─────────────────────────────────────────


def _patch_input(monkeypatch, sequence: list[str]):
    seq = iter(sequence)

    def fake_input(prompt=""):
        try:
            return next(seq)
        except StopIteration:
            raise EOFError("no more inputs")

    monkeypatch.setattr(builtins, "input", fake_input)


def _state():
    return SimpleNamespace(cfg=SimpleNamespace(api=SimpleNamespace(secret_key="x")),
                           mark=lambda *a, **k: None)


def test_wizard_overrides_set_via_menu(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    u = reg.register_pending("Patrick", "111")
    # [5] → user 1 → [1] Wert setzen → section 1 (homeassistant) → key 1 (token)
    #   → Wert "HA-token-123" → [0] zurück (Untermenü) → [0] zurück (Haupt)
    _patch_input(monkeypatch, ["5", "1", "1", "1", "1", "HA-token-123", "0", "0"])
    step_user_management(_state(), 1, 1)
    assert reg.get_override(u.id, "homeassistant", "token") == "HA-token-123"


def test_wizard_overrides_clear_key_via_menu(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "agentmail", "email_address", "p@a.to")
    # [5] → user 1 → [2] Einzelnen Wert entfernen → 1 (agentmail.email_address)
    #   → [0] zurück (Untermenü) → [0]
    _patch_input(monkeypatch, ["5", "1", "2", "1", "0", "0"])
    step_user_management(_state(), 1, 1)
    assert reg.get_override(u.id, "agentmail", "email_address") is None


def test_wizard_overrides_clear_section_via_menu(reg, monkeypatch, capsys):
    from piclaw.wizard_users import step_user_management
    u = reg.register_pending("Patrick", "111")
    reg.set_override(u.id, "homeassistant", "token", "x")
    reg.set_override(u.id, "homeassistant", "url", "http://x")
    # [5] → user 1 → [3] komplette Sektion → 1 (homeassistant) → [0] → [0]
    _patch_input(monkeypatch, ["5", "1", "3", "1", "0", "0"])
    step_user_management(_state(), 1, 1)
    assert "homeassistant" not in u.overrides


def test_wizard_overrides_user_back(reg, monkeypatch):
    """[5] → [0] (User-Auswahl abbrechen) → [0]"""
    from piclaw.wizard_users import step_user_management
    reg.register_pending("Patrick", "111")
    _patch_input(monkeypatch, ["5", "0", "0"])
    step_user_management(_state(), 1, 1)

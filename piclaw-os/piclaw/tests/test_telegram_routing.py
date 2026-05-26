"""
Tests fuer piclaw.messaging.bot_commands + Telegram-Routing-Logik.

Schwerpunkt: Slash-Commands & User-Resolution. Wir testen bot_commands.handle()
direkt mit einer frischen UserRegistry — kein echter Telegram-Mock noetig.
Zusaetzlich: TelegramAdapter._handle_message ohne HTTP, mit gemockter send().
"""

from __future__ import annotations

import asyncio
import json
import pytest

from piclaw.messaging import bot_commands
from piclaw.messaging.hub import IncomingMessage
from piclaw.messaging.telegram import TelegramAdapter
from piclaw import users as users_mod
from piclaw.users import UserRegistry


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    reg = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", reg)
    return reg


# ── bot_commands.handle: /start ──────────────────────────────────


def test_start_first_user_becomes_admin(isolated_registry):
    reply = bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    assert reply is not None
    assert "Admin" in reply
    u = isolated_registry.find_by_chat_id("111")
    assert u is not None and u.is_admin


def test_start_second_user_is_pending(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    assert reply is not None
    assert "registriert" in reply.lower()
    u = isolated_registry.find_by_chat_id("222")
    assert u is not None and u.role == "pending"


def test_start_uses_telegram_first_name_if_no_arg(isolated_registry):
    reply = bot_commands.handle("/start", "111", "PatrickFromTelegram", isolated_registry)
    u = isolated_registry.find_by_chat_id("111")
    assert u is not None
    assert u.name == "PatrickFromTelegram"


def test_start_idempotent_for_known_user(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    assert "Admin" in reply
    assert len(isolated_registry.all()) == 1  # nicht dupliziert


def test_start_with_bot_suffix(isolated_registry):
    """Telegram laesst /command@bot_name zu – wir muessen den Suffix abschneiden."""
    reply = bot_commands.handle("/start@piclawdev_bot Patrick", "111", "Patrick", isolated_registry)
    assert reply is not None
    assert isolated_registry.find_by_chat_id("111") is not None


# ── bot_commands.handle: /whoami, /web_token, /help ──────────────


def test_whoami_unknown(isolated_registry):
    reply = bot_commands.handle("/whoami", "999", "x", isolated_registry)
    assert "nicht registriert" in reply.lower()


def test_whoami_admin(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/whoami", "111", "Patrick", isolated_registry)
    assert "Patrick" in reply and "Admin" in reply


def test_web_token_returns_token_for_active(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    admin = isolated_registry.find_by_chat_id("111")
    reply = bot_commands.handle("/web_token", "111", "Patrick", isolated_registry)
    assert admin.web_token in reply


def test_web_token_refused_for_pending(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)  # admin
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    reply = bot_commands.handle("/web_token", "222", "Anna", isolated_registry)
    assert "freigabe" in reply.lower() or "approval" in reply.lower()


def test_web_token_for_unknown(isolated_registry):
    reply = bot_commands.handle("/web_token", "999", "x", isolated_registry)
    assert "nicht registriert" in reply.lower()


def test_help_user_vs_admin(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)  # admin
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    isolated_registry.approve("Anna")
    h_admin = bot_commands.handle("/help", "111", "Patrick", isolated_registry)
    h_user  = bot_commands.handle("/help", "222", "Anna", isolated_registry)
    assert "Admin" in h_admin
    assert "Admin" not in h_user


# ── Admin-Commands ───────────────────────────────────────────────


def test_pending_lists_waiting_users(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    reply = bot_commands.handle("/pending", "111", "Patrick", isolated_registry)
    assert "Anna" in reply


def test_pending_says_none_when_empty(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/pending", "111", "Patrick", isolated_registry)
    assert "keine" in reply.lower()


def test_approve_by_name(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    reply = bot_commands.handle("/approve Anna", "111", "Patrick", isolated_registry)
    assert "aktiviert" in reply.lower()
    assert isolated_registry.find_by_chat_id("222").role == "user"


def test_approve_unknown_name(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/approve Mike", "111", "Patrick", isolated_registry)
    assert "nicht gefunden" in reply.lower() or "❌" in reply


def test_approve_without_arg(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/approve", "111", "Patrick", isolated_registry)
    assert "name" in reply.lower()


def test_approve_refused_for_non_admin(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    isolated_registry.approve("Anna")
    bot_commands.handle("/start Eve", "333", "Eve", isolated_registry)
    reply = bot_commands.handle("/approve Eve", "222", "Anna", isolated_registry)  # Anna is user, not admin
    assert "autorisiert" in reply.lower() or "Admin" in reply


def test_approve_refused_for_pending(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    # Anna ist pending — darf nicht approven
    reply = bot_commands.handle("/approve Anna", "222", "Anna", isolated_registry)
    assert "autorisiert" in reply.lower() or "Admin" in reply


def test_users_lists_active(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    isolated_registry.approve("Anna")
    reply = bot_commands.handle("/users", "111", "Patrick", isolated_registry)
    assert "Patrick" in reply and "Anna" in reply


def test_revoke_removes_user(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    bot_commands.handle("/start Anna", "222", "Anna", isolated_registry)
    isolated_registry.approve("Anna")
    reply = bot_commands.handle("/revoke Anna", "111", "Patrick", isolated_registry)
    assert "entfernt" in reply.lower()
    assert isolated_registry.find_by_chat_id("222") is None


def test_revoke_last_admin_blocked(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    reply = bot_commands.handle("/revoke Patrick", "111", "Patrick", isolated_registry)
    assert "❌" in reply or "nicht entfernen" in reply.lower()


# ── Nicht-Commands fallen durch ──────────────────────────────────


def test_plain_text_returns_none(isolated_registry):
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    assert bot_commands.handle("Hallo Bot", "111", "Patrick", isolated_registry) is None
    assert bot_commands.handle("", "111", "Patrick", isolated_registry) is None


def test_unknown_slash_returns_none_for_admin(isolated_registry):
    """/foo wird an den Agent durchgereicht, falls bot_commands es nicht kennt."""
    bot_commands.handle("/start Patrick", "111", "Patrick", isolated_registry)
    assert bot_commands.handle("/foo bar", "111", "Patrick", isolated_registry) is None


# ── TelegramAdapter._handle_message – Integrationstest ───────────


class _FakeAdapter(TelegramAdapter):
    """Adapter ohne HTTP – sammelt send()-Aufrufe statt sie zu senden."""

    def __init__(self):
        super().__init__(token="fake", chat_id="0")
        self.sent: list[tuple[str, str]] = []  # (chat_id, text)

    async def send(self, text: str, chat_id: str | None = None):
        self.sent.append((str(chat_id), text))


def _msg(chat_id: str, text: str, first_name: str = "") -> dict:
    return {
        "chat": {"id": int(chat_id)},
        "text": text,
        "from": {"first_name": first_name},
    }


async def _noop_handler(inc: IncomingMessage) -> str:
    return f"agent-echo:{inc.text}|user_id={inc.user_id}"


@pytest.mark.asyncio
async def test_unknown_chat_gets_start_prompt(isolated_registry):
    a = _FakeAdapter()
    await a._handle_message("ping", "999", _msg("999", "ping"), _noop_handler)
    assert len(a.sent) == 1
    chat, text = a.sent[0]
    assert chat == "999"
    assert "/start" in text


@pytest.mark.asyncio
async def test_pending_user_gets_wait_message(isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    isolated_registry.register_pending("Anna", "222")  # pending
    a = _FakeAdapter()
    await a._handle_message("hi", "222", _msg("222", "hi"), _noop_handler)
    assert len(a.sent) == 1
    assert "freigabe" in a.sent[0][1].lower()


@pytest.mark.asyncio
async def test_active_user_message_dispatched_with_user_id(isolated_registry):
    admin = isolated_registry.register_pending("Patrick", "111")
    a = _FakeAdapter()
    await a._handle_message("ping", "111", _msg("111", "ping"), _noop_handler)
    # _noop_handler liefert "agent-echo:ping|user_id=<id>" zurueck → wird gesendet
    assert any(admin.id in text for _, text in a.sent)


@pytest.mark.asyncio
async def test_start_admin_notification_for_pending(isolated_registry):
    isolated_registry.register_pending("Patrick", "111")  # admin
    a = _FakeAdapter()
    # Anna meldet sich
    await a._handle_message("/start Anna", "222", _msg("222", "/start Anna", "Anna"), _noop_handler)
    # Erwartet: 1x reply an Anna (chat 222), 1x notification an Admin (chat 111)
    by_chat = {c: t for c, t in a.sent}
    assert "222" in by_chat
    assert "111" in by_chat
    assert "Anna" in by_chat["111"]
    assert "approve" in by_chat["111"].lower()


@pytest.mark.asyncio
async def test_start_first_user_no_admin_notification(isolated_registry):
    """Wenn /start den ersten User (=Admin) erzeugt, gibt es niemanden zu benachrichtigen."""
    a = _FakeAdapter()
    await a._handle_message("/start Patrick", "111", _msg("111", "/start Patrick", "Patrick"), _noop_handler)
    # Nur reply an Patrick selbst, KEINE Admin-Notify
    assert len(a.sent) == 1
    assert a.sent[0][0] == "111"


@pytest.mark.asyncio
async def test_unknown_command_passes_through(isolated_registry):
    """/foo (unbekannt) muss an den Agent gehen, nicht abgeschnitten werden."""
    admin = isolated_registry.register_pending("Patrick", "111")
    a = _FakeAdapter()
    await a._handle_message("/foo", "111", _msg("111", "/foo"), _noop_handler)
    # Agent-Echo enthält den unbekannten Command
    assert any("agent-echo:/foo" in t for _, t in a.sent)


@pytest.mark.asyncio
async def test_approve_notifies_promoted_user(isolated_registry):
    """Nach /approve <Name> bekommt der frischgebackene User eine DM."""
    isolated_registry.register_pending("Patrick", "111")  # admin
    isolated_registry.register_pending("Anna", "222")     # pending
    a = _FakeAdapter()
    # Patrick (chat 111) schickt /approve Anna
    await a._handle_message(
        "/approve Anna", "111",
        _msg("111", "/approve Anna", "Patrick"),
        _noop_handler,
    )
    # Mindestens 2 Sends: 1 an Patrick (Bestätigung) + 1 an Anna (Promote-Notify)
    chats = [c for c, _t in a.sent]
    assert "111" in chats           # Patrick bekommt Bestätigung
    assert "222" in chats           # Anna bekommt Promote-DM
    anna_msgs = [t for c, t in a.sent if c == "222"]
    assert any("freigeschaltet" in t.lower() for t in anna_msgs)
    assert any("/web_token" in t for t in anna_msgs)


@pytest.mark.asyncio
async def test_approve_no_notify_when_target_was_not_pending(isolated_registry):
    """Approve eines Users, der bereits aktiv ist → keine Promote-DM."""
    isolated_registry.register_pending("Patrick", "111")  # admin
    anna = isolated_registry.register_pending("Anna", "222")
    isolated_registry.approve(anna.id)  # Anna ist schon user
    a = _FakeAdapter()
    await a._handle_message(
        "/approve Anna", "111",
        _msg("111", "/approve Anna", "Patrick"),
        _noop_handler,
    )
    # Anna war nicht im pre-snapshot der pending → keine Notify an chat 222
    chats = [c for c, _t in a.sent]
    assert "222" not in chats


@pytest.mark.asyncio
async def test_approve_unknown_does_not_notify(isolated_registry):
    """/approve <ghost> verändert niemanden → keine Promote-DM."""
    isolated_registry.register_pending("Patrick", "111")
    a = _FakeAdapter()
    await a._handle_message(
        "/approve ghost", "111",
        _msg("111", "/approve ghost", "Patrick"),
        _noop_handler,
    )
    # Nur 1 Send: die Fehler-Antwort an Patrick
    assert len(a.sent) == 1
    assert a.sent[0][0] == "111"

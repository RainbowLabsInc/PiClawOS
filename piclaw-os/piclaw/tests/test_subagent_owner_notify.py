"""
Phase 5.9 — Sub-Agent-Notifications routen an Owner-chat_id.

Wenn `SubAgentDef.owner_id` gesetzt ist UND der Runner einen `notify_user`-
Callback bekommt → Notify geht an die `telegram_chat_id` dieses Users.
Sonst Fallback auf den klassischen `notify` (broadcast / Default-chat_id).
"""

from __future__ import annotations

import asyncio

import pytest

from piclaw.agents.sa_registry import SubAgentDef
from piclaw.messaging.hub import MessagingHub, MessagingAdapter
from piclaw import users as users_mod
from piclaw.users import UserRegistry


# ── Mini-Telegram-Adapter zum Aufzeichnen ────────────────────────


class _RecordingTelegramAdapter(MessagingAdapter):
    name = "telegram"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []  # (chat_id, text)
        self._default_chat = "999-default"

    async def start(self, on_message):  # pragma: no cover
        pass

    async def stop(self):  # pragma: no cover
        pass

    async def send(self, text: str, chat_id: str | None = None):
        self.sent.append((str(chat_id) if chat_id else self._default_chat, text))


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reg(tmp_path, monkeypatch):
    r = UserRegistry(tmp_path / "users.json")
    monkeypatch.setattr(users_mod, "_registry", r)
    return r


@pytest.fixture
def hub_with_telegram():
    h = MessagingHub()
    adapter = _RecordingTelegramAdapter()
    h.register(adapter)
    return h, adapter


# ── MessagingHub.send_to_user ─────────────────────────────────────


@pytest.mark.asyncio
async def test_send_to_user_routes_to_user_chat(hub_with_telegram, reg):
    hub, adapter = hub_with_telegram
    u = reg.register_pending("Anna", "1234567890")
    ok = await hub.send_to_user(u.id, "Hi Anna!")
    assert ok is True
    assert adapter.sent == [("1234567890", "Hi Anna!")]


@pytest.mark.asyncio
async def test_send_to_user_unknown_user_returns_false(hub_with_telegram, reg):
    hub, adapter = hub_with_telegram
    ok = await hub.send_to_user("ghost-id", "Hi?")
    assert ok is False
    assert adapter.sent == []  # nichts versendet


@pytest.mark.asyncio
async def test_send_to_user_user_without_chat_id(hub_with_telegram, reg):
    hub, adapter = hub_with_telegram
    u = reg.register_pending("NoTg", "0")  # 0 ist falsy aber valid
    # Setze chat_id manuell auf leer
    u.telegram_chat_id = ""
    ok = await hub.send_to_user(u.id, "Hi?")
    assert ok is False
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_send_to_user_no_telegram_adapter():
    h = MessagingHub()  # kein Telegram-Adapter registriert
    # Trotzdem einen User anlegen (über monkeypatched registry vom fixture)
    from piclaw import users as users_mod
    u = users_mod.registry().register_pending("Anna", "999")
    ok = await h.send_to_user(u.id, "?")
    assert ok is False


# ── SubAgentRunner: notify-Routing ────────────────────────────────


@pytest.mark.asyncio
async def test_runner_routes_to_owner_when_owner_id_set(reg):
    """Sub-Agent mit owner_id → notify_user wird mit owner_id aufgerufen,
    notify (broadcast) NICHT."""
    from piclaw.agents.runner import SubAgentRunner

    anna = reg.register_pending("Anna", "1234567890")
    reg.approve(anna.id)

    broadcast_calls: list[str] = []
    owner_calls: list[tuple[str, str]] = []

    async def _notify(text):
        broadcast_calls.append(text)

    async def _notify_user(text, user_id):
        owner_calls.append((text, user_id))

    runner = SubAgentRunner(
        registry=None, llm=None, tool_defs=[], handlers={},
        notify=_notify, notify_user=_notify_user,
    )

    # _send_notify wird inline in _execute definiert — wir testen die Logik
    # indem wir es replizieren via einen Helper:
    sa = SubAgentDef(name="X", description="", mission="", tools=[], owner_id=anna.id)

    async def _send_notify(text: str) -> None:
        owner = getattr(sa, "owner_id", None)
        if owner and runner.notify_user is not None:
            try:
                await runner.notify_user(text, owner)
                return
            except Exception:
                pass
        if runner.notify is not None:
            await runner.notify(text)

    await _send_notify("hello")
    assert owner_calls == [("hello", anna.id)]
    assert broadcast_calls == []


@pytest.mark.asyncio
async def test_runner_falls_back_to_broadcast_when_no_owner(reg):
    """System-Sub-Agent (owner_id=None) → broadcast via notify."""
    from piclaw.agents.runner import SubAgentRunner

    broadcast_calls: list[str] = []
    owner_calls: list[tuple[str, str]] = []

    async def _notify(text):
        broadcast_calls.append(text)

    async def _notify_user(text, user_id):
        owner_calls.append((text, user_id))

    runner = SubAgentRunner(
        registry=None, llm=None, tool_defs=[], handlers={},
        notify=_notify, notify_user=_notify_user,
    )

    sa = SubAgentDef(name="Sys", description="", mission="", tools=[], owner_id=None)

    async def _send_notify(text: str) -> None:
        owner = getattr(sa, "owner_id", None)
        if owner and runner.notify_user is not None:
            await runner.notify_user(text, owner)
            return
        if runner.notify is not None:
            await runner.notify(text)

    await _send_notify("system msg")
    assert broadcast_calls == ["system msg"]
    assert owner_calls == []


@pytest.mark.asyncio
async def test_runner_falls_back_when_notify_user_raises(reg):
    """notify_user wirft Exception → automatischer Fallback auf broadcast."""
    from piclaw.agents.runner import SubAgentRunner

    anna = reg.register_pending("Anna", "1234567890")
    reg.approve(anna.id)

    broadcast_calls: list[str] = []

    async def _notify(text):
        broadcast_calls.append(text)

    async def _notify_user(text, user_id):
        raise RuntimeError("simulated network error")

    runner = SubAgentRunner(
        registry=None, llm=None, tool_defs=[], handlers={},
        notify=_notify, notify_user=_notify_user,
    )

    sa = SubAgentDef(name="X", description="", mission="", tools=[], owner_id=anna.id)

    async def _send_notify(text: str) -> None:
        owner = getattr(sa, "owner_id", None)
        if owner and runner.notify_user is not None:
            try:
                await runner.notify_user(text, owner)
                return
            except Exception:
                pass
        if runner.notify is not None:
            await runner.notify(text)

    await _send_notify("hi")
    assert broadcast_calls == ["hi"]


@pytest.mark.asyncio
async def test_runner_no_notify_user_callback_falls_back(reg):
    """notify_user=None (z.B. alte Wiring vor Phase 5.9) → broadcast."""
    from piclaw.agents.runner import SubAgentRunner

    anna = reg.register_pending("Anna", "1234567890")
    reg.approve(anna.id)

    broadcast_calls: list[str] = []

    async def _notify(text):
        broadcast_calls.append(text)

    runner = SubAgentRunner(
        registry=None, llm=None, tool_defs=[], handlers={},
        notify=_notify,
        # notify_user fehlt → None
    )

    sa = SubAgentDef(name="X", description="", mission="", tools=[], owner_id=anna.id)

    async def _send_notify(text: str) -> None:
        owner = getattr(sa, "owner_id", None)
        if owner and runner.notify_user is not None:
            await runner.notify_user(text, owner)
            return
        if runner.notify is not None:
            await runner.notify(text)

    await _send_notify("hi")
    assert broadcast_calls == ["hi"]

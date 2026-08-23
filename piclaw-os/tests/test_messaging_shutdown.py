"""
Regressionstest: Messaging-Sessions werden beim Shutdown geschlossen.

Beobachtet 23.08.2026 in agent.log - bei jedem der drei Service-Restarts
stand direkt nach "piclaw-agent stopped." ein

    [ERROR] asyncio: Unclosed client session

Der Daemon startet den Telegram-Poll-Loop nicht (das macht der API-Prozess),
sendet aber ueber den Hub. `TelegramAdapter.send()` legt die ClientSession
lazy an, wenn noch keine existiert - `start()` wird also nie aufgerufen,
eine Session entsteht trotzdem. Der Graceful-Shutdown in daemon.py schloss
HomeAssistant und proactive, den Hub aber nicht.

Kein Runtime-Leak (die Session lebt genau einmal pro Prozess), aber ein
unsauberer Shutdown - und im Log ein ERROR, das bei jedem Neustart
Rauschen erzeugt und echte Fehler verdeckt.
"""

import pytest


class _FakeSession:
    """Minimal, damit der Test ohne echtes aiohttp/Netzwerk auskommt."""

    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_hub_stop_closes_lazily_created_session():
    """Der Pfad aus dem Vorfall: nur gesendet, nie gestartet."""
    from piclaw.messaging.telegram import TelegramAdapter
    from piclaw.messaging.hub import MessagingHub

    adapter = TelegramAdapter(token="t", chat_id="c")
    session = _FakeSession()
    adapter._session = session  # so, wie send() sie anlegen wuerde

    hub = MessagingHub()
    hub.register(adapter)

    await hub.stop()

    assert session.closed is True, (
        "Ohne diesen Close meldet asyncio bei jedem Shutdown "
        "'Unclosed client session'."
    )


@pytest.mark.asyncio
async def test_hub_stop_survives_adapter_without_session():
    """Ein nie benutzter Adapter darf den Shutdown nicht kippen."""
    from piclaw.messaging.telegram import TelegramAdapter
    from piclaw.messaging.hub import MessagingHub

    hub = MessagingHub()
    hub.register(TelegramAdapter(token="t", chat_id="c"))

    await hub.stop()  # darf nicht werfen


@pytest.mark.asyncio
async def test_one_failing_adapter_does_not_block_the_others():
    """hub.stop() faengt pro Adapter ab - sonst bleibt der Rest offen."""
    from piclaw.messaging.telegram import TelegramAdapter
    from piclaw.messaging.hub import MessagingHub

    class _Boom(TelegramAdapter):
        async def stop(self):
            raise RuntimeError("kaputt")

    good = TelegramAdapter(token="t", chat_id="c")
    session = _FakeSession()
    good._session = session

    hub = MessagingHub()
    hub.register(_Boom(token="t", chat_id="c"))
    hub.register(good)

    await hub.stop()

    assert session.closed is True


def test_daemon_shutdown_stops_the_hub():
    """Der Aufruf muss im Shutdown-Pfad von daemon.py stehen."""
    import inspect
    from piclaw import daemon

    src = inspect.getsource(daemon)
    shutdown = src.split("Graceful shutdown", 1)[1]
    assert "_hub.stop()" in shutdown, (
        "daemon.py schloss HomeAssistant und proactive, den Messaging-Hub "
        "aber nicht - genau daher kam die Unclosed-session-Meldung."
    )

"""
Regressionstests für vier Funde der Debugging-Session (Runde 2).

1. api.py: /api/metrics/stats war von /api/metrics/{metric_name} verschattet
   (FastAPI matcht in Registrierungs-Reihenfolge) – der Endpoint lieferte die
   leere Zeitreihe einer Metrik namens "stats" statt der DB-Statistiken.

2. api.py: der WebSocket-Chat verwarf den authentifizierten User und rief
   Agent.run ohne user_id auf. user_id=None ist die System-/„sieht
   alles"-Konvention – jeder Web-Chat-Nutzer bekam die volle Sicht auf
   fremde Daten.

3. agent.py: die HA-Schaltrichtung wurde per Substring erkannt – das "an" in
   "Wandlampe"/"Gang" ließ Aus-Befehle einschalten.

4. agent.py: Marketplace-Follow-ups ("erhöhe den Radius auf 50 km") mergten
   die vorherigen Suchparameter, verwarfen sie dann aber und delegierten nur
   den rohen Follow-up-Text ohne jeden Kontext.
"""

import contextlib

import pytest
from fastapi.testclient import TestClient

from piclaw.users import User


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_client(monkeypatch, user: User):
    import piclaw.api as api_mod
    from piclaw.auth import require_auth, require_auth_ws

    @contextlib.asynccontextmanager
    async def _noop(app):
        yield

    monkeypatch.setattr(api_mod.app.router, "lifespan_context", _noop)
    api_mod.app.dependency_overrides[require_auth] = lambda: user
    api_mod.app.dependency_overrides[require_auth_ws] = lambda: user
    return api_mod, TestClient(api_mod.app)


@pytest.fixture
def api_client(monkeypatch):
    admin = User(id="admin-id", name="Admin", telegram_chat_id="", role="admin",
                 web_token="t", created_at="2026-01-01")
    api_mod, client = _make_client(monkeypatch, admin)
    try:
        with client as c:
            yield api_mod, c
    finally:
        api_mod.app.dependency_overrides.clear()


@pytest.fixture
def member_client(monkeypatch):
    member = User(id="user-42", name="Mia", telegram_chat_id="", role="user",
                  web_token="t2", created_at="2026-01-01")
    api_mod, client = _make_client(monkeypatch, member)
    try:
        with client as c:
            yield api_mod, c
    finally:
        api_mod.app.dependency_overrides.clear()


# ── 1. /api/metrics/stats erreicht den Stats-Endpoint ────────────────────


def test_metrics_stats_route_not_shadowed(api_client):
    _api_mod, client = api_client
    r = client.get("/api/metrics/stats")

    assert r.status_code == 200
    body = r.json()
    # Stats-Form (DB-Statistiken), nicht die Zeitreihen-Form der
    # dynamischen Route ({"metric": "stats", "data": [...]}).
    assert "metric" not in body
    assert "total_points" in body
    assert "retention_days" in body


def test_metrics_dynamic_route_still_works(api_client):
    _api_mod, client = api_client
    r = client.get("/api/metrics/cpu_percent")

    assert r.status_code == 200
    assert r.json()["metric"] == "cpu_percent"


# ── 2. WebSocket-Chat reicht die user_id durch ───────────────────────────


class _RecordingAgent:
    def __init__(self):
        self.calls = []

    async def run(self, user_input, history=None, on_token=None, user_id=None):
        self.calls.append({"input": user_input, "user_id": user_id})
        return "ok"


def _ws_roundtrip(api_mod, client) -> _RecordingAgent:
    stub = _RecordingAgent()
    original = api_mod._agent
    api_mod._agent = stub
    try:
        with client.websocket_connect("/ws/chat?token=t") as ws:
            ws.send_json({"text": "zeig meine einkaufsliste"})
            # "thinking" + ggf. Pings überspringen bis zur Antwort
            for _ in range(5):
                msg = ws.receive_json()
                if msg.get("type") == "reply":
                    break
            assert msg == {"type": "reply", "text": "ok"}
    finally:
        api_mod._agent = original
    return stub


def test_ws_chat_passes_user_id_for_member(member_client):
    api_mod, client = member_client
    stub = _ws_roundtrip(api_mod, client)

    assert stub.calls, "Agent.run wurde nicht aufgerufen"
    # Non-Admin: eigene user_id, NICHT None (None = Vollsicht)
    assert stub.calls[0]["user_id"] == "user-42"


def test_ws_chat_legacy_admin_keeps_full_scope(monkeypatch):
    legacy = User(id="legacy-admin", name="Legacy Admin", telegram_chat_id="",
                  role="admin", web_token="t", created_at="")
    api_mod, client = _make_client(monkeypatch, legacy)
    try:
        with client as c:
            stub = _ws_roundtrip(api_mod, c)
        assert stub.calls[0]["user_id"] is None
    finally:
        api_mod.app.dependency_overrides.clear()


# ── 3. HA-Schaltrichtung: ganze Wörter, Aus vor Ein ──────────────────────


def test_ha_direction_off_wins_over_substring_an():
    from piclaw.agent import _ha_direction

    # "an" steckt als Substring in "wandlampe" – darf NICHT einschalten
    assert _ha_direction("schalte die wandlampe aus") == "off"
    assert _ha_direction("mach das licht im gang aus") == "off"
    assert _ha_direction("mach das licht an der decke aus") == "off"


def test_ha_direction_on_and_toggle():
    from piclaw.agent import _ha_direction

    assert _ha_direction("schalte das licht an") == "on"
    assert _ha_direction("mach die lampe ein") == "on"
    assert _ha_direction("licht einschalten bitte") == "on"
    assert _ha_direction("schalte das licht um auf toggle") == "toggle"
    assert _ha_direction("stell die heizung wärmer") is None


# ── 4. Marketplace-Follow-up führt die gemergten Parameter aus ───────────


@pytest.mark.asyncio
async def test_marketplace_followup_executes_merged_params():
    from piclaw.agent import Agent
    from piclaw.config import PiClawConfig
    from piclaw.llm.base import Message

    agent = Agent(PiClawConfig())
    calls = []

    async def _recorder(**kw):
        calls.append(kw)
        return "3 Inserate gefunden"

    agent._handlers["marketplace_search"] = _recorder

    history = [
        Message(role="user", content="Suche Gartentisch Rosengarten eBay"),
        Message(role="assistant", content="Hier sind die Ergebnisse …"),
    ]
    reply = await agent._run_internal(
        "erhöhe den Radius auf 50 km", history=history,
    )

    assert reply == "3 Inserate gefunden"
    assert len(calls) == 1
    # Kontext aus der vorherigen Suche bleibt erhalten …
    assert "gartentisch" in calls[0]["query"].lower()
    assert calls[0]["location"] == "Rosengarten"
    # … und der neue Radius wird übernommen.
    assert calls[0]["radius_km"] == 50

"""
REST-Routen der Einkaufsliste.

Schwerpunkt: Auth, Multi-User-Sichtbarkeit und das Antwortformat der
Sparkline-Route. Kein Netzwerk – die Angebotssuche wird gestubbt.
"""

import time

import pytest
from fastapi.testclient import TestClient

from piclaw.users import User

DAY = 86_400


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App ohne Lifespan (kein Agent/LLM) und mit fester Admin-Identität."""
    import contextlib

    import piclaw.api as api_mod
    import piclaw.shopping.store as store_mod
    from piclaw.auth import require_admin, require_auth

    monkeypatch.setattr(store_mod, "SHOPPING_DB", tmp_path / "shopping.db")
    store_mod.reset_db()

    @contextlib.asynccontextmanager
    async def _noop(app):
        yield

    monkeypatch.setattr(api_mod.app.router, "lifespan_context", _noop)
    admin = User(id="admin-id", name="Admin", telegram_chat_id="", role="admin",
                 web_token="t", created_at="2026-01-01")
    api_mod.app.dependency_overrides[require_auth] = lambda: admin
    api_mod.app.dependency_overrides[require_admin] = lambda: admin
    try:
        with TestClient(api_mod.app) as c:
            c._db = store_mod.get_db()
            yield c
    finally:
        api_mod.app.dependency_overrides.clear()
        store_mod.reset_db()


# ── CRUD ─────────────────────────────────────────────────────────────────


def test_liste_ist_anfangs_leer(client):
    r = client.get("/api/shopping/items")

    assert r.status_code == 200
    assert r.json()["items"] == []


def test_anlegen_und_auflisten(client):
    r = client.post("/api/shopping/items",
                    json={"name": "Butter", "qty": "250g", "max_price": 1.5})

    assert r.status_code == 200
    assert r.json()["created"] is True

    items = client.get("/api/shopping/items").json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Butter"
    assert items[0]["max_price"] == 1.5
    assert items[0]["status"] == "Datenaufbau läuft"


def test_anlegen_ohne_namen_ist_400(client):
    assert client.post("/api/shopping/items", json={}).status_code == 400
    assert client.post("/api/shopping/items", json={"name": "  "}).status_code == 400


def test_doppelter_artikel_ist_409(client):
    client.post("/api/shopping/items", json={"name": "Butter"})

    r = client.post("/api/shopping/items", json={"name": "butter"})

    assert r.status_code == 409
    assert "schon auf der Liste" in r.json()["detail"]


def test_ungueltiger_maxpreis_ist_400(client):
    r = client.post("/api/shopping/items", json={"name": "X", "max_price": "teuer"})

    assert r.status_code == 400


def test_loeschen(client):
    item_id = client.post("/api/shopping/items", json={"name": "Butter"}).json()["id"]

    r = client.delete(f"/api/shopping/items/{item_id}")

    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert client.get("/api/shopping/items").json()["items"] == []


def test_unbekannter_artikel_ist_404(client):
    assert client.delete("/api/shopping/items/999").status_code == 404
    assert client.get("/api/shopping/items/999/history").status_code == 404


# ── Sichtbarkeit ─────────────────────────────────────────────────────────


def test_fremder_artikel_gibt_404_nicht_403(client, monkeypatch):
    """Wie bei Sub-Agenten: die Existenz darf nicht durchsickern."""
    import piclaw.api as api_mod
    from piclaw.auth import require_auth

    fremd = client._db.add_item("Annas Milch", owner_id="anna-id")
    normal = User(id="patrick-id", name="Patrick", telegram_chat_id="",
                  role="user", web_token="t2", created_at="2026-01-01")
    api_mod.app.dependency_overrides[require_auth] = lambda: normal

    assert client.get("/api/shopping/items").json()["items"] == []
    assert client.delete(f"/api/shopping/items/{fremd.id}").status_code == 404
    assert client.get(f"/api/shopping/items/{fremd.id}/history").status_code == 404


def test_nutzer_sieht_eigene_und_globale(client, monkeypatch):
    import piclaw.api as api_mod
    from piclaw.auth import require_auth

    client._db.add_item("Haushalt", owner_id=None)
    client._db.add_item("Annas", owner_id="anna-id")
    normal = User(id="anna-id", name="Anna", telegram_chat_id="", role="user",
                  web_token="t2", created_at="2026-01-01")
    api_mod.app.dependency_overrides[require_auth] = lambda: normal

    namen = {i["name"] for i in client.get("/api/shopping/items").json()["items"]}

    assert namen == {"Haushalt", "Annas"}


# ── Sparkline-Route ──────────────────────────────────────────────────────


def test_history_liefert_metrics_format(client):
    """{data:[{ts,value}]} – gleiches Format wie /api/metrics/chart."""
    from piclaw.shopping.store import PricePoint

    db = client._db
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Milbona", "milbona")
    now = int(time.time())
    db.record_prices([PricePoint(pid, 1.10, now - 2 * DAY),
                      PricePoint(pid, 0.90, now)])

    d = client.get(f"/api/shopping/items/{item.id}/history?days=30").json()

    assert d["name"] == "Butter"
    assert [p["value"] for p in d["data"]] == [1.10, 0.90]
    assert all("ts" in p for p in d["data"])
    assert d["products"][0]["retailer"] == "lidl"


def test_history_respektiert_zeitfenster(client):
    from piclaw.shopping.store import PricePoint

    db = client._db
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Milbona", "milbona")
    now = int(time.time())
    db.record_prices([PricePoint(pid, 9.99, now - 200 * DAY),
                      PricePoint(pid, 1.10, now)])

    d = client.get(f"/api/shopping/items/{item.id}/history?days=30").json()

    assert [p["value"] for p in d["data"]] == [1.10]


def test_liste_meldet_preisrutsch(client):
    from piclaw.shopping.store import PricePoint

    db = client._db
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Milbona", "milbona")
    now = int(time.time())
    db.record_prices([PricePoint(pid, 1.10, now - (14 - i) * DAY) for i in range(14)])
    db.record_prices([PricePoint(pid, 0.90, now)])

    item_json = client.get("/api/shopping/items").json()["items"][0]

    assert item_json["is_drop"] is True
    assert item_json["best"]["price"] == 0.90
    assert "Allzeittief" in item_json["status"]


# ── Testen-Knopf ─────────────────────────────────────────────────────────


def test_test_route_trennt_treffer_von_ausreissern(client, monkeypatch):
    import piclaw.api as api_mod
    from piclaw.shopping.providers.base import Offer

    async def _fake_search(session, query, **kw):
        return [
            Offer(title="Original Irische Butter", brand="Kerrygold",
                  price=1.79, retailer="Lidl", retailer_key="lidl"),
            Offer(title="Buttermilch Drink", brand="Hamfelder Hof",
                  price=0.99, retailer="REWE", retailer_key="rewe"),
        ]

    monkeypatch.setattr(api_mod, "_shopping_probe", api_mod._shopping_probe)
    monkeypatch.setattr("piclaw.shopping.providers.search_all", _fake_search)

    d = client.post("/api/shopping/test", json={"query": "butter"}).json()

    assert d["total"] == 1
    assert d["matches"][0]["title"] == "Original Irische Butter"
    assert d["rejected"][0]["title"] == "Buttermilch Drink"


def test_test_route_ohne_query_ist_400(client):
    assert client.post("/api/shopping/test", json={}).status_code == 400


def test_test_route_fuer_bestehenden_artikel(client, monkeypatch):
    from piclaw.shopping.providers.base import Offer

    async def _fake_search(session, query, **kw):
        assert query == "geschirrspül"      # nutzt query, nicht name
        return [Offer(title="Geschirrspültabs", price=4.99, retailer="dm",
                      retailer_key="dm")]

    monkeypatch.setattr("piclaw.shopping.providers.search_all", _fake_search)
    item = client._db.add_item("Tabs", query="geschirrspül")

    d = client.post(f"/api/shopping/items/{item.id}/test").json()

    assert d["total"] == 1


# ── Auth ─────────────────────────────────────────────────────────────────


def test_routen_verlangen_auth(tmp_path, monkeypatch):
    """Ohne Override greift require_auth – 401 statt offener Daten."""
    import contextlib

    import piclaw.api as api_mod
    import piclaw.shopping.store as store_mod

    monkeypatch.setattr(store_mod, "SHOPPING_DB", tmp_path / "shopping.db")
    store_mod.reset_db()

    @contextlib.asynccontextmanager
    async def _noop(app):
        yield

    monkeypatch.setattr(api_mod.app.router, "lifespan_context", _noop)
    api_mod.app.dependency_overrides.clear()

    with TestClient(api_mod.app) as c:
        assert c.get("/api/shopping/items").status_code == 401
        assert c.post("/api/shopping/items", json={"name": "X"}).status_code == 401
        assert c.get("/api/shopping/stores").status_code == 401

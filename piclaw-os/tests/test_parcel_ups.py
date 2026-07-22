"""
Tests für den UPS-Track-API-Endpoint (_query_ups / _parse_ups_response).

Kein Test berührt Netzwerk oder die echte config.toml — CONFIG_DIR wird
pro Test auf tmp_path gepatcht (Lehre aus dem Store-Leak-Vorfall 18.07.).
"""

import asyncio

import pytest

import piclaw.tools.parcel_tracking as pt


@pytest.fixture(autouse=True)
def _isolate_ups_state(tmp_path, monkeypatch):
    """CONFIG_DIR weg von /etc/piclaw + Token-Cache pro Test leeren."""
    monkeypatch.setattr(pt, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(pt, "_ups_token", {"value": None, "expires_at": 0.0})


def _ups_response(**package_extra):
    package = {
        "currentStatus": {"type": "I", "description": "In Transit", "code": "070"},
        "activity": [
            {
                "date": "20260722",
                "time": "134501",
                "status": {"type": "I", "description": "Abfahrtscan", "code": "DP"},
                "location": {"address": {"city": "Herne"}},
            },
            {
                "date": "20260721",
                "time": "091200",
                "status": {"type": "M", "description": "Auftrag verarbeitet", "code": "MP"},
                "location": {"address": {}},
            },
        ],
        **package_extra,
    }
    return {"trackResponse": {"shipment": [{"package": [package]}]}}


def test_parse_in_transit_with_events():
    parsed = pt._parse_ups_response(_ups_response())
    assert parsed["raw_status"] == "in_transit"
    assert parsed["status_text"] == "In Transit"
    assert parsed["source"] == "ups_api"
    assert parsed["events"][0] == {
        "timestamp": "2026-07-22T13:45:01",
        "location": "Herne",
        "description": "Abfahrtscan",
        "status_code": "DP",
    }
    assert parsed["events"][1]["location"] == ""


def test_parse_delivered_and_eta_window():
    resp = _ups_response(
        deliveryDate=[{"type": "SDD", "date": "20260723"}],
        deliveryTime={"startTime": "093000", "endTime": "124500", "type": "EDW"},
    )
    resp["trackResponse"]["shipment"][0]["package"][0]["currentStatus"] = {
        "type": "D", "description": "Zugestellt", "code": "011",
    }
    parsed = pt._parse_ups_response(resp)
    assert parsed["raw_status"] == "delivered"
    assert parsed["eta"] == "2026-07-23"
    assert parsed["eta_window"] == {"from": "09:30", "to": "12:45", "date": "2026-07-23"}


def test_parse_unknown_type_falls_back_to_keywords():
    resp = _ups_response()
    resp["trackResponse"]["shipment"][0]["package"][0]["currentStatus"] = {
        "type": "ZZ", "description": "Out For Delivery Today", "code": "999",
    }
    parsed = pt._parse_ups_response(resp)
    assert parsed["raw_status"] == "out_for_delivery"


def test_parse_warning_response_returns_none():
    # UPS antwortet bei unbekannter TN mit shipment[] ohne package[]
    resp = {"trackResponse": {"shipment": [{"warnings": [
        {"code": "TW0001", "message": "Tracking Information Not Found"},
    ]}]}}
    assert pt._parse_ups_response(resp) is None
    assert pt._parse_ups_response({}) is None


@pytest.mark.asyncio
async def test_query_ups_without_credentials_skips():
    # Kein config.toml unter dem gepatchten CONFIG_DIR → kein Token → None,
    # ohne dass ein HTTP-Request abgesetzt wird.
    assert await pt._query_ups("1ZA7033G6824883822") is None


@pytest.mark.asyncio
async def test_get_ups_token_uses_cache(monkeypatch):
    monkeypatch.setattr(pt, "_load_ups_credentials", lambda: ("id", "secret"))
    pt._ups_token.update({"value": "cached-token", "expires_at": 9999999999.0})

    class _NoHTTP:
        def post(self, *a, **kw):  # pragma: no cover - darf nie laufen
            raise AssertionError("Token-Cache wurde ignoriert")

    assert await pt._get_ups_token(_NoHTTP()) == "cached-token"


@pytest.mark.asyncio
async def test_track_single_uses_ups_endpoint_not_parcello(monkeypatch):
    async def _fake_ups(tn, session=None):
        return {
            "source": "ups_api",
            "raw_status": "in_transit",
            "status_text": "In Transit",
            "events": [{"timestamp": "2026-07-22T13:45:01", "location": "Herne",
                        "description": "Abfahrtscan", "status_code": "DP"}],
            "eta": "2026-07-23",
            "eta_window": {"from": "09:30", "to": "12:45", "date": "2026-07-23"},
        }

    async def _no_parcello(tn, session=None):  # pragma: no cover
        raise AssertionError("Parcello darf für UPS nicht mehr angefragt werden")

    monkeypatch.setattr(pt, "_query_ups", _fake_ups)
    monkeypatch.setattr(pt, "_query_parcello", _no_parcello)

    result = await pt.track_single("1ZA7033G6824883822", "auto")
    assert result["carrier"] == "ups"
    assert result["status"] == "in_transit"
    assert result["events"][0]["location"] == "Herne"
    assert result["eta"] == "2026-07-23"
    assert result["eta_window"]["from"] == "09:30"


@pytest.mark.asyncio
async def test_track_single_unknown_carrier_still_tries_parcello(monkeypatch):
    called = []

    async def _dead_parcello(tn, session=None):
        called.append(tn)
        return None

    monkeypatch.setattr(pt, "_query_parcello", _dead_parcello)

    result = await pt.track_single("FEDEX123456789012", "fedex")
    assert called == ["FEDEX123456789012"]
    assert result["status"] == "unknown"

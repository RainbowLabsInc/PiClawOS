"""
Geo-Helfer: Distanz, Adressauflösung, Overpass-Umkreissuche.

Kein Netzwerk – Nominatim und Overpass werden per monkeypatch ersetzt.
Antwortformate stammen aus echten Aufrufen (Stand 08/2026).
"""

import pytest

from piclaw.tools import geo

# Hamburg Rathausmarkt / Berlin Alexanderplatz
HH = (53.5503, 9.9926)
B = (52.5200, 13.4050)


# ── Distanz ──────────────────────────────────────────────────────────────


def test_haversine_gegen_bekannte_distanz():
    """Hamburg–Berlin sind gut 255 km Luftlinie."""
    assert geo.haversine_km(*HH, *B) == pytest.approx(255, abs=3)


def test_haversine_identischer_punkt_ist_null():
    assert geo.haversine_km(*HH, *HH) == 0.0


def test_haversine_ist_symmetrisch():
    assert geo.haversine_km(*HH, *B) == pytest.approx(geo.haversine_km(*B, *HH))


# ── Genauigkeit der Adressauflösung ──────────────────────────────────────


def _hit(addresstype, address=None, lat=53.55, lon=9.99):
    return [{
        "lat": str(lat), "lon": str(lon),
        "addresstype": addresstype,
        "display_name": "Testtreffer",
        "address": address or {},
    }]


def test_hausnummer_gilt_als_exakt_auch_bei_fremdem_addresstype():
    """Der Fall, der beim Hamburger Rathausmarkt auffiel.

    Nominatim liefert addresstype='office', obwohl die Hausnummer sauber
    getroffen wurde – addresstype benennt das Objekt, nicht die Genauigkeit.
    Verlässlich ist address.house_number.
    """
    point = geo.GeoPoint(lat=53.55, lon=9.99, precision="office", house_number="1")

    assert point.is_exact
    assert point.quality == "Hausnummer"


def test_strassentreffer_ist_nicht_exakt():
    point = geo.GeoPoint(lat=53.55, lon=9.99, precision="road")

    assert not point.is_exact
    assert point.quality == "nur Straße"


def test_plz_zentroid_ist_nicht_exakt():
    """Der Fehler, den das ganze Design vermeiden soll."""
    point = geo.GeoPoint(lat=53.55, lon=9.99, precision="postcode")

    assert not point.is_exact
    assert point.quality == "nur Ort/PLZ"


def test_building_gilt_ohne_hausnummer_als_exakt():
    assert geo.GeoPoint(lat=1, lon=1, precision="building").is_exact


# ── Adressauflösung: Kaskade ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_strukturierte_suche_zuerst(monkeypatch):
    aufrufe = []

    async def _fake(session, params):
        aufrufe.append(params)
        return geo.GeoPoint(lat=53.55, lon=9.99, precision="house",
                            house_number="1", postcode="20095")

    monkeypatch.setattr(geo, "nominatim_lookup", _fake)

    point = await geo.address_to_coords(None, "Rathausmarkt", "1", "20095", "Hamburg")

    assert point.is_exact
    assert len(aufrufe) == 1                       # bei Treffer kein Fallback
    assert aufrufe[0]["street"] == "1 Rathausmarkt"
    assert aufrufe[0]["postalcode"] == "20095"
    assert aufrufe[0]["city"] == "Hamburg"


@pytest.mark.asyncio
async def test_fallback_auf_freeform_bei_ungenauem_treffer(monkeypatch):
    """Ungenauer Treffer beendet die Suche nicht – der nächste Versuch zählt."""
    aufrufe = []

    async def _fake(session, params):
        aufrufe.append(params)
        if "q" in params:
            return geo.GeoPoint(lat=53.55, lon=9.99, precision="house",
                                house_number="1")
        return geo.GeoPoint(lat=53.0, lon=9.0, precision="road")

    monkeypatch.setattr(geo, "nominatim_lookup", _fake)

    point = await geo.address_to_coords(None, "Rathausmarkt", "1", "20095", "Hamburg")

    assert point.is_exact
    assert point.lat == 53.55
    assert any("q" in p for p in aufrufe)


@pytest.mark.asyncio
async def test_ungenauer_treffer_wird_zurueckgegeben_wenn_nichts_besseres_kommt(monkeypatch):
    async def _fake(session, params):
        return geo.GeoPoint(lat=53.0, lon=9.0, precision="postcode")

    monkeypatch.setattr(geo, "nominatim_lookup", _fake)

    point = await geo.address_to_coords(None, "Gibtsnicht", "9", "20095", "Hamburg")

    assert point is not None
    assert not point.is_exact          # aber der Aufrufer sieht die Unschärfe


@pytest.mark.asyncio
async def test_ohne_treffer_none(monkeypatch):
    async def _fake(session, params):
        return None

    monkeypatch.setattr(geo, "nominatim_lookup", _fake)

    assert await geo.address_to_coords(None, "Nirgendwo", "1", "00000", "X") is None


@pytest.mark.asyncio
async def test_leere_adresse_fragt_nicht_an(monkeypatch):
    async def _fake(session, params):  # pragma: no cover
        raise AssertionError("darf nicht aufgerufen werden")

    monkeypatch.setattr(geo, "nominatim_lookup", _fake)

    assert await geo.address_to_coords(None) is None


# ── Overpass-Query und -Parsing ──────────────────────────────────────────


def test_query_nutzt_nwr_und_out_center():
    """Grosse Maerkte sind Ways/Relations – 'node' allein verliert sie."""
    ql = geo.build_shops_query(53.55, 9.99, 2.0)

    assert ql.startswith("[out:json][timeout:25];")
    assert "nwr[" in ql
    assert "around:2000,53.550000,9.990000" in ql
    assert "out center tags;" in ql
    assert "supermarket" in ql


def test_query_rundet_radius_auf_meter():
    assert "around:1500," in geo.build_shops_query(1.0, 1.0, 1.5)
    assert "around:10000," in geo.build_shops_query(1.0, 1.0, 10)


def test_parst_node():
    element = {
        "type": "node", "id": 123, "lat": 53.56, "lon": 10.0,
        "tags": {"shop": "supermarket", "name": "REWE City", "brand": "REWE",
                 "addr:street": "Ballindamm", "addr:housenumber": "40",
                 "addr:city": "Hamburg"},
    }

    shop = geo.parse_shop_element(element, *HH)

    assert shop.osm_id == "node/123"
    assert shop.brand == "REWE"
    assert shop.label == "REWE"
    assert shop.address == "Ballindamm 40, Hamburg"
    assert shop.distance_km > 0


def test_parst_way_ueber_center():
    """Way hat kein lat/lon, nur center – daher 'out center' in der Query."""
    element = {
        "type": "way", "id": 456,
        "center": {"lat": 53.56, "lon": 10.0},
        "tags": {"shop": "chemist", "name": "Budni"},
    }

    shop = geo.parse_shop_element(element, *HH)

    assert shop is not None
    assert shop.osm_id == "way/456"
    assert shop.lat == 53.56


def test_element_ohne_koordinaten_wird_verworfen():
    assert geo.parse_shop_element({"type": "way", "id": 1, "tags": {"name": "X"}}, *HH) is None


def test_namenloser_laden_wird_verworfen():
    element = {"type": "node", "id": 1, "lat": 53.56, "lon": 10.0,
               "tags": {"shop": "supermarket"}}

    assert geo.parse_shop_element(element, *HH) is None


def test_operator_zaehlt_als_marke():
    element = {"type": "node", "id": 1, "lat": 53.56, "lon": 10.0,
               "tags": {"shop": "supermarket", "operator": "EDEKA"}}

    assert geo.parse_shop_element(element, *HH).brand == "EDEKA"


# ── find_shops ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_shops_sortiert_nach_distanz(monkeypatch):
    async def _fake(session, ql):
        return [
            {"type": "node", "id": 1, "lat": 53.60, "lon": 10.10,
             "tags": {"shop": "supermarket", "name": "Fern"}},
            {"type": "node", "id": 2, "lat": 53.5505, "lon": 9.9930,
             "tags": {"shop": "supermarket", "name": "Nah"}},
        ]

    monkeypatch.setattr(geo, "overpass_query", _fake)

    shops = await geo.find_shops(None, *HH, radius_km=10)

    assert [s.name for s in shops] == ["Nah", "Fern"]


@pytest.mark.asyncio
async def test_find_shops_kappt_auf_maximum(monkeypatch):
    """In Innenstaedten liefert Overpass hunderte Treffer."""
    async def _fake(session, ql):
        return [
            {"type": "node", "id": i, "lat": 53.55 + i / 10000, "lon": 9.99,
             "tags": {"shop": "supermarket", "name": f"Markt {i}"}}
            for i in range(50)
        ]

    monkeypatch.setattr(geo, "overpass_query", _fake)

    alle = await geo.find_shops(None, *HH, radius_km=10, max_results=50)
    gekappt = await geo.find_shops(None, *HH, radius_km=10, max_results=10)

    assert len(gekappt) == 10
    # Gekappt wird nach dem Sortieren: es bleiben genau die naechsten zehn.
    assert [s.name for s in gekappt] == [s.name for s in alle[:10]]
    assert gekappt == sorted(gekappt, key=lambda s: s.distance_km)


@pytest.mark.asyncio
async def test_overpass_ausfall_gibt_leere_liste(monkeypatch):
    """504 vom Gemeinschaftsdienst ist Alltag, kein Grund zu werfen."""
    async def _fake(session, ql):
        return []

    monkeypatch.setattr(geo, "overpass_query", _fake)

    assert await geo.find_shops(None, *HH) == []


# ── Rate-Gate ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_gate_haelt_mindestabstand_ein(monkeypatch):
    """Nominatim erlaubt 1 Aufruf/Sekunde – eine Schleife darf nicht feuern."""
    schlafphasen = []

    async def _sleep(secs):
        schlafphasen.append(secs)

    monkeypatch.setattr(geo.asyncio, "sleep", _sleep)
    monkeypatch.setattr(geo, "_last_call", {})
    monkeypatch.setattr(geo, "_rate_lock", {})

    await geo._throttle("nominatim")     # erster Aufruf: kein Warten
    await geo._throttle("nominatim")     # zweiter: muss warten

    assert schlafphasen and schlafphasen[-1] > 0

"""
Warenkorb-Vergleich.

Die Kernfrage: in welchem *einzelnen* Laden ist der ganze Einkauf am
günstigsten. Es nützt nichts zu wissen, dass Butter bei Lidl und Kaffee bei
REWE am billigsten ist, wenn man dafür zwei Fahrten braucht.

Wichtigste Eigenschaft: Läden mit unterschiedlicher Abdeckung dürfen nicht
gegeneinander gestellt werden – 3 von 5 Artikeln sind kein günstigerer
Einkauf als 5 von 5.
"""

import pytest

from piclaw.shopping import basket
from piclaw.shopping.location import Surroundings
from piclaw.shopping.providers.base import Offer
from piclaw.shopping.store import Item


class _Home:
    lat, lon, zip_code = 53.55, 9.99, "20095"


def angebot(retailer_key, price, title="Ware", size=None):
    return Offer(title=title, retailer=retailer_key.upper(),
                 retailer_key=retailer_key, price=price,
                 unit_size=size, unit_label="kg" if size else "")


def umgebung(*keys, entfernungen=None):
    entfernungen = entfernungen or {}
    return Surroundings(
        shops=[{"retailer_key": k, "distance_km": entfernungen.get(k, 1.0),
                "street": ""} for k in keys],
        retailer_keys=set(keys),
        radius_km=10,
    )


def treffer_quelle(mapping):
    """mapping: suchbegriff -> [Offer]"""
    async def _search(session, query, **kw):
        return list(mapping.get(query.lower(), []))
    return _search


@pytest.fixture
def patch_search(monkeypatch):
    def _setzen(mapping):
        monkeypatch.setattr(basket, "search_all", treffer_quelle(mapping))
    return _setzen


# ── Rangfolge ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guenstigster_laden_gewinnt(patch_search):
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Kaffee", query="kaffee")]
    patch_search({
        "butter": [angebot("lidl", 1.00), angebot("rewe", 1.20)],
        "kaffee": [angebot("lidl", 5.00), angebot("rewe", 4.50)],
    })

    r = await basket.compare(None, items, _Home(), umgebung("lidl", "rewe"))

    assert [s.retailer_key for s in r.stores] == ["rewe", "lidl"]
    assert r.stores[0].total == 5.70   # REWE: 1.20 + 4.50
    assert r.stores[1].total == 6.00   # Lidl: 1.00 + 5.00


@pytest.mark.asyncio
async def test_abdeckung_schlaegt_preis(patch_search):
    """Ein Laden mit 1 von 2 Artikeln ist nicht 'billiger'."""
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Kaffee", query="kaffee")]
    patch_search({
        "butter": [angebot("lidl", 0.50), angebot("rewe", 1.20)],
        "kaffee": [angebot("rewe", 4.50)],          # Lidl hat keinen Kaffee
    })

    r = await basket.compare(None, items, _Home(), umgebung("lidl", "rewe"))

    assert r.stores[0].retailer_key == "rewe"       # trotz höherer Summe vorn
    assert r.stores[0].covered == 2
    assert r.stores[1].covered == 1
    assert r.stores[1].missing == ["Kaffee"]
    assert r.best_single.retailer_key == "rewe"


@pytest.mark.asyncio
async def test_guenstigster_treffer_je_haendler_zaehlt(patch_search):
    items = [Item(id=1, name="Butter", query="butter")]
    patch_search({"butter": [angebot("lidl", 2.00, "teuer"),
                             angebot("lidl", 1.00, "billig")]})

    r = await basket.compare(None, items, _Home(), umgebung("lidl"))

    assert r.stores[0].total == 1.00
    assert r.stores[0].treffer[0].title == "billig"


# ── Optimum und Ersparnis ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_optimum_verteilt_ueber_mehrere_laeden(patch_search):
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Kaffee", query="kaffee")]
    patch_search({
        "butter": [angebot("lidl", 1.00), angebot("rewe", 1.50)],
        "kaffee": [angebot("lidl", 5.00), angebot("rewe", 4.00)],
    })

    r = await basket.compare(None, items, _Home(), umgebung("lidl", "rewe"))

    assert r.optimum_total == 5.00           # 1.00 Lidl + 4.00 REWE
    assert r.optimum_stores == 2
    assert r.best_single.total == 5.50       # REWE komplett
    assert r.savings == 0.50


@pytest.mark.asyncio
async def test_keine_ersparnis_wenn_ein_laden_schon_optimal(patch_search):
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Kaffee", query="kaffee")]
    patch_search({
        "butter": [angebot("lidl", 1.00), angebot("rewe", 1.50)],
        "kaffee": [angebot("lidl", 4.00), angebot("rewe", 5.00)],
    })

    r = await basket.compare(None, items, _Home(), umgebung("lidl", "rewe"))

    assert r.optimum_stores == 1
    assert r.savings == 0.0


@pytest.mark.asyncio
async def test_ersparnis_nur_bei_voller_abdeckung(patch_search):
    """Sonst vergleicht man unterschiedliche Warenkörbe."""
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Kaffee", query="kaffee")]
    patch_search({
        "butter": [angebot("lidl", 1.00)],
        "kaffee": [angebot("rewe", 4.00)],
    })

    r = await basket.compare(None, items, _Home(), umgebung("lidl", "rewe"))

    assert r.best_single.covered == 1
    assert r.savings == 0.0


# ── Sonderfälle ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artikel_ohne_angebot_wird_benannt(patch_search):
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Trüffel", query="trueffel")]
    patch_search({"butter": [angebot("lidl", 1.00)]})

    r = await basket.compare(None, items, _Home(), umgebung("lidl"))

    assert r.ohne_angebot == ["Trüffel"]
    assert r.stores[0].covered == 1
    assert r.stores[0].missing == []      # Trüffel gibt es nirgends, kein Vorwurf
    # Nenner ist das Verfügbare: Lidl führt alles, was es gibt.
    assert r.comparable == 1
    assert r.item_count == 2


@pytest.mark.asyncio
async def test_leere_liste(patch_search):
    patch_search({})

    r = await basket.compare(None, [], _Home(), umgebung("lidl"))

    assert r.error
    assert r.stores == []


@pytest.mark.asyncio
async def test_gar_keine_angebote(patch_search):
    patch_search({})

    r = await basket.compare(
        None, [Item(id=1, name="Butter", query="butter")], _Home(), umgebung("lidl")
    )

    assert r.error == "keine Angebote gefunden"


@pytest.mark.asyncio
async def test_max_price_wird_beachtet(patch_search):
    items = [Item(id=1, name="Butter", query="butter", max_price=1.00)]
    patch_search({"butter": [angebot("lidl", 1.50), angebot("rewe", 0.90)]})

    r = await basket.compare(None, items, _Home(), umgebung("lidl", "rewe"))

    assert [s.retailer_key for s in r.stores] == ["rewe"]


@pytest.mark.asyncio
async def test_entfernung_wird_mitgefuehrt(patch_search):
    """2 € Ersparnis auf 8 km Umweg muss einordenbar sein."""
    items = [Item(id=1, name="Butter", query="butter")]
    patch_search({"butter": [angebot("lidl", 1.00), angebot("rewe", 1.50)]})

    r = await basket.compare(
        None, items, _Home(),
        umgebung("lidl", "rewe", entfernungen={"lidl": 8.2, "rewe": 0.3}),
    )

    je_laden = {s.retailer_key: s.distance_km for s in r.stores}
    assert je_laden == {"lidl": 8.2, "rewe": 0.3}


@pytest.mark.asyncio
async def test_ausfall_eines_artikels_kippt_nicht_den_korb(monkeypatch):
    items = [Item(id=1, name="Butter", query="butter"),
             Item(id=2, name="Kaffee", query="kaffee")]

    async def _search(session, query, **kw):
        if query == "butter":
            raise RuntimeError("Provider tot")
        return [angebot("rewe", 4.00)]

    monkeypatch.setattr(basket, "search_all", _search)

    r = await basket.compare(None, items, _Home(), umgebung("rewe"))

    assert r.stores[0].total == 4.00
    assert not r.error

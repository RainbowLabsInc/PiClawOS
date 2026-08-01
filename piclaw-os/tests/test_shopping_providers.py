"""
Angebots-Provider.

Alle Fixtures sind gekürzte, aber echte Antworten von api.marktguru.de und
offers.lidlplus.com (Stand 08/2026). Kein Netzwerk – die HTTP-Ebene wird per
monkeypatch ersetzt.

Wichtigste Eigenschaft: eine kaputte Quelle darf die Suche nicht kippen.
Beide APIs sind inoffiziell und ändern Feldformen ohne Ankündigung.
"""

import pytest

from piclaw.shopping.providers import registry
from piclaw.shopping.providers.base import Offer
from piclaw.shopping.providers.lidl import LidlProvider
from piclaw.shopping.providers.lidl import parse_offer as parse_lidl
from piclaw.shopping.providers.marktguru import MarktguruProvider
from piclaw.shopping.providers.marktguru import parse_offer as parse_mg

# ── Fixtures aus echten Antworten ────────────────────────────────────────

MG_OFFER = {
    "price": 1.79,
    "oldPrice": None,
    "unit": {"shortName": "kg", "id": 2, "name": "Kilogramm"},
    "referencePrice": 7.16,
    "description": "Versch. Sorten. Gekühlt. Je 250/200 g",
    "brand": {"uniqueName": "kerrygold", "name": "Kerrygold", "id": 114952},
    "product": {"name": "Original Irische Butter"},
    "advertisers": [{"uniqueName": "lidl", "name": "Lidl", "id": "retailers/126679"}],
    "validityDates": [{"from": "2026-07-29T22:00:00Z", "to": "2026-08-01T21:59:00Z"}],
    # images ist ein dict OHNE url – genau daran ist der Parser mal gescheitert
    "images": {"count": 1, "metadata": [{"aspectRatio": 1.44}]},
    "externalUrl": "",
}

LIDL_OFFER = {
    "id": "c7c7ea3a",
    "priceBox": {
        "priceSymbol": "€",
        "discountMessage": "-50%",
        "strikethrough": True,
        "largePartNumeric": 0.99,
        "smallPartNumeric": 1.99,
    },
    "title": "Lay's Chips",
    "brand": "LAY’S",
    "packaging": "Je 150/110 g (Max. 24 Stück)\nNormalpreis: 1.11\n1 kg = 7.40",
    "pricePerUnit": "1 kg = 6.60/9.00",
    "startValidityDateUTC": "2026-07-29T22:00:01Z",
    "endValidityDateUTC": "2026-08-01T21:59:59Z",
    "imageUrl": "https://static-coupons.lidlplus.com/x.jpg",
}

# Rabattaktion ohne Stückpreis – für eine Preisreihe wertlos.
LIDL_OHNE_PREIS = {
    "id": "abc",
    "priceBox": {"largePartNumeric": None},
    "title": "auf alle Baby, Kids & Toys Eigenmarke-Artikel",
}


# ── marktguru-Parser ─────────────────────────────────────────────────────


def test_mg_parst_marke_und_produkt_zum_titel():
    """Der Produktname entsteht erst aus Marke + Produkt."""
    offer = parse_mg(MG_OFFER)

    assert offer.title == "Kerrygold Original Irische Butter"
    assert offer.brand == "Kerrygold"
    assert offer.price == 1.79
    assert offer.retailer == "Lidl"
    assert offer.retailer_key == "lidl"
    assert offer.source == "marktguru"


def test_mg_uebernimmt_gueltigkeit_und_grundpreis():
    offer = parse_mg(MG_OFFER)

    assert offer.valid_from.startswith("2026-07-29")
    assert offer.valid_to.startswith("2026-08-01")
    assert "7.16 €/kg" in offer.unit
    assert "250/200 g" in offer.unit


def test_mg_images_als_dict_wirft_nicht():
    """images ist ein dict, kein Array – ein blindes [0] warf hier KeyError."""
    assert parse_mg(MG_OFFER).image == ""


def test_mg_ohne_preis_wird_verworfen():
    assert parse_mg({**MG_OFFER, "price": None}) is None
    assert parse_mg({**MG_OFFER, "price": 0}) is None


def test_mg_unbekannter_haendler_behaelt_klartext():
    offer = parse_mg({**MG_OFFER, "advertisers": [{"name": "Hofladen Meier"}]})

    assert offer.retailer == "Hofladen Meier"
    assert offer.retailer_key == ""


@pytest.mark.parametrize("kaputt", [
    {"advertisers": {}},
    {"advertisers": None},
    {"validityDates": {}},
    {"validityDates": []},
    {"brand": None},
    {"product": None},
])
def test_mg_haelt_geaenderte_feldformen_aus(kaputt):
    offer = parse_mg({**MG_OFFER, **kaputt})

    assert offer is not None
    assert offer.price == 1.79


# ── Lidl-Parser ──────────────────────────────────────────────────────────


def test_lidl_preis_und_streichpreis():
    offer = parse_lidl(LIDL_OFFER)

    assert offer.price == 0.99
    assert offer.old_price == 1.99
    assert offer.retailer_key == "lidl"
    assert offer.savings_pct == pytest.approx(0.502, abs=0.01)


def test_lidl_ohne_strikethrough_kein_altpreis():
    raw = {**LIDL_OFFER,
           "priceBox": {**LIDL_OFFER["priceBox"], "strikethrough": False}}

    assert parse_lidl(raw).old_price is None


def test_lidl_rabattaktion_ohne_preis_wird_verworfen():
    assert parse_lidl(LIDL_OHNE_PREIS) is None


def test_lidl_packaging_wird_zur_mengenangabe():
    offer = parse_lidl(LIDL_OFFER)

    assert "Je 150/110 g" in offer.unit
    assert "Normalpreis: 1.11" in offer.unit


# ── Gültigkeitsfenster ───────────────────────────────────────────────────


def test_zukuenftiges_angebot_ist_nicht_aktiv():
    """marktguru liefert auch die Angebote der nächsten Woche.

    Die dürfen weder als aktueller Preis gemeldet noch in die Preisreihe
    geschrieben werden.
    """
    offer = Offer(valid_from="2099-01-01T00:00:00Z", valid_to="2099-01-07T00:00:00Z")

    assert not offer.is_active()


def test_abgelaufenes_angebot_ist_nicht_aktiv():
    offer = Offer(valid_from="2020-01-01T00:00:00Z", valid_to="2020-01-07T00:00:00Z")

    assert not offer.is_active()


def test_ohne_datum_gilt_als_aktiv():
    assert Offer().is_active()


# ── Registry: Ausfallverhalten ───────────────────────────────────────────


class _Quelle:
    def __init__(self, name, offers=None, exc=None):
        self.name = name
        self._offers = offers or []
        self._exc = exc

    async def search(self, session, query, **kw):
        if self._exc:
            raise self._exc
        return self._offers


@pytest.mark.asyncio
async def test_ausgefallener_provider_kippt_die_suche_nicht(monkeypatch):
    gut = _Quelle("gut", [Offer(title="Butter", price=1.0, retailer_key="lidl")])
    kaputt = _Quelle("kaputt", exc=RuntimeError("API tot"))
    monkeypatch.setattr(registry, "available_providers", lambda names=None: [kaputt, gut])

    offers = await registry.search_all(None, "butter")

    assert len(offers) == 1
    assert offers[0].title == "Butter"


@pytest.mark.asyncio
async def test_unbekannter_providername_wird_uebersprungen():
    instances = registry.available_providers(["marktguru", "gibtsnicht"])

    assert [p.name for p in instances] == ["marktguru"]


@pytest.mark.asyncio
async def test_ergebnis_ist_nach_preis_sortiert(monkeypatch):
    quelle = _Quelle("q", [
        Offer(title="teuer", price=3.0, retailer_key="rewe"),
        Offer(title="billig", price=1.0, retailer_key="lidl"),
        Offer(title="mittel", price=2.0, retailer_key="penny"),
    ])
    monkeypatch.setattr(registry, "available_providers", lambda names=None: [quelle])

    offers = await registry.search_all(None, "x")

    assert [o.title for o in offers] == ["billig", "mittel", "teuer"]


@pytest.mark.asyncio
async def test_filter_auf_ketten_im_umkreis(monkeypatch):
    quelle = _Quelle("q", [
        Offer(title="a", price=1.0, retailer_key="lidl"),
        Offer(title="b", price=2.0, retailer_key="kaufland"),
        Offer(title="c", price=3.0, retailer_key=""),  # unbekannt: bleibt drin
    ])
    monkeypatch.setattr(registry, "available_providers", lambda names=None: [quelle])

    offers = await registry.search_all(None, "x", retailer_keys={"lidl"})

    assert [o.title for o in offers] == ["a", "c"]


@pytest.mark.asyncio
async def test_active_only_filtert_zukuenftige(monkeypatch):
    quelle = _Quelle("q", [
        Offer(title="jetzt", price=1.0),
        Offer(title="naechste woche", price=0.5,
              valid_from="2099-01-01T00:00:00Z", valid_to="2099-01-07T00:00:00Z"),
    ])
    monkeypatch.setattr(registry, "available_providers", lambda names=None: [quelle])

    offers = await registry.search_all(None, "x", active_only=True)

    assert [o.title for o in offers] == ["jetzt"]


def test_dedupe_bevorzugt_den_direkten_haendler():
    """Lidl-Angebote kommen doppelt – direkt und über marktguru."""
    offers = [
        Offer(title="Lay's Chips", price=0.99, retailer_key="lidl", source="marktguru"),
        Offer(title="Lay's Chips", price=0.99, retailer_key="lidl", source="lidl",
              old_price=1.99),
    ]

    result = registry.dedupe(offers)

    assert len(result) == 1
    assert result[0].source == "lidl"
    assert result[0].old_price == 1.99


def test_dedupe_behaelt_unterschiedliche_preise():
    """Verschiedene Preise sind verschiedene Aussagen, keine Dublette."""
    offers = [
        Offer(title="Lay's Chips", price=0.99, retailer_key="lidl", source="lidl"),
        Offer(title="Lay's Chips", price=1.11, retailer_key="lidl", source="marktguru"),
    ]

    assert len(registry.dedupe(offers)) == 2


# ── Fehlende Zugangsdaten ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_marktguru_ohne_schluessel_liefert_leer(monkeypatch):
    """Wie bei fehlenden UPS-Credentials: still degradieren, nie werfen."""
    from piclaw.shopping.providers import marktguru as mg

    mg.reset_credentials()

    async def _keine_keys(session):
        return None

    monkeypatch.setattr(mg, "_fetch_credentials", _keine_keys)

    assert await MarktguruProvider().search(None, "butter", zip_code="20095") == []


@pytest.mark.asyncio
async def test_marktguru_ohne_plz_liefert_leer():
    assert await MarktguruProvider().search(None, "butter", zip_code="") == []


@pytest.mark.asyncio
async def test_lidl_ohne_koordinaten_liefert_leer():
    """Ohne Filiale keine Angebote – marktguru deckt Lidl mit ab."""
    assert await LidlProvider().search(None, "chips", zip_code="20095") == []

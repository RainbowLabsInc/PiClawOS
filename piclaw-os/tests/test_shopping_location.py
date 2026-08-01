"""
Reduktion der Ladenliste.

Ein rein distanzsortiertes Limit ist hier falsch: 5 km um den Hamburger
Rathausmarkt liefern 130 Bäckereien. Die würden einen Baumarkt am Rand des
Radius verdrängen – und damit dessen Angebote unsichtbar machen, obwohl er
die einzige Filiale seiner Kette im Umkreis ist. Deshalb wird pro Kette
gekappt statt global.
"""

import pytest

from piclaw.shopping import location
from piclaw.tools.geo import Shop


def shop(brand, distance, name="", shop_type="supermarket"):
    return Shop(
        osm_id=f"node/{abs(hash((brand, distance))) % 10**6}",
        name=name or brand,
        brand=brand,
        shop_type=shop_type,
        lat=53.55,
        lon=9.99,
        distance_km=distance,
    )


def test_weit_entfernte_kette_ueberlebt_viele_nahe_laeden():
    """Der eigentliche Grund für die Reduktion."""
    baeckereien = [shop("", 0.1 + i / 100, name=f"Bäckerei {i}", shop_type="bakery")
                   for i in range(200)]
    baumarkt = shop("OBI", 9.2, shop_type="doityourself")

    behalten = location._reduce(baeckereien + [baumarkt])

    assert baumarkt in behalten
    assert len(behalten) < len(baeckereien)


def test_pro_kette_wird_gekappt():
    filialen = [shop("REWE", float(i)) for i in range(10)]

    behalten = location._reduce(filialen)

    assert len(behalten) == location._PRO_KETTE


def test_naechste_filiale_bleibt_erhalten():
    """Die Reihenfolge kommt sortiert an und muss erhalten bleiben."""
    filialen = [shop("REWE", 0.5), shop("REWE", 2.0), shop("REWE", 3.0),
                shop("REWE", 9.0)]

    behalten = location._reduce(filialen)

    assert [s.distance_km for s in behalten] == [0.5, 2.0, 3.0]


def test_verschiedene_ketten_zaehlen_getrennt():
    laeden = ([shop("REWE", float(i)) for i in range(5)]
              + [shop("Lidl", float(i)) for i in range(5)])

    behalten = location._reduce(laeden)

    marken = {s.brand for s in behalten}
    assert marken == {"REWE", "Lidl"}
    assert len(behalten) == 2 * location._PRO_KETTE


def test_laeden_ohne_kette_haben_eigenes_budget():
    namenlose = [shop("", 0.1 + i / 100, name=f"Hofladen {i}") for i in range(200)]

    behalten = location._reduce(namenlose)

    assert len(behalten) == location._OHNE_KETTE


def test_kette_erkannt_auch_ueber_den_namen():
    """OSM setzt die Marke mal in `brand`, mal nur in `name`."""
    laeden = [Shop(osm_id=f"node/{i}", name="OBI Baumarkt", brand="",
                   shop_type="doityourself", lat=53.5, lon=9.9,
                   distance_km=float(i)) for i in range(6)]

    behalten = location._reduce(laeden)

    assert len(behalten) == location._PRO_KETTE


def test_leere_liste():
    assert location._reduce([]) == []


@pytest.mark.parametrize("marke", ["OBI", "toom", "HORNBACH", "Fressnapf",
                                   "DAS FUTTERHAUS", "TEDi"])
def test_neue_ketten_werden_als_kette_behandelt(marke):
    """Sonst landen sie im knappen Budget für Läden ohne Zuordnung."""
    laeden = [shop(marke, float(i)) for i in range(10)]

    assert len(location._reduce(laeden)) == location._PRO_KETTE

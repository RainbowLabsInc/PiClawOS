"""
Live-Checks der Einkaufslisten-Datenquellen. MACHT ECHTE NETZWERK-CALLS.

Läuft NIE in der normalen Suite (`--ignore=tests/debug`). Gedacht als
Diagnose, wenn Angebote plötzlich leer bleiben: hier zeigt sich, ob die
Quelle tot ist oder es schlicht kein Angebot gibt.

    .venv/Scripts/python -m pytest tests/debug/test_debug_shopping.py -s

Nutzt bewusst eine öffentliche Testadresse (Hamburger Rathaus), keine
privaten Daten – das Repo ist öffentlich.
"""

import aiohttp
import pytest

from piclaw.shopping.providers import search_all
from piclaw.shopping.providers import lidl as lidl_mod
from piclaw.shopping.providers import marktguru as mg_mod
from piclaw.tools import geo

RATHAUS = (53.5503, 9.9926)
PLZ = "20095"


@pytest.mark.asyncio
async def test_nominatim_loest_hausnummer_auf():
    async with aiohttp.ClientSession() as s:
        point = await geo.address_to_coords(s, "Rathausmarkt", "1", PLZ, "Hamburg")

    print(f"\n  {point}")
    assert point is not None
    assert point.is_exact, (
        "Nominatim liefert die Hausnummer nicht mehr – Genauigkeitslogik prüfen"
    )


@pytest.mark.asyncio
async def test_overpass_findet_maerkte():
    async with aiohttp.ClientSession() as s:
        shops = await geo.find_shops(s, *RATHAUS, radius_km=2)

    typen: dict[str, int] = {}
    for shop in shops:
        typen[shop.shop_type] = typen.get(shop.shop_type, 0) + 1
    print(f"\n  {len(shops)} Läden, nach Typ: {typen}")
    for shop in shops[:5]:
        print(f"    {shop.distance_km:5.2f} km  {shop.label}  [{shop.shop_type}]")

    # Overpass antwortet unter Last mit 504 – dann ist die leere Liste
    # korrektes Verhalten, kein Testfehler.
    if not shops:
        pytest.skip("Overpass gerade nicht erreichbar (504/timeout)")
    assert any(s.shop_type == "supermarket" for s in shops)


@pytest.mark.asyncio
async def test_marktguru_schluessel_und_suche():
    mg_mod.reset_credentials()
    async with aiohttp.ClientSession() as s:
        creds = await mg_mod._get_credentials(s)
        assert creds, "Schlüssel nicht mehr im Config-Block – Seitenstruktur geändert"
        print(f"\n  Host {creds['host']}, Schlüssel gefunden")

        offers = await mg_mod.MarktguruProvider().search(s, "butter", zip_code=PLZ)

    print(f"  {len(offers)} Angebote")
    for o in offers[:5]:
        print(f"    {o.price:6.2f} €  {o.retailer:<16} {o.title}")
    assert offers, "marktguru liefert nichts für 'butter' – Antwortformat prüfen"


@pytest.mark.asyncio
async def test_lidl_filiale_und_angebote():
    lidl_mod.reset_cache()
    async with aiohttp.ClientSession() as s:
        store = await lidl_mod._nearest_store(s, *RATHAUS, PLZ)
        assert store, "Lidl-Filialsuche liefert nichts"
        print(f"\n  Filiale {store.get('storeKey')} – {store.get('name')}")

        offers = await lidl_mod._store_offers(s, str(store["storeKey"]))

    print(f"  {len(offers)} Angebote")
    for o in offers[:5]:
        alt = f" (statt {o.old_price:.2f})" if o.old_price else ""
        print(f"    {o.price:6.2f} €{alt:>16}  {o.title}")
    assert offers, "Lidl liefert keine Angebote – Routen prüfen"


@pytest.mark.asyncio
async def test_zusammenspiel_beider_quellen():
    async with aiohttp.ClientSession() as s:
        offers = await search_all(s, "butter", zip_code=PLZ,
                                  lat=RATHAUS[0], lon=RATHAUS[1], limit=15)

    quellen = {o.source for o in offers}
    aktiv = [o for o in offers if o.is_active()]
    print(f"\n  {len(offers)} Angebote aus {quellen}, davon {len(aktiv)} heute gültig")
    for o in offers[:8]:
        flag = "" if o.is_active() else "  [noch nicht gültig]"
        print(f"    {o.price:6.2f} €  {o.retailer:<16} {o.title[:44]}{flag}")
    assert offers


@pytest.mark.asyncio
async def test_tippfehler_liefert_nichts():
    """Die Grundlage des Testen-Knopfs im Dashboard."""
    async with aiohttp.ClientSession() as s:
        offers = await search_all(s, "buttre", zip_code=PLZ,
                                  lat=RATHAUS[0], lon=RATHAUS[1])

    print(f"\n  'buttre' -> {len(offers)} Treffer")
    assert not offers

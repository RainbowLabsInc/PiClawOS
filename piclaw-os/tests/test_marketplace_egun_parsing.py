"""Parsing-Tests für eGun-Trefferlisten.

Hintergrund: eGun hat ~09/2026 auf ein neues Layout umgestellt (UTF-8,
/search statt list_items.php, Links /item/ID/slug statt item.php?id=ID,
Restzeit als "15 Std, 7 Min"). Der alte Parser fand danach 0 Inserate –
still und ohne Fehler. Die klassische Ansicht bleibt bis 15.11.2026
erreichbar, deshalb halten diese Tests beide Varianten fest.
"""

import pytest

from piclaw.tools import marketplace
from piclaw.tools.marketplace import _decode_egun, _parse_egun, _search_egun


# Gekürzte, aber strukturgetreue Ausschnitte einer echten Seite (09/2026)
HTML_NEW = """<!DOCTYPE html>
<html lang="de"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head>
<body><ul class="auction-list auction-list--shelf">
<li data-auction-id="20424449"><div class="list-item list-item--featured">
    <a class="list-item__link" href="https://www.egun.de/item/20424449/selbstladebuechse-messerschmitt-ar15-kal-223rem-16-75-bronze-neuware">
        <span class="list-item__thumb">
            <img src="/thumb/fit-256x192/4.20424449.593359359.jpg" alt="Selbstladebüchse Messerschmitt AR15 Kal. .223Rem. 16,75&quot; bronze -NEUWARE-" loading="lazy">
        </span>
        <span class="list-item__body">
            <span class="list-item__title">
                <span class="list-item__title-text">
                     Selbstladebüchse Messerschmitt AR15 Kal. .223Rem. 16,75" bronze -NEUWARE-                </span>
                <span class="list-item__ref">
                    <span class="list-item__number">Nr. 20424449</span> <span class="list-item__seller">Jochen04</span></span>
                <span class="list-item__tags"><span class="list-item__legal list-item__legal--inline"><span class="badge badge--legal" title="EWB erforderlich">EWB</span></span><span class="badge badge--condition">Neuware</span>
                    <span class="badge badge--business">gewerblich</span></span>
            </span>
            <span class="list-item__legal list-item__legal--slot"><span class="badge badge--legal" title="EWB erforderlich">EWB</span></span>
            <span class="list-item__price-line">
                <span class="list-item__price-label list-item__price-label--start">Startpreis</span>
                <span class="list-item__price">1.099,00 €</span>
                <span class="list-item__buynow">Sofortkauf 1.199,00 €</span>
                <span class="list-item__price-sub list-item__bidstate list-item__bidstate--none">0 Gebote</span>
            </span>
            <span class="list-item__meta">
                <span class="list-item__bids list-item__bidstate list-item__bidstate--none">0 Gebote</span>
                <span class="list-item__ends" data-ends="1791139500">9 Tage, 0 Std</span>
            </span>
        </span>
    </a>
    <a rel="nofollow" class="list-item__watch list-item__watch--disabled" href="https://www.egun.de/watchlist/remember/20424449?redirect=/item/20282358/x" title="Merkliste (Anmeldung erforderlich)">☆</a>
</div>
</li>
<li data-auction-id="20483938"><div class="list-item list-item--featured">
    <a class="list-item__link" href="https://www.egun.de/item/20483938/walther-kkm-200-kaliber-22lr">
        <span class="list-item__body">
            <span class="list-item__title">
                <span class="list-item__title-text">
                    <span class="badge badge--new">neu</span>
                     Walther KKM 200 Kaliber .22lr                </span>
                <span class="list-item__ref">
                    <span class="list-item__number">Nr. 20483938</span> <span class="list-item__seller">Lachenmaier</span></span>
            </span>
            <span class="list-item__price-line">
                <span class="list-item__price-label list-item__price-label--bid">Aktuelles Gebot</span>
                <span class="list-item__price">526,00 €</span>
                <span class="list-item__price-sub list-item__bidstate list-item__bidstate--has">17 Gebote</span>
            </span>
            <span class="list-item__meta">
                <span class="list-item__ends" data-ends="1792259025">21 Tage, 23 Std</span>
            </span>
        </span>
    </a>
</div>
</li>
</ul></body></html>
"""

# Aus einer echten Suchseite (/search?query=Blaser, 09/2026): relative Links,
# "oder Preisvorschlag", Grundpreis und Stückzahl
HTML_SEARCH = """<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"></head><body>
<ul class="auction-list">
<li data-auction-id="19992648"><div class="list-item list-item--featured list-item--fett">
    <a class="list-item__link" href="/item/19992648/blaser-r8-austauschlauf-30-06sp-58cm-offene-visierung">
        <span class="list-item__thumb">
            <img src="/thumb/fit-256x192/3.19992648.596016232.jpg" alt="Blaser R8 Austauschlauf 30-06Sp 58cm offene Visierung" loading="lazy">
        </span>
        <span class="list-item__body">
            <span class="list-item__title">
                <span class="list-item__title-text">
                     Blaser R8 Austauschlauf 30-06Sp 58cm offene Visierung                </span>
                <span class="list-item__ref">
                    <span class="list-item__number">Nr. 19992648</span> <span class="list-item__seller">Waffen_Huber</span></span>
            </span>
            <span class="list-item__price-line">
                <span class="list-item__price-label list-item__price-label--buynow">Sofortkauf</span>
                <span class="list-item__price">950,00 €</span>
                <span class="list-item__haggle">oder Preisvorschlag</span>
            </span>
            <span class="list-item__meta">
                <span class="list-item__ends" data-ends="1790435009">20 Std, 12 Min</span>
            </span>
        </span>
    </a>
    <a rel="nofollow" class="list-item__watch list-item__watch--disabled" href="/watchlist/remember/19992648?redirect=/search?query%3DBlaser" title="Merkliste (Anmeldung erforderlich)">&#9734;</a>
</div>
</li>
<li data-auction-id="20482865"><div class="list-item">
    <a class="list-item__link" href="/item/20482865/blaser-r8-verschluss">
        <span class="list-item__body">
            <span class="list-item__title">
                <span class="list-item__title-text">
                     Blaser R8 Verschluss Verschlussführung rechts iControl                </span>
                <span class="list-item__tags"><span class="badge badge--condition">Neuware</span></span>
            </span>
            <span class="list-item__price-line">
                <span class="list-item__price-label list-item__price-label--buynow">Sofortkauf</span>
                <span class="list-item__price">415,00 €</span>
                <span class="list-item__base-price"><span class="visually-hidden">Grundpreis: </span>(415,00 € / Stück)</span>
                <span class="list-item__price-sub">noch 5 Stück</span>
            </span>
            <span class="list-item__meta">
                <span class="list-item__qty">noch 5 Stück</span>
                <span class="list-item__ends" data-ends="1790412045">13 Std, 50 Min</span>
            </span>
        </span>
    </a>
</div>
</li>
</ul></body></html>
"""

HTML_CLASSIC = (
    '<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1"></head>'
    '<table><tr>'
    '<td><a href="item.php?id=19310474"><img src="t.jpg"></a>'
    '<a href="item.php?id=19310474">ZF / Zielfernrohr Prinzess 4x B\xfcchse</a></td>'
    '<td>149,00 EUR</td><td>2</td><td>3 Tage</td>'
    '</tr></table></html>'
).encode("latin-1")


def test_parst_neues_layout():
    results = _parse_egun(_decode_egun(HTML_NEW.encode("utf-8")))

    assert len(results) == 2

    first = results[0]
    assert first["id"] == "20424449"
    assert first["platform"] == "egun"
    assert first["title"] == (
        'Selbstladebüchse Messerschmitt AR15 Kal. .223Rem. 16,75" bronze -NEUWARE-'
    )
    assert first["price"] == 1099.0
    assert first["price_text"] == "Startpreis 1.099,00 €"
    assert first["location"] == "endet in 9 Tage, 0 Std"
    assert first["url"] == (
        "https://www.egun.de/item/20424449/"
        "selbstladebuechse-messerschmitt-ar15-kal-223rem-16-75-bronze-neuware"
    )

    second = results[1]
    assert second["id"] == "20483938"
    # Verschachteltes "neu"-Badge im Titel-Span darf den Titel nicht abschneiden
    assert second["title"] == "Walther KKM 200 Kaliber .22lr"
    assert second["price"] == 526.0
    assert second["price_text"] == "Aktuelles Gebot 526,00 €"
    assert second["location"] == "endet in 21 Tage, 23 Std"


def test_parst_suchseite_mit_relativen_links():
    results = _parse_egun(_decode_egun(HTML_SEARCH.encode("utf-8")))

    assert [r["id"] for r in results] == ["19992648", "20482865"]

    first = results[0]
    assert first["title"] == "Blaser R8 Austauschlauf 30-06Sp 58cm offene Visierung"
    assert first["url"] == (
        "https://www.egun.de/item/19992648/blaser-r8-austauschlauf-30-06sp-58cm-offene-visierung"
    )
    assert first["price"] == 950.0
    assert first["price_text"] == "Sofortkauf 950,00 € oder Preisvorschlag"
    assert first["location"] == "endet in 20 Std, 12 Min"

    # Grundpreis-Span darf den Preis nicht überlagern
    second = results[1]
    assert second["title"] == "Blaser R8 Verschluss Verschlussführung rechts iControl"
    assert second["price"] == 415.0
    assert second["price_text"] == "Sofortkauf 415,00 €"
    assert second["location"] == "endet in 13 Std, 50 Min"


def test_neues_layout_utf8_wird_nicht_als_latin1_verstuemmelt():
    raw = HTML_NEW.encode("utf-8")
    # Auch ohne Content-Type-Header: charset aus <meta> lesen
    text = _decode_egun(raw)
    assert "Selbstladebüchse" in text
    assert "Ã¼" not in text


def test_parst_klassische_ansicht_weiterhin():
    results = _parse_egun(_decode_egun(HTML_CLASSIC))

    assert len(results) == 1
    assert results[0]["id"] == "19310474"
    assert results[0]["title"] == "ZF / Zielfernrohr Prinzess 4x Büchse"
    assert results[0]["price"] == 149.0
    assert results[0]["location"] == "3 Tage"
    assert results[0]["url"] == "https://www.egun.de/market/item.php?id=19310474"


def test_layoutwechsel_wird_als_fehler_geloggt(caplog):
    html = '<li data-auction-id="42"><div class="mystery"></div></li>'
    with caplog.at_level("ERROR", logger="piclaw.tools.marketplace"):
        assert _parse_egun(html) == []
    assert any("Layout-Änderung" in r.getMessage() for r in caplog.records)


class _FakeResp:
    def __init__(self, status, body, content_type):
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        for prefix, resp in self.pages.items():
            if url.startswith(prefix):
                return resp
        return _FakeResp(404, b"", "text/plain")


@pytest.mark.asyncio
async def test_suche_nutzt_neue_url_und_filtert_max_preis():
    session = _FakeSession({
        f"{marketplace.EGUN_BASE}/search?query=": _FakeResp(
            200, HTML_NEW.encode("utf-8"), "text/html; charset=UTF-8"
        ),
    })

    results = await _search_egun(session, "AR 15", max_price=600, max_results=10)

    # Neueste zuerst (Standard wäre "endet bald"), Preisfilter serverseitig
    assert session.urls[0] == (
        f"{marketplace.EGUN_BASE}/search?query=AR+15"
        "&wheremode=and&order=starts&asdes=desc&maxprice=600"
    )
    assert len(session.urls) == 1  # Treffer → kein Fallback auf klassische Ansicht
    assert [r["id"] for r in results] == ["20483938"]


@pytest.mark.asyncio
async def test_suche_faellt_auf_klassische_ansicht_zurueck():
    session = _FakeSession({
        f"{marketplace.EGUN_BASE}/market/list_items.php": _FakeResp(
            200, HTML_CLASSIC, "text/html"
        ),
    })

    results = await _search_egun(session, "zielfernrohr", max_price=200)

    assert len(session.urls) == 2
    assert "&maxpr=200" in session.urls[1]
    assert [r["id"] for r in results] == ["19310474"]


@pytest.mark.parametrize("raw, expected", [
    ("eGun Zielfernrohr 500 Euro", "Zielfernrohr"),
    ("bei egun Schmeisser AR15 unter 1500€", "Schmeisser AR15"),
    ("Walther KKM 200 max 800", "Walther KKM 200"),
    ("Zielfernrohr 1.200,00 €", "Zielfernrohr"),
    ("egun AR 15", "AR 15"),
])
def test_clean_query_entfernt_preisangaben(raw, expected):
    """Preis steckt schon in max_price – im Suchbegriff verhindert er bei der
    UND-Suche von eGun sämtliche Treffer ("Zielfernrohr 500")."""
    assert marketplace._clean_query(raw) == expected

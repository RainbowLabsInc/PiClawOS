"""Parsing-Tests für Kleinanzeigen-Trefferlisten.

Hintergrund: Kleinanzeigen hat ~09/2026 auf Utility-Klassen umgestellt
(aditem-* fiel weg). Die Suche lieferte danach HTTP 200, aber 0 Inserate –
still und ohne Fehler. Diese Tests halten beide Layout-Varianten fest.
"""

import pytest

from piclaw.tools.marketplace import _search_kleinanzeigen


# Gekürzte, aber strukturgetreue Ausschnitte einer echten Trefferliste (09/2026)
HTML_NEW = """
<div>
<article class="flex" data-adid="3510034305" data-href="/s-anzeige/x">
  <div class="relative z-raised basis-[200px]">
    <script type="application/ld+json">{"title":"Feststellknopf"}</script>
    <a class="text-secondary" href="/s-anzeige/feststellknopf-makita/3510034305-84-794">
      <div data-image-container><img src="https://img.kleinanzeigen.de/a.jpg"></div>
    </a>
  </div>
  <div class="z-raised flex grow">
    <div class="mb-xsmall flex items-start">
      <div class="flex items-center text-onSurfaceNonessential">
        <svg viewbox="0 0 24 24" data-title="locationOutline" class="shrink-0"><path d="M1 2"></path></svg>
        <span>22850 Norderstedt</span><span class="ml-xsmall">(33 km)</span>
      </div>
      <div class="flex items-center text-onSurfaceNonessential">
        <svg viewbox="0 0 24 24" data-title="clockOutline"><path d="M3 4"></path></svg>
        <span>Heute, 02:56</span>
      </div>
    </div>
    <div class="flex flex-col">
      <h3 class="mb-xsmall line-clamp-2 text-title3 font-strong hover:underline">
        <a class="text-secondary !text-onSurface" href="/s-anzeige/feststellknopf-makita/3510034305-84-794">Feststellknopf Makita DML809</a>
      </h3>
      <p class="mb-xsmall text-bodyRegular text-onSurfaceSubdued">Original Makita Ersatzteil ...</p>
      <div class="flex"><p class="my-xsmall text-title3 font-strong text-secondary">1.290 &euro; VB</p></div>
    </div>
  </div>
</article>
<article class="flex" data-adid="3510076360">
  <div class="z-raised flex grow">
    <div class="mb-xsmall flex items-start">
      <div class="flex items-center text-onSurfaceNonessential">
        <svg viewbox="0 0 24 24" data-title="locationOutline"><path d="M1 2"></path></svg>
        <span>85077 Manching</span>
      </div>
    </div>
    <div class="flex flex-col">
      <h3 class="mb-xsmall line-clamp-2 text-title3 font-strong hover:underline">
        <span class="cursor-pointer" data-url="/s-anzeige/zu-verschenken/3510076360-192-7612">Zu verschenken</span>
      </h3>
      <p class="mb-xsmall text-bodyRegular text-onSurfaceSubdued">Abholung vor 9:30 Uhr</p>
      <div><p class="flex"></p></div>
    </div>
  </div>
</article>
</div>
"""

HTML_OLD = """
<article class="aditem" data-adid="1234567890">
  <div class="aditem-main">
    <div class="text-module-begin">
      <a class="ellipsis" href="/s-anzeige/alt/1234567890">Altes Layout Inserat</a>
    </div>
    <p class="aditem-main--middle--price">80 &euro; VB</p>
    <span class="aditem-main--top--left">21224 Rosengarten</span>
  </div>
</article>
"""


async def _search(monkeypatch, html):
    async def fake_fetch(url, label="web"):
        return html

    monkeypatch.setattr("piclaw.tools.marketplace._fetch_html", fake_fetch)
    return await _search_kleinanzeigen(None, "Makita", max_results=10)


@pytest.mark.asyncio
async def test_parst_neues_layout(monkeypatch):
    results = await _search(monkeypatch, HTML_NEW)

    assert len(results) == 2

    first = results[0]
    assert first["id"] == "3510034305"
    assert first["title"] == "Feststellknopf Makita DML809"
    assert first["price"] == 1290.0
    assert "VB" in first["price_text"]
    assert first["location"] == "22850 Norderstedt"
    assert first["url"] == (
        "https://www.kleinanzeigen.de/s-anzeige/feststellknopf-makita/3510034305-84-794"
    )

    # Variante ohne <a>: Titel steckt in <span data-url>, kein Preis vorhanden
    second = results[1]
    assert second["title"] == "Zu verschenken"
    assert second["price"] is None
    assert second["price_text"] == ""
    assert second["location"] == "85077 Manching"
    assert second["url"].endswith("/s-anzeige/zu-verschenken/3510076360-192-7612")


@pytest.mark.asyncio
async def test_parst_altes_layout_weiterhin(monkeypatch):
    results = await _search(monkeypatch, HTML_OLD)

    assert len(results) == 1
    assert results[0]["title"] == "Altes Layout Inserat"
    assert results[0]["price"] == 80.0
    assert results[0]["location"] == "21224 Rosengarten"


@pytest.mark.asyncio
async def test_layoutwechsel_wird_als_fehler_geloggt(monkeypatch, caplog):
    """Artikel vorhanden, aber nicht parsebar → lauter Fehler statt stillem 0."""
    html = '<article data-adid="42"><div class="mystery"></div></article>'

    with caplog.at_level("ERROR", logger="piclaw.tools.marketplace"):
        results = await _search(monkeypatch, html)

    assert results == []
    assert any("Layout-Änderung" in r.getMessage() for r in caplog.records)

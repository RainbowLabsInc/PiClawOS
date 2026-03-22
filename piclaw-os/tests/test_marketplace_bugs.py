import asyncio
import pytest
from piclaw.tools.marketplace import (
    marketplace_search,
    _parse_price,
    format_results,
    format_results_telegram,
)

def test_parse_price():
    assert _parse_price("149 €") == 149.0
    assert _parse_price("1.299,00 €") == 1299.0
    assert _parse_price("VB 80 €") == 80.0
    assert _parse_price("Geschenkt") is None

@pytest.mark.asyncio
async def test_duplicate_results(tmp_path, monkeypatch):
    # Mock SEEN_FILE
    seen_file = tmp_path / "seen.json"
    monkeypatch.setattr("piclaw.tools.marketplace.SEEN_FILE", seen_file)

    # Mock searches to return same item twice
    async def mock_search(*args, **kwargs):
        return [{"id": "123", "platform": "test", "title": "Item 1", "price": 10.0, "url": "http://test"}]

    monkeypatch.setattr("piclaw.tools.marketplace._search_kleinanzeigen", mock_search)
    monkeypatch.setattr("piclaw.tools.marketplace._search_ebay", mock_search)
    monkeypatch.setattr("piclaw.tools.marketplace._search_web", lambda *a: [])

    # Run search on two platforms
    results = await marketplace_search("test", platforms=["kleinanzeigen", "ebay"])

    # It should only have ONE "new" result if discovery set is updated correctly
    assert results["new_count"] == 1
    assert len(results["new"]) == 1

def test_markdown_escaping():
    results = {
        "query": "test",
        "new": [{"platform": "web", "title": "Item [with] brackets", "url": "http://test", "price_text": "10 €"}]
    }
    output = format_results(results)
    # Check if title is escaped correctly
    assert "Item \\[with\\] brackets" in output

def test_format_results_telegram_empty():
    results = {"query": "test query", "new": []}
    output = format_results_telegram(results)
    assert output == "🔍 Keine neuen Inserate für *test query*."

def test_format_results_telegram_no_max_price():
    results = {
        "query": "test query",
        "new": [
            {
                "platform": "kleinanzeigen",
                "title": "Test Item 1 [Brackets]",
                "url": "http://test.com/1",
                "price_text": "50 €",
                "location": "Berlin",
            },
            {
                "platform": "ebay",
                "title": "Test Item 2",
                "url": "http://test.com/2",
                "price_text": "100 €",
            },
            {
                "platform": "web",
                "title": "Test Item 3",
                "url": "http://test.com/3",
                "location": "Hamburg",
            },
            {
                "platform": "unknown",
                "title": "Test Item 4",
                "url": "http://test.com/4",
            },
        ],
    }
    output = format_results_telegram(results)

    assert "🛒 *4 neue Inserate* für _test query_" in output
    assert "(max." not in output
    assert "📌 [Test Item 1 \\[Brackets\\]](http://test.com/1) · 50 € · Berlin" in output
    assert "🛍️ [Test Item 2](http://test.com/2) · 100 €" in output
    assert "🌐 [Test Item 3](http://test.com/3) · Hamburg" in output
    assert "🔗 [Test Item 4](http://test.com/4)" in output

def test_format_results_telegram_with_max_price():
    results = {
        "query": "test query",
        "max_price": 200.0,
        "new": [
            {
                "platform": "ebay",
                "title": "Test Item",
                "url": "http://test.com",
            }
        ],
    }
    output = format_results_telegram(results)

    # Needs to match exactly the generated line
    assert "🛒 *1 neue Inserate* für _test query_\n(max. 200 €)" in output

def test_format_results_telegram_truncation():
    # Create 15 dummy items
    items = []
    for i in range(15):
        items.append({
            "platform": "ebay",
            "title": f"Item {i}",
            "url": f"http://test.com/{i}",
        })

    results = {"query": "test query", "new": items}
    output = format_results_telegram(results)

    # Count how many items are displayed
    item_count = output.count("🛍️")
    assert item_count == 10

    # Check truncation message
    assert "\n_... und 5 weitere_" in output

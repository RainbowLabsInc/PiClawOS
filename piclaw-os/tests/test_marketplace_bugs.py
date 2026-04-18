import asyncio
import pytest
from piclaw.tools.marketplace import marketplace_search, _parse_price, format_results

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


def test_format_results_empty():
    results = {"query": "Raspberry Pi", "new": []}
    assert format_results(results) == "__NO_NEW_RESULTS__"

    results_no_new = {"query": "Laptop"}
    assert format_results(results_no_new) == "__NO_NEW_RESULTS__"


def test_format_results_header():
    results = {
        "query": "Raspberry Pi",
        "location": "Berlin",
        "max_price": 50.0,
        "new": [{"platform": "ebay", "title": "Pi", "price_text": "40 €"}]
    }
    output = format_results(results)
    assert "🛒 1 Inserate für 'Raspberry Pi' in Berlin (max. 50 €)" in output
    assert "──────────────────────────────────────────────────" in output


def test_format_results_platforms():
    results = {
        "query": "Test",
        "new": [
            {"platform": "kleinanzeigen", "title": "T1"},
            {"platform": "ebay", "title": "T2"},
            {"platform": "web", "title": "T3"},
            {"platform": "unknown_plat", "title": "T4"},
        ]
    }
    output = format_results(results)
    assert "1. 📌 [Kleinanzeigen] T1" in output
    assert "2. 🛍️ [eBay] T2" in output
    assert "3. 🌐 [Web] T3" in output
    assert "4. 🔗 [unknown_plat] T4" in output


def test_format_results_item_details():
    results = {
        "query": "Test",
        "new": [
            {
                "platform": "ebay",
                "title": "Full Item",
                "price_text": "10 €",
                "location": "Hamburg",
                "url": "http://example.com"
            },
            {
                "platform": "ebay",
                "title": "Minimal Item"
            }
        ]
    }
    output = format_results(results)
    assert "1. 🛍️ [eBay] Full Item" in output
    assert "💶 10 €" in output
    assert "📍 Hamburg" in output
    assert "🔗 http://example.com" in output

    assert "2. 🛍️ [eBay] Minimal Item" in output
    # Ensure no empty lines for missing details by checking the structure
    parts = output.split("2. 🛍️ [eBay] Minimal Item")
    assert "💶" not in parts[1]
    assert "📍" not in parts[1]
    assert "🔗" not in parts[1]


def test_format_results_truncation():
    results = {
        "query": "Many Items",
        "new": [{"platform": "ebay", "title": f"Item {i}"} for i in range(12)]
    }
    output = format_results(results)
    assert "10. 🛍️ [eBay] Item 9" in output
    assert "11." not in output
    assert "... und 2 weitere Inserate." in output


def test_city_leakage_in_query():
    from piclaw.agent import Agent
    from piclaw.config import PiClawConfig
    cfg = PiClawConfig()
    agent = Agent(cfg)

    # Test that city is extracted as location and removed from query
    res = agent._detect_marketplace_intent("Suche Gartentisch Rosengarten eBay")
    assert res is not None
    assert res["location"] == "Rosengarten"
    assert res["query"].lower() == "gartentisch"

    # Test with PLZ
    res2 = agent._detect_marketplace_intent("Suche Gartentisch 21224 eBay")
    assert res2 is not None
    assert res2["location"] == "21224"
    assert res2["query"].lower() == "gartentisch"

    # Multiple spaces and other words
    res3 = agent._detect_marketplace_intent("Suche dringend einen Gartentisch in Rosengarten max 50 eBay")
    assert res3 is not None
    assert res3["location"] == "Rosengarten"
    assert res3["max_price"] == 50.0
    assert "rosengarten" not in res3["query"].lower()
    assert "gartentisch" in res3["query"].lower()

def test_city_leakage_with_plz():
    from piclaw.agent import Agent
    from piclaw.config import PiClawConfig
    cfg = PiClawConfig()
    agent = Agent(cfg)

    res = agent._detect_marketplace_intent("Suche Gartentisch 21224 Rosengarten eBay")
    assert res is not None
    assert res["location"] == "21224"
    assert "rosengarten" not in res["query"].lower()
    assert "gartentisch" in res["query"].lower()

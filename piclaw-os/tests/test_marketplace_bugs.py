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
        return [
            {
                "id": "123",
                "platform": "test",
                "title": "Item 1",
                "price": 10.0,
                "url": "http://test",
            }
        ]

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
        "new": [
            {
                "platform": "web",
                "title": "Item [with] brackets",
                "url": "http://test",
                "price_text": "10 €",
            }
        ],
    }
    output = format_results(results)
    # Check if title is escaped correctly
    assert "Item \\[with\\] brackets" in output

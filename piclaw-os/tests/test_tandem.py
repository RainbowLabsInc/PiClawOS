"""Tests for piclaw.tools.tandem"""
import json
import pytest
from unittest.mock import patch
from piclaw.tools.tandem import browser_open, browser_snapshot, browser_click

@pytest.mark.asyncio
async def test_browser_open():
    mock_resp = {"tab": {"id": "tab-123"}}
    with patch("piclaw.tools.tandem._get_token", return_value="test-token"), \
         patch("piclaw.tools.tandem._call_api", return_value=mock_resp):
        result = await browser_open("https://example.com")
        assert "Opened https://example.com in tab tab-123" in result

@pytest.mark.asyncio
async def test_browser_snapshot():
    mock_resp = {"content": "page text"}
    with patch("piclaw.tools.tandem._get_token", return_value="test-token"), \
         patch("piclaw.tools.tandem._call_api", return_value=mock_resp):
        result = await browser_snapshot()
        data = json.loads(result)
        assert data["content"] == "page text"

@pytest.mark.asyncio
async def test_browser_click():
    with patch("piclaw.tools.tandem._get_token", return_value="test-token"), \
         patch("piclaw.tools.tandem._call_api", return_value={"ok": True}):
        result = await browser_click(ref="@e1")
        assert result == "Click successful."

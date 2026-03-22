"""Tests for piclaw.tools.tandem"""
import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from piclaw.tools.tandem import browser_open, browser_snapshot, browser_click, browser_type, browser_close, build_handlers

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

@pytest.mark.asyncio
async def test_browser_type():
    with patch("piclaw.tools.tandem._get_token", return_value="test-token"), \
         patch("piclaw.tools.tandem._call_api", return_value={"ok": True}):
        result = await browser_type(text="hello", ref="@e1")
        assert result == "Typing successful."

        result_no_ref = await browser_type(text="hello", clear=False)
        assert result_no_ref == "Typing successful."

@pytest.mark.asyncio
async def test_browser_close():
    with patch("piclaw.tools.tandem._get_token", return_value="test-token"), \
         patch("piclaw.tools.tandem._call_api", return_value={"ok": True}):
        result = await browser_close(tabId="tab-123")
        assert result == "Tab tab-123 closed."

@pytest.mark.asyncio
async def test_build_handlers():
    handlers = build_handlers()
    expected_keys = {
        "browser_open",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_close",
    }
    assert set(handlers.keys()) == expected_keys

    # Test that handlers correctly pass kwargs to underlying functions
    with patch("piclaw.tools.tandem.browser_open", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = "mocked_open"
        res = await handlers["browser_open"](url="http://test.com", focus=True)
        mock_open.assert_called_once_with(url="http://test.com", focus=True)
        assert res == "mocked_open"

    with patch("piclaw.tools.tandem.browser_snapshot", new_callable=AsyncMock) as mock_snapshot:
        mock_snapshot.return_value = "mocked_snapshot"
        res = await handlers["browser_snapshot"](compact=False)
        mock_snapshot.assert_called_once_with(compact=False)
        assert res == "mocked_snapshot"

    with patch("piclaw.tools.tandem.browser_click", new_callable=AsyncMock) as mock_click:
        mock_click.return_value = "mocked_click"
        res = await handlers["browser_click"](ref="@e1")
        mock_click.assert_called_once_with(ref="@e1")
        assert res == "mocked_click"

    with patch("piclaw.tools.tandem.browser_type", new_callable=AsyncMock) as mock_type:
        mock_type.return_value = "mocked_type"
        res = await handlers["browser_type"](text="test", ref="@e1")
        mock_type.assert_called_once_with(text="test", ref="@e1")
        assert res == "mocked_type"

    with patch("piclaw.tools.tandem.browser_close", new_callable=AsyncMock) as mock_close:
        mock_close.return_value = "mocked_close"
        res = await handlers["browser_close"](tabId="tab-123")
        mock_close.assert_called_once_with(tabId="tab-123")
        assert res == "mocked_close"

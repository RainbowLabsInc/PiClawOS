"""
PiClaw OS – Tandem Browser Bridge (v0.18)
Connects the agent to the Tandem Browser API (127.0.0.1:8765).
Allows complex web interactions, SPA analysis, and human-in-the-loop browsing.
"""

import asyncio
import json
import logging
import aiohttp
from pathlib import Path
from typing import Any, Optional

from piclaw.llm.base import ToolDefinition

logger = logging.getLogger("piclaw.tools.tandem")

TANDEM_API_URL = "http://127.0.0.1:8765"
TOKEN_FILE = Path.home() / ".tandem" / "api-token"

TOOL_DEFS = [
    ToolDefinition(
        name="browser_open",
        description="Opens a URL in a new Tandem Browser tab. Returns the tab ID.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to open."},
                "focus": {"type": "boolean", "description": "Whether to switch to the new tab immediately.", "default": False}
            },
            "required": ["url"]
        }
    ),
    ToolDefinition(
        name="browser_snapshot",
        description="Gets an accessibility-tree snapshot of the active tab. Useful for page analysis.",
        parameters={
            "type": "object",
            "properties": {
                "compact": {"type": "boolean", "description": "Whether to return a compact version.", "default": True}
            }
        }
    ),
    ToolDefinition(
        name="browser_click",
        description="Clicks an element in the browser by its ref (e.g. @e1) or text.",
        parameters={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Accessibility ref from snapshot (e.g. @e5)."},
                "text": {"type": "string", "description": "Text of the element to click if ref is not used."}
            }
        }
    ),
    ToolDefinition(
        name="browser_type",
        description="Types text into a form field in the browser.",
        parameters={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Accessibility ref from snapshot."},
                "text": {"type": "string", "description": "The text to type."},
                "clear": {"type": "boolean", "description": "Whether to clear the field first.", "default": True}
            },
            "required": ["text"]
        }
    ),
    ToolDefinition(
        name="browser_close",
        description="Closes a specific tab by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "tabId": {"type": "string", "description": "The ID of the tab to close."}
            },
            "required": ["tabId"]
        }
    )
]

def _get_token() -> str:
    """Reads the Tandem API token from the standard location."""
    if not TOKEN_FILE.exists():
        logger.warning("Tandem API token not found at %s", TOKEN_FILE)
        return ""
    return TOKEN_FILE.read_text().strip()

async def _call_api(method: str, path: str, data: dict = None) -> Any:
    """Helper to perform Tandem API calls."""
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{TANDEM_API_URL}{path}"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            fn = s.request
            async with fn(method, url, headers=headers, json=data) as r:
                if r.status == 401:
                    return "[ERROR] Tandem API Unauthorized. Check token."
                if r.status >= 400:
                    text = await r.text()
                    return f"[ERROR] Tandem API {r.status}: {text}"
                return await r.json()
    except Exception as e:
        return f"[ERROR] Could not connect to Tandem Browser: {e}"

async def browser_open(url: str, focus: bool = False) -> str:
    result = await _call_api("POST", "/tabs/open", {"url": url, "focus": focus, "source": "piclaw"})
    if isinstance(result, str) and result.startswith("[ERROR]"):
        return result
    tab_id = result.get("tab", {}).get("id", "unknown")
    return f"Opened {url} in tab {tab_id}"

async def browser_snapshot(compact: bool = True) -> str:
    path = f"/snapshot?compact=true" if compact else "/snapshot"
    result = await _call_api("GET", path)
    if isinstance(result, str) and result.startswith("[ERROR]"):
        return result
    return json.dumps(result, indent=2)

async def browser_click(ref: str = None, text: str = None) -> str:
    if ref:
        result = await _call_api("POST", "/snapshot/click", {"ref": ref})
    elif text:
        result = await _call_api("POST", "/find/click", {"by": "text", "value": text})
    else:
        return "[ERROR] Either ref or text is required."

    if isinstance(result, str) and result.startswith("[ERROR]"):
        return result
    return "Click successful."

async def browser_type(text: str, ref: str = None, clear: bool = True) -> str:
    if ref:
        result = await _call_api("POST", "/snapshot/fill", {"ref": ref, "value": text})
    else:
        # Fallback to find by placeholder or label if no ref
        result = await _call_api("POST", "/type", {"selector": "input", "text": text, "clear": clear})

    if isinstance(result, str) and result.startswith("[ERROR]"):
        return result
    return "Typing successful."

async def browser_close(tabId: str) -> str:
    result = await _call_api("POST", "/tabs/close", {"tabId": tabId})
    if isinstance(result, str) and result.startswith("[ERROR]"):
        return result
    return f"Tab {tabId} closed."

def build_handlers():
    return {
        "browser_open": lambda **kw: browser_open(**kw),
        "browser_snapshot": lambda **kw: browser_snapshot(**kw),
        "browser_click": lambda **kw: browser_click(**kw),
        "browser_type": lambda **kw: browser_type(**kw),
        "browser_close": lambda **kw: browser_close(**kw),
    }

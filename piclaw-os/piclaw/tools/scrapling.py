"""
PiClaw OS – Scrapling Integration
Adaptive web scraping framework with Cloudflare bypass (StealthyFetcher).
Allows the agent to autonomously fetch and extract web content.
"""

import logging
from typing import Dict, Any

from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.scrapling")

TOOL_DEFS = [
    ToolDefinition(
        name="scrape_url",
        description="Fetches a URL using Scrapling and returns the extracted markdown text. It automatically handles basic bot protections.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to scrape."},
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        name="scrape_css",
        description="Fetches a URL and extracts text/attributes from elements matching a specific CSS selector.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
                "selector": {"type": "string", "description": "CSS selector to extract (e.g. '.price', 'article h1')."},
                "attribute": {"type": "string", "description": "Optional attribute to extract instead of text (e.g. 'href', 'src')."}
            },
            "required": ["url", "selector"],
        },
    ),
    ToolDefinition(
        name="stealth_fetch",
        description="Fetches a URL using Scrapling's StealthyFetcher to bypass strict protections like Cloudflare. Returns the raw HTML or markdown.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The protected URL to fetch."},
                "as_markdown": {"type": "boolean", "description": "Return as Markdown instead of raw HTML (default: true).", "default": True}
            },
            "required": ["url"],
        },
    ),
]


async def scrape_url(url: str) -> str:
    """Fetches a URL using standard Scrapling Fetcher and returns text content."""
    try:
        from scrapling import AsyncFetcher
        fetcher = AsyncFetcher(auto_match=False)
        response = await fetcher.get(url)
        # Using markdown representation if available, or fallback to text
        try:
            return response.markdown[:4000] # Limit output size to prevent context overflow
        except AttributeError:
            return response.text[:4000]
    except ImportError:
        return "[ERROR] 'scrapling' library is not installed."
    except Exception as e:
        log.error("scrape_url error: %s", e)
        return f"[ERROR] Failed to scrape {url}: {e}"

async def scrape_css(url: str, selector: str, attribute: str = None) -> str:
    """Fetches a URL and extracts elements based on a CSS selector."""
    try:
        from scrapling import AsyncFetcher
        fetcher = AsyncFetcher(auto_match=False)
        response = await fetcher.get(url)

        elements = response.css(selector)
        if not elements:
            return f"No elements found matching '{selector}'."

        results = []
        for el in elements:
            if attribute:
                val = el.attrib.get(attribute)
                if val: results.append(val)
            else:
                results.append(el.text)

        # Limit to 50 results to avoid massive outputs
        return "\n".join(results[:50])

    except ImportError:
        return "[ERROR] 'scrapling' library is not installed."
    except Exception as e:
        log.error("scrape_css error: %s", e)
        return f"[ERROR] Failed to scrape css from {url}: {e}"

async def stealth_fetch(url: str, as_markdown: bool = True) -> str:
    """Fetches a URL using StealthyFetcher for heavy protections."""
    try:
        from scrapling import AsyncStealthyFetcher
        # Note: StealthyFetcher might be slower due to browser emulation
        fetcher = AsyncStealthyFetcher()
        response = await fetcher.get(url)

        if as_markdown:
            try:
                return response.markdown[:4000]
            except AttributeError:
                pass

        return response.text[:4000]
    except ImportError:
        return "[ERROR] 'scrapling' library is not installed."
    except Exception as e:
        log.error("stealth_fetch error: %s", e)
        return f"[ERROR] Stealth fetch failed for {url}: {e}"


def build_handlers() -> Dict[str, Any]:
    return {
        "scrape_url": scrape_url,
        "scrape_css": scrape_css,
        "stealth_fetch": stealth_fetch,
    }

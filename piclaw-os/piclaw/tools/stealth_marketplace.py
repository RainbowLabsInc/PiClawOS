"""
PiClaw OS – Stealth Marketplace Crawler Tool
A specialized, deep-search engine using Scrapling's StealthyFetcher.
Designed to bypass anti-bot protections and perform multi-page (pagination) scraping.
Used as a robust fallback when the fast, regex-based marketplace_search fails.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from urllib.parse import quote_plus, urljoin

from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.stealth_marketplace")

TOOL_DEFS = [
    ToolDefinition(
        name="marketplace_stealth_crawl",
        description=(
            "Performs a deep, stealthy, multi-page search on a specific marketplace. "
            "Use this ONLY if the standard 'marketplace_search' tool returns zero results (indicating a block) "
            "or if you need to comprehensively search multiple pages of results. "
            "It autonomously navigates 'Next Page' links for the specified number of rounds."
        ),
        parameters={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "The platform to scrape: 'kleinanzeigen' or 'ebay'.",
                },
                "query": {
                    "type": "string",
                    "description": "The search query (e.g., 'Raspberry Pi 5').",
                },
                "location": {
                    "type": "string",
                    "description": "Optional location or zip code (only for kleinanzeigen).",
                },
                "max_price": {
                    "type": "number",
                    "description": "Optional maximum price.",
                },
                "rounds": {
                    "type": "integer",
                    "description": "Number of pages to scrape in a row. Must be between 3 and 10.",
                    "default": 3,
                },
            },
            "required": ["platform", "query"],
        },
    ),
]


def _build_initial_url(platform: str, query: str, location: Optional[str] = None, max_price: Optional[float] = None) -> str:
    """Constructs the starting URL for the stealth crawl."""
    q = quote_plus(query)

    if platform == "kleinanzeigen":
        url = f"https://www.kleinanzeigen.de/s-{q}/k0"
        if location:
            loc = quote_plus(location)
            url = f"https://www.kleinanzeigen.de/s-{loc}/{q}/k0"
        if max_price:
            url += f"?maxPrice={int(max_price)}"
        return url

    elif platform == "ebay":
        url = f"https://www.ebay.de/sch/i.html?_nkw={q}&_sop=15"
        if max_price:
            url += f"&_udhi={int(max_price)}"
        return url

    raise ValueError(f"Unsupported stealth platform: {platform}")


def _run_stealth_crawl(platform: str, initial_url: str, rounds: int) -> dict:
    """Synchronous stealth crawling logic, offloaded to a separate thread."""
    from scrapling import StealthyFetcher

    fetcher = StealthyFetcher()
    results = []
    current_url = initial_url

    log.info("Starting stealth crawl on %s for %d rounds. Initial URL: %s", platform, rounds, current_url)

    for round_num in range(1, rounds + 1):
        if not current_url:
            log.debug("Round %d: No 'Next Page' URL found. Stopping early.", round_num)
            break

        log.debug("Round %d: Fetching %s", round_num, current_url)
        try:
            response = fetcher.get(current_url)
        except Exception as e:
            log.error("Stealth fetch failed in round %d: %s", round_num, e)
            break

        if response.status_code != 200:
            log.warning("HTTP %s returned in round %d.", response.status_code, round_num)
            break

        next_page_url = None

        if platform == "kleinanzeigen":
            # Extract listings using Scrapling's CSS selectors
            articles = response.css('article.aditem')
            for article in articles:
                title_el = article.css_first('a.ellipsis') or article.css_first('.text-module-begin a')
                price_el = article.css_first('p.aditem-main--middle--price')
                loc_el = article.css_first('.aditem-main--top--left')

                if not title_el:
                    continue

                title = title_el.text.strip()
                price_text = price_el.text.strip() if price_el else ""
                location_text = loc_el.text.strip() if loc_el else ""
                link = title_el.attrib.get('href', '')
                if link and not link.startswith('http'):
                    link = urljoin("https://www.kleinanzeigen.de", link)

                results.append({
                    "platform": "kleinanzeigen",
                    "title": title,
                    "price_text": price_text,
                    "location": location_text,
                    "url": link,
                    "round": round_num
                })

            # Find pagination "Next" button
            next_btn = response.css_first('.pagination-next')
            if next_btn:
                next_href = next_btn.attrib.get('href')
                if next_href:
                    next_page_url = urljoin("https://www.kleinanzeigen.de", next_href)

        elif platform == "ebay":
            # Extract listings
            items = response.css('li.s-item')
            for item in items:
                title_el = item.css_first('.s-item__title')
                price_el = item.css_first('.s-item__price')
                link_el = item.css_first('a.s-item__link')

                if not title_el or "Shop on eBay" in title_el.text:
                    continue

                title = title_el.text.strip()
                price_text = price_el.text.strip() if price_el else ""
                link = link_el.attrib.get('href', '') if link_el else ""
                # Clean tracking parameters from eBay links
                if link:
                    link = link.split('?')[0]

                results.append({
                    "platform": "ebay",
                    "title": title,
                    "price_text": price_text,
                    "location": "",
                    "url": link,
                    "round": round_num
                })

            # Find pagination "Next" button
            next_btn = response.css_first('a.pagination__next')
            if next_btn:
                next_page_url = next_btn.attrib.get('href')

        current_url = next_page_url

    log.info("Stealth crawl complete. Found %d items across %d rounds.", len(results), round_num)

    return {
        "status": "success",
        "rounds_completed": round_num if current_url else round_num - 1,
        "total_results": len(results),
        "results": results
    }


async def marketplace_stealth_crawl(
    platform: str,
    query: str,
    location: Optional[str] = None,
    max_price: Optional[float] = None,
    rounds: int = 3,
    **kwargs
) -> str:
    """Asynchronous wrapper for the stealth crawler."""
    # Enforce round limits
    rounds = max(3, min(int(rounds), 10))
    platform = platform.lower()

    if platform not in ["kleinanzeigen", "ebay"]:
        return "[ERROR] Platform must be 'kleinanzeigen' or 'ebay'."

    try:
        initial_url = _build_initial_url(platform, query, location, max_price)
    except Exception as e:
        return f"[ERROR] Failed to build URL: {e}"

    try:
        # Offload the blocking loop to a background thread
        res = await asyncio.to_thread(_run_stealth_crawl, platform, initial_url, rounds)

        # Format the output for the LLM
        if not res["results"]:
            return f"Stealth Crawl completed {res['rounds_completed']} rounds on {platform}, but found 0 results for '{query}'."

        lines = [
            f"🔍 Stealth Crawl Results for '{query}' on {platform}",
            f"   Rounds (Pages) Crawled: {res['rounds_completed']}/{rounds}",
            f"   Total Items Found: {res['total_results']}",
            "-" * 50
        ]

        # Limit to 20 results in the LLM context to prevent token overflow,
        # prioritizing a mix across rounds if possible, or just the top 20
        for i, item in enumerate(res["results"][:20], 1):
            price_str = f" - {item['price_text']}" if item.get('price_text') else ""
            loc_str = f" - {item['location']}" if item.get('location') else ""
            lines.append(f"{i}. [Page {item['round']}] {item['title']}{price_str}{loc_str}")
            lines.append(f"   URL: {item['url']}")

        if res['total_results'] > 20:
            lines.append(f"... and {res['total_results'] - 20} more items.")

        return "\n".join(lines)

    except ImportError:
        return "[ERROR] 'scrapling' library is not installed. Run 'pip install scrapling[fetchers] curl-cffi'."
    except Exception as e:
        log.error("marketplace_stealth_crawl error: %s", e)
        return f"[ERROR] Stealth crawl failed: {e}"


def build_handlers() -> Dict[str, Any]:
    return {
        "marketplace_stealth_crawl": marketplace_stealth_crawl,
    }

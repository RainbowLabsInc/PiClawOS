"""PiClaw OS – HTTP / Web browsing tool"""

import aiohttp
from html.parser import HTMLParser
from piclaw.llm.base import ToolDefinition

TOOL_DEFS = [
    ToolDefinition(
        name="http_fetch",
        description="Fetch a URL and return text content. Use for web browsing and API calls.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                "body": {"type": "string"},
                "headers": {"type": "object"},
            },
            "required": ["url"],
        },
    ),
]


class _StripHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts, self._skip = [], False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    def text(self):
        return " ".join(self._parts)[:8000]


async def http_fetch(url, method="GET", body=None, headers=None):
    hdrs = {"User-Agent": "PiClaw/0.2 (Raspberry Pi)"}
    if headers:
        hdrs.update(headers)
    try:
        async with aiohttp.ClientSession(
            headers=hdrs, timeout=aiohttp.ClientTimeout(total=20)
        ) as s:
            fn = s.post if method.upper() == "POST" else s.get
            async with fn(url, data=body) as r:
                ct = r.content_type or ""
                raw = await r.text(errors="replace")
                if "html" in ct:
                    p = _StripHTML()
                    p.feed(raw)
                    return f"[{r.status}] {url}\n\n{p.text()}"
                return f"[{r.status}] {url}\n\n{raw[:8000]}"
    except Exception as e:
        return f"[HTTP ERROR] {e}"


HANDLERS = {
    "http_fetch": lambda **kw: http_fetch(**kw),
}

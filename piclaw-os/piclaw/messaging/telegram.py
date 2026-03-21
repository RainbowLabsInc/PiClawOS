"""
PiClaw OS – Telegram Adapter
Long-polling bot. The original/primary messaging channel.

Setup:
  1. Create bot via @BotFather → get token
  2. Start a chat with the bot → get your chat_id
  3. Set in config.toml:
       [telegram]
       token   = "123456:ABC-..."
       chat_id = "123456789"
"""

import asyncio
import logging
import aiohttp

from piclaw.messaging.hub import MessagingAdapter, IncomingMessage, MessageHandler

log = logging.getLogger("piclaw.messaging.telegram")

API_BASE = "https://api.telegram.org/bot{token}"


class TelegramAdapter(MessagingAdapter):
    name = "telegram"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self._offset = 0
        self._stop = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None

    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    async def start(self, on_message: MessageHandler):
        self._stop.clear()
        self._session = aiohttp.ClientSession()
        log.info("Telegram adapter started.")
        await self.send("✅ PiClaw connected via Telegram.")
        await self._poll_loop(on_message)

    async def stop(self):
        self._stop.set()
        if self._session:
            await self._session.close()

    async def send(self, text: str, chat_id: str | None = None):
        cid = chat_id or self.chat_id
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        for chunk in _split(text, 4096):
            try:
                await self._session.post(
                    self._url("sendMessage"),
                    json={"chat_id": cid, "text": chunk, "parse_mode": "Markdown"},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
            except Exception as e:
                log.error("Telegram send error: %s", e)

    async def _poll_loop(self, on_message: MessageHandler):
        while not self._stop.is_set():
            try:
                async with self._session.get(
                    self._url("getUpdates"),
                    params={
                        "offset": self._offset,
                        "timeout": 20,
                        "allowed_updates": ["message"],
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.json()
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "").strip()
                        from_id = str(msg.get("chat", {}).get("id", ""))
                        if not text or from_id != self.chat_id:
                            continue
                        inc = IncomingMessage(
                            platform="telegram", sender_id=from_id, text=text, raw=msg
                        )
                        reply = await on_message(inc)
                        if reply:
                            await self.send(reply)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Telegram poll error: %s", e)
                await asyncio.sleep(5)


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] if text else [""]

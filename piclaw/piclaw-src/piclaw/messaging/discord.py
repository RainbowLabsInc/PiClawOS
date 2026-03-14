"""
PiClaw OS – Discord Adapter
Uses discord.py (py-cord fork). Bot listens in a configured channel.

Setup:
  1. Create application at https://discord.com/developers/applications
  2. Add a Bot, enable "Message Content Intent" under Bot → Privileged Gateway Intents
  3. Invite URL: OAuth2 → URL Generator → bot + Read/Send Messages
  4. Set in config.toml:
       [discord]
       token      = "Bot token here"
       channel_id = 1234567890123456789   # right-click channel → Copy ID
       # Optional: restrict to specific user IDs (empty = accept from all in channel)
       allowed_users = []

Notes:
  - Messages from OTHER bots are ignored automatically
  - If allowed_users is set, only those user IDs can command the agent
  - Discord has a 2000-char message limit; long replies are split
"""

import asyncio
import logging
from typing import Optional

from piclaw.messaging.hub import MessagingAdapter, IncomingMessage, MessageHandler

log = logging.getLogger("piclaw.messaging.discord")

DISCORD_LIMIT = 1900  # safe under 2000 char limit


class DiscordAdapter(MessagingAdapter):
    name = "discord"

    def __init__(self, token: str, channel_id: int,
                 allowed_users: list[int] | None = None):
        self.token         = token
        self.channel_id    = int(channel_id)
        self.allowed_users = [int(u) for u in (allowed_users or [])]
        self._client       = None
        self._channel      = None
        self._stop         = asyncio.Event()

    def is_configured(self) -> bool:
        return bool(self.token and self.channel_id)

    async def start(self, on_message: MessageHandler):
        try:
            import discord
        except ImportError:
            raise RuntimeError(
                "discord.py not installed. Run: pip install discord.py"
            )

        intents                    = discord.Intents.default()
        intents.message_content    = True
        self._client               = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            self._channel = self._client.get_channel(self.channel_id)
            if not self._channel:
                log.error("Discord: channel %s not found.", self.channel_id)
                return
            log.info("Discord bot ready: #%s", self._channel.name)
            await self.send("✅ PiClaw connected via Discord.")

        @self._client.event
        async def on_message(msg: discord.Message):
            # Ignore bot's own messages and other bots
            if msg.author.bot:
                return
            if msg.channel.id != self.channel_id:
                return
            if self.allowed_users and msg.author.id not in self.allowed_users:
                return
            text = msg.content.strip()
            if not text:
                return

            inc   = IncomingMessage(
                platform="discord",
                sender_id=str(msg.author.id),
                text=text,
                raw={"guild": str(msg.guild), "author": str(msg.author)},
            )
            # Show typing indicator while agent processes
            async with msg.channel.typing():
                reply = await on_message(inc)
            if reply:
                await self.send(reply)

        try:
            await self._client.start(self.token)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Discord error: %s", e, exc_info=True)

    async def stop(self):
        self._stop.set()
        if self._client:
            await self._client.close()

    async def send(self, text: str, chat_id: str | None = None):
        channel = self._channel
        if not channel:
            log.warning("Discord: channel not ready, message dropped.")
            return
        for chunk in _split_discord(text):
            try:
                await channel.send(chunk)
            except Exception as e:
                log.error("Discord send error: %s", e)

    async def send_alert(self, text: str, chat_id: str | None = None):
        """Use Discord embed for alerts."""
        channel = self._channel
        if not channel:
            return
        try:
            import discord
            embed = discord.Embed(
                description=text[:4096],
                color=discord.Color.red() if "CRITICAL" in text or "⛔" in text
                      else discord.Color.orange(),
            )
            embed.set_footer(text="PiClaw Watchdog")
            await channel.send(embed=embed)
        except Exception as _e:
            log.debug("Discord embed fallback (plain text): %s", _e)
            await self.send(text)


def _split_discord(text: str) -> list[str]:
    """Split at newlines where possible to keep code blocks intact."""
    if len(text) <= DISCORD_LIMIT:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > DISCORD_LIMIT:
            if current:
                parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        parts.append(current)
    return parts or [text[:DISCORD_LIMIT]]

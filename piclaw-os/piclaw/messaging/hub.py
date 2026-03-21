"""
PiClaw OS – Messaging Hub
Abstract adapter layer for all messaging platforms.

All adapters share the same interface:
  send(text)           – send a message to the configured chat
  send_alert(text)     – like send, but with platform-specific urgency styling
  on_message(callback) – register handler for incoming messages

The Hub routes outbound messages to ALL active adapters and
dispatches incoming messages from any adapter to the agent.

Adapters:
  TelegramAdapter   – existing, now refactored into this layer
  DiscordAdapter    – discord.py bot
  ThreemaAdapter    – threema.gateway SDK (E2E encrypted)
  WhatsAppAdapter   – Meta Cloud API (requires public HTTPS URL)
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Awaitable

log = logging.getLogger("piclaw.messaging")


@dataclass
class IncomingMessage:
    platform: str  # "telegram" | "discord" | "threema" | "whatsapp"
    sender_id: str  # platform-specific user/chat ID
    text: str
    raw: dict = None  # original payload for advanced use


MessageHandler = Callable[[IncomingMessage], Awaitable[str]]


class MessagingAdapter(ABC):
    """Base class for all messaging adapters."""

    name: str = "base"

    @abstractmethod
    async def start(self, on_message: MessageHandler):
        """Start listening for incoming messages."""
        ...

    @abstractmethod
    async def stop(self):
        """Graceful shutdown."""
        ...

    @abstractmethod
    async def send(self, text: str, chat_id: str | None = None):
        """Send a text message."""
        ...

    async def send_alert(self, text: str, chat_id: str | None = None):
        """Send with urgency formatting. Default: same as send."""
        await self.send(f"🚨 {text}", chat_id)

    def is_configured(self) -> bool:
        return True


class MessagingHub:
    """
    Routes messages between agent and all configured adapters.
    Outbound:  agent → Hub → all active adapters
    Inbound:   any adapter → Hub → agent callback
    """

    def __init__(self):
        self._adapters: list[MessagingAdapter] = []
        self._on_message: MessageHandler | None = None
        self._tasks: list[asyncio.Task] = []

    def register(self, adapter: MessagingAdapter):
        if adapter.is_configured():
            self._adapters.append(adapter)
            log.info("Registered adapter: %s", adapter.name)
        else:
            log.info("Adapter %s not configured – skipped.", adapter.name)

    async def start(self, on_message: MessageHandler):
        self._on_message = on_message
        for adapter in self._adapters:
            try:
                task = asyncio.create_task(
                    adapter.start(self._dispatch),
                    name=f"adapter-{adapter.name}",
                )
                self._tasks.append(task)
            except Exception as e:
                log.error("Failed to start %s: %s", adapter.name, e)

    async def stop(self):
        for adapter in self._adapters:
            try:
                await adapter.stop()
            except Exception as _e:
                log.debug("adapter stop (%s): %s", type(adapter).__name__, _e)
        for task in self._tasks:
            task.cancel()

    async def send_all(self, text: str):
        """Broadcast to all active adapters."""
        for adapter in self._adapters:
            try:
                await adapter.send(text)
            except Exception as e:
                log.error("Send error [%s]: %s", adapter.name, e)

    async def send_alert_all(self, text: str):
        """Broadcast alert to all active adapters."""
        for adapter in self._adapters:
            try:
                await adapter.send_alert(text)
            except Exception as e:
                log.error("Alert error [%s]: %s", adapter.name, e)

    async def _dispatch(self, msg: IncomingMessage) -> str:
        if self._on_message:
            try:
                return await self._on_message(msg)
            except Exception as e:
                log.error("Message handler error: %s", e)
                return "❌ Internal error processing message."
        return "No handler registered."

    def active_adapters(self) -> list[str]:
        return [a.name for a in self._adapters]

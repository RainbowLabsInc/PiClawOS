"""
PiClaw OS – Threema Adapter
Uses the official threema.gateway Python SDK (E2E mode).

Setup:
  1. Register at https://gateway.threema.ch
     → Request a Gateway ID (starts with *, e.g. *PICLAW01)
     → Choose "End-to-End encrypted mode"
     → Note your Gateway ID and API Secret

  2. Generate a key pair:
       pip install threema.gateway[e2e]
       threema-gateway generate /etc/piclaw/threema-private.key /etc/piclaw/threema-public.key

  3. Upload the public key to gateway.threema.ch → ID settings

  4. Set in config.toml:
       [threema]
       gateway_id      = "*PICLAW01"
       api_secret      = "your-api-secret"
       private_key_file = "/etc/piclaw/threema-private.key"
       recipient_id    = "YOURTHID"  # your personal Threema ID to receive messages

  5. For INCOMING messages, configure a webhook URL in the Gateway portal.
     Since the Pi may not have a public URL, you can use the "simple" mode
     (outgoing only) by leaving webhook_path empty.

Cost: ~CHF 0.01-0.03 per message (credit-based, min. CHF 100 purchase).

Note on encryption:
  E2E mode: Messages are encrypted on the Pi before sending.
  The Threema Gateway server never sees plaintext.
"""

import asyncio
import logging
from pathlib import Path

from piclaw.messaging.hub import MessagingAdapter, IncomingMessage, MessageHandler

log = logging.getLogger("piclaw.messaging.threema")


class ThreemaAdapter(MessagingAdapter):
    name = "threema"

    def __init__(
        self,
        gateway_id: str,
        api_secret: str,
        private_key_file: str,
        recipient_id: str,
        webhook_path: str = "",
    ):
        self.gateway_id = gateway_id
        self.api_secret = api_secret
        self.private_key_file = private_key_file
        self.recipient_id = recipient_id
        self.webhook_path = webhook_path
        self._stop = asyncio.Event()
        self._connection = None

    def is_configured(self) -> bool:
        return bool(
            self.gateway_id
            and self.api_secret
            and self.private_key_file
            and self.recipient_id
            and Path(self.private_key_file).exists()
        )

    async def _get_connection(self):
        if self._connection:
            return self._connection
        try:
            from threema.gateway import Connection

            self._connection = Connection(
                identity=self.gateway_id,
                secret=self.api_secret,
                key=f"file:{self.private_key_file}",
            )
            return self._connection
        except ImportError:
            raise RuntimeError(
                "threema.gateway not installed. Run: pip install threema.gateway[e2e]"
            )

    async def start(self, on_message: MessageHandler):
        log.info("Threema adapter starting.")
        await self.send("✅ PiClaw connected via Threema.")

        if not self.webhook_path:
            log.info("Threema: no webhook configured – outgoing only.")
            await self._stop.wait()
            return

        # Incoming via webhook – integrated into FastAPI
        log.info("Threema: incoming messages via webhook at %s", self.webhook_path)
        await self._stop.wait()

    async def stop(self):
        self._stop.set()
        if self._connection:
            try:
                await self._connection.close()
            except Exception as _e:
                log.debug("threema connection close: %s", _e)

    async def send(self, text: str, chat_id: str | None = None):
        recipient = chat_id or self.recipient_id
        try:
            from threema.gateway.e2e import TextMessage

            conn = await self._get_connection()
            msg = await TextMessage.create(
                connection=conn,
                to_id=recipient,
                text=text[:3500],  # Threema message size limit
            )
            await msg.send()
            log.debug("Threema message sent to %s", recipient)
        except Exception as e:
            log.error("Threema send error: %s", e)

    async def handle_webhook(self, payload: dict, on_message: MessageHandler):
        """
        Called by the FastAPI webhook endpoint when Threema delivers a message.
        Register this route in api.py:
          POST /webhook/threema
        """
        try:
            msg_type = payload.get("type")
            if msg_type != "text":
                return  # Ignore delivery receipts, images, etc.

            sender = payload.get("from", "")
            text = payload.get("text", "").strip()
            if not text:
                return

            inc = IncomingMessage(
                platform="threema",
                sender_id=sender,
                text=text,
                raw=payload,
            )
            reply = await on_message(inc)
            if reply:
                await self.send(reply, chat_id=sender)
        except Exception as e:
            log.error("Threema webhook handler error: %s", e)

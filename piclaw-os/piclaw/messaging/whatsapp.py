"""
PiClaw OS – WhatsApp Adapter
Uses Meta WhatsApp Business Cloud API.

⚠️  IMPORTANT – READ BEFORE SETUP ⚠️

WhatsApp on a home Raspberry Pi has real prerequisites you should know about:

REQUIREMENT 1 – Public HTTPS URL
  Meta sends incoming messages to your Pi via webhook.
  Your Pi needs a publicly reachable HTTPS URL for this.
  Options:
    a) Port forwarding (Router → Pi:7842) + DuckDNS free domain + Let's Encrypt
    b) Cloudflare Tunnel: `cloudflared tunnel --url http://localhost:7842`
       (free, no port forwarding needed – recommended for Pi)
    c) ngrok (free tier, URL changes on restart)

REQUIREMENT 2 – Meta Business Account
  You need a Meta Developer account + a WhatsApp Business app.
  Free "test mode" is available with 5 recipient numbers allowed.
  For personal use (1 number), the free tier is sufficient.

REQUIREMENT 3 – Dedicated phone number
  The number connected to WA Business cannot be used in regular WhatsApp.
  Solution: use a second SIM/number, or a VoIP number (e.g. sipgate.de free tier).

QUICK SETUP:
  1. Go to https://developers.facebook.com → Create App → Business → WhatsApp
  2. Note: Access Token, Phone Number ID, App Secret
  3. Setup webhook:
     a) Start Cloudflare Tunnel or ngrok pointing to port 7842
     b) In Meta Dashboard → WhatsApp → Configuration:
        Webhook URL: https://your-tunnel.trycloudflare.com/webhook/whatsapp
        Verify Token: (set to your whatsapp.verify_token in config.toml)
     c) Subscribe to: "messages"
  4. Set in config.toml:
       [whatsapp]
       access_token    = "EAA..."          # Meta token
       phone_number_id = "123456789"       # From Meta Dashboard
       app_secret      = "abc123..."       # For webhook verification
       verify_token    = "my-verify-token" # You choose this
       recipient       = "+491234567890"   # Your WhatsApp number to receive messages

If you don't want to deal with this, use Telegram or Discord instead.
WhatsApp can be disabled by leaving access_token empty.
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Optional

import aiohttp

from piclaw.messaging.hub import MessagingAdapter, IncomingMessage, MessageHandler

log = logging.getLogger("piclaw.messaging.whatsapp")

META_API_BASE = "https://graph.facebook.com/v19.0"


class WhatsAppAdapter(MessagingAdapter):
    name = "whatsapp"

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        app_secret: str,
        verify_token: str,
        recipient: str,
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.app_secret = app_secret
        self.verify_token = verify_token
        self.recipient = recipient  # E.164 format: +49...
        self._stop = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._message_handler: MessageHandler | None = None

    def is_configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id and self.recipient)

    async def start(self, on_message: MessageHandler):
        self._session = aiohttp.ClientSession()
        self._message_handler = on_message
        log.info("WhatsApp adapter started (webhook mode).")
        # Send startup notification
        await self.send("✅ PiClaw connected via WhatsApp.")
        # Adapter is webhook-driven – just wait
        await self._stop.wait()

    async def stop(self):
        self._stop.set()
        if self._session:
            await self._session.close()

    async def send(self, text: str, chat_id: str | None = None):
        recipient = chat_id or self.recipient
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        url = f"{META_API_BASE}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        # WhatsApp has a ~4096 char message limit
        for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": chunk},
            }
            try:
                async with self._session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        log.error("WhatsApp send error %s: %.200s", resp.status, body)
            except Exception as e:
                log.error("WhatsApp send exception: %s", e)

    # ── Webhook handlers (called from api.py) ─────────────────────

    async def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Handles GET /webhook/whatsapp for Meta's verification handshake."""
        if mode == "subscribe" and token == self.verify_token:
            log.info("WhatsApp webhook verified.")
            return challenge
        log.warning("WhatsApp webhook verification failed.")
        return None

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify X-Hub-Signature-256 header."""
        if not self.app_secret:
            return True  # skip if no secret configured
        expected = (
            "sha256="
            + hmac.new(
                self.app_secret.encode(),
                payload,
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(expected, signature)

    async def handle_webhook(self, payload: dict):
        """Process incoming POST /webhook/whatsapp from Meta."""
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        if msg.get("type") != "text":
                            continue
                        sender = msg.get("from", "")
                        text = msg.get("text", {}).get("body", "").strip()
                        if not text or not sender:
                            continue
                        # Only accept from configured recipient number
                        clean_sender = sender.lstrip("+")
                        clean_recipient = self.recipient.lstrip("+")
                        if (
                            clean_sender not in clean_recipient
                            and clean_recipient not in clean_sender
                        ):
                            log.warning("WhatsApp: ignored message from %s", sender)
                            continue
                        inc = IncomingMessage(
                            platform="whatsapp",
                            sender_id=sender,
                            text=text,
                            raw=msg,
                        )
                        if self._message_handler:
                            reply = await self._message_handler(inc)
                            if reply:
                                await self.send(reply, chat_id=sender)
        except Exception as e:
            log.error("WhatsApp webhook handler error: %s", e, exc_info=True)

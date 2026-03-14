"""PiClaw OS – Messaging package"""

from piclaw.messaging.hub      import MessagingHub, MessagingAdapter, IncomingMessage
from piclaw.messaging.telegram import TelegramAdapter
from piclaw.messaging.discord  import DiscordAdapter
from piclaw.messaging.threema  import ThreemaAdapter
from piclaw.messaging.whatsapp import WhatsAppAdapter


def build_hub(cfg) -> MessagingHub:
    """
    Build and configure a MessagingHub from PiClawConfig.
    Adapters with empty tokens/keys are automatically skipped.
    """
    hub = MessagingHub()

    # Telegram (primary)
    t = cfg.telegram
    hub.register(TelegramAdapter(
        token=t.token, chat_id=t.chat_id,
    ))

    # Discord
    d = cfg.discord
    hub.register(DiscordAdapter(
        token=d.token,
        channel_id=d.channel_id,
        allowed_users=d.allowed_users,
    ))

    # Threema
    th = cfg.threema
    hub.register(ThreemaAdapter(
        gateway_id=th.gateway_id,
        api_secret=th.api_secret,
        private_key_file=th.private_key_file,
        recipient_id=th.recipient_id,
        webhook_path=th.webhook_path,
    ))

    # WhatsApp
    w = cfg.whatsapp
    hub.register(WhatsAppAdapter(
        access_token=w.access_token,
        phone_number_id=w.phone_number_id,
        app_secret=w.app_secret,
        verify_token=w.verify_token,
        recipient=w.recipient,
    ))

    return hub


__all__ = [
    "build_hub", "MessagingHub", "MessagingAdapter", "IncomingMessage",
    "TelegramAdapter", "DiscordAdapter", "ThreemaAdapter", "WhatsAppAdapter",
]

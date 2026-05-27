"""
PiClaw OS – Telegram Adapter
Long-polling bot. The original/primary messaging channel.

Setup:
  1. Create bot via @BotFather → get token
  2. Start a chat with the bot → get your chat_id (Legacy: System-Broadcasts)
  3. Set in config.toml:
       [telegram]
       token   = "123456:ABC-..."
       chat_id = "123456789"

Multi-User-Routing (seit v0.18):
  - Eingehende Nachrichten werden via piclaw.users.UserRegistry pro chat_id
    einem User zugeordnet.
  - Unbekannte chat_ids können sich mit /start <Name> anmelden — der erste
    User wird Admin (siehe piclaw.users.register_pending).
  - Slash-Commands (/start, /whoami, /web_token, /approve, ...) werden VOR
    dem Agent von piclaw.messaging.bot_commands abgearbeitet.
  - chat_id im Constructor bleibt als Fallback für System-Broadcasts
    (Welcome, Alerts via send_all) — typischerweise die Admin-chat_id.
"""

import asyncio
import logging
import aiohttp

from piclaw.messaging.hub import MessagingAdapter, IncomingMessage, MessageHandler
from piclaw.messaging import bot_commands
from piclaw import users as users_mod

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
        # Markdown-Bereinigung: Python **bold** → Telegram *bold*
        clean = text.replace("**", "*")
        for chunk in _split(clean, 4096):
            # Erst: mit Markdown senden. Bei Parse-Fehler (400) merken, dass
            # ein Fallback ohne parse_mode nötig ist, aber NICHT den Fallback
            # innerhalb des outer async-with-Blocks aufrufen — der noch offene
            # Response-Context blockierte den Folge-POST stillschweigend.
            markdown_failed = False
            try:
                async with self._session.post(
                    self._url("sendMessage"),
                    json={"chat_id": cid, "text": chunk, "parse_mode": "Markdown"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        continue
                    body = await resp.text()
                    log.error(
                        "Telegram API Fehler %s: %s (text=%r)",
                        resp.status, body, chunk[:100],
                    )
                    markdown_failed = True
            except Exception as e:
                log.error("Telegram send error (Markdown): %s", e)
                markdown_failed = True

            if not markdown_failed:
                continue

            # Fallback ohne parse_mode — getrennter Request außerhalb des
            # ersten async-with-Scopes
            try:
                async with self._session.post(
                    self._url("sendMessage"),
                    json={"chat_id": cid, "text": chunk},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp2:
                    if resp2.status != 200:
                        body2 = await resp2.text()
                        log.error(
                            "Telegram Fallback auch fehlgeschlagen: %s: %s",
                            resp2.status, body2,
                        )
                    else:
                        log.info("Telegram Fallback (kein Markdown) OK")
            except Exception as e:
                log.error("Telegram send error (Fallback): %s", e)

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
                        if not text or not from_id:
                            continue
                        try:
                            await self._handle_message(text, from_id, msg, on_message)
                        except Exception as e:
                            log.exception("Routing error for chat %s: %s", from_id, e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Telegram poll error: %s", e)
                await asyncio.sleep(5)

    async def _handle_message(
        self,
        text: str,
        from_id: str,
        msg: dict,
        on_message: MessageHandler,
    ) -> None:
        """
        Multi-User-Routing pro eingehender Nachricht:
          1. Slash-Command → bot_commands.handle() → reply + ggf. Admin-Notification
          2. Unbekannte chat_id → /start-Hinweis
          3. Pending User → Warte-Hinweis
          4. Aktiver User → IncomingMessage mit user_id an Agent
        """
        registry = users_mod.registry()
        sender_name = (
            msg.get("from", {}).get("first_name", "")
            or msg.get("from", {}).get("username", "")
        )

        # Log JEDE eingehende Nachricht mit Routing-Entscheidung damit Debugging
        # nicht im Blindflug stattfindet. INFO-Level — bei Bedarf später auf DEBUG.
        _u = registry.find_by_chat_id(from_id)
        _route = (
            "command" if text.startswith("/")
            else "unknown_chat" if _u is None
            else f"pending:{_u.name}" if _u.role == "pending"
            else f"active:{_u.name}({_u.role})"
        )
        log.info(
            "Telegram IN: chat_id=%s sender=%r text=%.60r → route=%s",
            from_id, sender_name, text, _route,
        )

        # ── Slash-Command? ────────────────────────────────────────
        if text.startswith("/"):
            user_before = registry.find_by_chat_id(from_id)
            # Snapshot aller pending User VOR dem Command, damit wir nach
            # /approve den Übergang pending → user erkennen können.
            pending_chat_ids_before = {u.telegram_chat_id for u in registry.pending()}
            reply = bot_commands.handle(text, from_id, sender_name, registry)
            if reply is not None:
                await self.send(reply, chat_id=from_id)
                # Falls /start einen neuen pending User erzeugte → Admins
                # benachrichtigen (außer dem neuen User selbst, falls er Admin
                # ist – das ist der allererste-User-Bootstrap-Fall).
                user_after = registry.find_by_chat_id(from_id)
                if (
                    user_before is None
                    and user_after is not None
                    and user_after.role == "pending"
                ):
                    await self._notify_admins_new_pending(user_after, exclude_chat=from_id)
                # Falls /approve einen User von pending → user/admin gehoben hat:
                # diesen User direkt benachrichtigen ("Du wurdest freigeschaltet").
                await self._notify_promoted_users(pending_chat_ids_before)
                return

        # ── Nicht-Command: User aus Registry ──────────────────────
        user = registry.find_by_chat_id(from_id)
        if user is None:
            await self.send(
                "Hallo! Ich kenne dich noch nicht. Schick mir /start <Name> "
                "um dich anzumelden.",
                chat_id=from_id,
            )
            return
        if user.role == "pending":
            await self.send(
                f"Hallo {user.name}, du wartest noch auf Freigabe durch einen Admin.",
                chat_id=from_id,
            )
            return

        # ── Aktiver User: an Agent dispatchen ─────────────────────
        log.info(
            "Telegram IN → Agent.run: user=%s text=%.60r",
            user.name, text,
        )
        inc = IncomingMessage(
            platform="telegram",
            sender_id=from_id,
            text=text,
            raw=msg,
            user_id=user.id,
        )
        reply = await on_message(inc)
        log.info(
            "Telegram OUT: chat_id=%s reply_len=%s",
            from_id, len(reply) if reply else 0,
        )
        if reply:
            await self.send(reply, chat_id=from_id)

    async def _notify_promoted_users(self, pending_chat_ids_before: set[str]) -> None:
        """
        Findet User die VORHER pending waren und JETZT aktiv sind (z.B. nach
        /approve). Schickt jedem eine Willkommens-DM mit Hinweis auf /web_token.
        """
        registry = users_mod.registry()
        # Alle aktiven User die VORHER pending waren
        for u in registry.active():
            if u.telegram_chat_id in pending_chat_ids_before and u.telegram_chat_id:
                text = (
                    f"✅ Hallo {u.name}, du wurdest soeben freigeschaltet!\n\n"
                    f"Du kannst dem Bot jetzt ganz normal Nachrichten schicken.\n"
                    f"Falls du die Web-UI nutzen willst, schick `/web_token` —\n"
                    f"dann bekommst du deinen Login-Schlüssel."
                )
                try:
                    await self.send(text, chat_id=u.telegram_chat_id)
                except Exception as e:
                    log.warning(
                        "Promote-Notify an %s (chat=%s) fehlgeschlagen: %s",
                        u.name, u.telegram_chat_id, e,
                    )

    async def _notify_admins_new_pending(self, new_user, *, exclude_chat: str = "") -> None:
        registry = users_mod.registry()
        text = (
            f"🔔 Neue Registrierung: *{new_user.name}*\n"
            f"chat_id: `{new_user.telegram_chat_id}`\n\n"
            f"Aktivieren mit: `/approve {new_user.name}`"
        )
        for admin in registry.admins():
            if not admin.telegram_chat_id:
                continue
            if admin.telegram_chat_id == exclude_chat:
                continue
            try:
                await self.send(text, chat_id=admin.telegram_chat_id)
            except Exception as e:
                log.warning("Admin-Notify an %s fehlgeschlagen: %s", admin.name, e)


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] if text else [""]

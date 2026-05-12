"""Verifiziert den Telegram-Fallback-Pfad isoliert:

  1. Sendet eine Nachricht die garantiert Markdown-Parse-Fehler auslöst
     (unausbalancierte _ und [ — ähnlich dem realen Inbox-Scan-Output).
  2. Erwartet: Markdown-Versuch scheitert (Log: "Telegram API Fehler")
              → Fallback ohne parse_mode greift (Log: "Telegram Fallback OK")
              → Plain-Text-Nachricht kommt im Chat an.

Aufruf auf Pi: /opt/piclaw/.venv/bin/python /opt/piclaw/piclaw-os/scripts/test_telegram_fallback.py
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from piclaw.config import load
from piclaw.messaging.telegram import TelegramAdapter


async def main() -> None:
    cfg = load()
    adapter = TelegramAdapter(cfg.telegram.token, cfg.telegram.chat_id)

    # Garantiert Parse-Fehler: ungerade Anzahl `*` in einer Zeile.
    # Telegram MarkdownV1 sucht das schließende `*` und scheitert daran.
    bad_text = (
        "🤖 *Fallback-Test* [ok]\n"
        "Diese Nachricht hat *ein* einzelnes asterisk: *unbalanced\n"
        "und gleich noch eines: *also-broken\n"
        "Wenn sie ankommt, hat der Fallback-Pfad funktioniert."
    )

    print("\n=== Sende absichtlich kaputte Markdown-Nachricht ===")
    await adapter.send(bad_text)
    print("\n=== Erwarte im obigen Log ===")
    print("  - 1x 'Telegram API Fehler 400 ...'")
    print("  - 1x 'Telegram Fallback (kein Markdown) OK'")
    print("Und im Telegram-Chat eine Plain-Text-Version dieser Nachricht.")


if __name__ == "__main__":
    asyncio.run(main())

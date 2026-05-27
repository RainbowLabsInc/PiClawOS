"""
PiClaw OS – Bot-Command-Handler (Multi-User)
============================================
Slash-Commands die der Telegram-Adapter VOR dem Agent verarbeitet:

  /start [Name]      – Selbst-Registrierung (erster User wird Admin)
  /whoami            – eigene User-Info
  /web_token         – eigenen Web-/API-Token anzeigen (nur DM)
  /help              – Command-Liste
  /users   [admin]   – alle aktiven User
  /pending [admin]   – wartende User
  /approve <name|id> – pending User aktivieren
  /revoke  <name|id> – User entfernen

Rückgabe von handle():
  - str   : Antworttext an den Absender — KEIN weiteres Routing an den Agent
  - None  : kein Command (z.B. normale Nachricht) → Telegram-Adapter routet
            normal weiter an den Agent

Platform-agnostisch: nimmt eine UserRegistry-Instanz statt direkt das
Modul-Singleton. So koennen Tests und kuenftige Adapter (Discord, Threema)
dieselbe Logik wiederverwenden.
"""

from __future__ import annotations

import logging

from piclaw.users import UserRegistry, User

log = logging.getLogger("piclaw.messaging.bot_commands")


HELP_TEXT_USER = (
    "PiClaw Commands:\n"
    "/whoami     – eigene Info\n"
    "/web_token  – Web-/API-Token (zum Login in der Web-UI)\n"
    "/help       – diese Liste"
)

HELP_TEXT_ADMIN = (
    HELP_TEXT_USER
    + "\n\nAdmin:\n"
    + "/users           – aktive User\n"
    + "/pending         – wartende User\n"
    + "/approve <name>  – aktivieren\n"
    + "/revoke  <name>  – entfernen"
)


def handle(
    text: str,
    from_id: str,
    sender_name: str,
    registry: UserRegistry,
) -> str | None:
    """Entry-Point. Siehe Modul-Docstring."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=1)
    cmd = parts[0][1:].lower()
    # Telegram-Bot-Suffix entfernen ("/start@piclaw_bot" → "start")
    cmd = cmd.split("@", 1)[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    sender = registry.find_by_chat_id(from_id)

    if cmd == "start":
        return _cmd_start(arg, from_id, sender_name, registry, sender)
    if cmd == "whoami":
        return _cmd_whoami(sender, from_id)
    if cmd in ("web_token", "webtoken", "token"):
        return _cmd_web_token(sender)
    if cmd == "help":
        return _cmd_help(sender)

    # Ab hier nur Admin-Commands
    if cmd in ("users", "pending", "approve", "revoke"):
        if sender is None or not sender.is_admin:
            log.info("Admin-Command '%s' von Non-Admin %s abgewiesen.", cmd, from_id)
            return "❌ Admin-Befehl. Du bist nicht autorisiert."
        if cmd == "users":
            return _cmd_users(registry)
        if cmd == "pending":
            return _cmd_pending(registry)
        if cmd == "approve":
            return _cmd_approve(arg, registry)
        if cmd == "revoke":
            return _cmd_revoke(arg, registry)

    # Unbekannter "/foo" – nicht uns; an Agent durchreichen
    return None


# ── Command-Implementierungen ─────────────────────────────────────


def _cmd_start(
    arg: str,
    from_id: str,
    sender_name: str,
    registry: UserRegistry,
    existing: User | None,
) -> str:
    if existing is not None:
        if existing.role == "pending":
            return (
                f"Hallo {existing.name} – du bist registriert und wartest noch "
                f"auf Freigabe durch einen Admin."
            )
        if existing.is_admin:
            return f"Du bist eingeloggt als Admin ({existing.name}). /help für Befehle."
        return f"Du bist eingeloggt als {existing.name}. /help für Befehle."

    name = arg.strip() or sender_name.strip() or f"user-{from_id}"
    user = registry.register_pending(name=name, telegram_chat_id=from_id)
    if user.is_admin:
        return (
            f"✅ Willkommen, {user.name}! Du bist der erste User und automatisch Admin.\n"
            f"Mit /web_token bekommst du deinen Web-Login."
        )
    return (
        f"✅ Hallo {user.name}, du wurdest registriert.\n"
        f"Ein Admin muss dich noch freischalten, du bekommst hier Bescheid."
    )


def _cmd_whoami(sender: User | None, from_id: str) -> str:
    if sender is None:
        return (
            "Du bist (noch) nicht registriert.\n"
            f"chat_id: {from_id}\n"
            "Schick /start <Name> um dich anzumelden."
        )
    role_label = {"admin": "Admin", "user": "User", "pending": "wartet auf Freigabe"}.get(
        sender.role, sender.role
    )
    return (
        f"Name: {sender.name}\n"
        f"Rolle: {role_label}\n"
        f"User-ID: {sender.id}"
    )


def _cmd_web_token(sender: User | None) -> str:
    if sender is None:
        return "Du bist nicht registriert. Schick /start <Name>."
    if sender.role == "pending":
        return "Du wartest noch auf Admin-Freigabe – nach Approval bekommst du deinen Token."
    return (
        "🔑 Dein Web-/API-Token (geheim halten, nicht teilen):\n\n"
        f"`{sender.web_token}`\n\n"
        "Login in der Web-UI: Token im Feld eintragen, fertig."
    )


def _cmd_help(sender: User | None) -> str:
    if sender is not None and sender.is_admin:
        return HELP_TEXT_ADMIN
    return HELP_TEXT_USER


def _cmd_users(registry: UserRegistry) -> str:
    active = registry.active()
    if not active:
        return "Keine aktiven User."
    lines = ["Aktive User:"]
    for u in active:
        marker = "★" if u.is_admin else "•"
        last = f" (zuletzt: {u.last_seen[:16]})" if u.last_seen else ""
        lines.append(f"{marker} {u.name}  [{u.role}]{last}")
    return "\n".join(lines)


def _cmd_pending(registry: UserRegistry) -> str:
    pending = registry.pending()
    if not pending:
        return "Keine wartenden User."
    lines = ["Wartende User:"]
    for u in pending:
        lines.append(f"• {u.name}  (chat_id={u.telegram_chat_id})")
    lines.append("\nFreischalten mit: /approve <Name>")
    return "\n".join(lines)


def _cmd_approve(arg: str, registry: UserRegistry) -> str:
    if not arg:
        return "Bitte einen Namen angeben: /approve <Name>"
    u = registry.approve(arg)
    if u is None:
        return f"❌ Kein User mit Name/ID '{arg}' gefunden."
    if u.role != "user":
        return f"⚠️  {u.name} war nicht pending (Rolle: {u.role})."
    return f"✅ {u.name} ist jetzt aktiviert. Sag ihm/ihr, /web_token zu schicken."


def _cmd_revoke(arg: str, registry: UserRegistry) -> str:
    if not arg:
        return "Bitte einen Namen angeben: /revoke <Name>"
    u = registry.find_by_id(arg) or registry.find_by_name(arg)
    if u is None:
        return f"❌ Kein User mit Name/ID '{arg}' gefunden."
    if registry.revoke(u.id):
        return f"🗑️  {u.name} entfernt."
    return f"❌ Konnte {u.name} nicht entfernen (z.B. letzter Admin?)."

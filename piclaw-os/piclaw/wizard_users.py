"""
PiClaw OS – Wizard: User-Verwaltung (Multi-User)
================================================
Interaktiver Schritt im `piclaw setup`-Wizard sowie direkt aufrufbar
über `piclaw user setup`.

Funktionen:
  step_user_management(state, step, total)
      Schritt im Wizard-Stil (passt zu step_telegram, step_discord etc.).
      Loop-Menü: Freischalten / Anlegen / Token / Entfernen / Fertig.

  offer_bootstrap_admin(cfg, chat_id) -> bool
      Single-source-of-truth Bootstrap-Helper. Wird sowohl von
      `piclaw setup`'s step_telegram als auch von `piclaw messaging
      telegram` (cli.py:_setup_telegram) aufgerufen.

Beide nutzen UserRegistry aus piclaw.users.
"""

from __future__ import annotations

import sys

from piclaw import users as users_mod
from piclaw.users import UserRegistry, User
from piclaw.auth import generate_token


# ── UTF-8-Console-Sicherung (Windows-cp1252-Fallback) ──────────────


def _ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


# ── Bootstrap-Admin (shared mit cli.py-Setup) ──────────────────────


def offer_bootstrap_admin(cfg, chat_id: str) -> bool:
    """
    Bietet an, die übergebene Telegram-`chat_id` als Admin zu bootstrappen.
    Idempotent: wenn schon ein Admin existiert → No-op, return False.

    Nutzt cfg.api.secret_key als web_token, damit der bisherige API-Token
    nach Migration weiter funktioniert. Wenn secret_key leer ist → wird
    neu generiert und in cfg gespeichert.

    Returns True wenn ein Admin angelegt wurde.
    """
    _ensure_utf8_stdout()
    reg = users_mod.registry()
    if reg.has_admin():
        return False
    if not chat_id:
        return False

    print()
    print("  Möchtest du den Telegram-User mit dieser chat_id direkt als Admin")
    print("  registrieren? (Spart das spätere /start im Bot.)")
    try:
        yn = input("  [J/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        yn = "n"
    if yn and yn[0] == "n":
        print("  ⏩ Übersprungen — du kannst dich auch via /start am Bot anmelden.")
        return False

    try:
        name = input("  Anzeigename für den Admin [admin]: ").strip() or "admin"
    except (EOFError, KeyboardInterrupt):
        name = "admin"

    # Token sicherstellen
    if not cfg.api.secret_key:
        from piclaw.config import save as save_cfg
        cfg.api.secret_key = generate_token()
        save_cfg(cfg)

    try:
        user = reg.bootstrap_admin(
            name=name,
            telegram_chat_id=chat_id,
            web_token=cfg.api.secret_key,
        )
    except RuntimeError as e:
        print(f"  ⚠️  Bootstrap übersprungen: {e}")
        return False

    print(f"  ✅ Admin '{user.name}' angelegt.")
    print(f"     Vollständigen Web-Token sehen mit: piclaw user token {user.name}")
    return True


# ── Hauptmenü ─────────────────────────────────────────────────────


def step_user_management(state, step: int, total: int) -> None:
    """
    Wizard-Schritt: User-Verwaltung.

    Loop-Menü; verlässt nur bei [0] oder Ctrl-C. Jede Aktion ruft direkt
    UserRegistry-Funktionen aus piclaw.users.
    """
    _ensure_utf8_stdout()

    # Header (best-effort: Wizard-Helper wenn verfügbar)
    try:
        from piclaw.wizard import _header
        _header(step, total, "Benutzer -- Multi-User-Verwaltung", "[Users]")
    except Exception:
        print()
        print("=== Benutzer — Multi-User-Verwaltung ===")
        print()

    reg = users_mod.registry()

    while True:
        _print_overview(reg)
        choice = _ask_main_choice()
        if choice == "0":
            print()
            print("  ✅ Fertig.")
            return
        if choice == "1":
            _menu_approve(reg)
        elif choice == "2":
            _menu_add(reg)
        elif choice == "3":
            _menu_token(reg)
        elif choice == "4":
            _menu_revoke(reg)
        elif choice == "5":
            _menu_overrides(reg)
        else:
            print(f"  ⚠️  Unbekannte Auswahl: {choice!r}")


# ── Direkter Sub-Command (piclaw user setup) ──────────────────────


def run_standalone() -> int:
    """Wird von cli_users.cmd_user('setup') aufgerufen.
    Lädt config und ruft step_user_management mit Dummy-state auf."""
    _ensure_utf8_stdout()
    try:
        from piclaw.config import load as load_cfg
        # WizardState ist optional — wir nutzen ein leichtes Dict-Substitut
        class _Dummy:
            pass
        state = _Dummy()
        state.cfg = load_cfg()
        step_user_management(state, 1, 1)
        return 0
    except KeyboardInterrupt:
        print("\n  Abgebrochen.")
        return 1


# ── Helper: Anzeige ───────────────────────────────────────────────


def _print_overview(reg: UserRegistry) -> None:
    active = reg.active()
    pending = reg.pending()
    print()
    print(f"  Aktive User ({len(active)}):")
    if not active:
        print("    (keine)")
    for u in active:
        marker = "★" if u.is_admin else " "
        last = u.last_seen[:16] if u.last_seen else "—"
        print(f"    {marker} {u.name:<20}  {u.role:<6}  chat_id={u.telegram_chat_id:<14}  last_seen={last}")

    print()
    print(f"  Wartende ({len(pending)}):")
    if not pending:
        print("    (keine)")
    for u in pending:
        print(f"    • {u.name:<20}  chat_id={u.telegram_chat_id}")


def _ask_main_choice() -> str:
    print()
    print("  [1] Wartenden User freischalten")
    print("  [2] Weiteren User manuell anlegen")
    print("  [3] Token anzeigen / regenerieren")
    print("  [4] User entfernen")
    print("  [5] Einstellungen pro User (HA, AgentMail, Discord, …)")
    print("  [0] Fertig")
    try:
        return input("\n  Auswahl [0]: ").strip() or "0"
    except (EOFError, KeyboardInterrupt):
        return "0"


# ── Helper: Approve ───────────────────────────────────────────────


def _menu_approve(reg: UserRegistry) -> None:
    pending = reg.pending()
    if not pending:
        print("  ℹ️  Keine wartenden User.")
        return
    print()
    print("  Welchen User freischalten?")
    for i, u in enumerate(pending, 1):
        print(f"    [{i}] {u.name}  (chat_id={u.telegram_chat_id})")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(pending)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    target = pending[int(sel) - 1]
    u = reg.approve(target.id)
    if u is None:
        print(f"  ❌ Konnte {target.name} nicht aktivieren.")
        return
    print(f"  ✅ {u.name} ist jetzt '{u.role}'.")
    print(f"     Token: {u.web_token}")
    print("     Tipp: Der User kann den Token auch via /web_token im Bot abrufen.")


# ── Helper: Add ───────────────────────────────────────────────────


def _menu_add(reg: UserRegistry) -> None:
    print()
    print("  Neuen User anlegen.")
    try:
        name = input("  Anzeigename: ").strip()
        if not name:
            print("  ⏩ Abgebrochen.")
            return
        chat_id = input("  Telegram chat_id: ").strip()
        if not chat_id:
            print("  ⏩ Abgebrochen.")
            print("  Tipp: Empfänger sendet eine Nachricht an den Bot, dann die chat_id")
            print("        via @userinfobot oder https://api.telegram.org/bot<TOKEN>/getUpdates.")
            return
        role = input("  Rolle [user/admin] (user): ").strip().lower() or "user"
        if role not in ("user", "admin"):
            print(f"  ⚠️  Unbekannte Rolle '{role}'. Verwende 'user'.")
            role = "user"
    except (EOFError, KeyboardInterrupt):
        return

    try:
        u = reg.add_user(name=name, telegram_chat_id=chat_id, role=role)
    except ValueError as e:
        print(f"  ❌ {e}")
        return
    marker = "★ Admin" if u.is_admin else u.role
    print(f"  ✅ {u.name} angelegt ({marker}).")
    print(f"     Token: {u.web_token}")


# ── Helper: Token anzeigen / regenerieren ──────────────────────────


def _menu_token(reg: UserRegistry) -> None:
    active = reg.active()
    if not active:
        print("  ℹ️  Keine aktiven User.")
        return
    print()
    print("  Welcher User?")
    for i, u in enumerate(active, 1):
        marker = "★" if u.is_admin else " "
        print(f"    [{i}] {marker} {u.name}  ({u.role})")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(active)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    target = active[int(sel) - 1]
    print()
    print(f"  Aktueller Token von {target.name}:")
    print(f"    {target.web_token}")
    try:
        regen = input("\n  Token neu erzeugen? Alter Token wird ungültig. [j/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        regen = "n"
    if regen == "j":
        u = reg.regenerate_token(target.id)
        print(f"  ✅ Neuer Token für {u.name}:")
        print(f"    {u.web_token}")


# ── Helper: Revoke ────────────────────────────────────────────────


def _menu_revoke(reg: UserRegistry) -> None:
    all_users = reg.all()
    if not all_users:
        print("  ℹ️  Keine User.")
        return
    print()
    print("  Welchen User entfernen?")
    for i, u in enumerate(all_users, 1):
        marker = "★" if u.is_admin else "•" if u.role == "user" else "○"
        print(f"    [{i}] {marker} {u.name}  ({u.role}, chat_id={u.telegram_chat_id})")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(all_users)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    target = all_users[int(sel) - 1]
    try:
        confirm = input(f"  {target.name} wirklich entfernen? [j/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm != "j":
        print("  ⏩ Abgebrochen.")
        return
    if reg.revoke(target.id):
        print(f"  🗑️  {target.name} entfernt.")
    else:
        print(f"  ❌ Konnte {target.name} nicht entfernen (letzter Admin?).")


# ── Helper: Per-User-Overrides ────────────────────────────────────


# Verfügbare Sektionen + Keys mit Hinweisen (für die UX)
_OVERRIDE_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "homeassistant": [
        ("token", "Long-Lived Access Token (HA → Profil → Sicherheit)"),
        ("url",   "Base-URL z.B. http://192.168.1.42:8123"),
    ],
    "agentmail": [
        ("email_address",      "Eigene Inbox-Adresse z.B. anna@agentmail.to"),
        ("inbox_id",           "Inbox-ID aus AgentMail-Dashboard"),
        ("notification_email", "Persönliche Benachrichtigungs-Email"),
    ],
    "discord": [
        ("user_id", "Eigene Discord-User-ID (numerisch)"),
    ],
    "threema": [
        ("recipient_id", "Eigene 8-stellige Threema-ID"),
    ],
    "whatsapp": [
        ("recipient", "Eigene Nummer im E.164-Format z.B. +49…"),
    ],
}


def _menu_overrides(reg: UserRegistry) -> None:
    active = reg.active()
    if not active:
        print("  ℹ️  Keine aktiven User.")
        return
    print()
    print("  Welcher User?")
    for i, u in enumerate(active, 1):
        marker = "★" if u.is_admin else " "
        n_over = sum(len(s) for s in u.overrides.values())
        print(f"    [{i}] {marker} {u.name:<20}  ({n_over} Override(s))")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(active)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    target = active[int(sel) - 1]
    _user_overrides_submenu(reg, target)


def _user_overrides_submenu(reg: UserRegistry, user: User) -> None:
    while True:
        print()
        print(f"  Overrides für {user.name}:")
        if not user.overrides:
            print("    (keine — User nutzt überall die globalen Settings)")
        else:
            for section, kvs in user.overrides.items():
                for k, v in kvs.items():
                    shown = _mask_if_secret(k, v)
                    print(f"    [{section}] {k} = {shown}")
        print()
        print("  [1] Wert setzen / ändern")
        print("  [2] Einzelnen Wert entfernen")
        print("  [3] Komplette Sektion entfernen")
        print("  [0] Zurück")
        try:
            choice = input("\n  Auswahl: ").strip() or "0"
        except (EOFError, KeyboardInterrupt):
            return
        if choice == "0":
            return
        if choice == "1":
            _override_set_flow(reg, user)
        elif choice == "2":
            _override_clear_key_flow(reg, user)
        elif choice == "3":
            _override_clear_section_flow(reg, user)
        else:
            print("  ⚠️  Unbekannte Auswahl.")


def _override_set_flow(reg: UserRegistry, user: User) -> None:
    print()
    print("  Welche Sektion?")
    sections = list(_OVERRIDE_SCHEMA.keys())
    for i, s in enumerate(sections, 1):
        print(f"    [{i}] {s}")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(sections)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    section = sections[int(sel) - 1]
    keys = _OVERRIDE_SCHEMA[section]
    print()
    print(f"  Welcher Wert in [{section}]?")
    for i, (k, hint) in enumerate(keys, 1):
        cur = user.overrides.get(section, {}).get(k)
        cur_disp = f"  (aktuell: {_mask_if_secret(k, cur)})" if cur is not None else ""
        print(f"    [{i}] {k}   — {hint}{cur_disp}")
    print("    [0] Zurück")
    try:
        sel2 = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel2 == "0" or not sel2:
        return
    if not sel2.isdigit() or not (1 <= int(sel2) <= len(keys)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    key, _hint = keys[int(sel2) - 1]
    try:
        value = input(f"\n  Neuer Wert für {section}.{key} (leer = abbrechen): ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not value:
        print("  ⏩ Abgebrochen.")
        return
    parsed: object = value
    if value.isdigit():
        parsed = int(value)
    elif value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    reg.set_override(user.id, section, key, parsed)
    print(f"  ✅ {user.name}: {section}.{key} gesetzt.")


def _override_clear_key_flow(reg: UserRegistry, user: User) -> None:
    if not user.overrides:
        print("  ℹ️  Keine Overrides zu löschen.")
        return
    flat: list[tuple[str, str]] = []
    for section, kvs in user.overrides.items():
        for k in kvs.keys():
            flat.append((section, k))
    print()
    print("  Welchen Wert entfernen?")
    for i, (s, k) in enumerate(flat, 1):
        print(f"    [{i}] {s}.{k}")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(flat)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    section, key = flat[int(sel) - 1]
    reg.clear_override(user.id, section, key)
    print(f"  ✅ {section}.{key} entfernt.")


def _override_clear_section_flow(reg: UserRegistry, user: User) -> None:
    if not user.overrides:
        print("  ℹ️  Keine Overrides zu löschen.")
        return
    sections = list(user.overrides.keys())
    print()
    print("  Welche Sektion komplett entfernen?")
    for i, s in enumerate(sections, 1):
        n = len(user.overrides[s])
        print(f"    [{i}] {s}  ({n} Werte)")
    print("    [0] Zurück")
    try:
        sel = input("\n  Auswahl: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if sel == "0" or not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(sections)):
        print("  ⚠️  Ungültige Auswahl.")
        return
    section = sections[int(sel) - 1]
    reg.clear_override(user.id, section)
    print(f"  ✅ Sektion [{section}] entfernt.")


def _mask_if_secret(key: str, value) -> str:
    if value is None:
        return "(nicht gesetzt)"
    if isinstance(value, str) and any(s in key.lower() for s in ("token", "secret", "key", "password")):
        return f"{value[:6]}…" if len(value) > 6 else "***"
    return str(value)

"""
PiClaw OS – CLI: User-Verwaltung
================================
SSH-/Terminal-Befehle für die UserRegistry. Wird von cli.py via
`piclaw user <subcommand>` aufgerufen.

Subcommands:
  list                   – aktive User
  pending                – wartende User
  show <name|id>         – Details zu einem User
  approve <name|id>      – pending → user
  revoke <name|id>       – User entfernen (letzter Admin geschützt)
  promote <name|id>      – user → admin
  demote <name|id>       – admin → user (letzter Admin geschützt)
  add <name> --telegram <chat_id> [--role admin|user]
                         – User explizit anlegen (umgeht /start)
  token <name|id>        – web_token anzeigen
  token <name|id> --regenerate
                         – neuen Token erzeugen (alter wird ungültig)

Design:
  - Die CLI hat per Definition admin-äquivalenten Zugriff (lokaler Prozess,
    SSH-Login = god mode), daher kein zusätzliches Auth-Gate.
  - Alle Operationen nutzen die globale UserRegistry aus piclaw.users.
"""

from __future__ import annotations

import sys

from piclaw import users as users_mod
from piclaw.users import User


def _ensure_utf8_stdout() -> None:
    """
    Windows-Terminals laufen oft in cp1252 → UnicodeEncodeError für ★ ❌ etc.
    Auf Linux/macOS ist stdout meist schon UTF-8; auf Windows force-switchen.
    No-op falls reconfigure nicht verfügbar (z.B. wenn stdout ein Pipe/IDE ist).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


HELP = """\
piclaw user <subcommand>

Subcommands:
  setup                         interaktives Menü (Freischalten/Anlegen/Token/Entfernen)
  list                          aktive User auflisten
  pending                       wartende User
  show <name|id>                Details
  approve <name|id>             pending → user aktivieren
  revoke <name|id>              User entfernen
  promote <name|id>             user → admin
  demote <name|id>              admin → user
  add <name> --telegram <id>    [--role admin|user] User explizit anlegen
  token <name|id>               web_token anzeigen
  token <name|id> --regenerate  neuen Token erzeugen

Per-User-Overrides:
  settings <name|id>                       Alle Overrides eines Users anzeigen
  set <name|id> <section>.<key> <value>    Override setzen
                                           Beispiele:
                                             piclaw user set Anna homeassistant.token HA-...
                                             piclaw user set Anna agentmail.email_address anna@a.to
  clear <name|id> <section>[.<key>]        Override entfernen (Key oder ganze Sektion)
"""


def cmd_user(args: list[str]) -> int:
    """Dispatch. Returncode: 0 = OK, 1 = Fehler."""
    _ensure_utf8_stdout()
    if not args or args[0] in ("help", "-h", "--help"):
        print(HELP)
        return 0

    sub = args[0]
    rest = args[1:]
    reg = users_mod.registry()

    try:
        if sub == "setup":
            from piclaw.wizard_users import run_standalone
            return run_standalone()
        if sub == "list":
            return _list(reg)
        if sub == "pending":
            return _pending(reg)
        if sub == "show":
            return _show(reg, rest)
        if sub == "approve":
            return _approve(reg, rest)
        if sub == "revoke":
            return _revoke(reg, rest)
        if sub == "promote":
            return _set_role(reg, rest, "admin")
        if sub == "demote":
            return _set_role(reg, rest, "user")
        if sub == "add":
            return _add(reg, rest)
        if sub == "token":
            return _token(reg, rest)
        if sub == "settings":
            return _settings(reg, rest)
        if sub == "set":
            return _set_override_cmd(reg, rest)
        if sub == "clear":
            return _clear_override_cmd(reg, rest)
    except SystemExit:
        raise
    except Exception as e:
        print(f"❌ Fehler: {e}")
        return 1

    print(f"Unbekanntes Subcommand: {sub}")
    print(HELP)
    return 1


# ── Subcommand-Implementierungen ───────────────────────────────────


def _resolve(reg, ident: str) -> User | None:
    return reg.find_by_id(ident) or reg.find_by_name(ident)


def _list(reg) -> int:
    active = reg.active()
    if not active:
        print("Keine aktiven User.")
        return 0
    print(f"\n  {len(active)} aktive(r) User:\n")
    for u in active:
        marker = "★" if u.is_admin else " "
        last = u.last_seen[:16] if u.last_seen else "—"
        print(f"  {marker} {u.name:<20}  {u.role:<6}  chat_id={u.telegram_chat_id:<14}  last_seen={last}")
    print()
    return 0


def _pending(reg) -> int:
    p = reg.pending()
    if not p:
        print("Keine wartenden User.")
        return 0
    print(f"\n  {len(p)} wartende(r) User:\n")
    for u in p:
        print(f"    {u.name:<20}  chat_id={u.telegram_chat_id}  id={u.id[:8]}…")
    print("\n  Aktivieren mit: piclaw user approve <Name>\n")
    return 0


def _show(reg, args) -> int:
    if not args:
        print("Usage: piclaw user show <name|id>")
        return 1
    u = _resolve(reg, args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    print()
    print(f"  Name:      {u.name}")
    print(f"  ID:        {u.id}")
    print(f"  Rolle:     {u.role}")
    print(f"  Telegram:  {u.telegram_chat_id}")
    print(f"  Token:     {u.web_token[:8]}…   (vollständig via: piclaw user token {u.name})")
    print(f"  Angelegt:  {u.created_at}")
    print(f"  Last seen: {u.last_seen or '—'}")
    print()
    return 0


def _approve(reg, args) -> int:
    if not args:
        print("Usage: piclaw user approve <name|id>")
        return 1
    u = reg.approve(args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    if u.role == "admin":
        print(f"ℹ️  {u.name} ist bereits Admin.")
        return 0
    if u.role != "user":
        print(f"⚠️  {u.name} hat Rolle '{u.role}' — kein pending.")
        return 0
    print(f"✅ {u.name} aktiviert (jetzt: user).")
    return 0


def _revoke(reg, args) -> int:
    if not args:
        print("Usage: piclaw user revoke <name|id>")
        return 1
    u = _resolve(reg, args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    if reg.revoke(u.id):
        print(f"🗑️  {u.name} entfernt.")
        return 0
    print(f"❌ Konnte {u.name} nicht entfernen (letzter Admin?).")
    return 1


def _set_role(reg, args, target_role: str) -> int:
    if not args:
        verb = "promote" if target_role == "admin" else "demote"
        print(f"Usage: piclaw user {verb} <name|id>")
        return 1
    u = _resolve(reg, args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    before = u.role
    updated = reg.set_role(u.id, target_role)
    if updated is None:
        return 1
    if updated.role == before:
        print(f"⚠️  {u.name} bleibt '{before}' (letzter Admin?).")
        return 1
    print(f"✅ {u.name}: {before} → {updated.role}")
    return 0


def _parse_kv_flags(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """
    Trennt positionale Args von --flag value-Paaren.
    --foo bar         → flags['foo'] = 'bar'
    --foo=bar         → flags['foo'] = 'bar'
    --foo (boolean)   → flags['foo'] = ''
    """
    pos: list[str] = []
    flags: dict[str, str] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            if "=" in a:
                k, _, v = a[2:].partition("=")
                flags[k] = v
            else:
                k = a[2:]
                # Look ahead: ist nächstes ein Wert?
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    flags[k] = args[i + 1]
                    i += 1
                else:
                    flags[k] = ""
        else:
            pos.append(a)
        i += 1
    return pos, flags


def _add(reg, args) -> int:
    pos, flags = _parse_kv_flags(args)
    if not pos:
        print("Usage: piclaw user add <name> --telegram <chat_id> [--role admin|user]")
        return 1
    name = pos[0]
    chat_id = flags.get("telegram", "").strip()
    if not chat_id:
        print("❌ --telegram <chat_id> erforderlich.")
        return 1
    role = flags.get("role", "user").strip() or "user"
    try:
        u = reg.add_user(name=name, telegram_chat_id=chat_id, role=role)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    marker = "★ Admin" if u.is_admin else u.role
    print(f"✅ {u.name} angelegt ({marker}, chat_id={u.telegram_chat_id})")
    print(f"   Web-Token: {u.web_token}")
    return 0


def _token(reg, args) -> int:
    pos, flags = _parse_kv_flags(args)
    if not pos:
        print("Usage: piclaw user token <name|id> [--regenerate]")
        return 1
    u = _resolve(reg, pos[0])
    if u is None:
        print(f"❌ User '{pos[0]}' nicht gefunden.")
        return 1
    if "regenerate" in flags:
        u = reg.regenerate_token(u.id)
        print(f"🔄 Token regeneriert für {u.name}. Alter Token ist ab sofort ungültig.")
    print(f"\n  🔑 Web-Token für {u.name}:\n  {u.web_token}\n")
    return 0


# ── Per-User-Overrides ─────────────────────────────────────────────


def _settings(reg, args) -> int:
    if not args:
        print("Usage: piclaw user settings <name|id>")
        return 1
    u = _resolve(reg, args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    if not u.overrides:
        print(f"\n  Keine Overrides für {u.name}. (Nutzt überall die globalen Settings.)\n")
        return 0
    print(f"\n  Overrides für {u.name}:\n")
    for section, kvs in u.overrides.items():
        print(f"    [{section}]")
        for k, v in kvs.items():
            # Sensible Werte maskieren
            shown = v
            if isinstance(v, str) and any(s in k.lower() for s in ("token", "secret", "key", "password")):
                shown = f"{v[:6]}…" if len(v) > 6 else "***"
            print(f"      {k} = {shown}")
        print()
    return 0


def _set_override_cmd(reg, args) -> int:
    if len(args) < 3:
        print("Usage: piclaw user set <name|id> <section>.<key> <value>")
        print("  Beispiel: piclaw user set Anna homeassistant.token HA-abcdef...")
        return 1
    u = _resolve(reg, args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    path = args[1]
    if "." not in path:
        print("❌ Pfad muss <section>.<key> sein (z.B. homeassistant.token)")
        return 1
    section, key = path.split(".", 1)
    value = " ".join(args[2:])
    # Numerische Werte (für discord.user_id, channel_id etc.) parsen
    if value.isdigit():
        parsed: object = int(value)
    elif value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    else:
        parsed = value
    reg.set_override(u.id, section, key, parsed)
    print(f"✅ {u.name}: {section}.{key} = {value}")
    return 0


def _clear_override_cmd(reg, args) -> int:
    if len(args) < 2:
        print("Usage: piclaw user clear <name|id> <section>[.<key>]")
        return 1
    u = _resolve(reg, args[0])
    if u is None:
        print(f"❌ User '{args[0]}' nicht gefunden.")
        return 1
    path = args[1]
    section, _, key = path.partition(".")
    key = key or None
    ok = reg.clear_override(u.id, section, key)
    if not ok:
        print(f"⚠️  Kein Override für '{path}' bei {u.name}.")
        return 1
    if key:
        print(f"✅ Override entfernt: {u.name}.{section}.{key}")
    else:
        print(f"✅ Sektion entfernt: {u.name}.{section}")
    return 0

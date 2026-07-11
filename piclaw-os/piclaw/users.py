"""
PiClaw OS – User Registry
=========================
Persistente Liste der Personen, die das System nutzen dürfen.

Identität:
  - Primärer Anker: telegram_chat_id (User schreibt /start an den Bot)
  - Web-/API-Zugang: web_token (jeder User bekommt einen eigenen Bearer-Token)

Rollen:
  - admin    : darf alle Endpoints inkl. /api/users, /api/config, /api/backup/*
  - user     : darf seine eigenen Resources (Parcels, Routinen, SubAgents, Memory)
  - pending  : hat /start geschickt, wartet auf Admin-Approval

Erste-Nutzer-Regel:
  Wenn beim register_pending() noch kein Admin existiert, wird der neue User
  direkt mit role="admin" angelegt (selbst-Bootstrap).

Persistenz: CONFIG_DIR / "users.json"  (atomic write via fileutils)
Per-User-Daten: CONFIG_DIR / "users" / {user_id} / parcels.json, routines.json, …
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from piclaw.config import CONFIG_DIR
from piclaw.fileutils import atomic_write_json

log = logging.getLogger("piclaw.users")


USERS_FILE = CONFIG_DIR / "users.json"
USERS_DIR  = CONFIG_DIR / "users"


# ── Datenmodell ───────────────────────────────────────────────────


@dataclass
class User:
    id: str
    name: str
    telegram_chat_id: str
    role: str            # "admin" | "user" | "pending"
    web_token: str
    created_at: str
    last_seen: str = ""
    # Per-User-Overrides: section → {key: value}, überschreibt cfg.<section>.<key>.
    # Beispiel:
    #   {"homeassistant": {"token": "abc", "base_url": "http://192.168.1.5:8123"},
    #    "agentmail":     {"email_address": "anna@agentmail.to", "inbox_id": "..."},
    #    "discord":       {"user_id": 123456789},
    #    "threema":       {"recipient_id": "ABC..."},
    #    "whatsapp":      {"recipient": "+49..."}}
    # Leeres Dict (default) → User nutzt die globalen Settings.
    overrides: dict = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_active(self) -> bool:
        return self.role in ("admin", "user")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Registry ──────────────────────────────────────────────────────


class UserRegistry:
    """In-Memory-Registry mit Disk-Backing. Threadsicher genug für Single-Process FastAPI."""

    def __init__(self, path: Path):
        self._path: Path = path
        self._users: dict[str, User] = {}
        self._load()
        log.info("Users geladen: %d (%d admin, %d user, %d pending)",
                 len(self._users),
                 sum(1 for u in self._users.values() if u.role == "admin"),
                 sum(1 for u in self._users.values() if u.role == "user"),
                 sum(1 for u in self._users.values() if u.role == "pending"))

    # ---- Persistence ---------------------------------------------------------

    def _read_disk(self) -> dict[str, User] | None:
        """Liest users.json. None = Datei fehlerhaft (wurde quarantänisiert)."""
        import json
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {d["id"]: User.from_dict(d) for d in data if "id" in d}
        except Exception as e:
            # Defekte Datei NIE liegen lassen: Der nächste Save würde sie
            # sonst endgültig überschreiben. Wegschieben, Original erhalten.
            quarantine = self._path.with_name(
                self._path.name + datetime.now().strftime(".corrupt-%Y%m%d-%H%M%S")
            )
            try:
                os.replace(self._path, quarantine)
                log.error("users.json fehlerhaft (%s) – nach '%s' verschoben",
                          e, quarantine.name)
            except OSError as move_err:
                log.error("users.json fehlerhaft (%s), Quarantäne fehlgeschlagen: %s",
                          e, move_err)
            return None

    def _load(self) -> None:
        self._users = self._read_disk() or {}

    def _reload_merged(self) -> None:
        """Frischen Disk-Stand laden, bestehende User-Objekte aber IN-PLACE
        aktualisieren – außen gehaltene Referenzen (API-Handler, Tests)
        bleiben so gültig. Bei fehlerhafter Datei bleibt der In-Memory-Stand
        (letzter bekannter guter Zustand) erhalten."""
        fresh = self._read_disk()
        if fresh is None:
            return
        for uid, new_u in fresh.items():
            cur = self._users.get(uid)
            if cur is None:
                self._users[uid] = new_u
            else:
                for f in User.__dataclass_fields__:
                    setattr(cur, f, getattr(new_u, f))
        for uid in list(self._users.keys()):
            if uid not in fresh:
                del self._users[uid]

    def _save(self) -> None:
        atomic_write_json(self._path, [u.to_dict() for u in self._users.values()])

    def _atomic_modify(self, mutate):
        """Read-Merge-Write unter File-Lock (Muster: ReminderStore).

        Lädt users.json unter dem Lock frisch (in-place gemerged), führt
        `mutate()` auf dem aktuellen Stand aus (arbeitet über self._users)
        und persistiert, wenn mutate truthy zurückgibt. Nötig weil drei
        Writer existieren: API-Endpoints, Telegram-Registrierung und
        cli_users als separater Prozess – ohne Re-Read unter Lock verliert
        der langsamste Writer die Änderungen der anderen.
        """
        from piclaw.fileutils import with_file_lock

        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with with_file_lock(self._path):
                self._reload_merged()
                result = mutate()
                if result:
                    self._save()
                return result
        except TimeoutError as e:
            log.error("User registry: Schreibzugriff nicht möglich – %s", e)
            return None

    # ---- Queries -------------------------------------------------------------

    def all(self) -> list[User]:
        return list(self._users.values())

    def active(self) -> list[User]:
        return [u for u in self._users.values() if u.is_active]

    def pending(self) -> list[User]:
        return [u for u in self._users.values() if u.role == "pending"]

    def admins(self) -> list[User]:
        return [u for u in self._users.values() if u.is_admin]

    def has_admin(self) -> bool:
        return any(u.is_admin for u in self._users.values())

    def find_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def find_by_chat_id(self, chat_id: str) -> User | None:
        chat_id = str(chat_id)
        for u in self._users.values():
            if u.telegram_chat_id == chat_id:
                return u
        return None

    def find_by_name(self, name: str) -> User | None:
        name_lc = name.lower()
        for u in self._users.values():
            if u.name.lower() == name_lc:
                return u
        return None

    def find_by_token(self, candidate: str) -> User | None:
        """Constant-time-Vergleich über alle aktiven User. Pending darf NICHT einloggen."""
        if not candidate:
            return None
        match: User | None = None
        for u in self._users.values():
            if not u.is_active:
                continue
            if secrets.compare_digest(u.web_token, candidate):
                match = u
                # kein break – Timing soll nicht von Position abhängen
        return match

    # ---- Mutations -----------------------------------------------------------

    def register_pending(self, name: str, telegram_chat_id: str) -> User:
        """
        Legt einen neuen User an.
        Wenn noch kein Admin existiert -> role="admin" (selbst-Bootstrap),
        sonst role="pending" (wartet auf Approval).

        Wenn die telegram_chat_id schon registriert ist, wird der bestehende
        User zurückgegeben (idempotent).
        """
        result: dict = {}

        def _mut() -> bool:
            existing = self.find_by_chat_id(telegram_chat_id)
            if existing is not None:
                result["user"] = existing
                return False

            role = "admin" if not self.has_admin() else "pending"
            user = User(
                id=str(uuid.uuid4()),
                name=name.strip() or f"user-{telegram_chat_id}",
                telegram_chat_id=str(telegram_chat_id),
                role=role,
                web_token=secrets.token_urlsafe(32),
                created_at=_now_iso(),
            )
            self._users[user.id] = user
            result["user"] = user
            log.info("User registriert: %s (id=%s, role=%s)", user.name, user.id, user.role)
            return True

        self._atomic_modify(_mut)
        return result.get("user")

    def approve(self, id_or_name: str) -> User | None:
        result: dict = {}

        def _mut() -> bool:
            u = self.find_by_id(id_or_name) or self.find_by_name(id_or_name)
            result["user"] = u
            if u is None or u.role != "pending":
                return False
            u.role = "user"
            log.info("User approved: %s (id=%s)", u.name, u.id)
            return True

        self._atomic_modify(_mut)
        return result.get("user")

    def revoke(self, id_or_name: str) -> bool:
        def _mut() -> bool:
            u = self.find_by_id(id_or_name) or self.find_by_name(id_or_name)
            if u is None:
                return False
            if u.is_admin and len(self.admins()) == 1:
                log.warning("Revoke abgelehnt: %s ist der letzte Admin.", u.name)
                return False
            del self._users[u.id]
            log.info("User entfernt: %s", u.name)
            return True

        return bool(self._atomic_modify(_mut))

    def set_role(self, user_id: str, role: str) -> User | None:
        if role not in ("admin", "user", "pending"):
            raise ValueError(f"Unbekannte Rolle: {role}")
        result: dict = {}

        def _mut() -> bool:
            u = self._users.get(user_id)
            result["user"] = u
            if u is None:
                return False
            # Letzten Admin nicht degradieren
            if u.is_admin and role != "admin" and len(self.admins()) == 1:
                log.warning("Demote abgelehnt: %s ist der letzte Admin.", u.name)
                return False
            u.role = role
            return True

        self._atomic_modify(_mut)
        return result.get("user")

    def regenerate_token(self, id_or_name: str) -> User | None:
        """Erzeugt einen neuen web_token. Alter Token wird sofort ungültig."""
        result: dict = {}

        def _mut() -> bool:
            u = self.find_by_id(id_or_name) or self.find_by_name(id_or_name)
            result["user"] = u
            if u is None:
                return False
            u.web_token = secrets.token_urlsafe(32)
            log.info("Token regeneriert für %s (id=%s).", u.name, u.id)
            return True

        self._atomic_modify(_mut)
        return result.get("user")

    def add_user(
        self,
        *,
        name: str,
        telegram_chat_id: str,
        role: str = "user",
        web_token: str | None = None,
    ) -> User:
        """
        CLI-Helfer: User explizit anlegen (umgeht /start-Workflow).
        Wirft ValueError bei doppelter chat_id.
        """
        if role not in ("admin", "user", "pending"):
            raise ValueError(f"Unbekannte Rolle: {role}")
        result: dict = {}

        def _mut() -> bool:
            if self.find_by_chat_id(telegram_chat_id) is not None:
                result["dupe"] = True
                return False
            user = User(
                id=str(uuid.uuid4()),
                name=name.strip() or f"user-{telegram_chat_id}",
                telegram_chat_id=str(telegram_chat_id),
                role=role,
                web_token=web_token or secrets.token_urlsafe(32),
                created_at=_now_iso(),
            )
            self._users[user.id] = user
            result["user"] = user
            log.info("User manuell angelegt: %s (id=%s, role=%s)", user.name, user.id, user.role)
            return True

        self._atomic_modify(_mut)
        if result.get("dupe"):
            raise ValueError(f"chat_id {telegram_chat_id} bereits registriert.")
        return result.get("user")

    # ── Per-User-Overrides ────────────────────────────────────────

    def set_override(self, user_id: str, section: str, key: str, value) -> bool:
        """Setzt einen Override-Wert. None entfernt den Key."""
        def _mut() -> bool:
            u = self._users.get(user_id)
            if u is None:
                return False
            if value is None:
                sect = u.overrides.get(section, {})
                sect.pop(key, None)
                if not sect:
                    u.overrides.pop(section, None)
                else:
                    u.overrides[section] = sect
            else:
                u.overrides.setdefault(section, {})[key] = value
            return True

        return bool(self._atomic_modify(_mut))

    def clear_override(self, user_id: str, section: str, key: str | None = None) -> bool:
        """Entfernt einen einzelnen Override-Key (key gesetzt) oder eine
        komplette Sektion (key=None)."""
        def _mut() -> bool:
            u = self._users.get(user_id)
            if u is None:
                return False
            if section not in u.overrides:
                return False
            if key is None:
                u.overrides.pop(section, None)
            else:
                u.overrides[section].pop(key, None)
                if not u.overrides[section]:
                    u.overrides.pop(section, None)
            return True

        return bool(self._atomic_modify(_mut))

    def get_override(self, user_id: str, section: str, key: str):
        """Liest einen Override-Wert. None wenn nicht gesetzt."""
        u = self._users.get(user_id)
        if u is None:
            return None
        return u.overrides.get(section, {}).get(key)

    def mark_seen(self, user_id: str) -> None:
        u = self._users.get(user_id)
        if u is not None:
            u.last_seen = _now_iso()
            # Kein _save() pro Request – last_seen darf eventually-consistent sein
            # und würde sonst bei jedem API-Call eine Disk-Write verursachen.

    def bootstrap_admin(
        self,
        *,
        name: str,
        telegram_chat_id: str,
        web_token: str,
    ) -> User:
        """
        Wird von der Migration aufgerufen: legt einen Admin mit vorgegebenem Token
        an (statt einen neuen zu generieren). Wirft RuntimeError wenn schon ein
        Admin existiert – sicheres Verhalten gegen versehentliches Überschreiben.
        """
        if self.has_admin():
            raise RuntimeError("bootstrap_admin: es existiert bereits ein Admin.")
        user = User(
            id=str(uuid.uuid4()),
            name=name,
            telegram_chat_id=str(telegram_chat_id),
            role="admin",
            web_token=web_token,
            created_at=_now_iso(),
        )
        self._users[user.id] = user
        self._save()
        log.info("Bootstrap-Admin angelegt: %s (id=%s)", user.name, user.id)
        return user


# ── Per-User-Pfade ─────────────────────────────────────────────────


def user_path(user_id: str, *parts: str) -> Path:
    """
    Liefert den Pfad CONFIG_DIR/users/{user_id}/<parts>.
    Erzeugt keine Verzeichnisse — das übernimmt ensure_user_dirs().
    """
    return USERS_DIR.joinpath(user_id, *parts)


def ensure_user_dirs(user_id: str) -> Path:
    """Legt das User-Datenverzeichnis und gängige Subdirs an. Idempotent."""
    base = user_path(user_id)
    base.mkdir(parents=True, exist_ok=True)
    (base / "memory").mkdir(exist_ok=True)
    (base / "memory" / "sessions").mkdir(exist_ok=True)
    return base


# ── Modul-Singleton + Convenience-Wrapper ──────────────────────────


_registry: UserRegistry | None = None


def registry() -> UserRegistry:
    """Globalen Singleton lazy initialisieren."""
    global _registry
    if _registry is None:
        _registry = UserRegistry(USERS_FILE)
    return _registry


def reload() -> UserRegistry:
    """Singleton neu laden (Tests, Migration, Hot-Reload)."""
    global _registry
    _registry = UserRegistry(USERS_FILE)
    return _registry


# Direkte Wrapper – damit Aufrufer nicht zwischen registry().foo() und users.foo()
# wechseln müssen. Stilistisch passt das zu auth.get_token() / set_token().

def find_by_token(candidate: str) -> User | None:
    return registry().find_by_token(candidate)


def find_by_chat_id(chat_id: str) -> User | None:
    return registry().find_by_chat_id(chat_id)


def find_by_id(user_id: str) -> User | None:
    return registry().find_by_id(user_id)


def has_admin() -> bool:
    return registry().has_admin()


def get_setting(
    user_id: str | None,
    section: str,
    key: str,
    fallback=None,
):
    """
    Pro-User-Setting mit Override-Priorität.

    - user_id=None  → liefert fallback (kein User-Kontext, also globale Sicht)
    - user_id gesetzt + Override vorhanden → Override-Wert
    - user_id gesetzt + kein Override → fallback

    Aufrufer übergibt typischerweise:
        get_setting(get_current_user_id(), "homeassistant", "token",
                    fallback=cfg.homeassistant.token)
    """
    if not user_id:
        return fallback
    val = registry().get_override(user_id, section, key)
    return val if val is not None else fallback


def get_setting_for_current(section: str, key: str, fallback=None):
    """Bequemer Wrapper: nutzt automatisch den aktuellen ContextVar-User."""
    from piclaw.agent_context import get_current_user_id
    return get_setting(get_current_user_id(), section, key, fallback)


# ── Helpers ────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

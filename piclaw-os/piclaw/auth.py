"""
PiClaw OS – API Authentication
==============================
Pro-User-Bearer-Token mit Migrations-Fallback auf den Legacy-Single-Token.

Design seit Multi-User (v0.18):
  - Jeder User in piclaw.users hat seinen eigenen web_token (Pro-User-Auth).
  - require_auth() liefert das `User`-Objekt – nicht mehr nur den Token-String.
  - Solange users.json keinen aktiven User enthält, fällt require_auth auf den
    Legacy-Token (`config.toml[api].secret_key`) zurück und liefert einen
    synthetischen "legacy-admin"-User. Das überbrückt die Migration.
  - Sobald ein echter Admin im Registry existiert, wird der Legacy-Token
    abgelehnt – Single-User-Mode ist dann formal vorbei.

Webhooks (/webhook/*) sind weiterhin exempt (eigene Signaturen).
/health und / sind weiterhin exempt.

Rate-Limiting: 10 Fehlversuche pro IP → 15 Min Lockout. Unverändert.

Migration siehe scripts/migrate_to_multiuser.py (Phase 6 im Multi-User-Plan).
"""

import secrets
import logging
import time
from collections import defaultdict
from fastapi import HTTPException, Security, Query, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from piclaw import users as users_mod
from piclaw.users import User

log = logging.getLogger("piclaw.auth")

_security = HTTPBearer(auto_error=False)

# Module-level Legacy-Token-Cache – set once by lifespan, read by Legacy-Fallback.
_legacy_token: str = ""

# ── Rate Limiting ─────────────────────────────────────────────────

_MAX_FAILURES = 10          # Fehlversuche pro IP bevor Lockout
_LOCKOUT_SECONDS = 900      # 15 Minuten Lockout
_CLEANUP_INTERVAL = 300     # Alte Einträge alle 5 Min aufräumen

_fail_counts: dict[str, int] = defaultdict(int)
_lockout_until: dict[str, float] = {}
_last_cleanup: float = 0.0


def _rate_limit_check(client_ip: str) -> None:
    """Prüft ob eine IP gesperrt ist. Räumt alte Einträge auf."""
    global _last_cleanup
    now = time.time()

    # Periodisches Cleanup
    if now - _last_cleanup > _CLEANUP_INTERVAL:
        expired = [ip for ip, t in _lockout_until.items() if t < now]
        for ip in expired:
            _lockout_until.pop(ip, None)
            _fail_counts.pop(ip, None)
        _last_cleanup = now

    # Lockout prüfen
    locked_until = _lockout_until.get(client_ip, 0)
    if locked_until > now:
        remaining = int(locked_until - now)
        log.warning("Rate-limited IP %s – noch %ds gesperrt", client_ip, remaining)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {remaining}s.",
        )


def _rate_limit_fail(client_ip: str) -> None:
    """Registriert einen fehlgeschlagenen Auth-Versuch."""
    _fail_counts[client_ip] += 1
    if _fail_counts[client_ip] >= _MAX_FAILURES:
        _lockout_until[client_ip] = time.time() + _LOCKOUT_SECONDS
        log.warning(
            "IP %s nach %d Fehlversuchen für %ds gesperrt",
            client_ip, _fail_counts[client_ip], _LOCKOUT_SECONDS,
        )


def _rate_limit_success(client_ip: str) -> None:
    """Setzt den Fehlerzähler bei Erfolg zurück."""
    _fail_counts.pop(client_ip, None)
    _lockout_until.pop(client_ip, None)


# ── Legacy-Token (Single-User-Mode, vor Migration) ────────────────


def set_token(token: str) -> None:
    """Legacy: vom Lifespan in api.py aufgerufen. Hält den Single-User-Token."""
    global _legacy_token
    _legacy_token = token


def get_token() -> str:
    """Legacy: HTML-Injection in api.py:121. Phase 5 ersetzt das durch Login."""
    return _legacy_token


def generate_token() -> str:
    """Generate a new cryptographically random token."""
    return secrets.token_urlsafe(32)


def _verify_legacy(candidate: str) -> bool:
    """Constant-time comparison gegen den Legacy-Token. Backwards-compat."""
    if not _legacy_token or not candidate:
        return False
    return secrets.compare_digest(_legacy_token, candidate)


def _legacy_admin_user() -> User:
    """Synthetischer User für Legacy-Token-Mode (vor Migration). Nicht persistiert."""
    return User(
        id="legacy-admin",
        name="Legacy Admin",
        telegram_chat_id="",
        role="admin",
        web_token=_legacy_token,
        created_at="",
    )


# Backwards-compat alias – einige Aufrufer nutzten `verify(...)`. Wird nur noch
# vom Legacy-Pfad benötigt; neue Aufrufer sollen users.find_by_token() nutzen.
verify = _verify_legacy


# ── Auth-Resolution ───────────────────────────────────────────────


def _resolve_user(candidate: str | None) -> User | None:
    """
    Token → User. Reihenfolge:
      1. Echter User aus users.json (Pro-User-Token)
      2. Legacy-Fallback NUR wenn noch kein aktiver User registriert ist
         (Migration noch nicht gelaufen).
    """
    if not candidate:
        return None
    user = users_mod.find_by_token(candidate)
    if user is not None:
        return user
    # Legacy-Fallback: nur solange das System noch im Single-User-Mode ist
    registry = users_mod.registry()
    if not registry.active() and _verify_legacy(candidate):
        return _legacy_admin_user()
    return None


# ── FastAPI dependencies ──────────────────────────────────────────


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
    token_param: str | None = Query(default=None, alias="token"),
) -> User:
    """
    Dependency for REST endpoints.
    Accepts token via:
      - Authorization: Bearer <token>  header
      - ?token=<token>                 query parameter (for WebSocket)
    Rate-limits failed attempts per IP (10 fails → 15 min lockout).
    Returns: das authentifizierte User-Objekt.
    """
    client_ip = request.client.host if request.client else "unknown"
    _rate_limit_check(client_ip)

    candidate: str | None = None
    if credentials and credentials.scheme.lower() == "bearer":
        candidate = credentials.credentials
    elif token_param:
        candidate = token_param

    user = _resolve_user(candidate)
    if user is None:
        _rate_limit_fail(client_ip)
        log.warning("Rejected API request from %s – invalid or missing token.", client_ip)
        raise HTTPException(
            status_code=401,
            detail="Unauthorized – valid Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _rate_limit_success(client_ip)
    # last_seen pflegen — nur für echte Registry-User, nicht für legacy-admin
    if user.id != "legacy-admin":
        users_mod.registry().mark_seen(user.id)
    return user


async def require_admin(user: User = Depends(require_auth)) -> User:
    """Dependency: erlaubt nur User mit role=admin."""
    if not user.is_admin:
        log.warning("Admin-Endpoint von Non-Admin '%s' (id=%s) abgewiesen.",
                    user.name, user.id)
        raise HTTPException(status_code=403, detail="Forbidden – admin only.")
    return user


async def require_auth_ws(token: str | None = Query(default=None)) -> User:
    """
    Dependency for WebSocket endpoints.
    Client must connect with: ws://host:port/ws/chat?token=<token>
    """
    user = _resolve_user(token)
    if user is None:
        # Ohne diese Zeile sind WS-Rejects im Journal unsichtbar – ein
        # Browser mit veraltetem Token reconnected dann alle 3s völlig stumm.
        log.warning("Rejected WebSocket connect – invalid or missing token.")
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.id != "legacy-admin":
        users_mod.registry().mark_seen(user.id)
    return user

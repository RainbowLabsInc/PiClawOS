"""
PiClaw OS – API Authentication
Single static Bearer token for the REST API and WebSocket.

Design:
  - One token per installation, auto-generated on first boot.
  - Stored in /etc/piclaw/config.toml under [api] secret_key.
  - Token is shown via `piclaw config get` and embedded in the web UI
    (injected into the HTML by the `/` route, since the server already
    knows it).
  - Webhooks (/webhook/*) are exempt – they use their own signature
    verification (HMAC for WhatsApp, Threema's own scheme).
  - /api/health is exempt for monitoring scripts.
  - Rate limiting: 10 failed attempts per IP → 15 min lockout.

Usage:
  from piclaw.auth import require_auth, generate_token, get_token

  @app.get("/api/something")
  async def endpoint(token: str = Depends(require_auth)):
      ...
"""

import secrets
import logging
import time
from collections import defaultdict
from fastapi import HTTPException, Security, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

log = logging.getLogger("piclaw.auth")

_security = HTTPBearer(auto_error=False)

# Module-level token cache – set once by lifespan, read by all requests.
_token: str = ""

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


def set_token(token: str):
    """Called by lifespan after loading/generating the token."""
    global _token
    _token = token


def get_token() -> str:
    """Return the current API token."""
    return _token


def generate_token() -> str:
    """Generate a new cryptographically random token."""
    return secrets.token_urlsafe(32)


def verify(candidate: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if not _token or not candidate:
        return False
    return secrets.compare_digest(_token, candidate)


# ── FastAPI dependencies ──────────────────────────────────────────


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
    token_param: str | None = Query(default=None, alias="token"),
) -> str:
    """
    Dependency for REST endpoints.
    Accepts token via:
      - Authorization: Bearer <token>  header
      - ?token=<token>                 query parameter (for WebSocket)
    Rate-limits failed attempts per IP (10 fails → 15 min lockout).
    """
    client_ip = request.client.host if request.client else "unknown"
    _rate_limit_check(client_ip)

    candidate = None

    if credentials and credentials.scheme.lower() == "bearer":
        candidate = credentials.credentials
    elif token_param:
        candidate = token_param

    if not candidate or not verify(candidate):
        _rate_limit_fail(client_ip)
        log.warning("Rejected API request from %s – invalid or missing token.", client_ip)
        raise HTTPException(
            status_code=401,
            detail="Unauthorized – valid Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _rate_limit_success(client_ip)
    return candidate


async def require_auth_ws(token: str | None = Query(default=None)) -> str:
    """
    Dependency for WebSocket endpoints.
    Client must connect with: ws://host:port/ws/chat?token=<token>
    """
    if not token or not verify(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token

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

Usage:
  from piclaw.auth import require_auth, generate_token, get_token

  @app.get("/api/something")
  async def endpoint(token: str = Depends(require_auth)):
      ...
"""

import secrets
import logging
from fastapi import HTTPException, Security, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

log = logging.getLogger("piclaw.auth")

_security = HTTPBearer(auto_error=False)

# Module-level token cache – set once by lifespan, read by all requests.
_token: str = ""


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
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
    token_param: str | None = Query(default=None, alias="token"),
) -> str:
    """
    Dependency for REST endpoints.
    Accepts token via:
      - Authorization: Bearer <token>  header
      - ?token=<token>                 query parameter (for WebSocket)
    """
    candidate = None

    if credentials and credentials.scheme.lower() == "bearer":
        candidate = credentials.credentials
    elif token_param:
        candidate = token_param

    if not candidate or not verify(candidate):
        log.warning("Rejected API request – invalid or missing token.")
        raise HTTPException(
            status_code=401,
            detail="Unauthorized – valid Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return candidate


async def require_auth_ws(token: str | None = Query(default=None)) -> str:
    """
    Dependency for WebSocket endpoints.
    Client must connect with: ws://host:port/ws/chat?token=<token>
    """
    if not token or not verify(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token

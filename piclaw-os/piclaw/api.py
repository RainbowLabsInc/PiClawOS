"""
PiClaw OS – REST + WebSocket API
Serves the web dashboard and exposes the agent via WebSocket chat.
Port: 7842

Authentication:
  All /api/* endpoints require:  Authorization: Bearer <token>
  WebSocket (/ws/chat) requires: ?token=<token> query param
  Exempt: /, /health, /webhook/* (own signature verification)

The token is auto-generated on first boot, stored in config.toml,
and injected into the web UI HTML by the / route.
"""

import asyncio
import json
import logging
import psutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager, suppress as contextlib_suppress

from piclaw.config   import load as load_cfg, save as save_cfg, PiClawConfig
from piclaw.agent    import Agent
from piclaw.llm.base import Message
from piclaw.messaging import build_hub, IncomingMessage
from piclaw.auth     import require_auth, require_auth_ws, require_admin, set_token, generate_token
from piclaw.taskutils import create_background_task
from piclaw.request_context import new_request_id, request_scope
from piclaw.logging_setup import configure_logging
from piclaw.users    import User
from piclaw import users as users_mod
from piclaw.agents import sa_history

log = logging.getLogger("piclaw.api")

_cfg:   PiClawConfig = load_cfg()
_agent: Agent        = None
_hub                 = None   # MessagingHub


async def _agent_message_handler(msg: IncomingMessage) -> str:
    """Route incoming message from any platform to the agent.
    msg.user_id wird an Agent.run gegeben → setzt ContextVar für Tool-Handler.
    """
    if not _agent:
        return "Agent not ready yet."
    return await _agent.run(msg.text, user_id=msg.user_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cfg, _agent, _hub

    # ── Logging: INFO statt Python-Default WARNING ─────────────────
    # configure_logging() installiert ContextFilter (request_id) und wählt
    # JSON-Format wenn PICLAW_LOG_FORMAT=json gesetzt ist, sonst Text mit
    # automatischem [rid=xxxxxxxx] Suffix sobald eine ID im Scope steht.
    configure_logging(level=logging.INFO)

    # ── Token: generate once, persist in config ────────────────────
    if not _cfg.api.secret_key:
        _cfg.api.secret_key = generate_token()
        save_cfg(_cfg)
        log.info("Generated new API token and saved to config.")
    set_token(_cfg.api.secret_key)
    log.info("API token loaded (first 8 chars: %.8s…)", _cfg.api.secret_key)

    _agent = Agent(_cfg)
    create_background_task(_agent.boot(start_sub_agents=False), name="agent-boot")
    _hub = build_hub(_cfg)
    _agent._telegram_send = lambda text: create_background_task(_hub.send_all(text))
    # Multi-User: Sub-Agents mit owner_id senden ihre Notifications an die
    # chat_id des Owners (statt an die Default-chat_id). Fallback wenn der User
    # nicht gefunden wird, liegt in hub.send_to_user / runner._send_notify.
    _agent._telegram_send_to_user = lambda text, user_id: create_background_task(
        _hub.send_to_user(user_id, text)
    )
    create_background_task(_hub.start(_agent_message_handler), name="messaging-hub")
    log.info("PiClaw API started on :%s", _cfg.api.port)
    yield
    # ── Graceful shutdown ──────────────────────────────────────────
    if _agent and _agent.sa_runner:
        n = await _agent.sa_runner.stop_all()
        if n:
            log.info("Stopped %s sub-agent(s).", n)
    if _hub:
        await _hub.stop()


# ── App setup ─────────────────────────────────────────────────

app = FastAPI(title="PiClaw OS", version="0.8.0", docs_url=None, lifespan=lifespan)

# CORS-Defaults sind absichtlich restriktiv: WS-Auth laeuft ueber Query-Param,
# REST ueber Bearer-Token. allow_credentials muss daher nicht True sein.
# Origins kommt aus der Config; wenn ein Operator wirklich Wildcard will,
# muss er das explizit als "*" setzen.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.api.cors_origins or [],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Obs.1: Request-ID-Middleware ───────────────────────────────────
# Jeder HTTP-Request bekommt eine eigene UUID. Bestehender Code, der
# einen X-Request-ID-Header mitsendet (z.B. ein Reverse-Proxy), wird
# respektiert; sonst wird eine generiert. Die ID landet als ContextVar
# in allen Sub-Aufrufen (LLM-Routing, Memory, Tools) und kann via
# /api/trace/{request_id} später nachverfolgt werden. Auch in jeder
# Response als X-Request-ID-Header zurückgegeben, damit Konsumenten
# Logs korrelieren können ohne den Server fragen zu müssen.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "").strip()
    rid = incoming if (incoming and len(incoming) <= 64) else new_request_id()
    with request_scope(rid):
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


# ── Public endpoints (no auth) ────────────────────────────────────

@app.get("/health")
async def health():
    """Unauthenticated health check for monitoring scripts."""
    return {"status": "ok", "agent": _cfg.agent_name if _cfg else "PiClaw"}


@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Serve web UI.
    Multi-User: kein Token mehr im HTML injiziert. Der Client liest seinen
    Token aus LocalStorage (Key: `piclaw_token`) und wird beim ersten Besuch
    via prompt() danach gefragt. Der User holt den Token via `/web_token`
    im Telegram-Bot oder via `piclaw user token <name>` per SSH.
    """
    html_path = Path(__file__).parent / "web" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>PiClaw OS</h1><p>Web UI not found.</p>")
    html = html_path.read_text(encoding="utf-8")
    # Login-Bootstrap: Token aus LocalStorage oder prompten
    bootstrap = (
        "<script>(function(){\n"
        "  let t = localStorage.getItem('piclaw_token');\n"
        "  if (!t) {\n"
        "    t = prompt('PiClaw Web-Token (im Telegram /web_token, oder per CLI piclaw user token <Name>):');\n"
        "    if (t) localStorage.setItem('piclaw_token', t);\n"
        "  }\n"
        "  window.PICLAW_TOKEN = t || '';\n"
        "  window.PICLAW_LOGOUT = function(){ localStorage.removeItem('piclaw_token'); location.reload(); };\n"
        "})();</script>"
    )
    html = html.replace("</head>", f"{bootstrap}\n</head>", 1)
    return HTMLResponse(html)


# ── Webhook endpoints (own auth, exempt from Bearer) ──────────────

@app.get("/webhook/whatsapp")
async def whatsapp_verify(
    hub_mode:         str | None = None,
    hub_challenge:    str | None = None,
    hub_verify_token: str | None = None,
):
    from fastapi.responses import PlainTextResponse
    if not _hub:
        raise HTTPException(503)
    for adapter in _hub._adapters:
        if adapter.name == "whatsapp":
            result = await adapter.verify_webhook(
                hub_mode or "", hub_verify_token or "", hub_challenge or ""
            )
            if result:
                return PlainTextResponse(result)
    raise HTTPException(403, "Verification failed")


@app.post("/webhook/whatsapp")
async def whatsapp_incoming(request: Request):
    body    = await request.body()
    sig     = request.headers.get("X-Hub-Signature-256", "")
    payload = await request.json()
    if not _hub:
        return {"status": "not ready"}
    for adapter in _hub._adapters:
        if adapter.name == "whatsapp":
            if not adapter.verify_signature(body, sig):
                raise HTTPException(403, "Invalid signature")
            await adapter.handle_webhook(payload)
    return {"status": "ok"}


@app.post("/webhook/threema")
async def threema_incoming(request: Request):
    if not _hub:
        return {"status": "not ready"}
    auth_header = request.headers.get("Authorization", "")
    payload = await request.json()
    for adapter in _hub._adapters:
        if adapter.name == "threema":
            if not adapter.verify_token(auth_header):
                raise HTTPException(403, "Invalid webhook token")
            await adapter.handle_webhook(payload, _agent_message_handler)
    return {"status": "ok"}


# ── Authenticated API endpoints ───────────────────────────────────
# All routes below require: Authorization: Bearer <token>

@app.get("/api/messaging")
async def messaging_status(_: User = Depends(require_auth)):
    if not _hub:
        return {"adapters": []}
    return {"adapters": _hub.active_adapters()}


# ── User Management (Admin) ───────────────────────────────────────


@app.get("/api/whoami")
async def whoami(user: User = Depends(require_auth)):
    """Wer bin ich? Liefert das eigene User-Objekt (ohne web_token)."""
    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "telegram_chat_id": user.telegram_chat_id,
        "is_admin": user.is_admin,
        "last_seen": user.last_seen,
    }


def _user_to_dict(u: User, include_token: bool = False) -> dict:
    d = {
        "id": u.id, "name": u.name, "role": u.role,
        "telegram_chat_id": u.telegram_chat_id,
        "created_at": u.created_at, "last_seen": u.last_seen,
    }
    if include_token:
        d["web_token"] = u.web_token
    return d


@app.get("/api/users")
async def list_users(_: User = Depends(require_admin)):
    """Admin: Liste aller aktiven User (ohne Tokens)."""
    reg = users_mod.registry()
    return {"users": [_user_to_dict(u) for u in reg.active()]}


@app.get("/api/users/pending")
async def list_pending(_: User = Depends(require_admin)):
    """Admin: User die /start gemacht haben und auf Freigabe warten."""
    reg = users_mod.registry()
    return {"pending": [_user_to_dict(u) for u in reg.pending()]}


@app.post("/api/users/{id_or_name}/approve")
async def approve_user(id_or_name: str, _: User = Depends(require_admin)):
    """Admin: pending User → user."""
    reg = users_mod.registry()
    u = reg.approve(id_or_name)
    if u is None:
        raise HTTPException(404, f"User '{id_or_name}' not found")
    return {"approved": True, "user": _user_to_dict(u)}


@app.post("/api/users/{id_or_name}/revoke")
async def revoke_user(id_or_name: str, _: User = Depends(require_admin)):
    """Admin: User entfernen. Letzter Admin kann sich nicht selbst entfernen."""
    reg = users_mod.registry()
    target = reg.find_by_id(id_or_name) or reg.find_by_name(id_or_name)
    if target is None:
        raise HTTPException(404, f"User '{id_or_name}' not found")
    if not reg.revoke(target.id):
        raise HTTPException(409, "Cannot revoke last admin")
    return {"revoked": True, "name": target.name}


# ── Sub-agent endpoints ───────────────────────────────────────────

@app.get("/api/subagents")
async def subagents_status(user: User = Depends(require_auth)):
    """Sub-Agenten: User sieht eigene + System; Admin (oder Lookup mit
    user_id=None) sieht alle."""
    if not _agent or not _agent.sa_runner:
        return {"sub_agents": []}
    full = _agent.sa_runner.status_dict()
    # Frischere Laufdaten aus der History-Datei überlagern: die Registry
    # dieses Prozesses sieht Daemon-Läufe erst nach Prozess-Neustart
    # (kein Hot-Reload), die History-Datei ist immer aktuell.
    latest = sa_history.latest_per_agent()
    for a in full.get("sub_agents", []):
        entry = latest.get(a.get("id"))
        if not entry:
            continue
        if not a.get("last_run") or entry["ts"] > a["last_run"]:
            a["last_run"] = entry["ts"]
            if not a.get("running"):
                a["last_status"] = entry["status"]
        a["last_result"] = entry.get("result")
        a["last_duration_s"] = entry.get("duration_s")
    if user.is_admin:
        return full
    # Non-admin: filter durch sa_registry
    visible_ids = {a.id for a in _agent.sa_registry.list_all(user.id)}
    full["sub_agents"] = [a for a in full.get("sub_agents", []) if a.get("id") in visible_ids]
    return full


@app.post("/api/subagents")
async def subagent_create(request: Request, user: User = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    body     = await request.json()
    required = ("name", "description", "mission")
    missing  = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(400, f"Missing required fields: {missing}")
    from piclaw.agents.sa_registry import SubAgentDef
    # Multi-User: API-erstellte Sub-Agenten gehören dem aufrufenden User.
    # Admins können privileged/trusted setzen, Non-Admin nicht.
    owner_id = None if user.is_admin else user.id
    agent_def = SubAgentDef(
        name        = body["name"],
        description = body["description"],
        mission     = body["mission"],
        tools       = body.get("tools", []),
        schedule    = body.get("schedule", "once"),
        llm_tags    = body.get("llm_tags", []),
        notify      = body.get("notify", True),
        trusted     = body.get("trusted", False) if user.is_admin else False,
        privileged  = body.get("privileged", False) if user.is_admin else False,
        max_steps   = body.get("max_steps", 10),
        timeout     = body.get("timeout", 300),
        created_by  = "api",
        owner_id    = owner_id,
    )
    agent_id = _agent.sa_registry.add(agent_def)
    if body.get("start_now"):
        await _agent.sa_runner.start_agent(agent_id)
    return {"id": agent_id, "name": agent_def.name, "created": True}


@app.delete("/api/subagents/{name}")
async def subagent_remove(name: str, user: User = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    sa = _agent.sa_registry.get(name)
    if not sa:
        raise HTTPException(404, f"Sub-agent '{name}' not found")
    # Multi-User: nur eigene oder Admin darf System-Sub-Agenten löschen
    if not sa.visible_to(user.id):
        raise HTTPException(404, f"Sub-agent '{name}' not found")
    if sa.is_system and not user.is_admin:
        raise HTTPException(403, "Only admins can remove system sub-agents")
    agent_id = sa.id
    # API process: stop our copy of the task (no-op for the daemon's task,
    # different process), then remove from our registry memory + disk.
    if agent_id in _agent.sa_runner._tasks and not _agent.sa_runner._tasks[agent_id].done():
        await _agent.sa_runner.stop_agent(name)
    removed = _agent.sa_registry.remove(name)
    # Daemon process: tell it to stop its schedule-loop and drop from memory.
    # Without this the daemon would keep firing the agent on schedule and
    # its next mark_run save would resurrect the deleted entry.
    from piclaw import ipc
    ipc.write_remove(agent_id)
    return {"removed": removed, "name": name}


@app.post("/api/subagents/{name}/start")
async def subagent_start(name: str, _: str = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    result = await _agent.sa_runner.start_agent(name)
    return {"result": result}


@app.post("/api/subagents/{name}/stop")
async def subagent_stop(name: str, _: str = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    result = await _agent.sa_runner.stop_agent(name)
    return {"result": result}


@app.post("/api/subagents/{name}/run")
async def subagent_run_now(name: str, _: str = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    sa = _agent.sa_registry.get(name)
    if not sa:
        raise HTTPException(404, f"Sub-agent '{name}' not found")
    create_background_task(
        _agent.sa_runner._execute(sa),
        name=f"subagent-api-run-{sa.id}",
    )
    return {"triggered": True, "name": name}


@app.get("/api/subagents/{name}/history")
async def subagent_history(name: str, limit: int = 20, user: User = Depends(require_auth)):
    """Letzte Läufe eines Sub-Agenten (neuester zuerst), aus sa_history."""
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    sa = _agent.sa_registry.get(name)
    if not sa or not sa.visible_to(None if user.is_admin else user.id):
        raise HTTPException(404, f"Sub-agent '{name}' not found")
    return {
        "id": sa.id,
        "name": sa.name,
        "history": sa_history.history_for(sa.id, limit),
    }


# ── Einkaufsliste ─────────────────────────────────────────────────
#
# Nur GET/POST/DELETE – die CORS-Middleware oben laesst PUT/PATCH nicht zu.
# Sichtbarkeit wie bei Sub-Agenten: fremde Artikel geben 404 statt 403,
# damit die Existenz nicht durchsickert.


def _shopping_scope(user: User) -> str | None:
    """None = sieht alles (Admin), sonst die eigene User-ID."""
    return None if user.is_admin else user.id


def _shopping_item_or_404(db, item_id: int, user: User):
    item = db.get_item(item_id)
    if not item or (not user.is_admin and item.owner_id not in (None, user.id)):
        raise HTTPException(404, f"Artikel {item_id} nicht gefunden")
    return item


@app.get("/api/shopping/items")
async def shopping_items(_days: int = 90, user: User = Depends(require_auth)):
    """Liste inkl. bestem aktuellem Preis und Trend."""
    try:
        from piclaw.shopping import analysis
        from piclaw.shopping.store import get_db

        db = get_db()
        out = []
        for item in db.list_items(owner_id=_shopping_scope(user)):
            history = db.item_history(item.id)
            best = db.best_current(item.id)
            verdict = None
            if best and history:
                verdict = analysis.evaluate(history[:-1], best["price"])
            out.append({
                **item.to_dict(),
                "best": best,
                # Bestes Preis-Leistungs-Verhaeltnis – kann ein anderes
                # Produkt sein als der niedrigste Absolutpreis.
                "best_unit": db.best_unit_price(item.id),
                "trend": analysis.trend(history),
                "points": len(history),
                "status": verdict.describe() if verdict else "Datenaufbau läuft",
                "is_drop": bool(verdict and verdict.is_drop),
            })
        return {"items": out}
    except Exception as e:
        log.exception("shopping_items: %s", e)
        return {"error": str(e), "items": []}


@app.post("/api/shopping/items")
async def shopping_item_create(request: Request, user: User = Depends(require_auth)):
    from piclaw.shopping.store import get_db

    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Feld 'name' fehlt")

    db = get_db()
    owner_id = _shopping_scope(user)
    if db.find_item_by_name(name, owner_id=owner_id):
        raise HTTPException(409, f"'{name}' steht schon auf der Liste")

    max_price = body.get("max_price")
    try:
        max_price = float(max_price) if max_price not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "max_price muss eine Zahl sein") from None

    item = db.add_item(
        name,
        query=(body.get("query") or "").strip(),
        qty=(body.get("qty") or "").strip(),
        max_price=max_price,
        owner_id=owner_id,
    )
    return {"created": True, **item.to_dict()}


@app.delete("/api/shopping/items/{item_id}")
async def shopping_item_remove(item_id: int, user: User = Depends(require_auth)):
    from piclaw.shopping.store import get_db

    db = get_db()
    item = _shopping_item_or_404(db, item_id, user)
    return {"removed": db.remove_item(item.id), "name": item.name}


@app.get("/api/shopping/items/{item_id}/history")
async def shopping_item_history(
    item_id: int, days: int = 90, user: User = Depends(require_auth)
):
    """Preisreihe fuer die Sparkline.

    Format {data:[{ts,value}]} wie /api/metrics/chart/{name}, damit das
    Dashboard dieselbe Chart-Funktion nutzen kann.
    """
    import time

    from piclaw.shopping.store import get_db

    db = get_db()
    item = _shopping_item_or_404(db, item_id, user)
    since = int(time.time()) - max(1, days) * 86_400
    series = db.item_history_detailed(item.id, since_ts=since)
    return {
        "id": item.id,
        "name": item.name,
        "days": days,
        # value/ts wie bei /api/metrics/chart, damit die Chart-Funktion passt;
        # retailer/title beantworten zusaetzlich "wo war es an dem Tag am
        # guenstigsten".
        "data": [
            {"ts": p["ts"], "value": p["price"], "retailer": p["retailer"],
             "title": p["title"], "unit_price_text": p["unit_price_text"]}
            for p in series
        ],
        "retailers": db.retailer_summary(item.id, since_ts=since),
        "products": [
            {**p.to_dict(), "points": len(db.history(p.id, since_ts=since))}
            for p in db.list_products(item.id)
        ],
    }


@app.post("/api/shopping/test")
async def shopping_test_query(request: Request, _: User = Depends(require_auth)):
    """Live-Test eines Suchbegriffs, ohne etwas zu speichern.

    Der Testen-Knopf im Dashboard: zeigt sofort, ob ein Begriff ueberhaupt
    Treffer liefert. Faengt Tippfehler ab und macht sichtbar, dass
    zusammengesetzte Woerter oft nichts finden.
    """
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Feld 'query' fehlt")
    return await _shopping_probe(query)


@app.post("/api/shopping/items/{item_id}/test")
async def shopping_test_item(item_id: int, user: User = Depends(require_auth)):
    from piclaw.shopping.store import get_db

    db = get_db()
    item = _shopping_item_or_404(db, item_id, user)
    return await _shopping_probe(item.search_term, strict=item.strict_matching)


async def _shopping_probe(query: str, strict: bool = True) -> dict:
    import aiohttp

    from piclaw.shopping import location
    from piclaw.shopping.matching import matches_item, normalize_title
    from piclaw.shopping.providers import search_all

    try:
        cfg = location._shopping_cfg(None)
        async with aiohttp.ClientSession() as session:
            home, _surroundings = await location.resolve(session)
            offers = await search_all(
                session, query,
                zip_code=home.zip_code if home else "",
                lat=home.lat if home else None,
                lon=home.lon if home else None,
                providers=cfg.providers, active_only=True, limit=20,
            )
        matched, rejected = [], []
        for offer in offers:
            passt = not strict or matches_item(
                normalize_title(offer.brand, offer.title), query
            )
            (matched if passt else rejected).append(offer.to_dict())
        return {
            "query": query,
            "matches": matched[:8],
            "rejected": rejected[:5],
            "total": len(matched),
        }
    except Exception as e:
        log.exception("shopping test '%s': %s", query, e)
        return {"query": query, "error": str(e), "matches": [], "rejected": []}


@app.get("/api/shopping/home")
async def shopping_home_get(_: User = Depends(require_auth)):
    """Aktuelle Heimatadresse – befuellt das Formular im Dashboard vor."""
    from piclaw.shopping import location

    try:
        cfg = load_cfg()
        street, house_number, zip_code, city, country = location.address_parts(cfg)
        sc = location._shopping_cfg(cfg)
        return {
            "street": street,
            "house_number": house_number,
            "zip_code": zip_code,
            "city": city,
            "country": country,
            # Gleiche Quelle wie die Umkreissuche, inkl. Per-User-Override –
            # sonst zeigt das Formular einen anderen Radius als gesucht wird.
            "radius_km": location._user_override(
                "shopping", "radius_km", sc.radius_km
            ),
            "configured": bool(street or zip_code or city),
            # Sind Koordinaten fest gesetzt, haben sie Vorrang – das muss die
            # UI wissen, sonst wundert sich der Nutzer, warum die Adresse
            # keine Wirkung hat.
            "coords_override": getattr(sc, "home_latitude", None) is not None,
        }
    except Exception as e:
        log.exception("shopping_home_get: %s", e)
        return {"error": str(e), "configured": False}


@app.post("/api/shopping/home")
async def shopping_home_set(request: Request, _: User = Depends(require_admin)):
    """Setzt die Heimatadresse und meldet zurueck, wie genau sie auflöst.

    require_admin, weil das die globale config.toml aendert.

    Antwortet immer mit der Genauigkeit: ein PLZ-Zentroid als Mittelpunkt
    macht alle Entfernungen wertlos, und das darf nicht stillschweigend
    passieren.
    """
    import aiohttp

    from piclaw.shopping import location

    body = await request.json()
    street = (body.get("street") or "").strip()
    zip_code = (body.get("zip_code") or "").strip()
    city = (body.get("city") or "").strip()
    if not (street or zip_code or city):
        raise HTTPException(400, "Mindestens Straße, PLZ oder Ort angeben")

    radius = body.get("radius_km")
    try:
        radius = float(radius) if radius not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "radius_km muss eine Zahl sein") from None

    try:
        location.write_home_address(
            street=street,
            house_number=(body.get("house_number") or "").strip(),
            zip_code=zip_code,
            city=city,
            country=(body.get("country") or "de").strip().lower(),
            radius_km=radius,
        )
    except Exception as e:
        log.exception("Heimatadresse schreiben fehlgeschlagen: %s", e)
        raise HTTPException(500, f"config.toml nicht schreibbar: {e}") from None

    cfg = load_cfg()
    async with aiohttp.ClientSession() as session:
        home = await location.resolve_home(session, cfg=cfg, force=True)

    if home is None:
        return {
            "saved": True, "resolved": False, "exact": False,
            "warning": ("Adresse gespeichert, aber nicht auffindbar. "
                        "Schreibweise prüfen oder Koordinaten direkt setzen."),
        }
    return {
        "saved": True,
        "resolved": True,
        "exact": home.is_exact,
        "precision": home.precision,
        "zip_code": home.zip_code,
        "warning": home.warning,
    }


@app.get("/api/shopping/stores")
async def shopping_stores_list(refresh: bool = False, _: User = Depends(require_auth)):
    import aiohttp

    from piclaw.shopping import location

    try:
        async with aiohttp.ClientSession() as session:
            home, surroundings = await location.resolve(session, force=refresh)
        if home is None:
            return {"configured": False, "shops": [],
                    "hint": "Kein Wohnort hinterlegt"}
        return {
            "configured": True,
            "radius_km": surroundings.radius_km,
            "precision": home.precision,
            "exact": home.is_exact,
            "warning": home.warning,
            "from_cache": surroundings.from_cache,
            "shops": surroundings.shops,
        }
    except Exception as e:
        log.exception("shopping_stores: %s", e)
        return {"error": str(e), "shops": []}


@app.post("/api/shopping/basket")
async def shopping_basket_compare(user: User = Depends(require_auth)):
    """In welchem einzelnen Laden ist der ganze Einkauf am guenstigsten?

    Sucht live ueber alle Artikel – das dauert einige Sekunden und laeuft
    deshalb bewusst auf Knopfdruck, nicht beim Laden der Seite.
    """
    import aiohttp

    from piclaw.shopping import basket, location
    from piclaw.shopping.store import get_db

    try:
        db = get_db()
        items = [i for i in db.list_items(owner_id=_shopping_scope(user))
                 if not i.muted]
        if not items:
            return {"error": "Die Einkaufsliste ist leer.", "stores": []}

        async with aiohttp.ClientSession() as session:
            home, surroundings = await location.resolve(session)
            if home is None:
                return {"error": "Kein Wohnort hinterlegt.", "stores": []}
            ergebnis = await basket.compare(session, items, home, surroundings)
        return ergebnis.to_dict()
    except Exception as e:
        log.exception("shopping_basket: %s", e)
        return {"error": str(e), "stores": []}


@app.post("/api/shopping/sample")
async def shopping_sample_now(_: User = Depends(require_admin)):
    """Loest den Preis-Sammellauf sofort aus (sonst taeglich 06:00)."""
    from piclaw.shopping.sampler import run_sample

    create_background_task(run_sample(), name="shopping-sample-api")
    return {"triggered": True}


# ── Soul endpoints ────────────────────────────────────────────────

@app.get("/api/soul")
async def soul_get(_: str = Depends(require_auth)):
    from piclaw import soul as soul_mod
    return {"content": soul_mod.load(), "path": str(soul_mod.get_path())}


@app.post("/api/soul")
async def soul_set(request: Request, _: User = Depends(require_admin)):
    from piclaw import soul as soul_mod
    body    = await request.json()
    content = body.get("content", "")
    if not content.strip():
        raise HTTPException(400, "Content cannot be empty")
    result = soul_mod.save(content)
    return {"result": result}


@app.post("/api/soul/append")
async def soul_append(request: Request, _: User = Depends(require_admin)):
    from piclaw import soul as soul_mod
    body    = await request.json()
    section = body.get("section", "")
    if not section.strip():
        raise HTTPException(400, "Section cannot be empty")
    result = soul_mod.append(section)
    return {"result": result}


# ── Memory endpoints ──────────────────────────────────────────────

@app.get("/api/memory/stats")
async def memory_stats(_: str = Depends(require_auth)):
    if not _agent:
        return {}
    from piclaw.memory.store import memory_stats as ms
    s      = ms()
    status = await _agent.qmd.status()
    return {**s, **status}


@app.get("/api/memory/search")
async def memory_search(q: str, collection: str = "all", mode: str = "query",
                        _: str = Depends(require_auth)):
    if not _agent or not q:
        return {"results": []}
    col     = None if collection == "all" else collection
    results = await _agent.qmd.search(q, top_k=8, collection=col, mode=mode)
    return {"results": [
        {"text": r.text, "source": r.source,
         "score": round(r.score, 3), "collection": r.collection}
        for r in results
    ]}


# ── System endpoints ──────────────────────────────────────────────

@app.get("/api/mode")
async def llm_mode(_: str = Depends(require_auth)):
    if not _agent:
        return {"mode": "booting", "backends": []}
    return _agent.llm.get_status_dict()


@app.get("/api/llm/health")
async def llm_health(_: str = Depends(require_auth)):
    """Health-Monitor-Status (Rate-Limits, letzte Fehler) aus der vom
    Daemon zyklisch geschriebenen Status-Datei. Der Monitor läuft nur im
    piclaw-agent-Prozess; read_status_file() enthält den 10-min-Staleness-
    Cutoff bereits."""
    from piclaw.llm import health_monitor

    return health_monitor.read_status_file()


@app.get("/api/stats")
async def stats(_: str = Depends(require_auth)):
    cpu_pct = psutil.cpu_percent(interval=0.2)
    mem     = psutil.virtual_memory()
    disk    = psutil.disk_usage("/")
    boot_ts = psutil.boot_time()
    uptime  = int(datetime.now().timestamp() - boot_ts)
    h, r    = divmod(uptime, 3600)
    m, s    = divmod(r, 60)

    temp = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as _f:
            temp = int(_f.read().strip()) / 1000
    except Exception:
        try:
            t = psutil.sensors_temperatures()
            for entries in t.values():
                if entries: temp = entries[0].current; break
        except Exception as _e:
            log.debug("psutil temp fallback: %s", _e)

    import socket
    loop = asyncio.get_running_loop()
    try:
        hostname = socket.gethostname()
        # run_in_executor: gethostbyname kann mDNS-Lookup blockieren
        ip = await loop.run_in_executor(None, socket.gethostbyname, hostname)
    except Exception:
        hostname, ip = "piclaw", "unknown"

    return {
        "cpu_percent":  cpu_pct,
        "cpu_cores":    psutil.cpu_count(),
        "temp_celsius": temp,
        "memory": {
            "used_mb":  mem.used  // 1_048_576,
            "total_mb": mem.total // 1_048_576,
            "percent":  mem.percent,
        },
        "disk": {
            "used_gb":  round(disk.used  / 1_073_741_824, 1),
            "total_gb": round(disk.total / 1_073_741_824, 1),
            "percent":  disk.percent,
        },
        "uptime":   f"{h}h {m}m {s}s",
        "hostname": hostname,
        "ip":       ip,
        "agent":    _cfg.agent_name if _cfg else "PiClaw",
        "llm":      f"{_cfg.llm.backend}/{_cfg.llm.model}" if _cfg else "",
    }


@app.get("/api/services")
async def services(_: str = Depends(require_auth)):
    if not _cfg:
        return []
    result = []
    for name in _cfg.services.managed:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        state = out.decode().strip()
        if not state:
            state = "inactive"
        result.append({"name": name, "state": state, "active": state == "active"})
    return result


@app.get("/api/config")
async def get_config(_: str = Depends(require_auth)):
    """Safe subset of config – never returns secret_key or API keys."""
    if not _cfg:
        return {}
    return {
        "agent_name":  _cfg.agent_name,
        "llm_backend": _cfg.llm.backend,
        "llm_model":   _cfg.llm.model,
        "api_port":    _cfg.api.port,
    }


# ── WebSocket Chat ────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)

    async def send(self, ws: WebSocket, data: dict):
        try:
            await ws.send_text(json.dumps(data))
        except Exception as _e:
            log.debug("WS send failed (client disconnected): %s", _e)


_manager = ConnectionManager()
_sessions: dict[str, list[Message]] = {}


# ── Hardware endpoints ────────────────────────────────────────────

@app.get("/api/hardware")
async def hardware_info(_: str = Depends(require_auth)):
    """Pi hardware telemetry: model, temp, throttle, clocks, voltages."""
    try:
        from piclaw.hardware.pi_info import read_pi_info
        from piclaw.hardware.thermal import get_thermal_state
        info    = await read_pi_info()
        thermal = get_thermal_state()
        data    = info.to_dict()
        if thermal:
            data["thermal"] = thermal.to_dict()
        return data
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/hardware/thermal")
async def hardware_thermal(_: str = Depends(require_auth)):
    """Current thermal state and LLM routing recommendation."""
    try:
        from piclaw.hardware.thermal import get_thermal_state, make_status
        from piclaw.hardware.pi_info import current_temp, is_throttled
        status = get_thermal_state()
        if status is None:
            temp = current_temp()
            if temp is None:
                return {"available": False, "message": "Temperature not readable"}
            status = make_status(temp, throttle_active=is_throttled())
        return {"available": True, **status.to_dict()}
    except Exception as e:
        return {"available": False, "error": str(e)}


@app.get("/api/hardware/i2c")
async def hardware_i2c(bus: int = -1, _: str = Depends(require_auth)):
    """Scan I2C bus(es) and return found devices."""
    try:
        from piclaw.hardware.i2c_scan import scan_bus, scan_all_buses
        if bus == -1:
            results = await scan_all_buses()
        else:
            results = [await scan_bus(bus)]
        return {
            "buses": [
                {
                    "bus":       r.bus,
                    "simulated": r.simulated,
                    "error":     r.error,
                    "count":     r.count,
                    "devices": [
                        {
                            "address":  f"0x{d.address:02X}",
                            "name":     d.name,
                            "desc":     d.desc,
                            "category": d.category,
                            "known":    d.known,
                        }
                        for d in r.devices
                    ]
                }
                for r in results
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sensors")
async def sensors_list(_: str = Depends(require_auth)):
    """List all registered named sensors."""
    try:
        from piclaw.hardware import get_sensor_registry
        reg     = get_sensor_registry()
        sensors = reg.list_all()
        return {
            "count":   len(sensors),
            "sensors": [s.to_dict() for s in sensors],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sensors/read")
async def sensors_read_all(_: str = Depends(require_auth)):
    """Read all enabled sensors concurrently."""
    try:
        from piclaw.hardware import get_sensor_registry
        from piclaw.hardware.sensors import read_all_sensors
        reg      = get_sensor_registry()
        readings = await read_all_sensors(reg)
        return {
            "count":    len(readings),
            "readings": [
                {
                    "sensor":    r.sensor_name,
                    "values":    r.values,
                    "error":     r.error,
                    "simulated": r.simulated,
                    "timestamp": r.timestamp,
                }
                for r in readings
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sensors/{name}")
async def sensor_read_one(name: str, _: str = Depends(require_auth)):
    """Read a specific named sensor."""
    try:
        from piclaw.hardware import get_sensor_registry
        from piclaw.hardware.sensors import read_sensor
        reg    = get_sensor_registry()
        sensor = reg.get(name)
        if not sensor:
            from fastapi import HTTPException
            raise HTTPException(404, f"Sensor '{name}' not found")
        reading = await read_sensor(sensor)
        reg.update_reading(name, reading)
        return {
            "sensor":    reading.sensor_name,
            "values":    reading.values,
            "error":     reading.error,
            "simulated": reading.simulated,
            "timestamp": reading.timestamp,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/sensors")
async def sensor_add(request: Request, _: User = Depends(require_admin)):
    """Register a new named sensor."""
    try:
        from piclaw.hardware import get_sensor_registry
        from piclaw.hardware.sensors import SensorDef, ALL_TYPES
        body = await request.json()
        name = body.get("name", "").strip()
        typ  = body.get("type", "").strip()
        if not name or not typ:
            return {"error": "name and type are required"}
        if typ not in ALL_TYPES:
            return {"error": f"Unknown type. Valid: {', '.join(ALL_TYPES)}"}
        reg = get_sensor_registry()
        if reg.get(name):
            return {"error": f"Sensor '{name}' already exists"}
        sensor = SensorDef(
            name        = name,
            type        = typ,
            description = body.get("description", ""),
            config      = body.get("config", {}),
        )
        reg.add(sensor)
        return {"ok": True, "name": name}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/sensors/{name}")
async def sensor_delete(name: str, _: User = Depends(require_admin)):
    """Remove a named sensor."""
    try:
        from piclaw.hardware import get_sensor_registry
        reg = get_sensor_registry()
        if reg.remove(name):
            return {"ok": True}
        return {"error": f"Sensor '{name}' not found"}
    except Exception as e:
        return {"error": str(e)}


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket, _: str = Depends(require_auth_ws)):
    """WebSocket chat. Auth via ?token=<token> query param."""
    await _manager.connect(websocket)
    session_id = id(websocket)
    _sessions[session_id] = []
    log.info("WebSocket connected: %s", session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning("WebSocket malformed JSON (session %s): %s", session_id, e)
                await _manager.send(websocket, {"type": "error", "text": "Ungültige Nachricht"})
                continue
            user_text = msg.get("text", "").strip()
            if not user_text:
                continue

            await _manager.send(websocket, {"type": "thinking"})

            async def on_token(token: str):
                await _manager.send(websocket, {"type": "token", "text": token})

            history = _sessions.get(session_id, [])

            # Periodische Heartbeat-Pings damit der WebSocket nicht stirbt
            # während der lokale LLM auf der Pi 4 in einer langen Tool-Call-
            # Inference hängt (gemma-4 mit 8k Kontext kann 30-60 s brauchen).
            # Ohne diese Heartbeats schließt uvicorn nach ws_ping_timeout
            # mit Code 1011 ("keepalive ping timeout").
            async def _ping_loop():
                # CancelledError NICHT schlucken – sonst kann asyncio die
                # Cancellation nicht propagieren und die Cleanup-Logik
                # (await ping_task im finally) bekommt evtl. einen Haenger.
                while True:
                    await asyncio.sleep(15)
                    await _manager.send(websocket, {"type": "thinking"})

            ping_task = create_background_task(_ping_loop(), name=f"ws-ping-{session_id}")
            try:
                # Obs.1: jede WS-Iteration kriegt eigene Request-ID.
                # Im Unterschied zu HTTP-Requests gibt es hier keine
                # Middleware, also setzen wir den Scope explizit.
                with request_scope():
                    reply = await _agent.run(
                        user_text, history=history, on_token=on_token,
                    )
            finally:
                ping_task.cancel()
                with contextlib_suppress(asyncio.CancelledError):
                    await ping_task

            history.append(Message(role="user",      content=user_text))
            history.append(Message(role="assistant", content=reply))
            _sessions[session_id] = history[-40:]

            await _manager.send(websocket, {"type": "reply", "text": reply})

    except WebSocketDisconnect:
        log.info("WebSocket disconnected: %s", session_id)
    except Exception as e:
        log.error("WebSocket error: %s", e, exc_info=True)
        try:
            await _manager.send(websocket, {"type": "error", "text": str(e)})
        except Exception:
            log.debug("Could not send error to already-broken WebSocket %s", session_id)
    finally:
        # Läuft bei jedem Exit-Pfad (sauberer Disconnect, Exception, ...) –
        # sonst bleiben _connections/_sessions bei hartem Verbindungsabbruch hängen.
        _manager.disconnect(websocket)
        _sessions.pop(session_id, None)


# ── Entrypoint ────────────────────────────────────────────────────

def run(host: str = "0.0.0.0", port: int = 7842):
    import uvicorn
    # ws_ping defaults (20s/20s) sind zu kurz für lokale LLM-Inferenz auf
    # Pi-Hardware. Ein gemma-4-Tool-Call dauert leicht 30-60s; währenddessen
    # blockiert der llama.cpp-Aufruf den Event-Loop, sodass Pings nicht
    # rechtzeitig beantwortet werden → Server schließt mit Code 1011.
    uvicorn.run("piclaw.api:app", host=host, port=port,
                log_level="info", reload=False,
                ws_ping_interval=30,
                ws_ping_timeout=180)


# ══════════════════════════════════════════════════════════════════
# Metriken API (v0.10)
# ══════════════════════════════════════════════════════════════════

@app.get("/api/metrics")
async def api_metrics_latest(_: str = Depends(require_auth)):
    """Aktuellste Werte aller Metriken."""
    try:
        from piclaw.metrics import get_db
        db = get_db()
        result = db.query_latest_all()
        return {"metrics": result, "count": len(result)}
    except Exception as e:
        return {"error": str(e), "metrics": {}}


@app.get("/api/metrics/{metric_name}")
async def api_metric_history(
    metric_name: str,
    since: int = 3600,
    resolution: int = 60,
    _: str = Depends(require_auth),
):
    """Zeitreihenwerte für eine Metrik."""
    try:
        from piclaw.metrics import get_db
        db = get_db()
        rows = db.query(metric_name, since_s=since, limit=500)
        return {
            "metric": metric_name,
            "since_s": since,
            "points": len(rows),
            "data": rows,
        }
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/api/metrics/chart/{metric_name}")
async def api_metric_chart(
    metric_name: str,
    since: int = 3600,
    resolution: int = 60,
    _: str = Depends(require_auth),
):
    """Downgesampelte Daten für Chart-Darstellung."""
    try:
        from piclaw.metrics import get_db
        db = get_db()
        result = db.query_range([metric_name], since_s=since, resolution=resolution)
        return {
            "metric": metric_name,
            "resolution_s": resolution,
            "data": result.get(metric_name, []),
        }
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/api/metrics/stats")
async def api_metrics_stats(_: str = Depends(require_auth)):
    """Datenbank-Statistiken."""
    try:
        from piclaw.metrics import get_db
        return get_db().stats()
    except Exception as e:
        return {"error": str(e)}


# ── Obs.4: Trace-Endpoint ─────────────────────────────────────────

@app.get("/api/trace/{request_id}")
async def api_trace(
    request_id: str,
    _: str = Depends(require_auth),
):
    """Liefert alle Routing-Events einer Request-ID, chronologisch geordnet.

    Eine Anfrage durchläuft typischerweise diese Phasen:
      classify  – Task wurde klassifiziert (tags + confidence + method)
      select    – Backend-Reihenfolge wurde gewählt
      call      – Backend-Aufruf (Erfolg oder Fehler mit code+latency)
      final     – Antwort an User ausgeliefert (selected_backend + latency)

    Die request_id steht im Response-Header `X-Request-ID` jedes
    HTTP-Aufrufs, und in jeder Log-Zeile dieser Anfrage als [rid=…].
    """
    try:
        from piclaw.metrics import get_db
        events = get_db().query_routing_events(request_id)
        return {
            "request_id": request_id,
            "event_count": len(events),
            "events": events,
        }
    except Exception as e:
        return {"error": str(e), "request_id": request_id, "events": []}


# ══════════════════════════════════════════════════════════════════
# Kamera API (v0.10)
# ══════════════════════════════════════════════════════════════════

@app.get("/api/camera/list")
async def api_camera_list(_: str = Depends(require_auth)):
    """Listet verfügbare Kameras auf."""
    try:
        from piclaw.hardware.camera import detect_cameras
        cameras = detect_cameras()
        return {
            "cameras": [
                {"index": c.index, "name": c.name, "driver": c.driver,
                 "resolution": list(c.resolution)}
                for c in cameras
            ]
        }
    except Exception as e:
        return {"error": str(e), "cameras": []}


@app.post("/api/camera/snapshot")
async def api_camera_snapshot(_: str = Depends(require_auth)):
    """Nimmt ein Foto auf und gibt den Pfad zurück."""
    try:
        from piclaw.hardware.camera import capture_snapshot
        import os
        path = await capture_snapshot()
        return {
            "path": str(path),
            "filename": path.name,
            "size_kb": round(os.path.getsize(path) / 1024, 1),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/camera/image/{filename}")
async def api_camera_image(filename: str, _: str = Depends(require_auth)):
    """Liefert ein aufgenommenes Bild."""
    from piclaw.hardware.camera import CAPTURE_DIR
    path = (CAPTURE_DIR / filename).resolve()
    if not path.exists() or not path.is_relative_to(CAPTURE_DIR.resolve()):
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type="image/jpeg")


# ══════════════════════════════════════════════════════════════════
# Backup API (v0.10)
# ══════════════════════════════════════════════════════════════════

@app.get("/api/backup/list")
async def api_backup_list(_: str = Depends(require_auth)):
    """Listet alle verfügbaren Backups auf."""
    try:
        from piclaw.backup import list_backups
        backups = list_backups()
        return {
            "backups": [
                {
                    "filename": b.path.name,
                    "ts": b.ts,
                    "datetime": b.datetime_str,
                    "size_kb": b.size_kb,
                    "version": b.version,
                    "files": b.files,
                    "age": b.age_str,
                }
                for b in backups
            ]
        }
    except Exception as e:
        return {"error": str(e), "backups": []}


@app.post("/api/backup/create")
async def api_backup_create(
    note: str = "",
    include_metrics: bool = False,
    _: User = Depends(require_admin),
):
    """Erstellt ein neues Backup."""
    try:
        from piclaw.backup import create_backup
        import os
        path = await create_backup(include_metrics=include_metrics, note=note)
        return {
            "ok": True,
            "filename": path.name,
            "path": str(path),
            "size_kb": round(os.path.getsize(path) / 1024, 1),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Konfigurations-Wizard API (v0.10.1)
# Liest und schreibt Konfiguration sicher über den Browser-Wizard.
# API-Keys werden maskiert zurückgegeben (nie im Klartext).
# ══════════════════════════════════════════════════════════════════

def _mask(value: str, show: int = 4) -> str:
    """Zeigt nur die letzten `show` Zeichen, Rest maskiert."""
    if not value:
        return ""
    if len(value) <= show:
        return "●" * len(value)
    return "●" * (len(value) - show) + value[-show:]


@app.get("/api/wizard/config")
async def wizard_get_config(_: str = Depends(require_auth)):
    """
    Liefert alle Konfigurationswerte für den Browser-Wizard.
    Sensible Felder (API-Keys, Tokens, Passwörter) werden maskiert.
    """
    from piclaw.config import load
    cfg = load()
    return {
        "agent": {
            "name":      cfg.agent_name,
            "log_level": cfg.log_level,
        },
        "llm": {
            "backend":     cfg.llm.backend,
            "model":       cfg.llm.model,
            "api_key":     _mask(cfg.llm.api_key),
            "api_key_set": bool(cfg.llm.api_key),
            "base_url":    cfg.llm.base_url,
            "temperature": cfg.llm.temperature,
            "max_tokens":  cfg.llm.max_tokens,
        },
        "telegram": {
            "token":     _mask(cfg.telegram.token),
            "token_set": bool(cfg.telegram.token),
            "chat_id":   cfg.telegram.chat_id,
        },
        "discord": {
            "token":      _mask(cfg.discord.token),
            "token_set":  bool(cfg.discord.token),
            "channel_id": cfg.discord.channel_id,
        },
        "mqtt": {
            "broker":   "",
            "port":     1883,
            "username": "",
            "ha_discovery": True,
        },
        "hardware": {
            "fan_enabled": False,
            "fan_pin":     14,
        },
        "api": {
            "port":      cfg.api.port,
            "token_set": bool(cfg.api.secret_key),
        },
        "updater": {
            "auto_check": cfg.updater.auto_check,
            "channel":    cfg.updater.channel,
        },
    }


@app.post("/api/wizard/save")
async def wizard_save_config(body: dict, _: User = Depends(require_admin)):
    """
    Speichert Konfigurationsänderungen aus dem Browser-Wizard.
    Felder die mit '●' anfangen werden ignoriert (unveränderte maskierte Werte).
    """
    from piclaw.config import load, save as cfg_save

    cfg = load()
    changed: list[str] = []

    def _apply(new_val: str | None, getter, setter, label: str):
        if new_val is None:
            return
        v = str(new_val).strip()
        if not v or v.startswith("●"):
            return  # maskierter Wert → nicht überschreiben
        current = getter()
        if v != current:
            setter(v)
            changed.append(label)

    # ── Agent ──────────────────────────────────────────────────────
    section = body.get("agent", {})
    _apply(section.get("name"),      lambda: cfg.agent_name,    lambda v: setattr(cfg, "agent_name", v),     "agent.name")
    _apply(section.get("log_level"), lambda: cfg.log_level,     lambda v: setattr(cfg, "log_level", v),      "agent.log_level")

    # ── LLM ────────────────────────────────────────────────────────
    section = body.get("llm", {})
    _apply(section.get("backend"),  lambda: cfg.llm.backend,  lambda v: setattr(cfg.llm, "backend", v),  "llm.backend")
    _apply(section.get("model"),    lambda: cfg.llm.model,    lambda v: setattr(cfg.llm, "model", v),    "llm.model")
    _apply(section.get("api_key"),  lambda: cfg.llm.api_key,  lambda v: setattr(cfg.llm, "api_key", v),  "llm.api_key")
    _apply(section.get("base_url"), lambda: cfg.llm.base_url, lambda v: setattr(cfg.llm, "base_url", v), "llm.base_url")
    if "temperature" in section:
        try:
            cfg.llm.temperature = float(section["temperature"])
            changed.append("llm.temperature")
        except (ValueError, TypeError):
            pass
    if "max_tokens" in section:
        try:
            cfg.llm.max_tokens = int(section["max_tokens"])
            changed.append("llm.max_tokens")
        except (ValueError, TypeError):
            pass

    # ── Telegram ───────────────────────────────────────────────────
    section = body.get("telegram", {})
    _apply(section.get("token"),   lambda: cfg.telegram.token,   lambda v: setattr(cfg.telegram, "token", v),   "telegram.token")
    _apply(section.get("chat_id"), lambda: cfg.telegram.chat_id, lambda v: setattr(cfg.telegram, "chat_id", v), "telegram.chat_id")

    # ── Discord ────────────────────────────────────────────────────
    section = body.get("discord", {})
    _apply(section.get("token"), lambda: cfg.discord.token, lambda v: setattr(cfg.discord, "token", v), "discord.token")
    if section.get("channel_id"):
        try:
            cfg.discord.channel_id = int(section["channel_id"])
            changed.append("discord.channel_id")
        except (ValueError, TypeError):
            pass

    # ── Hardware ───────────────────────────────────────────────────
    section = body.get("hardware", {})
    if "fan_enabled" in section:
        changed.append("hardware.fan_enabled")
    if "fan_pin" in section:
        try:
            _ = int(section["fan_pin"])
            changed.append("hardware.fan_pin")
        except (ValueError, TypeError):
            pass

    # ── API-Token rotieren ─────────────────────────────────────────
    if body.get("rotate_token"):
        import secrets as _sec
        cfg.api.secret_key = _sec.token_urlsafe(32)
        changed.append("api.secret_key (rotiert)")

    # ── Updater ────────────────────────────────────────────────────
    section = body.get("updater", {})
    if "auto_check" in section:
        cfg.updater.auto_check = bool(section["auto_check"])
        changed.append("updater.auto_check")
    _apply(section.get("channel"), lambda: cfg.updater.channel, lambda v: setattr(cfg.updater, "channel", v), "updater.channel")

    # ── Speichern ──────────────────────────────────────────────────
    if changed:
        cfg_save(cfg)

    return {
        "ok":     True,
        "saved":  len(changed) > 0,
        "changed": changed,
        "restart_required": any(
            k in changed for k in ["llm.backend", "llm.api_key", "llm.model",
                                   "telegram.token", "discord.token", "api.secret_key (rotiert)"]
        ),
    }


@app.post("/api/wizard/test/llm")
async def wizard_test_llm(_: User = Depends(require_admin)):
    """Sendet einen schnellen Test-Ping an das konfigurierte LLM."""
    try:
        from piclaw.config import load
        from piclaw.llm import create_backend
        cfg = load()
        if not cfg.llm.api_key and cfg.llm.backend not in ("local", "ollama"):
            return {"ok": False, "error": "Kein API-Key konfiguriert"}
        backend = create_backend(cfg)
        resp = await asyncio.wait_for(
            backend.complete([{"role": "user", "content": "Reply with exactly: OK"}]),
            timeout=15,
        )
        return {"ok": True, "response": str(resp)[:100]}
    except TimeoutError:
        return {"ok": False, "error": "Timeout (>15s) – API erreichbar?"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@app.post("/api/wizard/test/telegram")
async def wizard_test_telegram(_: User = Depends(require_admin)):
    """Sendet eine Test-Nachricht via Telegram."""
    try:
        from piclaw.config import load
        import aiohttp
        cfg = load()
        if not cfg.telegram.token or not cfg.telegram.chat_id:
            return {"ok": False, "error": "Token oder Chat-ID fehlt"}
        url = f"https://api.telegram.org/bot{cfg.telegram.token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "chat_id": cfg.telegram.chat_id,
                "text": "✅ PiClaw Konfigurations-Test erfolgreich!"
            }, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                if data.get("ok"):
                    return {"ok": True, "message": "Nachricht gesendet!"}
                return {"ok": False, "error": data.get("description", "Unbekannter Fehler")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

# Hinweis: Ersteinrichtung läuft per SSH-Terminal: `piclaw setup`
# Der API-Server ist bei Erststart noch nicht aktiv – kein /setup-Webendpoint.

if __name__ == "__main__":
    import uvicorn
    from piclaw.config import load as _load
    _cfg = _load()
    uvicorn.run(
        "piclaw.api:app",
        host=_cfg.api.host or "0.0.0.0",
        port=_cfg.api.port or 7842,
        log_level="info",
        reload=False,
        # Längere WS-Ping-Toleranz für lange LLM-Antworten (siehe run()).
        ws_ping_interval=30,
        ws_ping_timeout=180,
    )

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
import os
import psutil
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from piclaw.config   import load as load_cfg, save as save_cfg, PiClawConfig
from piclaw.agent    import Agent

# ── Logging setup for API process ─────────────────────────────────────────────
def _setup_api_logging() -> None:
    """Ensure piclaw.* loggers write to api.log in the API process."""
    import sys
    _LOG_DIR = Path("/var/log/piclaw")
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = _LOG_DIR / "api.log"
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) and
               getattr(h, "baseFilename", "").endswith("api.log")
               for h in root.handlers):
        fh = logging.FileHandler(str(_log_file))
        fh.setFormatter(_fmt)
        fh.setLevel(logging.INFO)
        root.addHandler(fh)
    root.setLevel(logging.INFO)

_setup_api_logging()
from piclaw.llm.base import Message
from piclaw.messaging import build_hub, IncomingMessage
from piclaw.auth     import require_auth, require_auth_ws, set_token, get_token, generate_token
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.api")

_cfg:   PiClawConfig = None
_agent: Agent        = None
_hub                 = None   # MessagingHub


async def _agent_message_handler(msg: IncomingMessage) -> str:
    """Route incoming message from any platform to the agent."""
    if not _agent:
        return "Agent not ready yet."
    return await _agent.run(msg.text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cfg, _agent, _hub
    # Re-apply logging after uvicorn overwrites root handlers at startup
    _setup_api_logging()
    _cfg = load_cfg()

    # ── Token: generate once, persist in config ────────────────────
    if not _cfg.api.secret_key:
        _cfg.api.secret_key = generate_token()
        save_cfg(_cfg)
        log.info("Generated new API token and saved to config.")
    set_token(_cfg.api.secret_key)
    log.info("API token loaded (first 8 chars: %.8s…)", _cfg.api.secret_key)

    _agent = Agent(_cfg)
    _agent.start_scheduler()
    create_background_task(_agent.boot(), name="agent-boot")
    _hub = build_hub(_cfg)
    _agent._telegram_send = lambda text: create_background_task(_hub.send_all(text))
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Public endpoints (no auth) ────────────────────────────────────

@app.get("/health")
async def health():
    """Unauthenticated health check for monitoring scripts."""
    return {"status": "ok", "agent": _cfg.agent_name if _cfg else "PiClaw"}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve web UI with token injected as JS variable."""
    html_path = Path(__file__).parent / "web" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>PiClaw OS</h1><p>Web UI not found.</p>")
    html = html_path.read_text(encoding="utf-8")
    # Inject token so the dashboard can authenticate API calls.
    # The token is only embedded in the HTML if the server is serving it –
    # i.e. you must have network access to the Pi to receive it.
    token_script = f'<script>window.PICLAW_TOKEN = "{get_token()}";</script>'
    html = html.replace("</head>", f"{token_script}\n</head>", 1)
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
    payload = await request.json()
    if not _hub:
        return {"status": "not ready"}
    for adapter in _hub._adapters:
        if adapter.name == "threema":
            await adapter.handle_webhook(payload, _agent_message_handler)
    return {"status": "ok"}


# ── Authenticated API endpoints ───────────────────────────────────
# All routes below require: Authorization: Bearer <token>

@app.get("/api/messaging")
async def messaging_status(_: str = Depends(require_auth)):
    if not _hub:
        return {"adapters": []}
    return {"adapters": _hub.active_adapters()}


# ── Sub-agent endpoints ───────────────────────────────────────────

@app.get("/api/subagents")
async def subagents_status(_: str = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        return {"sub_agents": []}
    return _agent.sa_runner.status_dict()


@app.post("/api/subagents")
async def subagent_create(request: Request, _: str = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    body     = await request.json()
    required = ("name", "description", "mission")
    missing  = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(400, f"Missing required fields: {missing}")
    from piclaw.agents.sa_registry import SubAgentDef
    agent_def = SubAgentDef(
        name        = body["name"],
        description = body["description"],
        mission     = body["mission"],
        tools       = body.get("tools", []),
        schedule    = body.get("schedule", "once"),
        llm_tags    = body.get("llm_tags", []),
        notify      = body.get("notify", True),
        trusted     = body.get("trusted", False),
        max_steps   = body.get("max_steps", 10),
        timeout     = body.get("timeout", 300),
        created_by  = "api",
    )
    agent_id = _agent.sa_registry.add(agent_def)
    if body.get("start_now"):
        await _agent.sa_runner.start_agent(agent_id)
    return {"id": agent_id, "name": agent_def.name, "created": True}


@app.delete("/api/subagents/{name}")
async def subagent_remove(name: str, _: str = Depends(require_auth)):
    if not _agent or not _agent.sa_runner:
        raise HTTPException(503, "Agent not ready")
    sa = _agent.sa_registry.get(name)
    if not sa:
        raise HTTPException(404, f"Sub-agent '{name}' not found")
    if sa.id in _agent.sa_runner._tasks and not _agent.sa_runner._tasks[sa.id].done():
        await _agent.sa_runner.stop_agent(name)
    removed = _agent.sa_registry.remove(name)
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


# ── Soul endpoints ────────────────────────────────────────────────

@app.get("/api/soul")
async def soul_get(_: str = Depends(require_auth)):
    from piclaw import soul as soul_mod
    return {"content": soul_mod.load(), "path": str(soul_mod.get_path())}


@app.post("/api/soul")
async def soul_set(request: Request, _: str = Depends(require_auth)):
    from piclaw import soul as soul_mod
    body    = await request.json()
    content = body.get("content", "")
    if not content.strip():
        raise HTTPException(400, "Content cannot be empty")
    result = soul_mod.save(content)
    return {"result": result}


@app.post("/api/soul/append")
async def soul_append(request: Request, _: str = Depends(require_auth)):
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
        temp = int(open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8").read().strip()) / 1000
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
        proc = await asyncio.create_subprocess_shell(
            f"systemctl is-active {name} 2>/dev/null || echo inactive",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        state   = out.decode().strip()
        result.append({"name": name, "state": state, "active": state == "active"})
    return result


@app.get("/api/schedules")
async def schedules(_: str = Depends(require_auth)):
    if not _agent:
        return []
    return list(_agent.scheduler._schedules.values())


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
async def sensor_add(request: Request, _: str = Depends(require_auth)):
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
async def sensor_delete(name: str, _: str = Depends(require_auth)):
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
            reply   = await _agent.run(user_text, history=history, on_token=on_token)

            history.append(Message(role="user",      content=user_text))
            history.append(Message(role="assistant", content=reply))
            _sessions[session_id] = history[-40:]

            await _manager.send(websocket, {"type": "reply", "text": reply})

    except WebSocketDisconnect:
        _manager.disconnect(websocket)
        _sessions.pop(session_id, None)
        log.info("WebSocket disconnected: %s", session_id)
    except Exception as e:
        log.error("WebSocket error: %s", e, exc_info=True)
        await _manager.send(websocket, {"type": "error", "text": str(e)})


# ── Entrypoint ────────────────────────────────────────────────────

def run(host: str = "0.0.0.0", port: int = 7842):
    import uvicorn
    uvicorn.run("piclaw.api:app", host=host, port=port,
                log_level="info", reload=False)


# ══════════════════════════════════════════════════════════════════
# Metriken API (v0.10)
# ══════════════════════════════════════════════════════════════════

@app.get("/api/metrics")
async def api_metrics_latest(_: str = Depends(require_auth)):
    """Aktuellste Werte aller Metriken."""
    try:
        from piclaw.metrics import get_db
        db = get_db()
        names = db.list_metrics()
        result = {}
        for name in names:
            latest = db.query_latest(name)
            if latest:
                result[name] = latest
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
        import time
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
    path = CAPTURE_DIR / filename
    if not path.exists() or not path.is_relative_to(CAPTURE_DIR):
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
    _: str = Depends(require_auth),
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
async def wizard_save_config(body: dict, _: str = Depends(require_auth)):
    """
    Speichert Konfigurationsänderungen aus dem Browser-Wizard.
    Felder die mit '●' anfangen werden ignoriert (unveränderte maskierte Werte).
    """
    from piclaw.config import load, save as cfg_save
    import secrets

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
async def wizard_test_llm(_: str = Depends(require_auth)):
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
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Timeout (>15s) – API erreichbar?"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@app.post("/api/wizard/test/telegram")
async def wizard_test_telegram(_: str = Depends(require_auth)):
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
    )

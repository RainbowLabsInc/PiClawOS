#!/usr/bin/env python3
"""
PiClaw OS – CLI
`piclaw` command available in SSH session.
"""

import asyncio
import sys
import os


BANNER = """
  ██████╗ ██╗ ██████╗██╗      █████╗ ██╗    ██╗
  ██╔══██╗██║██╔════╝██║     ██╔══██╗██║    ██║
  ██████╔╝██║██║     ██║     ███████║██║ █╗ ██║
  ██╔═══╝ ██║██║     ██║     ██╔══██║██║███╗██║
  ██║     ██║╚██████╗███████╗██║  ██║╚███╔███╔╝
  ╚═╝     ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  OS v0.9
"""

HELP = """
Commands:
  chat              Interactive AI agent session  (default)
  doctor            System health check
  start             Start API + agent services
  stop              Stop API + agent services
  status            Show service status
  config get        Show current config
  config set <k> <v> Update a config value
  web               Show web UI URL
  model             Manage local LLM models
  soul show         Show current soul file
  soul edit         Open soul file in $EDITOR
  soul reset        Restore default soul
  agent list        List all sub-agents
  agent start <n>   Start a sub-agent
  agent stop <n>    Stop a running sub-agent
  agent remove <n>  Delete a sub-agent
  agent run <n>     Trigger immediate one-off run
  messaging status  Show configured messaging adapters
  messaging test    Send a test message to all adapters
  messaging setup   Interactive setup wizard
  backup            Create a backup of config + memory
  backup list       List available backups
  backup restore    Restore latest (or specific) backup
  metrics           Show latest system metrics
  metrics history   Show metric history (cpu_temp_c, cpu_percent, …)
  camera snapshot   Take a photo with the Pi camera
  camera list       List available cameras
  routine           List all routines and their status
  routine enable    Enable a routine (e.g. 'morning_briefing')
  routine disable   Disable a routine
  briefing          Generate and print a briefing now
  briefing send     Generate and send via messaging (morning/evening/status)
  setup             First-boot setup wizard (LLM, Telegram, Soul)
  help              This message

Type 'exit' or Ctrl+C to leave the agent chat.
"""


def _api_running(cfg) -> bool:
    """Prüft ob piclaw-api auf localhost läuft."""
    import urllib.request, urllib.error
    try:
        url = f"http://127.0.0.1:{cfg.api.port}/health"
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


def cmd_chat():
    from piclaw.config import load

    async def _run_via_api(cfg):
        """Chat über WebSocket-API – Modell bleibt im Daemon-RAM."""
        import websockets, json, sys
        from piclaw.auth import get_token
        # Token aus auth-Modul (gesetzt beim API-Start) oder aus config
        token = get_token() or cfg.api.secret_key
        if not token:
            raise ValueError("Kein API-Token – piclaw setup ausführen")
        url = f"ws://127.0.0.1:{cfg.api.port}/ws/chat?token={token}"
        print(BANNER)
        print(f"  {cfg.agent_name} ready. Type 'exit' to quit, 'help' for commands.")
        print(f"  \033[2m(Verbunden mit laufendem Daemon – sofortige Antworten)\033[0m\n")
        try:
            async with websockets.connect(url) as ws:
                while True:
                    try:
                        text = input("\033[1;35m[you]\033[0m ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n\033[2mSession ended.\033[0m")
                        break
                    if not text:
                        continue
                    if text.lower() in ("exit", "quit", "q"):
                        print("\033[2mGoodbye.\033[0m")
                        break
                    if text.lower() == "help":
                        print(HELP)
                        continue
                    await ws.send(json.dumps({"text": text}))
                    reply_parts = []
                    print("\033[2mThinking…\033[0m", end="\r", flush=True)
                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg["type"] == "thinking":
                            continue
                        elif msg["type"] == "token":
                            if not reply_parts:
                                print(" " * 20, end="\r")
                            print(msg["text"], end="", flush=True)
                            reply_parts.append(msg["text"])
                        elif msg["type"] == "reply":
                            if not reply_parts:
                                print(" " * 20, end="\r")
                                print(f"\033[1;36m[{cfg.agent_name}]\033[0m {msg['text']}\n")
                            else:
                                print(f"\n")
                            break
                        elif msg["type"] == "error":
                            print(f"\n\033[31m❌ {msg['text']}\033[0m\n")
                            break
        except Exception as e:
            print(f"\n\033[31mWebSocket-Fehler: {e}\033[0m")
            raise

    async def _run_direct(cfg):
        """Fallback: direkter Agent-Start (lädt Modell neu)."""
        from piclaw.agent import Agent
        agent = Agent(cfg)
        await agent.boot()
        print(BANNER)
        print(f"  {cfg.agent_name} ready. Type 'exit' to quit, 'help' for commands.")
        print(f"  \033[33m(Offline-Modus – API nicht erreichbar)\033[0m\n")
        history = []
        while True:
            try:
                text = input("\033[1;35m[you]\033[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\033[2mSession ended.\033[0m")
                break
            if not text:
                continue
            if text.lower() in ("exit", "quit", "q"):
                print("\033[2mGoodbye.\033[0m")
                break
            if text.lower() == "help":
                print(HELP)
                continue
            print("\033[2mThinking…\033[0m", end="\r", flush=True)
            reply = await agent.run(text, history=history)
            from piclaw.llm import Message as _Msg
            history.append(_Msg(role="user", content=text))
            history.append(_Msg(role="assistant", content=reply))
            print(f"\033[1;36m[{cfg.agent_name}]\033[0m {reply}\n")

    async def _run():
        cfg = load()
        if _api_running(cfg):
            try:
                await _run_via_api(cfg)
                return
            except Exception:
                pass  # Fallback auf direkten Modus
        await _run_direct(cfg)

    asyncio.run(_run())


def cmd_doctor():
    import platform, asyncio
    from piclaw.config import load

    async def _check():
        cfg = load()
        from piclaw.agent import Agent
        agent  = Agent(cfg)
        ok     = await agent.llm.health_check()
        import psutil, socket
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        print("\n🔍 PiClaw Doctor\n")
        print(f"  Agent       : {cfg.agent_name}")
        # Zeige echten Modellnamen: bei local den Dateinamen, sonst model aus config
        _model_display = cfg.llm.model
        if cfg.llm.backend == "local":
            from pathlib import Path as _P
            _mp = _P(cfg.llm.model) if cfg.llm.model else None
            if _mp and _mp.exists():
                _model_display = _mp.name
            else:
                from piclaw.llm.local import DEFAULT_MODEL_PATH as _DMP
                _model_display = _DMP.name if _DMP.exists() else f"{cfg.llm.model} (nicht gefunden)"
        _health_str = "✅ OK" if ok else "❌ UNREACHABLE (check API key)" if cfg.llm.backend != "local" else "❌ Modell nicht gefunden – piclaw model download"
        print(f"  LLM backend : {cfg.llm.backend} / {_model_display}")
        print(f"  LLM health  : {_health_str}")
        print(f"  Python      : {platform.python_version()}")
        print(f"  Platform    : {platform.platform()}")
        print(f"  Hostname    : {socket.gethostname()}")
        print(f"  Memory      : {mem.used//1_048_576} / {mem.total//1_048_576} MB")
        print(f"  Disk        : {disk.used//1_073_741_824:.1f} / {disk.total//1_073_741_824:.1f} GB")
        try:
            temp = int(open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8").read()) / 1000
            print(f"  CPU Temp    : {temp:.1f}°C")
        except OSError:
            pass  # thermal_zone0 not present on non-Pi
        # Soul
        from piclaw import soul as soul_mod
        soul_path = soul_mod.get_path()
        # API Token
        if cfg.api.secret_key:
            print("  API Token   : ✅ set (piclaw config token)")
        else:
            print("  API Token   : ⬜ not generated yet")
        if soul_path.exists():
            soul_size = soul_path.stat().st_size
            print(f"  Soul        : ✅ {soul_path} ({soul_size} B)")
        else:
            print("  Soul        : ⬜ Not created yet (will be on first boot)")
        # Sub-agents
        from piclaw.agents.sa_registry import SubAgentRegistry
        reg    = SubAgentRegistry()
        agents = reg.list_all()
        if agents:
            running = sum(1 for a in agents if a.last_status == "running")
            ok_n    = sum(1 for a in agents if a.last_status == "ok")
            err_n   = sum(1 for a in agents if a.last_status == "error")
            print(f"  Sub-Agents  : ✅ {len(agents)} defined  "
                  f"(ok={ok_n}, error={err_n}, running={running})")
        else:
            print("  Sub-Agents  : ⬜ None defined")
        try:
            import aiohttp; print("  aiohttp     : ✅")
        except ImportError:
            print("  aiohttp     : ❌")
        try:
            import fastapi; print("  fastapi     : ✅")
        except ImportError:
            print("  fastapi     : ❌")
        print()

    asyncio.run(_check())


def cmd_web():
    from piclaw.config import load
    import socket
    cfg = load()
    try:
        hostname = socket.gethostname()
        ip       = socket.gethostbyname(hostname)
    except Exception:
        ip = "YOUR_PI_IP"
    print("\n  🌐 PiClaw Web UI")
    print(f"  http://{ip}:{cfg.api.port}")
    print(f"  http://{hostname}.local:{cfg.api.port}\n")


def cmd_config(args):
    from piclaw.config import load, save, CONFIG_FILE
    cfg = load()
    if not args or args[0] == "get":
        import tomllib
        print(f"\n  Config: {CONFIG_FILE}\n")
        with open(CONFIG_FILE, "rb") as f:
            import pprint
            pprint.pprint(tomllib.load(f))
        print()
    elif args[0] == "token":
        if cfg.api.secret_key:
            print(f"\n  🔑 API Token (Bearer):\n  {cfg.api.secret_key}\n")
            print(f"  Usage: curl -H 'Authorization: Bearer {cfg.api.secret_key}' \\")
            print(f"         http://piclaw.local:{cfg.api.port}/api/stats\n")
        else:
            print("  Token not generated yet. Start the API service first.")
    elif args[0] == "set" and len(args) == 3:
        key, val = args[1], args[2]
        if   key == "llm.api_key":    cfg.llm.api_key    = val
        elif key == "llm.model":      cfg.llm.model      = val
        elif key == "llm.backend":    cfg.llm.backend    = val
        elif key == "agent_name":     cfg.agent_name     = val
        else:
            print(f"Unknown config key: {key}")
            print("Supported: llm.api_key, llm.model, llm.backend, agent_name")
            return
        save(cfg)
        print(f"  ✅ {key} updated.")
    else:
        print("Usage: piclaw config get | piclaw config set <key> <value>")


def cmd_service(action):
    os.system(f"sudo systemctl {action} piclaw-agent piclaw-api")


def cmd_model(args):
    from piclaw.llm.model_manager import download_model, list_models, remove_model
    sub = args[0] if args else "list"
    if sub == "list":
        print(list_models())
    elif sub == "download":
        mid = args[1] if len(args) > 1 else "phi3-mini-q4"
        asyncio.run(download_model(mid))
    elif sub == "remove":
        mid = args[1] if len(args) > 1 else ""
        print(remove_model(mid))
    elif sub == "status":
        from piclaw.llm.local import DEFAULT_MODEL_PATH
        path = DEFAULT_MODEL_PATH
        if path.exists():
            mb = path.stat().st_size // 1_048_576
            print(f"  ✅ Phi-3 Mini Q4 installed ({mb} MB) → {path}")
        else:
            print("  ⬇ Not downloaded. Run: piclaw model download")
    else:
        print("Usage: piclaw model [list|download [id]|remove [id]|status]")


def cmd_messaging(args):
    from piclaw.config import load
    sub = args[0] if args else "status"
    cfg = load()

    if sub == "status":
        print("\n📡 Messaging Adapters\n")
        adapters = [
            ("Telegram",  bool(cfg.telegram.token and cfg.telegram.chat_id),
             f"chat_id={cfg.telegram.chat_id or '(not set)'}"),
            ("Discord",   bool(cfg.discord.token and cfg.discord.channel_id),
             f"channel={cfg.discord.channel_id or '(not set)'}"),
            ("Threema",   bool(cfg.threema.gateway_id and cfg.threema.api_secret),
             f"gateway={cfg.threema.gateway_id or '(not set)'}"),
            ("WhatsApp",  bool(cfg.whatsapp.access_token),
             f"number={cfg.whatsapp.recipient or '(not set)'}"),
        ]
        for name, ok, detail in adapters:
            icon = "✅" if ok else "⬜"
            print(f"  {icon} {name:12} {detail}")
        print()

    elif sub == "test":
        print("Sending test message to all configured adapters…")
        async def _test():
            from piclaw.messaging import build_hub
            hub = build_hub(cfg)
            await hub.send_all("🧪 PiClaw test message – adapters working correctly.")
            print(f"  Sent to: {', '.join(hub.active_adapters()) or 'none configured'}")
        asyncio.run(_test())

    elif sub == "setup":
        sub2 = args[1] if len(args) > 1 else None
        _messaging_setup_wizard(cfg, sub2)

    else:
        print("Usage: piclaw messaging [status|test|setup [telegram|discord|threema|whatsapp]]")


def _messaging_setup_wizard(cfg, platform=None):
    """Interactive setup wizard for messaging adapters."""
    from piclaw.config import save

    platforms = {
        "telegram":  _setup_telegram,
        "discord":   _setup_discord,
        "threema":   _setup_threema,
        "whatsapp":  _setup_whatsapp,
    }

    if platform and platform in platforms:
        platforms[platform](cfg)
        return

    print("\n🔧 Messaging Setup Wizard\n")
    print("Welchen Adapter möchtest du einrichten?")
    for i, (name, _) in enumerate(platforms.items(), 1):
        current = {
            "telegram":  bool(cfg.telegram.token),
            "discord":   bool(cfg.discord.token),
            "threema":   bool(cfg.threema.gateway_id),
            "whatsapp":  bool(cfg.whatsapp.access_token),
        }[name]
        status = "✅" if current else "⬜"
        print(f"  {i}. {status} {name.capitalize()}")
    print("  0. Abbrechen\n")

    choice = input("Auswahl [0-4]: ").strip()
    names = list(platforms.keys())
    if choice in ("1","2","3","4"):
        name = names[int(choice)-1]
        platforms[name](cfg)
    else:
        print("Abgebrochen.")


def _setup_telegram(cfg):
    from piclaw.config import save
    print("\n📱 Telegram Setup\n")
    print("1. Gehe zu @BotFather in Telegram")
    print("2. Tippe /newbot und folge den Anweisungen")
    print("3. Kopiere den Bot-Token\n")
    token = input("Bot-Token (oder Enter zum Überspringen): ").strip()
    if not token:
        print("Übersprungen.")
        return
    print("\n4. Schreibe deinem neuen Bot eine Nachricht")
    print("5. Öffne: https://api.telegram.org/bot<TOKEN>/getUpdates")
    print("   und kopiere die chat.id aus der Antwort\n")
    chat_id = input("Chat-ID: ").strip()
    if not chat_id:
        print("Abgebrochen.")
        return
    cfg.telegram.token   = token
    cfg.telegram.chat_id = chat_id
    save(cfg)
    print("\n✅ Telegram konfiguriert.")
    print("   Neustart: sudo systemctl restart piclaw-api\n")


def _setup_discord(cfg):
    from piclaw.config import save
    print("\n🎮 Discord Setup\n")
    print("1. https://discord.com/developers/applications → New Application")
    print("2. Bot → Add Bot → 'Message Content Intent' aktivieren")
    print("3. Bot-Token kopieren\n")
    token = input("Bot-Token (oder Enter zum Überspringen): ").strip()
    if not token:
        print("Übersprungen.")
        return
    print("\n4. OAuth2 → URL Generator → bot + Read/Send Messages → einladen")
    print("5. Discord: Einstellungen → Erweitert → Entwicklermodus")
    print("   Rechtsklick auf Kanal → Kanal-ID kopieren\n")
    channel_id_str = input("Kanal-ID: ").strip()
    if not channel_id_str.isdigit():
        print("Ungültige Kanal-ID.")
        return
    user_ids_str = input("Deine User-ID (Enter = alle erlaubt): ").strip()
    allowed = [int(user_ids_str)] if user_ids_str.isdigit() else []
    cfg.discord.token         = token
    cfg.discord.channel_id    = int(channel_id_str)
    cfg.discord.allowed_users = allowed
    save(cfg)
    print("\n✅ Discord konfiguriert.")
    print("   Neustart: sudo systemctl restart piclaw-api\n")


def _setup_threema(cfg):
    from piclaw.config import save
    from pathlib import Path
    print("\n🔒 Threema Gateway Setup\n")
    print("1. Registrierung: https://gateway.threema.ch")
    print("   → Gateway-ID beantragen (z.B. *PICLAW01)")
    print("   → E2E-Modus wählen\n")
    print("2. Schlüsselpaar generieren:")
    print("   threema-gateway generate /etc/piclaw/threema-private.key /etc/piclaw/threema-public.key")
    print("   Dann Public Key im Gateway-Portal hochladen\n")
    gw_id = input("Gateway-ID (z.B. *PICLAW01, Enter zum Überspringen): ").strip()
    if not gw_id:
        print("Übersprungen.")
        return
    api_secret  = input("API-Secret: ").strip()
    recipient   = input("Deine Threema-ID (8 Zeichen): ").strip()
    key_file    = input(f"Private-Key-Datei [{cfg.threema.private_key_file}]: ").strip()
    if not key_file:
        key_file = cfg.threema.private_key_file
    cfg.threema.gateway_id       = gw_id
    cfg.threema.api_secret       = api_secret
    cfg.threema.recipient_id     = recipient
    cfg.threema.private_key_file = key_file
    save(cfg)
    print("\n✅ Threema konfiguriert.")
    if not Path(key_file).exists():
        print(f"   ⚠️  Key-Datei nicht gefunden: {key_file}")
        print("   Erst Schlüssel generieren, dann Neustart.\n")
    else:
        print("   Neustart: sudo systemctl restart piclaw-api\n")


def _setup_whatsapp(cfg):
    from piclaw.config import save
    print("\n💬 WhatsApp Meta Cloud API Setup\n")
    print("⚠️  Voraussetzung: Öffentliche HTTPS-URL!")
    print("   Einfachste Lösung – Cloudflare Tunnel (kostenlos):")
    print("   cloudflared tunnel --url http://localhost:7842")
    print("   → gibt eine URL aus (z.B. https://abc.trycloudflare.com)\n")
    print("1. https://developers.facebook.com → App erstellen → WhatsApp")
    print("2. Temporären Access Token kopieren")
    print("3. Telefonnummer-ID kopieren\n")
    access_token    = input("Access Token (EAA..., Enter zum Überspringen): ").strip()
    if not access_token:
        print("Übersprungen.")
        return
    phone_number_id = input("Telefonnummer-ID: ").strip()
    app_secret      = input("App Secret: ").strip()
    recipient       = input("Deine WhatsApp-Nummer (+49...): ").strip()
    verify_token    = input(f"Verify Token [{cfg.whatsapp.verify_token}]: ").strip()
    if not verify_token:
        verify_token = cfg.whatsapp.verify_token
    cfg.whatsapp.access_token    = access_token
    cfg.whatsapp.phone_number_id = phone_number_id
    cfg.whatsapp.app_secret      = app_secret
    cfg.whatsapp.recipient       = recipient
    cfg.whatsapp.verify_token    = verify_token
    save(cfg)
    print("\n✅ WhatsApp konfiguriert.")
    print("   Webhook-URL im Meta-Portal eintragen:")
    print("   https://DEINE-URL/webhook/whatsapp")
    print(f"  Verify Token: {verify_token}")
    print("   Neustart: sudo systemctl restart piclaw-api\n")
    print("   Then type in your Discord channel to chat with the agent.\n")


def cmd_soul(args):
    from piclaw import soul as soul_mod
    sub = args[0] if args else "show"

    if sub == "show":
        content = soul_mod.load()
        path    = soul_mod.get_path()
        print(f"\n📄 Soul file: {path}\n")
        print(content)
        print()

    elif sub == "edit":
        path   = soul_mod.get_path()
        # Ensure file exists before opening
        soul_mod.load()
        editor = os.environ.get("EDITOR", "nano")
        print(f"  Opening {path} in {editor}…")
        os.system(f"{editor} {path}")
        print("  Soul updated. Changes take effect in the next conversation.")

    elif sub == "reset":
        confirm = input("  ⚠️  Reset soul to default? This overwrites your customizations. [y/N] ").strip().lower()
        if confirm == "y":
            from piclaw.soul import DEFAULT_SOUL
            result = soul_mod.save(DEFAULT_SOUL)
            print(f"  ✅ {result}")
        else:
            print("  Abgebrochen.")

    else:
        print("Usage: piclaw soul [show|edit|reset]")


def cmd_agent(args):
    from piclaw.config import load
    from piclaw.agents.sa_registry import SubAgentRegistry
    from piclaw.agents.runner      import SubAgentRunner

    sub  = args[0] if args else "list"
    name = args[1] if len(args) > 1 else None

    registry = SubAgentRegistry()

    if sub == "list":
        agents = registry.list_all()
        if not agents:
            print("\n  No sub-agents defined yet.")
            print("  Create one via the agent chat: 'Erstelle einen Agenten der…'\n")
            return
        print(f"\n  Sub-Agents ({len(agents)}):\n")
        for a in agents:
            status_icon = {
                "ok": "✅", "error": "❌", "timeout": "⏱️",
                "running": "⚙️", None: "⬜",
            }.get(a.last_status, "⬜")
            enabled_str = "" if a.enabled else "  [disabled]"
            print(f"  {status_icon} [{a.id}] {a.name}{enabled_str}")
            print(f"       {a.description}")
            print(f"       schedule: {a.schedule}  |  tools: {', '.join(a.tools) if a.tools else 'all'}")
            print(f"       last run: {a.last_run or 'never'}  |  status: {a.last_status or '—'}")
            print()

    elif sub == "start":
        if not name:
            print("Usage: piclaw agent start <name>")
            return
        # Start via the API (agent might be running in a separate process)
        result = _api_call("POST", f"/api/subagents/{name}/start")
        if result:
            print(f"  {result.get('result', result)}")
        else:
            # Fallback: show instruction
            print("  ℹ️  API not reachable. To start from within the agent, type:")
            print(f"     piclaw  →  'Starte den Sub-Agenten {name}'")

    elif sub == "stop":
        if not name:
            print("Usage: piclaw agent stop <name>")
            return
        result = _api_call("POST", f"/api/subagents/{name}/stop")
        if result:
            print(f"  {result.get('result', result)}")
        else:
            print("  ℹ️  API not reachable. Agent may not be running.")

    elif sub == "remove":
        if not name:
            print("Usage: piclaw agent remove <name>")
            return
        agent = registry.get(name)
        if not agent:
            print(f"  Sub-agent '{name}' not found.")
            return
        confirm = input(f"  Delete '{agent.name}' ({agent.description})? [y/N] ").strip().lower()
        if confirm == "y":
            result = _api_call("DELETE", f"/api/subagents/{name}")
            if result:
                print("  ✅ Removed.")
            else:
                # Fallback: direct registry delete
                registry.remove(name)
                print(f"  ✅ '{name}' removed from registry.")
        else:
            print("  Abgebrochen.")

    elif sub == "run":
        if not name:
            print("Usage: piclaw agent run <name>")
            return
        result = _api_call("POST", f"/api/subagents/{name}/run")
        if result:
            print("  ⚙️  Triggered. Check logs or Telegram for result.")
        else:
            print("  ℹ️  API not reachable. Agent daemon may not be running.")

    else:
        print("Usage: piclaw agent [list|start|stop|remove|run] [name]")


def _api_call(method: str, path: str, body: dict = None) -> dict | None:
    """Simple synchronous HTTP call to local PiClaw API. Returns None if unreachable."""
    import urllib.request, urllib.error, json as _json, logging as _log
    from piclaw.config import load
    cfg = load()
    url = f"http://127.0.0.1:{cfg.api.port}{path}"
    _logger = _log.getLogger("piclaw.cli.api")
    try:
        data = _json.dumps(body).encode() if body else None
        req  = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if cfg.api.secret_key:
            req.add_header("Authorization", f"Bearer {cfg.api.secret_key}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        _logger.debug("API unreachable (%s %s): %s", method, path, e)
        return None
    except Exception as e:
        _logger.warning("API call failed (%s %s): %s", method, path, e)
        return None



def cmd_setup():
    """
    Interaktiver Ersteinrichtungs-Wizard (SSH/Terminal).
    Führt Schritt für Schritt durch LLM, Messaging, WLAN,
    Hardware und Soul – ohne Browser, ohne GUI.
    """
    from piclaw.wizard import run as wizard_run
    wizard_run()


def _edit_soul_interactive():
    """Open SOUL.md in $EDITOR or guide inline input."""
    import os, subprocess
    from piclaw import soul
    editor = os.environ.get("EDITOR", "")
    if editor:
        import piclaw.soul as soul_mod
        soul_path = soul_mod.SOUL_FILE
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        if not soul_path.exists():
            soul.load()  # creates default
        subprocess.call([editor, str(soul_path)])
        print("  ✅ Soul gespeichert.")
    else:
        print("  Kein $EDITOR gesetzt. Gib deinen Soul direkt ein.")
        print("  (Leere Zeile + Enter zum Abschließen, oder Ctrl+C zum Überspringen)\n")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        if lines:
            soul.save("\n".join(lines))
            print("  ✅ Soul gespeichert.")
        else:
            print("  ⏩ Kein Inhalt – übersprungen.")


def main():
    import sys
    args = sys.argv[1:]
    if not args:
        cmd_chat()
        return

    cmd = args[0]
    if   cmd in ("chat",  ""):            cmd_chat()
    elif cmd == "doctor":                 cmd_doctor()
    elif cmd == "setup":                  cmd_setup()
    elif cmd == "web":                    cmd_web()
    elif cmd == "config":                 cmd_config(args[1:])
    elif cmd == "model":                  cmd_model(args[1:])
    elif cmd == "soul":                   cmd_soul(args[1:])
    elif cmd == "agent":                  cmd_agent(args[1:])
    elif cmd == "messaging":              cmd_messaging(args[1:])
    elif cmd == "start":                  cmd_service("start")
    elif cmd == "stop":                   cmd_service("stop")
    elif cmd == "status":                 cmd_service("status")
    elif cmd == "backup":                 cmd_backup(args[1:])
    elif cmd == "metrics":                cmd_metrics(args[1:])
    elif cmd == "camera":                 cmd_camera(args[1:])
    elif cmd == "routine":                cmd_routine(args[1:])
    elif cmd == "briefing":               cmd_briefing(args[1:])
    elif cmd in ("help", "-h", "--help"): print(BANNER + HELP)
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'piclaw help' for available commands.")


if __name__ == "__main__":
    main()


# ── Backup ─────────────────────────────────────────────────────────

def cmd_backup(args: list):
    import asyncio
    from piclaw.backup import create_backup, list_backups, restore_backup, format_backup_list

    sub = args[0] if args else "create"

    if sub == "list":
        backups = list_backups()
        print(format_backup_list(backups))

    elif sub in ("restore", "wiederherstellen"):
        backup_path = None
        if len(args) > 1 and args[1] == "--file":
            from pathlib import Path
            backup_path = Path(args[2])

        print("  🔍 Backup-Inhalte prüfen (dry-run)…")
        dry = asyncio.run(restore_backup(backup_path=backup_path, dry_run=True))
        if not dry["ok"]:
            print(f"  ❌ {dry['error']}")
            return

        print(f"\n  Backup: {dry['backup']}  ({dry['backup_ts']})")
        print(f"  {len(dry['restored'])} Dateien werden wiederhergestellt:")
        for f in dry['restored'][:10]:
            print(f"    {f}")
        if len(dry['restored']) > 10:
            print(f"    … und {len(dry['restored'])-10} weitere")

        ans = input("\n  Wirklich wiederherstellen? [j/N]: ").strip().lower()
        if ans not in ("j", "y"):
            print("  Abgebrochen.")
            return

        result = asyncio.run(restore_backup(backup_path=backup_path))
        if result["ok"]:
            print(f"\n  ✅ {len(result['restored'])} Dateien wiederhergestellt.")
            print("  Services neu starten: piclaw stop && piclaw start")
        else:
            print(f"\n  ❌ Fehler: {result['errors']}")

    else:  # create
        note = " ".join(args[1:]) if len(args) > 1 else ""
        inc_metrics = "--metrics" in args

        print("  📦 Backup wird erstellt…")
        path = asyncio.run(create_backup(include_metrics=inc_metrics, note=note))
        import os
        size_kb = round(os.path.getsize(path) / 1024, 1)
        print(f"\n  ✅ Backup erstellt: {path}")
        print(f"     Größe: {size_kb} KB")
        print("\n  Auflisten: piclaw backup list")
        print("  Wiederherstellen: piclaw backup restore")


# ── Metriken ────────────────────────────────────────────────────────

def cmd_metrics(args: list):
    from piclaw.metrics import get_db, _read_cpu_temp
    import time, psutil

    sub = args[0] if args else "show"

    if sub == "history":
        metric = args[1] if len(args) > 1 else "cpu_temp_c"
        since  = int(args[2]) if len(args) > 2 else 3600

        db = get_db()
        rows = db.query(metric, since_s=since, limit=20)
        if not rows:
            print(f"  Keine Daten für '{metric}' in den letzten {since//60} Minuten.")
            print(f"  Bekannte Metriken: {', '.join(db.list_metrics())}")
            return

        unit = rows[0].get("unit", "")
        print(f"\n  {metric} (letzte {len(rows)} Werte, {since//60}min):\n")
        for r in reversed(rows):
            import datetime
            dt = datetime.datetime.fromtimestamp(r['ts']).strftime("%H:%M:%S")
            bar_len = int(r['value'] / 2) if unit in ("%", "°C") else 10
            bar = "█" * min(bar_len, 50)
            print(f"  {dt}  {r['value']:>7.1f}{unit}  {bar}")

    else:  # show – aktuelle Werte
        db = get_db()
        stats = db.stats()

        print("\n  📊 Aktuelle Systemmetriken:\n")
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        temp = _read_cpu_temp()

        def bar(pct, width=20):
            filled = int(pct / 100 * width)
            color = "\033[32m" if pct < 70 else "\033[33m" if pct < 85 else "\033[31m"
            return f"{color}{'█'*filled}{'░'*(width-filled)}\033[0m"

        print(f"  CPU Last  : {cpu:5.1f}%  {bar(cpu)}")
        print(f"  RAM       : {mem.percent:5.1f}%  {bar(mem.percent)}  ({mem.used//1024//1024} / {mem.total//1024//1024} MB)")
        print(f"  Disk      : {disk.percent:5.1f}%  {bar(disk.percent)}  ({disk.free//1024//1024//1024:.1f} GB frei)")
        if temp:
            print(f"  CPU Temp  : {temp:5.1f}°C  {bar(temp * 100/85)}")

        print(f"\n  DB: {stats['total_points']} Messpunkte · {stats['distinct_metrics']} Metriken · {stats['size_kb']} KB")
        print(f"  Metriken: {', '.join(db.list_metrics()[:8])}")
        print("\n  Verlauf: piclaw metrics history cpu_temp_c 3600")


# ── Kamera ──────────────────────────────────────────────────────────

def cmd_camera(args: list):
    import asyncio

    sub = args[0] if args else "snapshot"

    if sub == "list":
        from piclaw.hardware.camera import detect_cameras
        cameras = detect_cameras()
        if not cameras:
            print("  Keine Kameras gefunden.")
            print("  Pi Camera: sudo apt install libcamera-apps")
            print("  USB-Webcam: sudo apt install fswebcam")
        else:
            print(f"\n  Gefundene Kameras ({len(cameras)}):\n")
            for cam in cameras:
                print(f"  [{cam.index}] {cam.name}")
                print(f"       Treiber: {cam.driver}  Auflösung: {cam.resolution[0]}x{cam.resolution[1]}")

    elif sub == "describe":
        from piclaw.hardware.camera import capture_snapshot, describe_image
        prompt = " ".join(args[1:]) if len(args) > 1 else "Beschreibe was du siehst."
        print("  📸 Foto aufnehmen…")
        try:
            path = asyncio.run(capture_snapshot())
            print(f"  ✅ Foto: {path}")
            print(f"  🔍 Vision-Analyse: {prompt}\n")
            description = asyncio.run(describe_image(path, prompt))
            print(f"  {description}")
        except Exception as e:
            print(f"  ❌ Fehler: {e}")

    else:  # snapshot
        from piclaw.hardware.camera import capture_snapshot
        filename = args[1] if len(args) > 1 else None
        print("  📸 Foto aufnehmen…")
        try:
            path = asyncio.run(capture_snapshot(filename=filename))
            import os
            size_kb = round(os.path.getsize(path) / 1024, 1)
            print(f"  ✅ Foto gespeichert: {path} ({size_kb} KB)")
        except Exception as e:
            print(f"  ❌ Fehler: {e}")
            print("  Kamera angeschlossen? Prüfen: piclaw camera list")


# ── Routinen CLI ──────────────────────────────────────────────────

def cmd_routine(args: list):
    """piclaw routine [enable|disable|list] [name]"""
    from piclaw.config import CONFIG_DIR
    from piclaw.routines import RoutineRegistry

    registry = RoutineRegistry(CONFIG_DIR / "routines.json")
    sub = args[0] if args else "list"

    if sub == "list" or sub == "":
        routines = registry.all()
        print("\nRoutinen:\n")
        for r in routines:
            status  = "\033[32m[AN]\033[0m" if r.enabled else "\033[90m[AUS]\033[0m"
            last    = f"  zuletzt: {r.last_run[:16]}" if r.last_run else ""
            print(f"  {status}  {r.name:<25}  {r.cron:<18}  {r.action}{last}")
        print()
        print("  piclaw routine enable <name>   – aktivieren")
        print("  piclaw routine disable <name>  – deaktivieren")
        print()

    elif sub == "enable":
        name = " ".join(args[1:])
        if not name:
            print("Usage: piclaw routine enable <name>")
            return
        if registry.enable(name):
            r = registry.get(name)
            print(f"  \033[32m✓\033[0m Routine '{r.name}' aktiviert  [{r.cron}]")
        else:
            print(f"  Routine '{name}' nicht gefunden.")
            print("  piclaw routine list – alle Routinen anzeigen")

    elif sub == "disable":
        name = " ".join(args[1:])
        if registry.disable(name):
            print(f"  \033[33m✓\033[0m Routine '{name}' deaktiviert.")
        else:
            print(f"  Routine '{name}' nicht gefunden.")

    else:
        print(f"Unbekannter Unterbefehl: {sub}")
        print("  piclaw routine list | enable <name> | disable <name>")


# ── Briefing CLI ──────────────────────────────────────────────────

def cmd_briefing(args: list):
    """piclaw briefing [send] [morning|evening|weekly|status]"""
    import asyncio
    from piclaw.config import load
    from piclaw.briefing import generate_briefing

    sub  = args[0] if args else "print"
    kind = args[1] if len(args) > 1 else "status"

    # "piclaw briefing morning" (kein sub-cmd)
    if sub in ("morning", "evening", "weekly", "status"):
        kind = sub
        sub  = "print"

    cfg = load()

    async def _run():
        msg = await generate_briefing(kind, cfg, llm=None)

        if sub == "send":
            try:
                from piclaw.messaging import build_hub
                hub = build_hub(cfg)
                await hub.send_all(msg)
                print(f"\033[32m✓ Briefing gesendet ({kind})\033[0m\n")
            except Exception as e:
                print(f"\033[33m⚠ Senden fehlgeschlagen: {e}\033[0m\n")

        print(msg)
        print()

    asyncio.run(_run())

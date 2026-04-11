#!/usr/bin/env python3
"""
PiClaw OS â CLI
`piclaw` command available in SSH session.
"""

import asyncio
import os


BANNER = """
  âââââââ âââ ââââââââââ      ââââââ âââ    âââ
  ââââââââââââââââââââââ     âââââââââââ    âââ
  ââââââââââââââ     âââ     âââââââââââ ââ âââ
  âââââââ ââââââ     âââ     ââââââââââââââââââ
  âââ     ââââââââââââââââââââââ  âââââââââââââ
  âââ     âââ ââââââââââââââââââ  âââ ââââââââ  OS v0.9
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
  metrics history   Show metric history (cpu_temp_c, cpu_percent, â¦)
  camera snapshot   Take a photo with the Pi camera
  camera list       List available cameras
  routine           List all routines and their status
  routine enable    Enable a routine (e.g. 'morning_briefing')
  routine disable   Disable a routine
  briefing          Generate and print a briefing now
  skill             Manage ClawHub skills (search, install, list, remove)
  briefing send     Generate and send via messaging (morning/evening/status)
  update            Update PiClaw via git pull (update check|piclaw|system)
  setup             First-boot setup wizard (LLM, Telegram, Soul)
  help              This message

Type 'exit' or Ctrl+C to leave the agent chat.
"""


def _api_running(cfg) -> bool:
    """PrÃ¼ft ob piclaw-api auf localhost lÃ¤uft."""
    import urllib.request
    import urllib.error

    try:
        url = f"http://127.0.0.1:{cfg.api.port}/health"
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


def cmd_chat():
    from piclaw.config import load

    async def _run_via_api(cfg):
        """Chat Ã¼ber WebSocket-API â Modell bleibt im Daemon-RAM."""
        import websockets
        import json
        from piclaw.auth import get_token

        # Token aus auth-Modul (gesetzt beim API-Start) oder aus config
        token = get_token() or cfg.api.secret_key
        if not token:
            raise ValueError("Kein API-Token â piclaw setup ausfÃ¼hren")
        url = f"ws://127.0.0.1:{cfg.api.port}/ws/chat?token={token}"
        print(BANNER)
        print(f"  {cfg.agent_name} ready. Type 'exit' to quit, 'help' for commands.")
        print(
            "  \033[2m(Verbunden mit laufendem Daemon â sofortige Antworten)\033[0m\n"
        )
        try:
            async with websockets.connect(
                url,
                ping_interval=20,  # keepalive alle 20s
                ping_timeout=300,  # 5 Min warten (grosse Modelle + Marketplace)
                open_timeout=15,
                close_timeout=10,
            ) as ws:
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
                    print("\033[2mThinkingâ¦\033[0m", end="\r", flush=True)
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
                                print(
                                    f"\033[1;36m[{cfg.agent_name}]\033[0m {msg['text']}\n"
                                )
                            else:
                                print("\n")
                            break
                        elif msg["type"] == "error":
                            print(f"\n\033[31mâ {msg['text']}\033[0m\n")
                            break
        except Exception as e:
            print(f"\n\033[31mWebSocket-Fehler: {e}\033[0m")
            raise

    async def _run_direct(cfg):
        """Fallback: direkter Agent-Start (lÃ¤dt Modell neu)."""
        from piclaw.agent import Agent

        agent = Agent(cfg)
        await agent.boot()
        print(BANNER)
        print(f"  {cfg.agent_name} ready. Type 'exit' to quit, 'help' for commands.")
        print("  \033[33m(Offline-Modus â API nicht erreichbar)\033[0m\n")
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
            print("\033[2mThinkingâ¦\033[0m", end="\r", flush=True)
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
    import platform
    import asyncio
    from piclaw.config import load

    async def _check():
        cfg = load()
        from piclaw.agent import Agent

        agent = Agent(cfg)
        ok = await agent.llm.health_check()
        import psutil
        import socket

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        print("\nð PiClaw Doctor\n")
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

                _model_display = (
                    _DMP.name if _DMP.exists() else f"{cfg.llm.model} (nicht gefunden)"
                )
        _health_str = (
            "â OK"
            if ok
            else "â UNREACHABLE (check API key)"
            if cfg.llm.backend != "local"
            else "â Modell nicht gefunden â piclaw model download"
        )
        print(f"  LLM backend : {cfg.llm.backend} / {_model_display}")
        print(f"  LLM health  : {_health_str}")
        print(f"  Python      : {platform.python_version()}")
        print(f"  Platform    : {platform.platform()}")
        print(f"  Hostname    : {socket.gethostname()}")
        print(f"  Memory      : {mem.used // 1_048_576} / {mem.total // 1_048_576} MB")
        print(
            f"  Disk        : {disk.used // 1_073_741_824:.1f} / {disk.total // 1_073_741_824:.1f} GB"
        )
        from piclaw.hardware.pi_info import current_temp
        temp = current_temp()
        if temp is not None:
            print(f"  CPU Temp    : {temp:.1f}Â°C")
        # Soul
        from piclaw import soul as soul_mod

        soul_path = soul_mod.get_path()
        # API Token
        if cfg.api.secret_key:
            print("  API Token   : â set (piclaw config token)")
        else:
            print("  API Token   : â¬ not generated yet")
        if soul_path.exists():
            soul_size = soul_path.stat().st_size
            print(f"  Soul        : â {soul_path} ({soul_size} B)")
        else:
            print("  Soul        : â¬ Not created yet (will be on first boot)")
        # Sub-agents
        from piclaw.agents.sa_registry import SubAgentRegistry

        reg = SubAgentRegistry()
        agents = reg.list_all()
        if agents:
            running = sum(1 for a in agents if a.last_status == "running")
            ok_n = sum(1 for a in agents if a.last_status == "ok")
            err_n = sum(1 for a in agents if a.last_status == "error")
            print(
                f"  Sub-Agents  : â {len(agents)} defined  "
                f"(ok={ok_n}, error={err_n}, running={running})"
            )
        else:
            print("  Sub-Agents  : â¬ None defined")
        # ââ Home Assistant ââââââââââââââââââââââââââââââââââââââââ
        try:
            from piclaw.config import CONFIG_FILE
            import tomllib as _tomllib
            _raw = _tomllib.load(open(CONFIG_FILE, "rb")) if CONFIG_FILE.exists() else {}
            _ha = _raw.get("homeassistant", {})
            _ha_url = _ha.get("url", "")
            _ha_token = _ha.get("token", "")
            if _ha_url and _ha_token:
                import aiohttp as _aio
                _ha_connected = False
                for _attempt in range(3):
                    try:
                        async with _aio.ClientSession() as _ses:
                            async with _ses.get(
                                f"{_ha_url.rstrip('/')}/api/",
                                headers={"Authorization": f"Bearer {_ha_token}"},
                                timeout=_aio.ClientTimeout(total=5),
                                ssl=False
                            ) as _r:
                                if _r.status == 200:
                                    _data = await _r.json()
                                    _ver = _data.get("version") or _data.get("ha_version") or ""
                                    _ver_str = f" â HA {_ver}" if _ver else ""
                                    print(f"  Home Assist : â verbunden ({_ha_url}){_ver_str}")
                                    _ha_connected = True
                                    break
                                else:
                                    print(f"  Home Assist : â HTTP {_r.status} â Token ungÃ¼ltig?")
                                    _ha_connected = True
                                    break
                    except Exception as _e:
                        if _attempt < 2:
                            await asyncio.sleep(10)
                        else:
                            print(f"  Home Assist : â Fehler nach 3 Versuchen: {_e}")
                            _ha_connected = True
                            break
            else:
                print("  Home Assist : â¬ nicht konfiguriert (piclaw setup)")
        except Exception as _e:
            print(f"  Home Assist : â Fehler: {_e}")

        # ââ Messaging âââââââââââââââââââââââââââââââââââââââââââââ
        _tg = "â" if cfg.telegram.token and cfg.telegram.chat_id else "â¬"
        _dc = "â" if cfg.discord.token else "â¬"
        _am = "â¬"
        if cfg.agentmail.api_key:
            _am = f"â {cfg.agentmail.email_address}" if cfg.agentmail.email_address else "â (keine Inbox)"
        print(f"  Telegram    : {_tg}")
        print(f"  Discord     : {_dc}")
        print(f"  AgentMail   : {_am}")

        try:
            import aiohttp

            print("  aiohttp     : â")
        except ImportError:
            print("  aiohttp     : â")
        try:
            import fastapi

            print("  fastapi     : â")
        except ImportError:
            print("  fastapi     : â")
        try:
            import scrapling  # noqa: F401

            print("  scrapling   : â")
        except ImportError:
            print("  scrapling   : â  (pip install scrapling)")

        # ââ System-Checks (Invarianten) ââââââââââââââââââââââââââ
        from pathlib import Path as _Path
        import stat as _stat

        _install = _Path("/opt/piclaw")
        _symlink = _install / "piclaw"
        _target  = _install / "piclaw-os" / "piclaw"
        _logdir  = _Path("/var/log/piclaw")
        _ipc     = _Path("/etc/piclaw/ipc")

        # INV_021 â Symlink
        if _symlink.is_symlink() and _symlink.resolve() == _target.resolve():
            print("  Symlink     : â  /opt/piclaw/piclaw â piclaw-os/piclaw/")
        elif _symlink.exists():
            print("  Symlink     : â  Kein Symlink! git pull hat keinen Effekt")
            print("                    sudo bash /opt/piclaw/piclaw-os/tools/fix_install_path.sh")
        else:
            print("  Symlink     : â¬  /opt/piclaw nicht gefunden (abweichende Installation?)")

        # INV_022 â /var/log/piclaw
        if _logdir.exists():
            try:
                import pwd as _pwd
                _owner = _pwd.getpwuid(_logdir.stat().st_uid).pw_name
                if _owner == "piclaw":
                    print("  Log-Dir     : â  /var/log/piclaw (owner: piclaw)")
                else:
                    print(f"  Log-Dir     : â  Owner: {_owner} (erwartet: piclaw)")
                    print("                    sudo chown -R piclaw:piclaw /var/log/piclaw")
            except Exception:
                print("  Log-Dir     : â¬  Rechte nicht prÃ¼fbar")
        else:
            print("  Log-Dir     : â  /var/log/piclaw fehlt")
            print("                    sudo mkdir -p /var/log/piclaw && sudo chown -R piclaw:piclaw /var/log/piclaw")

        # IPC chmod 1777
        if _ipc.exists():
            _mode = _stat.S_IMODE(_ipc.stat().st_mode)
            if _mode == 0o1777:
                print("  IPC-Dir     : â  /etc/piclaw/ipc (chmod 1777)")
            else:
                print(f"  IPC-Dir     : â  chmod {oct(_mode)} (erwartet 1777)")
                print("                    sudo chmod 1777 /etc/piclaw/ipc")
        else:
            print("  IPC-Dir     : â¬  /etc/piclaw/ipc fehlt")

        # .git/objects Rechte (verhindert 'piclaw update' Fehler)
        _git_objects = _install / ".git" / "objects"
        if _git_objects.exists():
            import pwd as _pwd2
            try:
                _git_owner = _pwd2.getpwuid(_git_objects.stat().st_uid).pw_name
                if _git_owner == "piclaw":
                    print("  .git Rechte : â  /opt/piclaw/.git (owner: piclaw)")
                else:
                    print(f"  .git Rechte : â  Owner: {_git_owner} (erwartet: piclaw)")
                    print("                    sudo chown -R piclaw:piclaw /opt/piclaw/.git")
            except Exception:
                print("  .git Rechte : â¬  Nicht prÃ¼fbar")
        else:
            print("  .git Rechte : â¬  /opt/piclaw/.git nicht gefunden")

        print()

    asyncio.run(_check())


def cmd_web():
    from piclaw.config import load
    import socket

    cfg = load()
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except Exception:
        ip = "YOUR_PI_IP"
    print("\n  ð PiClaw Web UI")
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
            print(f"\n  ð API Token (Bearer):\n  {cfg.api.secret_key}\n")
            print(f"  Usage: curl -H 'Authorization: Bearer {cfg.api.secret_key}' \\")
            print(f"         http://piclaw.local:{cfg.api.port}/api/stats\n")
        else:
            print("  Token not generated yet. Start the API service first.")
    elif args[0] == "set" and len(args) == 3:
        key, val = args[1], args[2]
        _llm_changed = False
        if key == "llm.api_key":
            cfg.llm.api_key = val
            _llm_changed = True
        elif key == "llm.model":
            cfg.llm.model = val
            _llm_changed = True
        elif key == "llm.backend":
            cfg.llm.backend = val
            _llm_changed = True
        elif key == "llm.base_url":
            cfg.llm.base_url = val
            _llm_changed = True
        elif key == "agent_name":
            cfg.agent_name = val
        else:
            print(f"Unknown config key: {key}")
            print("Supported: llm.api_key, llm.model, llm.backend, llm.base_url, agent_name")
            return
        save(cfg)
        print(f"  â {key} updated.")
        # LLM-Registry leeren damit der Router beim nÃ¤chsten Start neu bootstrappt
        if _llm_changed:
            from piclaw.config import CONFIG_DIR
            registry_file = CONFIG_DIR / "llm_registry.json"
            if registry_file.exists():
                registry_file.write_text("{}")
                print("  ð LLM-Registry zurÃ¼ckgesetzt (wird beim Neustart neu aufgebaut)")
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
        from piclaw.llm.model_manager import DEFAULT_MODEL_ID as _DEFAULT_MID
        mid = args[1] if len(args) > 1 else _DEFAULT_MID
        result = asyncio.run(download_model(mid))
        if result:
            print(f"  {result}")
    elif sub == "remove":
        mid = args[1] if len(args) > 1 else ""
        print(remove_model(mid))
    elif sub == "status":
        from piclaw.llm.local import DEFAULT_MODEL_PATH

        path = DEFAULT_MODEL_PATH
        if path.exists():
            mb = path.stat().st_size // 1_048_576
            print(f"  â Phi-3 Mini Q4 installed ({mb} MB) â {path}")
        else:
            print("  â¬ Not downloaded. Run: piclaw model download")
    else:
        print("Usage: piclaw model [list|download [id]|remove [id]|status]")


def cmd_messaging(args):
    from piclaw.config import load

    sub = args[0] if args else "status"
    cfg = load()

    if sub == "status":
        print("\nð¡ Messaging Adapters\n")
        adapters = [
            (
                "Telegram",
                bool(cfg.telegram.token and cfg.telegram.chat_id),
                f"chat_id={cfg.telegram.chat_id or '(not set)'}",
            ),
            (
                "Discord",
                bool(cfg.discord.token and cfg.discord.channel_id),
                f"channel={cfg.discord.channel_id or '(not set)'}",
            ),
            (
                "Threema",
                bool(cfg.threema.gateway_id and cfg.threema.api_secret),
                f"gateway={cfg.threema.gateway_id or '(not set)'}",
            ),
            (
                "WhatsApp",
                bool(cfg.whatsapp.access_token),
                f"number={cfg.whatsapp.recipient or '(not set)'}",
            ),
        ]
        for name, ok, detail in adapters:
            icon = "â" if ok else "â¬"
            print(f"  {icon} {name:12} {detail}")
        print()

    elif sub == "test":
        print("Sending test message to all configured adaptersâ¦")

        async def _test():
            from piclaw.messaging import build_hub

            hub = build_hub(cfg)
            await hub.send_all("ð§ª PiClaw test message â adapters working correctly.")
            print(f"  Sent to: {', '.join(hub.active_adapters()) or 'none configured'}")

        asyncio.run(_test())

    elif sub == "setup":
        sub2 = args[1] if len(args) > 1 else None
        _messaging_setup_wizard(cfg, sub2)

    else:
        print(
            "Usage: piclaw messaging [status|test|setup [telegram|discord|threema|whatsapp|agentmail]]"
        )


def _messaging_setup_wizard(cfg, platform=None):
    """Interactive setup wizard for messaging adapters."""
    platforms = {
        "telegram": _setup_telegram,
        "discord": _setup_discord,
        "threema": _setup_threema,
        "whatsapp": _setup_whatsapp,
        "agentmail": _setup_agentmail,
    }

    if platform and platform in platforms:
        platforms[platform](cfg)
        return

    print("\nð§ Messaging Setup Wizard\n")
    print("Welchen Adapter mÃ¶chtest du einrichten?")
    for i, (name, _) in enumerate(platforms.items(), 1):
        current = {
            "telegram": bool(cfg.telegram.token),
            "discord": bool(cfg.discord.token),
            "threema": bool(cfg.threema.gateway_id),
            "whatsapp": bool(cfg.whatsapp.access_token),
            "agentmail": bool(cfg.agentmail.api_key),
        }[name]
        status = "â" if current else "â¬"
        label = "AgentMail (E-Mail fÃ¼r Dameon)" if name == "agentmail" else name.capitalize()
        print(f"  {i}. {status} {label}")
    print("  0. Abbrechen\n")

    choice = input("Auswahl [0-5]: ").strip()
    names = list(platforms.keys())
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        name = names[int(choice) - 1]
        platforms[name](cfg)
    else:
        print("Abgebrochen.")


def _setup_telegram(cfg):
    from piclaw.config import save

    print("\nð± Telegram Setup\n")
    print("1. Gehe zu @BotFather in Telegram")
    print("2. Tippe /newbot und folge den Anweisungen")
    print("3. Kopiere den Bot-Token\n")
    token = input("Bot-Token (oder Enter zum Ãberspringen): ").strip()
    if not token:
        print("Ãbersprungen.")
        return
    print("\n4. Schreibe deinem neuen Bot eine Nachricht")
    print("5. Ãffne: https://api.telegram.org/bot<TOKEN>/getUpdates")
    print("   und kopiere die chat.id aus der Antwort\n")
    chat_id = input("Chat-ID: ").strip()
    if not chat_id:
        print("Abgebrochen.")
        return
    cfg.telegram.token = token
    cfg.telegram.chat_id = chat_id
    save(cfg)
    print("\nâ Telegram konfiguriert.")
    print("   Neustart: sudo systemctl restart piclaw-api\n")


def _setup_discord(cfg):
    from piclaw.config import save

    print("\nð® Discord Setup\n")
    print("1. https://discord.com/developers/applications â New Application")
    print("2. Bot â Add Bot â 'Message Content Intent' aktivieren")
    print("3. Bot-Token kopieren\n")
    token = input("Bot-Token (oder Enter zum Ãberspringen): ").strip()
    if not token:
        print("Ãbersprungen.")
        return
    print("\n4. OAuth2 â URL Generator â bot + Read/Send Messages â einladen")
    print("5. Discord: Einstellungen â Erweitert â Entwicklermodus")
    print("   Rechtsklick auf Kanal â Kanal-ID kopieren\n")
    channel_id_str = input("Kanal-ID: ").strip()
    if not channel_id_str.isdigit():
        print("UngÃ¼ltige Kanal-ID.")
        return
    user_ids_str = input("Deine User-ID (Enter = alle erlaubt): ").strip()
    allowed = [int(user_ids_str)] if user_ids_str.isdigit() else []
    cfg.discord.token = token
    cfg.discord.channel_id = int(channel_id_str)
    cfg.discord.allowed_users = allowed
    save(cfg)
    print("\nâ Discord konfiguriert.")
    print("   Neustart: sudo systemctl restart piclaw-api\n")


def _setup_threema(cfg):
    from piclaw.config import save
    from pathlib import Path

    print("\nð Threema Gateway Setup\n")
    print("1. Registrierung: https://gateway.threema.ch")
    print("   â Gateway-ID beantragen (z.B. *PICLAW01)")
    print("   â E2E-Modus wÃ¤hlen\n")
    print("2. SchlÃ¼sselpaar generieren:")
    print(
        "   threema-gateway generate /etc/piclaw/threema-private.key /etc/piclaw/threema-public.key"
    )
    print("   Dann Public Key im Gateway-Portal hochladen\n")
    gw_id = input("Gateway-ID (z.B. *PICLAW01, Enter zum Ãberspringen): ").strip()
    if not gw_id:
        print("Ãbersprungen.")
        return
    api_secret = input("API-Secret: ").strip()
    recipient = input("Deine Threema-ID (8 Zeichen): ").strip()
    key_file = input(f"Private-Key-Datei [{cfg.threema.private_key_file}]: ").strip()
    if not key_file:
        key_file = cfg.threema.private_key_file
    cfg.threema.gateway_id = gw_id
    cfg.threema.api_secret = api_secret
    cfg.threema.recipient_id = recipient
    cfg.threema.private_key_file = key_file
    save(cfg)
    print("\nâ Threema konfiguriert.")
    if not Path(key_file).exists():
        print(f"   â ï¸  Key-Datei nicht gefunden: {key_file}")
        print("   Erst SchlÃ¼ssel generieren, dann Neustart.\n")
    else:
        print("   Neustart: sudo systemctl restart piclaw-api\n")


def _setup_whatsapp(cfg):
    from piclaw.config import save

    print("\nð¬ WhatsApp Meta Cloud API Setup\n")
    print("â ï¸  Voraussetzung: Ãffentliche HTTPS-URL!")
    print("   Einfachste LÃ¶sung â Cloudflare Tunnel (kostenlos):")
    print("   cloudflared tunnel --url http://localhost:7842")
    print("   â gibt eine URL aus (z.B. https://abc.trycloudflare.com)\n")
    print("1. https://developers.facebook.com â App erstellen â WhatsApp")
    print("2. TemporÃ¤ren Access Token kopieren")
    print("3. Telefonnummer-ID kopieren\n")
    access_token = input("Access Token (EAA..., Enter zum Ãberspringen): ").strip()
    if not access_token:
        print("Ãbersprungen.")
        return
    phone_number_id = input("Telefonnummer-ID: ").strip()
    app_secret = input("App Secret: ").strip()
    recipient = input("Deine WhatsApp-Nummer (+49...): ").strip()
    verify_token = input(f"Verify Token [{cfg.whatsapp.verify_token}]: ").strip()
    if not verify_token:
        verify_token = cfg.whatsapp.verify_token
    cfg.whatsapp.access_token = access_token
    cfg.whatsapp.phone_number_id = phone_number_id
    cfg.whatsapp.app_secret = app_secret
    cfg.whatsapp.recipient = recipient
    cfg.whatsapp.verify_token = verify_token
    save(cfg)
    print("\nâ WhatsApp konfiguriert.")
    print("   Webhook-URL im Meta-Portal eintragen:")
    print("   https://DEINE-URL/webhook/whatsapp")
    print(f"  Verify Token: {verify_token}")
    print("   Neustart: sudo systemctl restart piclaw-api\n")
    print("   Then type in your Discord channel to chat with the agent.\n")


def _setup_agentmail(cfg):
    from piclaw.config import save

    print("\nð§ AgentMail Setup â E-Mail-Adresse fÃ¼r Dameon\n")
    print("AgentMail gibt deinem Agenten eine eigene E-Mail-Adresse.")
    print("Damit kann er sich bei API-Providern registrieren,")
    print("BestÃ¤tigungsmails empfangen und autonom handeln.\n")
    print("1. Gehe zu https://agentmail.to")
    print("2. Erstelle einen Account und generiere einen API-Key")
    print("3. Kopiere den API-Key\n")
    api_key = input("AgentMail API-Key (oder Enter zum Ãberspringen): ").strip()
    if not api_key:
        print("Ãbersprungen.")
        return

    cfg.agentmail.api_key = api_key
    save(cfg)

    # Inbox erstellen
    print("\nMÃ¶chtest du direkt eine Inbox fÃ¼r Dameon erstellen?")
    agent_name = cfg.agent_name or "Dameon"
    username = input(f"Benutzername [{agent_name.lower()}]: ").strip()
    if not username:
        username = agent_name.lower()

    print(f"\nErstelle Inbox {username}@agentmail.to ...")
    try:
        import asyncio

        async def _create():
            from piclaw.tools.agentmail import agentmail_create_inbox
            result = await agentmail_create_inbox(cfg.agentmail, display_name=agent_name, username=username)
            return result

        result = asyncio.run(_create())
        print(result)

        # Inbox-ID aus Ergebnis extrahieren und speichern
        if "ID:" in result:
            import re
            id_match = re.search(r"ID:\s*(\S+)", result)
            email_match = re.search(r"Email:\s*(\S+)", result)
            if id_match:
                cfg.agentmail.inbox_id = id_match.group(1)
            if email_match:
                cfg.agentmail.email_address = email_match.group(1)
            save(cfg)
            print("\nâ AgentMail konfiguriert.")
            print(f"   E-Mail: {cfg.agentmail.email_address}")
            print(f"   Inbox-ID: {cfg.agentmail.inbox_id}")
        else:
            print("\nâ ï¸ API-Key gespeichert, aber Inbox konnte nicht erstellt werden.")
            print("   Dameon kann die Inbox beim nÃ¤chsten Start selbst erstellen.")

    except ImportError:
        print("\nâ ï¸ 'agentmail' Python-Paket nicht installiert.")
        print("   Installiere mit: pip install agentmail --break-system-packages")
        print("   API-Key wurde gespeichert â Inbox kann danach erstellt werden.")
    except Exception as e:
        print(f"\nâ ï¸ Fehler beim Erstellen der Inbox: {e}")
        print("   API-Key wurde gespeichert â Inbox kann spÃ¤ter erstellt werden.")

    print("   Neustart: sudo systemctl restart piclaw-agent piclaw-api\n")


def cmd_soul(args):
    from piclaw import soul as soul_mod

    sub = args[0] if args else "show"

    if sub == "show":
        content = soul_mod.load()
        path = soul_mod.get_path()
        print(f"\nð Soul file: {path}\n")
        print(content)
        print()

    elif sub == "edit":
        path = soul_mod.get_path()
        # Ensure file exists before opening
        soul_mod.load()
        editor = os.environ.get("EDITOR", "nano")
        print(f"  Opening {path} in {editor}â¦")
        os.system(f"{editor} {path}")
        print("  Soul updated. Changes take effect in the next conversation.")

    elif sub == "reset":
        confirm = (
            input(
                "  â ï¸  Reset soul to default? This overwrites your customizations. [y/N] "
            )
            .strip()
            .lower()
        )
        if confirm == "y":
            from piclaw.soul import DEFAULT_SOUL

            result = soul_mod.save(DEFAULT_SOUL)
            print(f"  â {result}")
        else:
            print("  Abgebrochen.")

    else:
        print("Usage: piclaw soul [show|edit|reset]")


def cmd_agent(args):
    from piclaw.agents.sa_registry import SubAgentRegistry

    sub = args[0] if args else "list"
    name = args[1] if len(args) > 1 else None

    registry = SubAgentRegistry()

    if sub == "list":
        agents = registry.list_all()
        if not agents:
            print("\n  No sub-agents defined yet.")
            print("  Create one via the agent chat: 'Erstelle einen Agenten derâ¦'\n")
            return
        print(f"\n  Sub-Agents ({len(agents)}):\n")
        for a in agents:
            status_icon = {
                "ok": "â",
                "error": "â",
                "timeout": "â±ï¸",
                "running": "âï¸",
                None: "â¬",
            }.get(a.last_status, "â¬")
            enabled_str = "" if a.enabled else "  [disabled]"
            print(f"  {status_icon} [{a.id}] {a.name}{enabled_str}")
            print(f"       {a.description}")
            print(
                f"       schedule: {a.schedule}  |  tools: {', '.join(a.tools) if a.tools else 'all'}"
            )
            print(
                f"       last run: {a.last_run or 'never'}  |  status: {a.last_status or 'â'}"
            )
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
            print("  â¹ï¸  API not reachable. To start from within the agent, type:")
            print(f"     piclaw  â  'Starte den Sub-Agenten {name}'")

    elif sub == "stop":
        if not name:
            print("Usage: piclaw agent stop <name>")
            return
        result = _api_call("POST", f"/api/subagents/{name}/stop")
        if result:
            print(f"  {result.get('result', result)}")
        else:
            print("  â¹ï¸  API not reachable. Agent may not be running.")

    elif sub == "remove":
        if not name:
            print("Usage: piclaw agent remove <name>")
            return
        agent = registry.get(name)
        if not agent:
            print(f"  Sub-agent '{name}' not found.")
            return
        confirm = (
            input(f"  Delete '{agent.name}' ({agent.description})? [y/N] ")
            .strip()
            .lower()
        )
        if confirm == "y":
            result = _api_call("DELETE", f"/api/subagents/{name}")
            if result:
                print("  â Removed.")
            else:
                # Fallback: direct registry delete
                registry.remove(name)
                print(f"  â '{name}' removed from registry.")
        else:
            print("  Abgebrochen.")

    elif sub == "run":
        if not name:
            print("Usage: piclaw agent run <name>")
            return
        result = _api_call("POST", f"/api/subagents/{name}/run")
        if result:
            print("  âï¸  Triggered. Check logs or Telegram for result.")
        else:
            print("  â¹ï¸  API not reachable. Agent daemon may not be running.")

    else:
        print("Usage: piclaw agent [list|start|stop|remove|run] [name]")


def _api_call(method: str, path: str, body: dict = None) -> dict | None:
    """Simple synchronous HTTP call to local PiClaw API. Returns None if unreachable."""
    import urllib.request
    import json as _json
    import logging as _log
    from piclaw.config import load

    cfg = load()
    url = f"http://127.0.0.1:{cfg.api.port}{path}"
    _logger = _log.getLogger("piclaw.cli.api")
    try:
        data = _json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
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
    FÃ¼hrt Schritt fÃ¼r Schritt durch LLM, Messaging, WLAN,
    Hardware und Soul â ohne Browser, ohne GUI.
    """
    from piclaw.wizard import run as wizard_run

    wizard_run()


def _edit_soul_interactive():
    """Open SOUL.md in $EDITOR or guide inline input."""
    import os
    import subprocess
    from piclaw import soul

    editor = os.environ.get("EDITOR", "")
    if editor:
        import piclaw.soul as soul_mod

        soul_path = soul_mod.SOUL_FILE
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        if not soul_path.exists():
            soul.load()  # creates default
        subprocess.call([editor, str(soul_path)])
        print("  â Soul gespeichert.")
    else:
        print("  Kein $EDITOR gesetzt. Gib deinen Soul direkt ein.")
        print("  (Leere Zeile + Enter zum AbschlieÃen, oder Ctrl+C zum Ãberspringen)\n")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        if lines:
            soul.save("\n".join(lines))
            print("  â Soul gespeichert.")
        else:
            print("  â© Kein Inhalt â Ã¼bersprungen.")


def cmd_llm(args):
    """Manage LLM backends in the registry."""
    from piclaw.config import load
    from piclaw.llm.registry import LLMRegistry, BackendConfig

    sub = args[0] if args else "list"
    load()

    registry = LLMRegistry()

    if sub == "list":
        print(registry.summary())

    elif sub == "add":
        # Parse --key value pairs
        kw = {}
        i = 1
        while i < len(args):
            if args[i].startswith("--") and i + 1 < len(args):
                key = args[i][2:].replace("-", "_")
                kw[key] = args[i + 1]
                i += 2
            else:
                i += 1
        required = ["name", "provider", "model"]
        missing = [r for r in required if r not in kw]
        if missing:
            print(f"  Fehlende Parameter: {', '.join('--' + m for m in missing)}")
            print(
                "  Beispiel: piclaw llm add --name kimi --provider openai --model moonshotai/kimi-k2-instruct-0905 --api-key nvapi-... --base-url https://integrate.api.nvidia.com/v1 --priority 8"
            )
            return
        tags = [t.strip() for t in kw.pop("tags", "general").split(",")]
        bc = BackendConfig(
            name=kw.pop("name"),
            provider=kw.pop("provider"),
            model=kw.pop("model"),
            api_key=kw.pop("api_key", kw.pop("api-key", "")),
            base_url=kw.pop("base_url", kw.pop("base-url", "")),
            priority=int(kw.pop("priority", 5)),
            temperature=float(kw.pop("temperature", 0.7)),
            max_tokens=int(kw.pop("max_tokens", 4096)),
            timeout=int(kw.pop("timeout", 60)),
            tags=tags,
            notes=kw.pop("notes", ""),
        )
        print(f"  {registry.add(bc)}")

    elif sub == "remove":
        name = args[1] if len(args) > 1 else None
        if not name:
            print("  Usage: piclaw llm remove <name>")
            return
        print(f"  {registry.remove(name)}")

    elif sub == "update":
        name = args[1] if len(args) > 1 else None
        if not name:
            print("  Usage: piclaw llm update <name> --key value ...")
            return
        kw = {}
        i = 2
        while i < len(args):
            if args[i].startswith("--") and i + 1 < len(args):
                key = args[i][2:].replace("-", "_")
                kw[key] = args[i + 1]
                i += 2
            else:
                i += 1
        if not kw:
            print("  Keine Ãnderungen angegeben.")
            return
        print(f"  {registry.update(name, **kw)}")

    elif sub == "enable":
        name = args[1] if len(args) > 1 else None
        if name:
            print(f"  {registry.update(name, enabled=True)}")
    elif sub == "disable":
        name = args[1] if len(args) > 1 else None
        if name:
            print(f"  {registry.update(name, enabled=False)}")


    elif sub == "test":
        name = args[1] if len(args) > 1 else None
        if not name:
            print("  Usage: piclaw llm test <name>")
            return
        cfg = registry.get(name)
        if not cfg:
            print(f"  Backend '{name}' nicht gefunden.")
            return
        import asyncio
        import time
        from piclaw.llm.api import OpenAIBackend, AnthropicBackend
        from piclaw.llm.base import Message
        api_key = cfg.api_key or ""
        print(f"  Testing '{name}' ({cfg.provider}/{cfg.model})...")
        t0 = time.time()
        try:
            if cfg.provider == "anthropic":
                backend = AnthropicBackend(
                    api_key=api_key, model=cfg.model,
                    temperature=cfg.temperature, max_tokens=32, timeout=15
                )
            else:
                backend = OpenAIBackend(
                    api_key=api_key, model=cfg.model,
                    base_url=cfg.base_url or "", temperature=cfg.temperature,
                    max_tokens=32, timeout=15
                )
            msgs = [Message(role="user", content="Reply with exactly: OK")]
            resp = asyncio.run(backend.chat(msgs))
            ms = int((time.time() - t0) * 1000)
            reply = (resp.content or "").strip()[:60]
            print(f"  OK ({ms}ms) -> {reply!r}")
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            print(f"  FEHLER ({ms}ms): {e}")
    else:
        print("Usage: piclaw llm [list|add|remove|update|enable|disable|test]")
        print("  piclaw llm list")
        print(
            "  piclaw llm add --name <n> --provider openai --model <m> --api-key <k> --base-url <u> --priority 8 --tags general,coding"
        )
        print("  piclaw llm remove <name>")
        print("  piclaw llm update <name> --model <new-model>")
        print("  piclaw llm enable/disable <name>")


# ââ Update âââââââââââââââââââââââââââââââââââââââââââââââââââââââââ


def cmd_update(args: list):
    """piclaw update [check|piclaw|system]"""
    import asyncio
    from piclaw.config import load
    from piclaw.tools.updater import system_update

    sub = args[0] if args else "piclaw"
    cfg = load()

    print(f"\n  ð PiClaw Update ({sub})â¦\n")
    result = asyncio.run(system_update(target=sub, cfg=cfg.updater))
    print(f"  {result}\n")


# ââ Debug ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ


def cmd_debug(args: list):
    """piclaw debug â run debug/test scripts via pytest"""
    import asyncio
    import os
    import sys
    from pathlib import Path

    base_dir = Path(__file__).parent.parent
    tests_dir = base_dir / "tests"
    debug_dir = tests_dir / "debug"

    scripts_map = {}
    if tests_dir.exists():
        for f in sorted(tests_dir.glob("test_*.py")):
            scripts_map[f"[test]  {f.name}"] = f
    if debug_dir.exists():
        for f in sorted(debug_dir.glob("test_debug_*.py")):
            scripts_map[f"[debug] {f.name}"] = f

    if not scripts_map:
        print("\n  â Keine Testskripte gefunden.\n")
        return

    print("\nð PiClaw Debug")
    print("â" * 40)
    entries = list(scripts_map.keys())
    for i, name in enumerate(entries, 1):
        print(f"  {i}. {name}")
    print("  0. Abbrechen")
    print("  a. Alle ausfÃ¼hren\n")

    choice = input("Auswahl [0/a/Nummer]: ").strip().lower()
    if choice == "0" or not choice:
        return
    if choice == "a":
        selected = entries
    else:
        try:
            selected = [
                entries[int(x.strip()) - 1] for x in choice.split(",") if x.strip()
            ]
        except (ValueError, IndexError):
            print("  â UngÃ¼ltige Auswahl")
            return

    paths = [str(scripts_map[s]) for s in selected]
    save = input("Ausgabe in Datei speichern? [y/N]: ").strip().lower() in ("y", "j")

    async def _run():
        all_output = []
        for path in paths:
            script = Path(path)
            # [debug] scripts run directly with Python, [test] scripts via pytest
            if script.parent.name == "debug":
                cmd = [sys.executable, path]
            else:
                cmd = [sys.executable, "-m", "pytest", "-v", path]

            print(f"\n  â¶  {script.name}\n")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(base_dir),
                env={"PYTHONPATH": str(base_dir), **os.environ},
            )
            out, _ = await proc.communicate()
            output = out.decode("utf-8", errors="replace")
            print(output)
            all_output.append(f"=== {script.name} ===\n{output}")

        if save:
            log = base_dir / "debug_output.txt"
            log.write_text("\n".join(all_output))
            print(f"\n  ð¾ Gespeichert: {log}\n")

    asyncio.run(_run())


def main():
    import sys

    args = sys.argv[1:]
    if not args:
        cmd_chat()
        return

    cmd = args[0]
    if cmd in ("chat", ""):
        cmd_chat()
    elif cmd == "doctor":
        cmd_doctor()
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "web":
        cmd_web()
    elif cmd == "config":
        cmd_config(args[1:])
    elif cmd == "model":
        cmd_model(args[1:])
    elif cmd == "soul":
        cmd_soul(args[1:])
    elif cmd == "agent":
        cmd_agent(args[1:])
    elif cmd == "messaging":
        cmd_messaging(args[1:])
    elif cmd == "start":
        cmd_service("start")
    elif cmd == "stop":
        cmd_service("stop")
    elif cmd == "status":
        cmd_service("status")
    elif cmd == "backup":
        cmd_backup(args[1:])
    elif cmd == "metrics":
        cmd_metrics(args[1:])
    elif cmd == "camera":
        cmd_camera(args[1:])
    elif cmd == "routine":
        cmd_routine(args[1:])
    elif cmd == "briefing":
        cmd_briefing(args[1:])
    elif cmd == "skill":
        cmd_skill(args[1:])
    elif cmd == "llm":
        cmd_llm(args[1:])
    elif cmd == "update":
        cmd_update(args[1:])
    elif cmd == "debug":
        cmd_debug(args[1:])
    elif cmd in ("help", "-h", "--help"):
        print(BANNER + HELP)
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'piclaw help' for available commands.")


# ââ Backup âââââââââââââââââââââââââââââââââââââââââââââââââââââââââ


def cmd_backup(args: list):
    import asyncio
    from piclaw.backup import (
        create_backup,
        list_backups,
        restore_backup,
        format_backup_list,
    )

    sub = args[0] if args else "create"

    if sub == "list":
        backups = list_backups()
        print(format_backup_list(backups))

    elif sub in ("restore", "wiederherstellen"):
        backup_path = None
        if len(args) > 1 and args[1] == "--file":
            from pathlib import Path

            backup_path = Path(args[2])

        print("  ð Backup-Inhalte prÃ¼fen (dry-run)â¦")
        dry = asyncio.run(restore_backup(backup_path=backup_path, dry_run=True))
        if not dry["ok"]:
            print(f"  â {dry['error']}")
            return

        print(f"\n  Backup: {dry['backup']}  ({dry['backup_ts']})")
        print(f"  {len(dry['restored'])} Dateien werden wiederhergestellt:")
        for f in dry["restored"][:10]:
            print(f"    {f}")
        if len(dry["restored"]) > 10:
            print(f"    â¦ und {len(dry['restored']) - 10} weitere")

        ans = input("\n  Wirklich wiederherstellen? [j/N]: ").strip().lower()
        if ans not in ("j", "y"):
            print("  Abgebrochen.")
            return

        result = asyncio.run(restore_backup(backup_path=backup_path))
        if result["ok"]:
            print(f"\n  â {len(result['restored'])} Dateien wiederhergestellt.")
            print("  Services neu starten: piclaw stop && piclaw start")
        else:
            print(f"\n  â Fehler: {result['errors']}")

    else:  # create
        note = " ".join(args[1:]) if len(args) > 1 else ""
        inc_metrics = "--metrics" in args

        print("  ð¦ Backup wird erstelltâ¦")
        path = asyncio.run(create_backup(include_metrics=inc_metrics, note=note))
        import os

        size_kb = round(os.path.getsize(path) / 1024, 1)
        print(f"\n  â Backup erstellt: {path}")
        print(f"     GrÃ¶Ãe: {size_kb} KB")
        print("\n  Auflisten: piclaw backup list")
        print("  Wiederherstellen: piclaw backup restore")


# ââ Metriken ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ


def cmd_metrics(args: list):
    from piclaw.metrics import get_db, _read_cpu_temp
    import psutil

    sub = args[0] if args else "show"

    if sub == "history":
        metric = args[1] if len(args) > 1 else "cpu_temp_c"
        since = int(args[2]) if len(args) > 2 else 3600

        db = get_db()
        rows = db.query(metric, since_s=since, limit=20)
        if not rows:
            print(f"  Keine Daten fÃ¼r '{metric}' in den letzten {since // 60} Minuten.")
            print(f"  Bekannte Metriken: {', '.join(db.list_metrics())}")
            return

        unit = rows[0].get("unit", "")
        print(f"\n  {metric} (letzte {len(rows)} Werte, {since // 60}min):\n")
        import datetime
        for r in reversed(rows):
            dt = datetime.datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
            bar_len = int(r["value"] / 2) if unit in ("%", "Â°C") else 10
            bar = "â" * min(bar_len, 50)
            print(f"  {dt}  {r['value']:>7.1f}{unit}  {bar}")

    else:  # show â aktuelle Werte
        db = get_db()
        stats = db.stats()

        print("\n  ð Aktuelle Systemmetriken:\n")
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        temp = _read_cpu_temp()

        def bar(pct, width=20):
            filled = int(pct / 100 * width)
            color = "\033[32m" if pct < 70 else "\033[33m" if pct < 85 else "\033[31m"
            return f"{color}{'â' * filled}{'â' * (width - filled)}\033[0m"

        print(f"  CPU Last  : {cpu:5.1f}%  {bar(cpu)}")
        print(
            f"  RAM       : {mem.percent:5.1f}%  {bar(mem.percent)}  ({mem.used // 1024 // 1024} / {mem.total // 1024 // 1024} MB)"
        )
        print(
            f"  Disk      : {disk.percent:5.1f}%  {bar(disk.percent)}  ({disk.free // 1024 // 1024 // 1024:.1f} GB frei)"
        )
        if temp:
            print(f"  CPU Temp  : {temp:5.1f}Â°C  {bar(temp * 100 / 85)}")

        print(
            f"\n  DB: {stats['total_points']} Messpunkte Â· {stats['distinct_metrics']} Metriken Â· {stats['size_kb']} KB"
        )
        print(f"  Metriken: {', '.join(db.list_metrics()[:8])}")
        print("\n  Verlauf: piclaw metrics history cpu_temp_c 3600")


# ââ Kamera ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ


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
                print(
                    f"       Treiber: {cam.driver}  AuflÃ¶sung: {cam.resolution[0]}x{cam.resolution[1]}"
                )

    elif sub == "describe":
        from piclaw.hardware.camera import capture_snapshot, describe_image

        prompt = " ".join(args[1:]) if len(args) > 1 else "Beschreibe was du siehst."
        print("  ð¸ Foto aufnehmenâ¦")
        try:
            path = asyncio.run(capture_snapshot())
            print(f"  â Foto: {path}")
            print(f"  ð Vision-Analyse: {prompt}\n")
            description = asyncio.run(describe_image(path, prompt))
            print(f"  {description}")
        except Exception as e:
            print(f"  â Fehler: {e}")

    else:  # snapshot
        from piclaw.hardware.camera import capture_snapshot

        filename = args[1] if len(args) > 1 else None
        print("  ð¸ Foto aufnehmenâ¦")
        try:
            path = asyncio.run(capture_snapshot(filename=filename))
            import os

            size_kb = round(os.path.getsize(path) / 1024, 1)
            print(f"  â Foto gespeichert: {path} ({size_kb} KB)")
        except Exception as e:
            print(f"  â Fehler: {e}")
            print("  Kamera angeschlossen? PrÃ¼fen: piclaw camera list")


# ââ Routinen CLI ââââââââââââââââââââââââââââââââââââââââââââââââââ


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
            status = "\033[32m[AN]\033[0m" if r.enabled else "\033[90m[AUS]\033[0m"
            last = f"  zuletzt: {r.last_run[:16]}" if r.last_run else ""
            print(f"  {status}  {r.name:<25}  {r.cron:<18}  {r.action}{last}")
        print()
        print("  piclaw routine enable <name>   â aktivieren")
        print("  piclaw routine disable <name>  â deaktivieren")
        print()

    elif sub == "enable":
        name = " ".join(args[1:])
        if not name:
            print("Usage: piclaw routine enable <name>")
            return
        if registry.enable(name):
            r = registry.get(name)
            print(f"  \033[32mâ\033[0m Routine '{r.name}' aktiviert  [{r.cron}]")
        else:
            print(f"  Routine '{name}' nicht gefunden.")
            print("  piclaw routine list â alle Routinen anzeigen")

    elif sub == "disable":
        name = " ".join(args[1:])
        if registry.disable(name):
            print(f"  \033[33mâ\033[0m Routine '{name}' deaktiviert.")
        else:
            print(f"  Routine '{name}' nicht gefunden.")

    else:
        print(f"Unbekannter Unterbefehl: {sub}")
        print("  piclaw routine list | enable <name> | disable <name>")


# ââ Briefing CLI ââââââââââââââââââââââââââââââââââââââââââââââââââ


def cmd_briefing(args: list):
    """piclaw briefing [send] [morning|evening|weekly|status]"""
    import asyncio
    from piclaw.config import load
    from piclaw.briefing import generate_briefing

    sub = args[0] if args else "print"
    kind = args[1] if len(args) > 1 else "status"

    # "piclaw briefing morning" (kein sub-cmd)
    if sub in ("morning", "evening", "weekly", "status"):
        kind = sub
        sub = "print"

    cfg = load()

    async def _run():
        msg = await generate_briefing(kind, cfg, llm=None)

        if sub == "send":
            try:
                from piclaw.messaging import build_hub

                hub = build_hub(cfg)
                await hub.send_all(msg)
                await hub.close()
                print(f"\033[32mâ Briefing gesendet ({kind})\033[0m\n")
            except Exception as e:
                print(f"\033[33mâ  Senden fehlgeschlagen: {e}\033[0m\n")

        print(msg)
        print()

    asyncio.run(_run())


# ââ ClawHub Skill CLI ââââââââââââââââââââââââââââââââââââââââââââââ


def cmd_skill(args: list):
    """piclaw skill <search|install|list|remove> [slug]"""
    import asyncio
    from piclaw.tools.clawhub import (
        clawhub_search, clawhub_info, clawhub_install,
        clawhub_list_installed, clawhub_uninstall,
    )

    sub = args[0] if args else "list"
    slug = args[1] if len(args) > 1 else ""

    async def _run():
        if sub in ("search", "s") and slug:
            print(await clawhub_search(slug))
        elif sub in ("info", "i") and slug:
            print(await clawhub_info(slug))
        elif sub in ("install", "add") and slug:
            print(await clawhub_install(slug))
        elif sub in ("list", "ls", "l"):
            print(clawhub_list_installed())
        elif sub in ("remove", "rm", "uninstall") and slug:
            print(await clawhub_uninstall(slug))
        else:
            print("Verwendung:")
            print("  piclaw skill search <name>    Skill suchen")
            print("  piclaw skill info <slug>      Details anzeigen")
            print("  piclaw skill install <slug>   Skill installieren")
            print("  piclaw skill list             Installierte Skills")
            print("  piclaw skill remove <slug>    Skill entfernen")
            print()
            print("Beispiel: piclaw skill install caldav-calendar")
            print("Browse:   https://clawhub.ai")

    asyncio.run(_run())


if __name__ == "__main__":
    main()

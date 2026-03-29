"""
PiClaw OS – Agent Daemon
Entrypoint for the `piclaw-agent` systemd service.
Runs the agentic background loop (scheduler, heartbeat, memory indexing).
The web API (piclaw-api) runs separately via piclaw/api.py.

This daemon handles:
  - Scheduled/recurring tasks from the Scheduler
  - Heartbeat file writes for Watchdog monitoring
  - Periodic memory re-indexing (qmd update)
  - Background crawl job pickup (delegates to piclaw-crawler)
"""

import asyncio
import logging
import signal
import sys

from piclaw.config import load as load_cfg, LOG_DIR
from piclaw.agent import Agent

log = logging.getLogger("piclaw.daemon")


async def _daemon_main():
    cfg = load_cfg()

    # ── Messaging Hub (früh, damit Notify-Callbacks bereit sind) ──
    _hub = None
    try:
        from piclaw.messaging import build_hub

        _hub = build_hub(cfg)
    except Exception as e:
        log.warning("Messaging Hub Fehler: %s", e)

    async def _notify_all(msg: str):
        if _hub:
            try:
                await _hub.send_all(msg)
            except Exception as e:
                log.debug("Notify Fehler: %s", e)

    # ── Home Assistant Connector ───────────────────────────────────
    try:
        from piclaw.tools import homeassistant as ha_mod

        ha_client = await ha_mod.start(notify_callback=_notify_all)
        if ha_client:
            ok, info = await ha_client.ping()
            if ok:
                log.info("Home Assistant verbunden: %s", info)
            else:
                log.warning("Home Assistant nicht erreichbar: %s", info)
        else:
            log.info("Home Assistant nicht konfiguriert – HA-Tools deaktiviert")
    except Exception as e:
        log.warning("HA Connector Fehler: %s", e)

    agent = Agent(cfg)
    agent.start_scheduler()
    # Messaging Hub in Agent einhängen – damit Sub-Agenten (auch per Bash/CLI
    # erstellt) Ergebnisse via Telegram/Discord senden können.
    # Gleiche Late-Binding-Logik wie in api.py.
    agent._telegram_send = lambda text: asyncio.ensure_future(_notify_all(text))
    await agent.boot()

    log.info("piclaw-agent daemon running.")

    stop = asyncio.Event()

    # ── LLM Health Monitor ─────────────────────────────────────────
    try:
        from piclaw.llm.health_monitor import start_monitor
        from piclaw.taskutils import create_background_task
        _monitor = start_monitor(
            registry=agent.llm.registry if hasattr(agent.llm, "registry") else None,
            multirouter=agent.llm,
            notify=_notify_all,
        )
        if _monitor.registry:
            create_background_task(_monitor.start(stop), name="llm-health-monitor")
            log.info("LLM Health Monitor gestartet.")
        else:
            log.info("LLM Health Monitor: kein Registry – übersprungen.")
    except Exception as _e:
        log.warning("LLM Health Monitor konnte nicht starten: %s", _e)

    # IPC: Trigger-Polling starten (run_now via API)
    from piclaw.ipc import poll_triggers
    from piclaw.taskutils import create_background_task
    create_background_task(poll_triggers(agent.sa_runner), name="ipc-poll")

    # ── Proaktiver Agent ───────────────────────────────────────────
    try:
        from piclaw import proactive as proactive_mod

        proactive_runner = await proactive_mod.start(
            cfg=cfg,
            hub=_hub,
            llm=agent.llm,
            agent=agent,
        )
        # Runner der Routinen-Tools bekannt machen
        agent._proactive = proactive_runner
        log.info(
            "Proaktiver Agent gestartet (%d Routinen aktiv)",
            len(proactive_runner.registry.enabled()),
        )
    except Exception as e:
        log.warning("Proaktiver Agent konnte nicht starten: %s", e)

    # ── Thermal Monitor ────────────────────────────────────────────
    try:
        from piclaw.hardware.thermal import run_thermal_monitor

        async def _mem_log(txt: str):
            if hasattr(agent, "_memory") and agent._memory:
                try:
                    await agent._memory.after_turn(None, txt, None)
                except Exception as _e:
                    log.debug("mem_log after_turn: %s", _e)

        fan_enabled = bool(
            getattr(cfg, "hardware", None)
            and getattr(cfg.hardware, "fan_enabled", False)
        )
        create_background_task(
            run_thermal_monitor(
                notify_fn=_notify_all,
                memory_fn=_mem_log,
                fan_enabled=fan_enabled,
                stop_event=stop,
            ),
            name="thermal-monitor",
        )
        log.info("Thermal monitor started.")
    except Exception as e:
        log.warning("Thermal monitor could not start: %s", e)

    def _sig(*_):
        log.info("Shutdown signal received.")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _sig)

    await stop.wait()
    # ── Graceful shutdown ──────────────────────────────────────────
    if hasattr(agent, "sa_runner") and agent.sa_runner:
        n = await agent.sa_runner.stop_all()
        if n:
            log.info("Stopped %s sub-agent(s).", n)
    try:
        from piclaw.tools import homeassistant as ha_mod

        await ha_mod.stop()
    except Exception as _e:
        log.debug("HA stop: %s", _e)
    try:
        from piclaw import proactive as proactive_mod

        await proactive_mod.stop()
    except Exception as _e:
        log.debug("proactive stop: %s", _e)
    log.info("piclaw-agent stopped.")


def run():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(LOG_DIR / "agent.log")),
        ],
    )
    asyncio.run(_daemon_main())


if __name__ == "__main__":
    run()

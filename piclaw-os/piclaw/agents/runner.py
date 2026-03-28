"""
PiClaw OS – Sub-Agent Runner
Executes sub-agents defined in the registry.

Each sub-agent runs its own lightweight agentic loop:
  1. Build a system prompt from its mission + available tools
  2. Call the LLM with its allowed tools
  3. Dispatch tool calls
  4. Repeat until done or max_steps reached
  5. Return result + optionally notify via messaging hub

Schedule types:
  once          – run once immediately, then mark done
  cron:<expr>   – run on cron schedule (requires croniter)
  interval:<s>  – run every N seconds
  continuous    – run in a loop with a short sleep between cycles

Isolation:
  Each sub-agent runs as an asyncio Task (not a separate process).
  It shares the Pi's resources but has its own tool scope.
  For true process isolation, promote to a systemd service via sa_promote().
"""

import asyncio
import logging
import traceback
from datetime import datetime
from typing import Optional
from collections.abc import Callable, Awaitable

from piclaw.agents.sa_registry import SubAgentDef, SubAgentRegistry
from piclaw.llm.base import Message, LLMBackend, ToolCall, ToolDefinition
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.agents.runner")

# Short sleep between continuous agent cycles (seconds)
CONTINUOUS_SLEEP = 10


class SubAgentRunner:
    """
    Manages the lifecycle of all dynamic sub-agents.
    Owned by the main Agent instance.
    """

    def __init__(
        self,
        registry: SubAgentRegistry,
        llm: LLMBackend,
        tool_defs: list[ToolDefinition],
        handlers: dict[str, Callable],
        notify: Callable[[str], Awaitable] | None = None,
        memory_log: Callable[[str], Awaitable] | None = None,
        report_to_main: Callable[[str], Awaitable] | None = None,
    ):
        self.registry = registry
        self.llm = llm
        self.tool_defs = tool_defs
        self.handlers = handlers
        self.notify = notify  # async fn(text) → sends to messaging hub
        self.report_to_main = report_to_main  # async fn(prompt) → Main Agent antwortet
        self.memory_log = memory_log  # async fn(text) → writes to QMD memory
        self._tasks: dict[str, asyncio.Task] = {}  # agent_id → Task
        self._stop_events: dict[str, asyncio.Event] = {}

    # ── Public API ─────────────────────────────────────────────────

    async def stop_all(self) -> int:
        """Stop all running sub-agents. Returns count stopped."""
        running = self.running_agents()
        for aid in running:
            await self.stop_agent(aid)
        # Give tasks a moment to finish cleanly
        if running:
            await asyncio.sleep(0.5)
        return len(running)

    async def start_agent(self, id_or_name: str) -> str:
        """Start a sub-agent by ID or name."""
        agent = self.registry.get(id_or_name)
        if not agent:
            return f"Sub-agent '{id_or_name}' not found."
        if agent.id in self._tasks and not self._tasks[agent.id].done():
            return f"Sub-agent '{agent.name}' is already running."

        stop_event = asyncio.Event()
        self._stop_events[agent.id] = stop_event
        task = asyncio.create_task(
            self._run_loop(agent, stop_event),
            name=f"subagent-{agent.id}-{agent.name}",
        )
        self._tasks[agent.id] = task

        # Cleanup callback for installer locks
        def _cleanup(t):
            self._on_done(agent.id, t)
            if agent.name == "InstallerAgent":
                # Important for tests: import inside the closure to pick up monkeypatched version
                from piclaw.agents.watchdog import INSTALLER_LOCK_FILE

                if INSTALLER_LOCK_FILE.exists():
                    INSTALLER_LOCK_FILE.unlink()
                    log.info("Installer lock file removed.")

        task.add_done_callback(_cleanup)
        log.info("Sub-agent '%s' started (schedule=%s)", agent.name, agent.schedule)
        return f"Sub-agent '{agent.name}' started."

    async def stop_agent(self, id_or_name: str) -> str:
        """Stop a running sub-agent gracefully."""
        agent = self.registry.get(id_or_name)
        if not agent:
            return f"Sub-agent '{id_or_name}' not found."
        ev = self._stop_events.get(agent.id)
        if ev:
            ev.set()
        task = self._tasks.get(agent.id)
        if task and not task.done():
            task.cancel()
            return f"Sub-agent '{agent.name}' stopped."
        return f"Sub-agent '{agent.name}' was not running."

    async def start_all_scheduled(self):
        """Start all enabled sub-agents that have a recurring schedule.
        
        Bereinigt beim Start verwaiste once-Agenten die nie ausgeführt wurden
        (entstehen wenn der Daemon während einer once-Ausführung neugestartet wird).
        """
        # ── Verwaiste once-Agenten bereinigen ──────────────────────
        stale_once = [
            a for a in self.registry.list_all()
            if a.schedule == "once" or a.name.startswith("SearchAssistant")
        ]
        for agent in stale_once:
            # Nur entfernen wenn letzter Status gesetzt (schon gelaufen)
            # ODER wenn kein Status (nie gestartet – verwaist durch Neustart)
            if agent.last_status in (None, "ok", "error", "timeout"):
                self.registry.remove(agent.id)
                log.info(
                    "Startup-Cleanup: verwaister once-Agent '%s' (%s) entfernt",
                    agent.name, agent.last_status
                )

        # ── Wiederkehrende Agenten starten ─────────────────────────
        for agent in self.registry.list_enabled():
            if agent.schedule not in ("once",):
                await self.start_agent(agent.id)

    def running_agents(self) -> list[str]:
        return [aid for aid, task in self._tasks.items() if not task.done()]

    def status_dict(self) -> dict:
        agents = self.registry.list_all()
        result = []
        for a in agents:
            task = self._tasks.get(a.id)
            running = task is not None and not task.done()
            result.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "schedule": a.schedule,
                    "enabled": a.enabled,
                    "running": running,
                    "last_run": a.last_run,
                    "last_status": a.last_status,
                    "trusted": a.trusted,
                    "privileged": a.privileged,
                }
            )
        return {"sub_agents": result}

    # ── Schedule loop ──────────────────────────────────────────────

    async def _run_loop(self, agent: SubAgentDef, stop: asyncio.Event):
        """Main loop for the sub-agent, respecting its schedule."""
        schedule = agent.schedule.strip()

        if schedule == "once":
            await self._execute(agent)

        elif schedule == "continuous":
            while not stop.is_set():
                await self._execute(agent)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=CONTINUOUS_SLEEP)
                except TimeoutError:
                    pass

        elif schedule.startswith("interval:"):
            try:
                interval = int(schedule.split(":")[1])
            except (ValueError, IndexError):
                log.error("Invalid interval schedule: %s", schedule)
                return
            while not stop.is_set():
                await self._execute(agent)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    pass

        elif schedule.startswith("cron:"):
            expr = schedule[5:]
            await self._cron_loop(agent, expr, stop)

        else:
            log.error("Unknown schedule '%s' for agent '%s'", schedule, agent.name)

    async def _cron_loop(self, agent: SubAgentDef, expr: str, stop: asyncio.Event):
        try:
            from croniter import croniter
        except ImportError:
            log.warning("croniter not installed – falling back to once")
            await self._execute(agent)
            return

        cron = croniter(expr, datetime.now())
        while not stop.is_set():
            next_run = cron.get_next(datetime)
            delay = (next_run - datetime.now()).total_seconds()
            if delay > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                    break  # stop event fired
                except TimeoutError:
                    pass
            await self._execute(agent)

    # ── Execution ─────────────────────────────────────────────────

    async def _execute(self, agent: SubAgentDef):
        """Run one cycle of the sub-agent's agentic loop."""
        log.info("Sub-agent '%s' executing…", agent.name)
        self.registry.mark_run(agent.id, "running")
        start = datetime.now()

        try:
            # ── Direct Mode: Tool direkt aufrufen, kein LLM ────────
            if agent.direct_tool:
                result = await asyncio.wait_for(
                    self._direct_tool_call(agent),
                    timeout=agent.timeout,
                )
            else:
                result = await asyncio.wait_for(
                    self._agentic_loop(agent),
                    timeout=agent.timeout,
                )
            status = "ok"
            log.info(
                "Sub-agent '%s' done in %ss",
                agent.name,
                (datetime.now() - start).seconds,
            )
        except TimeoutError:
            result = f"Sub-agent '{agent.name}' timed out after {agent.timeout}s."
            status = "timeout"
            log.warning(result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            result = f"Sub-agent '{agent.name}' error: {e}\n{traceback.format_exc()}"
            status = "error"
            log.error(result)

        self.registry.mark_run(agent.id, status)

        # ── Auto-cleanup einmaliger Agenten ────────────────────────
        # once-Agenten und SearchAssistant werden nach Abschluss automatisch entfernt
        if agent.schedule == "once" or agent.name.startswith("SearchAssistant"):
            self.registry.remove(agent.id)
            log.info("Sub-agent '%s' (once) after run removed from registry", agent.name)

        # ── Write result to memory so mainagent can recall it ──────
        if self.memory_log and result:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            mem_entry = f"[{ts}] Sub-Agent '{agent.name}' ({status}): {result[:800]}"
            create_background_task(self.memory_log(mem_entry))

        # ── Stille Tokens herausfiltern ────────────────────────────
        # Manche Tools signalisieren "kein Output nötig" mit speziellen Tokens.
        # Wichtig: nicht auf "" setzen (das triggert den Fallback-Bericht!)
        # Stattdessen notify=False simulieren via Flag.
        _SILENT_TOKENS = ("__NO_NEW_RESULTS__", "__NO_NEW_DEVICES__", "__SILENT__")
        _intentionally_silent = False
        if result and result.strip() in _SILENT_TOKENS:
            log.debug("Sub-agent '%s': stilles Token (%s) – keine Telegram-Nachricht", agent.name, result.strip())
            _intentionally_silent = True
            result = ""

        # ── Notify via messaging hub ────────────────────────────────
        log.info("Sub-agent '%s': result=%s notify=%s",
                 agent.name, "ok" if result and result.strip() else "empty", agent.notify)
        if _intentionally_silent:
            log.debug("Sub-agent '%s': bewusst still – kein Telegram", agent.name)
        elif not result or not result.strip() or result.strip() == "(no output)":
            # Fallback: Kein Output vom Sub-Agenten → Main Agent fragt nach Status
            log.warning("Sub-agent '%s': leeres/kein Ergebnis", agent.name)
            if agent.notify and self.notify and self.report_to_main:
                # An Main Agent weiterleiten damit dieser eine sinnvolle Antwort formuliert
                fallback_prompt = (
                    f"Der Sub-Agent '{agent.name}' hat soeben seine Aufgabe ausgeführt "
                    f"(schedule: {agent.schedule}). Aufgabe: {agent.description}. "
                    f"Bitte fasse den aktuellen Status kurz zusammen und sende es als Bericht."
                )
                try:
                    summary = await self.report_to_main(fallback_prompt)
                    if summary and summary.strip():
                        header = f"🤖 **{agent.name}** [bericht]\n"
                        await self.notify(header + summary[:1500])
                        log.info("Sub-agent '%s': Fallback-Bericht via Main Agent gesendet", agent.name)
                except Exception as e:
                    log.warning("Sub-agent '%s': Fallback-Bericht Fehler: %s", agent.name, e)
        elif not agent.notify:
            log.debug("Sub-agent '%s': notify=False", agent.name)
        elif not self.notify:
            log.error("Sub-agent '%s': KEIN Notify-Callback! Telegram nicht konfiguriert?", agent.name)
        elif agent.direct_tool and self._is_quiet_network_result(result):
            # Heartbeat-Logik: nur für Direct-Tool-Agenten (z.B. Netzwerk-Monitor).
            # Marktplatz-Agenten sollen kein Netzwerk-Heartbeat senden.
            # Greift sowohl bei __NO_NEW_DEVICES__ als auch wenn der LLM
            # trotzdem Freitext schreibt (z.B. "Alles ruhig, keine neuen Geräte").
            import time as _time
            _HB_KEY = f"_hb_{agent.id}"
            _last_hb = getattr(self, _HB_KEY, 0)
            _now = _time.time()
            _hb_interval = 3600  # 1 Stunde
            if _now - _last_hb >= _hb_interval:
                setattr(self, _HB_KEY, _now)
                header = f"🤖 *{agent.name}* [heartbeat]\n"
                heartbeat_msg = header + "✅ Netzwerk sauber – keine neuen Geräte in der letzten Stunde."
                try:
                    await self.notify(heartbeat_msg)
                    log.info("Sub-agent '%s': Heartbeat gesendet", agent.name)
                except Exception as e:
                    log.warning("Sub-agent '%s': Heartbeat-Fehler: %s", agent.name, e)
            else:
                _remaining = int((_hb_interval - (_now - _last_hb)) / 60)
                log.debug("Sub-agent '%s': alles ruhig, nächster Heartbeat in %dmin", agent.name, _remaining)
        else:
            header = f"🤖 *{agent.name}* [{status}]\n"
            try:
                await self.notify(header + result[:1500])
                log.info("Sub-agent '%s': Telegram-Notify OK (%d Zeichen)", agent.name, len(result))
            except Exception as e:
                log.error("Sub-agent '%s': Notify FEHLER: %s", agent.name, e)

    async def _direct_tool_call(self, agent: SubAgentDef) -> str:
        """
        Führt ein einzelnes Tool direkt aus – ohne LLM.
        Ideal für periodische Checks (Netzwerk-Scan, Temperatur etc.)
        die keine Intelligenz brauchen, nur ein Tool-Ergebnis.
        Spart 3 LLM-Calls pro Run.
        """
        handler = self.handlers.get(agent.direct_tool)
        if not handler:
            return f"[ERROR] Direct tool '{agent.direct_tool}' nicht gefunden."
        try:
            result = handler()
            if asyncio.iscoroutine(result):
                result = await result
            # Leeres Ergebnis = kein neues Gerät → stilles Token
            if not result:
                return "__NO_NEW_DEVICES__"
            return str(result)
        except Exception as e:
            return f"[ERROR] Direct tool '{agent.direct_tool}' Fehler: {e}"

    def _is_quiet_network_result(self, result: str) -> bool:
        """
        Erkennt ob ein Sub-Agenten-Ergebnis "alles ruhig" bedeutet.

        Logik: Standardmäßig ist alles "quiet" – nur wenn der Text
        explizite Gerätedaten enthält (MAC, IP, 🚨 etc.) wird sofort
        gesendet. So wird auch LLM-Freitext wie "Alles normal" korrekt
        gedrosselt, ohne dass wir alle möglichen Formulierungen kennen müssen.
        """
        if not result or not result.strip():
            return False
        r = result.strip()
        # Explizites "alles ok" Signal → immer quiet
        if r == "__NO_NEW_DEVICES__":
            return True
        # Enthält echte Gerätedaten → SOFORT senden (nicht quiet)
        device_indicators = [
            "mac:", "ip: ", "hersteller:", "vendor:", "hostname:",
            "🚨", "neues gerät", "new device", "unbekanntes gerät",
            "new device detected", "🔍 neues",
        ]
        r_lower = r.lower()
        if any(kw in r_lower for kw in device_indicators):
            return False
        # Alles andere (Freitext, "alles ruhig", "normal", etc.) → quiet
        return True

    async def _agentic_loop(self, agent: SubAgentDef) -> str:
        """
        Lightweight agentic loop for a sub-agent.
        Mirrors the main Agent.run() but uses the sub-agent's mission + tool scope.
        """
        # Filter tools to only what this sub-agent is allowed to use
        allowed_tools = self._filter_tools(agent)

        system = (
            f"You are a sub-agent named '{agent.name}' running on a Raspberry Pi 5.\n"
            f"Your mission:\n{agent.mission}\n\n"
            "Execute your mission autonomously using the available tools.\n"
            "Be concise. When done, summarize what you did in 2-3 sentences.\n"
            f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        messages: list[Message] = [
            Message(role="system", content=system),
            Message(role="user", content=f"Execute your mission: {agent.description}"),
        ]

        final_reply = "(no output)"

        for step in range(agent.max_steps):
            # Route to preferred LLM backend if tags given
            if agent.llm_tags:
                # Temporarily inject routing hint into first user message
                messages[-1] = Message(
                    role="user",
                    content=messages[-1].content,
                )

            try:
                response = await self.llm.chat(messages, tools=allowed_tools)
            except Exception as e:
                return f"LLM error in sub-agent: {e}"

            messages.append(Message(role="assistant", content=response.content or ""))

            if not response.tool_calls:
                final_reply = response.content or "(no output)"
                break

            for call in response.tool_calls:
                log.debug("  [%s] tool: %s", agent.name, call.name)
                result = await self._dispatch(call)
                messages.append(
                    Message(
                        role="tool",
                        content=result,
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                )
        else:
            final_reply = "⚠️ Sub-agent reached max steps."

        return final_reply

    def _filter_tools(self, agent: SubAgentDef) -> list[ToolDefinition]:
        """
        Return the tool subset this sub-agent is allowed to use.
        Applies sandbox restrictions (tier-1 always blocked, tier-2 by default).
        """
        from piclaw.agents.sandbox import filter_tools_for_subagent

        return filter_tools_for_subagent(
            all_tool_defs=self.tool_defs,
            agent_allowlist=agent.tools,
            trusted=agent.trusted,
            privileged=agent.privileged,
        )

    async def _dispatch(self, call: ToolCall) -> str:
        handler = self.handlers.get(call.name)
        if not handler:
            return f"[ERROR] Tool not available: {call.name}"
        try:
            result = handler(**call.arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            return f"[TOOL ERROR] {call.name}: {e}"

    # ── Callbacks ─────────────────────────────────────────────────

    def _on_done(self, agent_id: str, task: asyncio.Task):
        agent = self.registry.get(agent_id)
        name = agent.name if agent else agent_id
        if task.cancelled():
            log.info("Sub-agent '%s' was cancelled.", name)
        elif task.exception():
            log.error("Sub-agent '%s' crashed: %s", name, task.exception())
            if agent:
                self.registry.mark_run(agent_id, "error")
        else:
            log.debug("Sub-agent '%s' task completed.", name)

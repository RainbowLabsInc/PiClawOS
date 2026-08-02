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
import contextlib
import logging
import re
import traceback
from datetime import datetime, timedelta
from collections.abc import Callable, Awaitable

from piclaw.agents import sa_history
from piclaw.agents.sa_registry import SubAgentDef, SubAgentRegistry
from piclaw.llm.base import Message, LLMBackend, ToolCall, ToolDefinition
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.agents.runner")


class MaxStepsExceeded(RuntimeError):
    """Raised when an agentic loop reaches agent.max_steps without producing a
    final answer. Treated as an error status by _execute (not 'ok')."""


class LLMCallFailed(RuntimeError):
    """Raised when the LLM call inside the agentic loop fails (auth, rate-limit,
    network, server error). Treated as an error status by _execute (not 'ok')."""


# Short sleep between continuous agent cycles (seconds)
CONTINUOUS_SLEEP = 10

# Untergrenze für interval:-Schedules. Jeder Run triggert memory_log →
# `qmd update` (Node-Prozess, ~1 CPU-Kern); ein Sekunden-Intervall erzeugt
# damit Dauerlast auf dem Pi (SlowAgent-Debug-Leiche lief 6 Tage bei ~2.5 Load).
MIN_INTERVAL_SEC = 60


def _interval_seconds(schedule: str, agent_name: str) -> int | None:
    """Parst 'interval:<sec>' und hebt Werte unter MIN_INTERVAL_SEC an.
    Returns None bei unparsebarem Schedule."""
    try:
        interval = int(schedule.split(":")[1])
    except (ValueError, IndexError):
        log.error("Invalid interval schedule: %s", schedule)
        return None
    if interval < MIN_INTERVAL_SEC:
        log.warning(
            "Sub-agent '%s': interval:%d unter Minimum – auf %ds angehoben (Dauerlast-Schutz)",
            agent_name, interval, MIN_INTERVAL_SEC,
        )
        return MIN_INTERVAL_SEC
    return interval

def _next_run_iso(agent: SubAgentDef) -> str | None:
    """Nächster geplanter Lauf als ISO-String (Anzeige in der Web-UI).

    Best-effort: None bei once/continuous/disabled oder unparsebarem
    Schedule. Bei interval: eine Schätzung ab last_run – die Schedule-Loop
    tickt unabhängig davon.
    """
    if not agent.enabled:
        return None
    schedule = agent.schedule.strip()
    if schedule.startswith("cron:"):
        try:
            from croniter import croniter

            expr = schedule.split(":", 1)[1].strip()
            nxt = croniter(expr, datetime.now()).get_next(datetime)
            return nxt.isoformat(timespec="seconds")
        except Exception:
            return None
    if schedule.startswith("interval:"):
        # Bewusst nicht _interval_seconds(): das würde bei jedem Status-Poll
        # die Clamp-Warnung ins Log wiederholen.
        try:
            interval = max(int(schedule.split(":")[1]), MIN_INTERVAL_SEC)
        except (ValueError, IndexError):
            return None
        base = datetime.now()
        if agent.last_run:
            try:
                base = datetime.fromisoformat(agent.last_run)
            except ValueError:
                pass
        nxt = max(base + timedelta(seconds=interval), datetime.now())
        return nxt.isoformat(timespec="seconds")
    return None


_DEVICE_INDICATORS_RE = re.compile(
    r"(?:new device detected|unbekanntes gerät|hersteller:|neues gerät|"
    r"new device|hostname:|vendor:|🔍 neues|mac:|ip: |🚨)"
)

# Telegram MarkdownV1 Sonderzeichen die in dynamischem Content (Sub-Agent-Namen,
# Tool-Output, Mail-Subjects, Email-Adressen) escapt werden müssen, sonst öffnet
# z.B. ein einzelnes "_" in "Inbox_Scan_Pakete" eine italic-Entity die nie
# geschlossen wird → Telegram 400 "Can't find end of the entity".
_MD_V1_ESCAPE_RE = re.compile(r"([_*\[\]()~`])")


def _escape_md_v1(s: str) -> str:
    """Escape MarkdownV1 Sonderzeichen für Telegram sendMessage."""
    return _MD_V1_ESCAPE_RE.sub(r"\\\1", s)


def _display_name(name: str) -> str:
    """Subagent-Namen für Anzeige aufhübschen: Unterstriche → Leerzeichen.
    Der Name in subagents.json bleibt unverändert."""
    return name.replace("_", " ")


# Direct-Tools, deren Output bereits Markdown-formatiert ist und NICHT
# erneut durch _escape_md_v1 gejagt werden darf (sonst werden Bold/Italic/Links
# als Klartext mit sichtbaren Sonderzeichen gerendert).
_PREFORMATTED_DIRECT_TOOLS: frozenset[str] = frozenset({
    "marketplace_monitor",
    "parcel_monitor",
    "shopping_digest",
})


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
        notify_user: Callable[[str, str], Awaitable] | None = None,
    ):
        self.registry = registry
        self.llm = llm
        self.tool_defs = tool_defs
        self.handlers = handlers
        self.notify = notify  # async fn(text) → sends to messaging hub (broadcast)
        # Multi-User: optional async fn(text, user_id) → routet zur chat_id des
        # Owners. Wenn None oder agent.owner_id is None → Fallback auf notify
        # (System-Sub-Agents wie temp_check senden weiter an die Default-chat_id).
        self.notify_user = notify_user
        self.report_to_main = report_to_main  # async fn(prompt) → Main Agent antwortet
        self.memory_log = memory_log  # async fn(text) → writes to QMD memory
        self._tasks: dict[str, asyncio.Task] = {}  # agent_id → Task
        self._stop_events: dict[str, asyncio.Event] = {}
        # Tasks the hard-cap watchdog abandoned because they refused to honour
        # cancellation (typically blocked on asyncio.to_thread / scrapling).
        # Keyed by agent_id; the previous abandoned task is overwritten when a
        # new one is leaked, so its done-callback is the last chance to log
        # when (if ever) the runaway work actually finishes. See _execute().
        self._abandoned: dict[str, asyncio.Task] = {}

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
            return f"Sub-Agent '{id_or_name}' nicht gefunden."
        if agent.id in self._tasks and not self._tasks[agent.id].done():
            return f"Sub-Agent '{agent.name}' läuft bereits."

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
        return f"Sub-Agent '{agent.name}' gestartet."

    async def stop_agent(self, id_or_name: str) -> str:
        """Stop a running sub-agent gracefully."""
        agent = self.registry.get(id_or_name)
        if not agent:
            return f"Sub-Agent '{id_or_name}' nicht gefunden."
        ev = self._stop_events.get(agent.id)
        if ev:
            ev.set()
        task = self._tasks.get(agent.id)
        if task and not task.done():
            task.cancel()
            return f"Sub-Agent '{agent.name}' gestoppt."
        return f"Sub-Agent '{agent.name}' lief nicht."

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
        # Stagger: zwischen jedem Start kurz yielden damit bereits gestartete Tasks
        # ihren ersten await-Punkt erreichen, bevor der nächste erstellt wird.
        # Das verteilt Boot-HTTP-Requests statt alle 5 Agents gleichzeitig loszuschicken.
        scheduled = [
            a for a in self.registry.list_enabled()
            if a.schedule not in ("once",)
        ]
        for idx, agent in enumerate(scheduled):
            await self.start_agent(agent.id)
            if idx < len(scheduled) - 1:
                await asyncio.sleep(3)  # 3 s Abstand zwischen Task-Starts

    def running_agents(self) -> list[str]:
        return [aid for aid, task in self._tasks.items() if not task.done()]

    def status_dict(self) -> dict:
        agents = self.registry.list_all()

        # Owner-Namen für die Web-UI auflösen. Lazy import: piclaw.users
        # wird sonst im Daemon-Prozess nicht gebraucht.
        def _owner_name(uid: str | None) -> str | None:
            if not uid:
                return None
            try:
                from piclaw import users as users_mod

                u = users_mod.find_by_id(uid)
                return u.name if u else None
            except Exception:
                return None

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
                    "direct_tool": a.direct_tool,
                    "mission": a.mission,
                    "owner_id": a.owner_id,
                    "owner_name": _owner_name(a.owner_id),
                    "next_run": _next_run_iso(a),
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
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=CONTINUOUS_SLEEP)

        elif schedule.startswith("interval:"):
            interval = _interval_seconds(schedule, agent.name)
            if interval is None:
                return
            while not stop.is_set():
                await self._execute(agent)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=interval)

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
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                    break  # stop event fired
            await self._execute(agent)

    # ── Execution ─────────────────────────────────────────────────

    # Grace window we give a hard-timed-out task to honour `task.cancel()`
    # before we give up and abandon it to the background. Plenty for a
    # cooperative coroutine to unwind its `async with`/`finally` blocks,
    # short enough that a frozen scrapling/Playwright thread can't keep
    # the daemon loop blocked.
    _HARD_TIMEOUT_GRACE_S = 2.0

    async def _run_with_hard_timeout(
        self,
        coro: Awaitable,
        *,
        timeout: int,
        agent: SubAgentDef,
    ):
        """Run ``coro`` with a hard wall-clock cap of ``timeout`` seconds.

        Why not ``asyncio.wait_for``? In Python 3.11+, ``wait_for`` cancels
        the inner task and then **awaits its completion** before raising
        ``TimeoutError``. If the inner task is suspended on an
        ``asyncio.to_thread(...)`` call (scrapling / Playwright / any
        sync I/O), the underlying OS thread cannot be cancelled and
        ``wait_for`` blocks indefinitely – the failure mode that let
        ``Monitor_TW_PLZ21224_250km`` run for 38 536 s while holding the
        LLM lock.

        ``asyncio.wait`` does not have this behaviour: it returns the
        moment the timeout fires, even if pending tasks refuse to
        cancel. We best-effort cancel, give the task a short grace
        window to unwind cleanly, and abandon it if it still hasn't
        finished.
        """
        task = asyncio.create_task(
            coro, name=f"subagent-run-{agent.id}-{agent.name}"
        )
        done, _pending = await asyncio.wait({task}, timeout=timeout)
        if task in done:
            return task.result()

        # Hard cap exceeded – stop pretending we can run it to completion.
        task.cancel()
        # Brief grace period for cooperative cancellation (closes aiohttp
        # sessions, releases locks, etc.). Survives the second timeout
        # because asyncio.wait, not wait_for.
        done, _pending = await asyncio.wait(
            {task}, timeout=self._HARD_TIMEOUT_GRACE_S
        )
        if task in done:
            # It honoured the cancel within grace – consume the
            # CancelledError so it isn't reported as an unhandled
            # exception, then raise TimeoutError below.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                task.result()
        else:
            self._abandon_runaway_task(task, agent, timeout)

        raise TimeoutError(
            f"Sub-agent '{agent.name}' hard-capped after {timeout}s"
        )

    def _abandon_runaway_task(
        self, task: asyncio.Task, agent: SubAgentDef, timeout: int
    ) -> None:
        """Track a task that ignored our cancel so it can't accumulate
        silently. Replaces any previously abandoned task for the same
        agent; the prior task's done-callback is still wired up – we
        just stop holding a reference to it here."""
        log.error(
            "Sub-agent '%s' ignored cancel after %ss hard timeout "
            "(likely blocked on asyncio.to_thread / sync I/O). "
            "Abandoning task to the background; daemon loop continues.",
            agent.name, timeout,
        )
        prev = self._abandoned.get(agent.id)
        if prev is not None and not prev.done():
            log.warning(
                "Sub-agent '%s': previous abandoned task still alive – "
                "indicates a persistent block (e.g. captive portal, "
                "wedged Playwright). Consider disabling this agent.",
                agent.name,
            )
        self._abandoned[agent.id] = task

        def _on_runaway_done(t: asyncio.Task) -> None:
            if self._abandoned.get(agent.id) is t:
                self._abandoned.pop(agent.id, None)
            if t.cancelled():
                log.info(
                    "Sub-agent '%s': abandoned task finally cancelled.",
                    agent.name,
                )
            elif t.exception() is not None:
                log.warning(
                    "Sub-agent '%s': abandoned task ended with %r.",
                    agent.name, t.exception(),
                )
            else:
                log.info(
                    "Sub-agent '%s': abandoned task eventually completed.",
                    agent.name,
                )

        task.add_done_callback(_on_runaway_done)

    async def _execute(self, agent: SubAgentDef):
        """Run one cycle of the sub-agent's agentic loop."""
        log.info("Sub-agent '%s' executing…", agent.name)
        self.registry.mark_run(agent.id, "running")
        start = datetime.now()

        try:
            # ── Direct Mode: Tool direkt aufrufen, kein LLM ────────
            if agent.direct_tool:
                inner = self._direct_tool_call(agent)
            else:
                inner = self._agentic_loop(agent)
            result = await self._run_with_hard_timeout(
                inner, timeout=agent.timeout, agent=agent
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
        except MaxStepsExceeded as e:
            result = str(e)
            status = "error"
        except LLMCallFailed as e:
            result = str(e)
            status = "error"
            log.error("Sub-agent '%s' LLM error: %s", agent.name, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            result = f"Sub-agent '{agent.name}' error: {e}\n{traceback.format_exc()}"
            status = "error"
            log.error(result)

        self.registry.mark_run(agent.id, status)
        sa_history.record_run(
            agent.id,
            agent.name,
            status,
            (datetime.now() - start).total_seconds(),
            result,
            agent.owner_id,
        )

        # ── Auto-cleanup einmaliger Agenten ────────────────────────
        # once-Agenten und SearchAssistant werden nach Abschluss automatisch entfernt
        if agent.schedule == "once" or agent.name.startswith("SearchAssistant"):
            self.registry.remove(agent.id)
            log.info("Sub-agent '%s' (once) after run removed from registry", agent.name)

        # ── Write result to memory so mainagent can recall it ──────
        # ── Stille Tokens ──────────────────────────────────────────
        # Tools signalisieren "kein neues Ergebnis" mit diesen Tokens.
        _SILENT_TOKENS = ("__NO_NEW_RESULTS__", "__NO_NEW_DEVICES__", "__SILENT__")
        _intentionally_silent = bool(result and result.strip() in _SILENT_TOKENS)
        if _intentionally_silent:
            log.debug("Sub-agent '%s': stilles Token – kein Output", agent.name)

        # ── Write result to memory so mainagent can recall it ──────
        # Silent Tokens NICHT ins Memory – sie erzeugen stundenweisen Rausch
        if self.memory_log and result and not _intentionally_silent:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            mem_entry = f"[{ts}] Sub-Agent '{agent.name}' ({status}): {result[:800]}"

            async def _memory_log_with_timeout(entry: str, agent_name: str) -> None:
                """Wrap memory_log in a timeout so a hung QMD write cannot
                block this sub-agent's next iteration. 5s is generous for a
                local SQLite + embedding update; anything beyond suggests
                QMD itself is stuck and the entry would be stale anyway.
                """
                try:
                    await asyncio.wait_for(self.memory_log(entry), timeout=5.0)
                except TimeoutError:
                    log.warning(
                        "memory_log timeout for sub-agent '%s' (entry dropped)",
                        agent_name,
                    )
                except Exception as e:
                    log.warning("memory_log failed for '%s': %s", agent_name, e)

            create_background_task(
                _memory_log_with_timeout(mem_entry, agent.name),
                name=f"memory-log-{agent.id}",
            )

        # ── Notify via messaging hub ────────────────────────────────
        _has_output = bool(
            result and result.strip()
            and not _intentionally_silent
            and result.strip() != "(no output)"
        )
        log.info("Sub-agent '%s': result=%s notify=%s",
                 agent.name, "ok" if _has_output else "empty", agent.notify)

        # ── Multi-User-Notify-Helper ────────────────────────────────
        # Wenn dem Sub-Agent ein owner_id zugeordnet ist UND ein notify_user-
        # Callback gewired ist → schicke an die chat_id des Owners. Sonst
        # Fallback auf den klassischen Broadcast-Pfad (notify). Letzteres
        # gilt für System-Sub-Agents (owner_id=None) wie temp_check und
        # bei Migrationen, in denen notify_user noch nicht gewired ist.
        async def _send_notify(text: str) -> None:
            owner = getattr(agent, "owner_id", None)
            if owner and self.notify_user is not None:
                try:
                    await self.notify_user(text, owner)
                    return
                except Exception as e:
                    log.warning(
                        "Sub-agent '%s': notify_user fehlgeschlagen (owner=%s, %s) "
                        "– Fallback auf broadcast.",
                        agent.name, owner, e,
                    )
            if self.notify is not None:
                await self.notify(text)

        # ── Heartbeat-Helper (Netzwerk-Monitor, max 1x / 2h) ───────
        async def _maybe_send_heartbeat() -> None:
            """Sendet gedrosselten Heartbeat für den Netzwerk-Monitor."""
            if not (agent.direct_tool == "check_new_devices" and agent.notify and self.notify):
                return
            import time as _time
            _hb_interval = 7200  # 2h — bewusst seltener als stündlich gegen Notify-Spam
            _hb_key = f"_hb_{agent.id}"
            _last_hb = getattr(self, _hb_key, 0.0)
            _now = _time.time()
            if _now - _last_hb < _hb_interval:
                log.debug("Sub-agent '%s': alles ruhig, nächster Heartbeat in %dmin",
                          agent.name, int((_hb_interval - (_now - _last_hb)) / 60))
                return
            setattr(self, _hb_key, _now)
            hb_msg = (f"🤖 *{_escape_md_v1(_display_name(agent.name))}* [heartbeat]\n"
                      "✅ Netzwerk sauber – keine neuen Geräte in den letzten 2 Stunden.")
            try:
                await _send_notify(hb_msg)
                log.info("Sub-agent '%s': Heartbeat gesendet", agent.name)
            except Exception as e:
                log.warning("Sub-agent '%s': Heartbeat-Fehler: %s", agent.name, e)

        if _intentionally_silent:
            # Still beenden. Ausnahme: Netzwerk-Monitor-Heartbeat.
            await _maybe_send_heartbeat()

        elif not _has_output:
            # Echter leerer Output → Fallback via Main Agent
            log.warning("Sub-agent '%s': kein Ergebnis – Fallback wird ausgelöst", agent.name)
            if agent.notify and self.notify and self.report_to_main:
                fallback_prompt = (
                    f"Der Sub-Agent '{agent.name}' hat soeben seine Aufgabe ausgeführt "
                    f"(schedule: {agent.schedule}, Beschreibung: {agent.description}). "
                    "Fasse den aktuellen Systemstatus kurz auf Deutsch zusammen."
                )
                try:
                    summary = await self.report_to_main(fallback_prompt)
                    if summary and summary.strip():
                        await _send_notify(
                            f"🤖 *{_escape_md_v1(_display_name(agent.name))}* [status]\n"
                            + _escape_md_v1(summary[:1500])
                        )
                        log.info("Sub-agent '%s': Fallback-Status via Main Agent gesendet", agent.name)
                except Exception as e:
                    log.warning("Sub-agent '%s': Fallback Fehler: %s", agent.name, e)

        elif not agent.notify:
            log.debug("Sub-agent '%s': notify=False", agent.name)

        elif not self.notify:
            log.error("Sub-agent '%s': KEIN Notify-Callback! Telegram nicht konfiguriert?", agent.name)

        elif agent.direct_tool == "check_new_devices" and self._is_quiet_network_result(result):
            # Netzwerk-Monitor: nicht-leeres aber ruhiges Ergebnis → Heartbeat
            await _maybe_send_heartbeat()

        else:
            try:
                safe_name = _escape_md_v1(_display_name(agent.name))
                if agent.direct_tool in _PREFORMATTED_DIRECT_TOOLS:
                    # Output ist bereits sauberer Markdown (Bold, Italic, Links) –
                    # nicht nochmal escapen, sonst werden die Sonderzeichen als
                    # Klartext gerendert.
                    body = result[:1500]
                else:
                    body = _escape_md_v1(result[:1500])
                await _send_notify(f"🤖 *{safe_name}* [{status}]\n" + body)
                log.info(
                    "Sub-agent '%s': Telegram-Notify OK (%d Zeichen, owner=%s)",
                    agent.name, len(result), getattr(agent, "owner_id", None) or "broadcast",
                )
            except Exception as e:
                log.error("Sub-agent '%s': Notify FEHLER: %s", agent.name, e)

    async def _direct_tool_call(self, agent: SubAgentDef) -> str:
        """
        Führt ein einzelnes Tool direkt aus – ohne LLM.
        Ideal für periodische Checks (Netzwerk-Scan, Temperatur etc.)
        die keine Intelligenz brauchen, nur ein Tool-Ergebnis.
        Spart 3 LLM-Calls pro Run.
        """
        # ── Marktplatz-Monitor: Parameter aus mission-JSON lesen ────
        # Kein Closure, kein externer Handler nötig – Params in subagents.json.
        # Neustart-sicher: alles steht dauerhaft in der Registry.
        if agent.direct_tool == "marketplace_monitor":
            return await self._run_marketplace_monitor(agent)

        if agent.direct_tool == "parcel_monitor":
            return await self._run_parcel_monitor(agent)

        handler = self.handlers.get(agent.direct_tool)
        if not handler:
            return f"[ERROR] Direct tool '{agent.direct_tool}' nicht gefunden."
        try:
            # Nutzerkontext aus dem Sub-Agenten setzen, damit nutzerbezogene
            # Tools nur die Daten ihres Owners sehen. Ohne das läuft jedes
            # direct_tool im System-Scope und sieht ALLES – bei einem
            # Digest je Nutzer bekäme jeder die Liste des anderen.
            # owner_id=None bleibt System-Scope (bisheriges Verhalten).
            from piclaw.agent_context import user_scope

            with user_scope(getattr(agent, "owner_id", None)):
                result = handler()
                if asyncio.iscoroutine(result):
                    result = await result
            # Leeres Ergebnis = kein neues Gerät → stilles Token
            if not result:
                return "__NO_NEW_DEVICES__"
            return str(result)
        except Exception as e:
            return f"[ERROR] Direct tool '{agent.direct_tool}' Fehler: {e}"

    async def _run_marketplace_monitor(self, agent: SubAgentDef) -> str:
        """
        Marktplatz-Monitor: liest Parameter direkt aus agent.mission (JSON).
        Neustart-sicher – keine Closures, keine externe Datei nötig.

        mission-Format (JSON):
          {"query": "Gartentisch", "platforms": ["kleinanzeigen"],
           "location": "21224", "radius_km": 20, "max_price": null,
           "max_results": 10}
        """
        import json as _json
        try:
            params = _json.loads(agent.mission)
        except Exception:
            return "[ERROR] marketplace_monitor: mission kein gueltiges JSON"

        # Direkt marketplace_search importieren und awaiten
        try:
            from piclaw.tools.marketplace import marketplace_search as _mp_fn
            result = await _mp_fn(
                query=params.get("query", ""),
                platforms=params.get("platforms", ["kleinanzeigen"]),
                location=params.get("location"),
                radius_km=params.get("radius_km"),
                max_price=params.get("max_price"),
                max_results=params.get("max_results", 10),
                country=params.get("country", "de"),
                notify_all=False,
            )
        except Exception as e:
            return f"[ERROR] marketplace_monitor Fehler: {e}"

        log.debug("_run_marketplace_monitor '%s': marketplace_search done, new=%d",
                  agent.name, len(result.get("new", [])))
        if not result.get("new"):
            return "__NO_NEW_RESULTS__"

        from piclaw.tools.marketplace import format_results_telegram
        return format_results_telegram(result)

    async def _run_parcel_monitor(self, agent: SubAgentDef) -> str:
        """
        Paket-Monitor: Prüft alle aktiven Pakete auf Statusänderungen.
        Kein mission-JSON nötig – liest direkt aus parcels.json.
        Inbox-Scan ist NICHT mehr Teil davon (siehe parcel_inbox_import).
        """
        try:
            from piclaw.tools.parcel_tracking import parcel_monitor_check
            return await parcel_monitor_check()
        except Exception as e:
            log.exception("Sub-agent 'Monitor_Pakete': Fehler %s", e)
            return f"[ERROR] parcel_monitor Fehler: {e}"

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
        if _DEVICE_INDICATORS_RE.search(r.lower()):
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
            f"Du bist Sub-Agent '{agent.name}' auf einem Raspberry Pi 5.\n"
            f"Deine Aufgabe:\n{agent.mission}\n\n"
            "Führe deine Aufgabe eigenständig mit den verfügbaren Tools aus.\n"
            "Antworte immer auf Deutsch. Fasse das Ergebnis am Ende in 2-3 Sätzen zusammen.\n"
            f"Aktuelle Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        messages: list[Message] = [
            Message(role="system", content=system),
            Message(role="user", content=f"Führe deine Aufgabe aus: {agent.description}"),
        ]

        final_reply = "(no output)"
        tool_sequence: list[str] = []

        for step in range(agent.max_steps):
            try:
                response = await self.llm.chat(messages, tools=allowed_tools)
            except Exception as e:
                raise LLMCallFailed(
                    f"LLM error in sub-agent '{agent.name}' step {step}: {e}"
                ) from e

            messages.append(Message(role="assistant", content=response.content or ""))

            if not response.tool_calls:
                final_reply = response.content or "(no output)"
                break

            for call in response.tool_calls:
                log.debug("  [%s] tool: %s", agent.name, call.name)
                tool_sequence.append(call.name)
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
            log.warning(
                "Sub-Agent '%s' hat max_steps=%d erreicht. Tool-Sequenz (%d Calls): %s",
                agent.name, agent.max_steps, len(tool_sequence), tool_sequence,
            )
            raise MaxStepsExceeded(
                f"⚠️ Sub-Agent '{agent.name}' hat maximale Schritte "
                f"({agent.max_steps}) erreicht."
            )

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
            return f"[FEHLER] Tool nicht verfügbar: {call.name}"
        try:
            result = handler(**call.arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            return f"[TOOL ERROR] {call.name}: {e}"

    # ── Callbacks ─────────────────────────────────────────────────

    # Restart policy for protected agents: capped exponential backoff with a
    # sliding 1-hour window. Values picked to recover fast from transient
    # faults (flapping nmap, LLM 503) while preventing a crash loop from
    # burning CPU on a Pi. Fields live on the runner instance (in-memory only
    # – a daemon restart resets them, which is the desired behaviour).
    _PROTECTED_RESTART_MAX_ATTEMPTS = 5
    _PROTECTED_RESTART_WINDOW_S = 3600
    _PROTECTED_RESTART_BASE_DELAY_S = 2
    _PROTECTED_RESTART_MAX_DELAY_S = 60

    def _on_done(self, agent_id: str, task: asyncio.Task):
        self._tasks.pop(agent_id, None)   # Aufräumen damit done Tasks kein Speicherleck erzeugen
        agent = self.registry.get(agent_id)
        name = agent.name if agent else agent_id
        if task.cancelled():
            log.info("Sub-agent '%s' was cancelled.", name)
            return
        if task.exception():
            exc = task.exception()
            log.error("Sub-agent '%s' crashed: %s", name, exc, exc_info=exc)
            if agent:
                self.registry.mark_run(agent_id, "error")
        else:
            log.debug("Sub-agent '%s' task completed.", name)

        # ── Auto-restart for protected agents ──────────────────────
        # Without this, Monitor_Netzwerk silently disappears on any unhandled
        # exception in _run_loop (e.g. croniter parse, event-loop teardown)
        # and the "3-layer protection" advertised in docs/subagents.md only
        # kicks in on the next full daemon boot. This closes that gap.
        if not agent or not agent.enabled:
            return
        from piclaw.agents.sa_tools import _PROTECTED_AGENTS
        if agent.name not in _PROTECTED_AGENTS:
            return

        self._schedule_protected_restart(agent)

    def _schedule_protected_restart(self, agent: "SubAgentDef") -> None:
        """Re-arm a protected agent after an unexpected task exit.

        Uses a sliding 1h window to cap restart attempts. Anything beyond the
        cap is left for the next daemon boot – indicates a systemic issue that
        a tight retry loop can't fix.
        """
        import time as _time

        win_key = f"_restart_win_{agent.id}"
        cnt_key = f"_restart_cnt_{agent.id}"
        now = _time.time()

        # Reset window if it has expired
        if now - getattr(self, win_key, 0.0) > self._PROTECTED_RESTART_WINDOW_S:
            setattr(self, win_key, now)
            setattr(self, cnt_key, 0)

        attempt = getattr(self, cnt_key, 0) + 1
        setattr(self, cnt_key, attempt)

        if attempt > self._PROTECTED_RESTART_MAX_ATTEMPTS:
            log.error(
                "Protected agent '%s' crashed %d times in %ds – giving up until "
                "next daemon boot. Check logs for root cause.",
                agent.name, attempt, self._PROTECTED_RESTART_WINDOW_S,
            )
            return

        delay = min(
            self._PROTECTED_RESTART_MAX_DELAY_S,
            self._PROTECTED_RESTART_BASE_DELAY_S * (2 ** (attempt - 1)),
        )
        log.warning(
            "Protected agent '%s' ended unexpectedly (attempt %d/%d) – "
            "restarting in %ds.",
            agent.name, attempt, self._PROTECTED_RESTART_MAX_ATTEMPTS, delay,
        )

        async def _delayed_restart(agent_id: str, d: int) -> None:
            try:
                await asyncio.sleep(d)
                await self.start_agent(agent_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # pragma: no cover - belt & suspenders
                log.error("Auto-restart of '%s' failed: %s", agent_id, e, exc_info=e)

        create_background_task(
            _delayed_restart(agent.id, delay),
            name=f"protected-restart-{agent.id}",
        )

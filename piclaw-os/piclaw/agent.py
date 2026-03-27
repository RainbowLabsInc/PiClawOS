"""
PiClaw OS – Core Agent
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Callable

from piclaw.config import PiClawConfig, CRASH_DIR
from piclaw.llm import create_backend, Message, ToolDefinition, ToolCall
from piclaw.taskutils import create_background_task

from piclaw.tools import shell as shell_mod
from piclaw.tools import network as network_mod
from piclaw.tools import gpio as gpio_mod
from piclaw.tools import services as services_mod
from piclaw.tools import updater as updater_mod
from piclaw.tools.scheduler import Scheduler

from piclaw.memory import QMDBackend, MemoryMiddleware
from piclaw.memory.tools import TOOL_DEFS as MEMORY_TOOL_DEFS
from piclaw.memory.tools import build_handlers as build_memory_handlers
from piclaw.agents import heartbeat_loop
from piclaw.agents.orchestration import TOOL_DEFS as AGENT_TOOL_DEFS
from piclaw.agents.orchestration import build_handlers as build_agent_handlers
from piclaw.agents.sa_registry import (
    SubAgentRegistry,
    SubAgentDef,
    INSTALLER_MISSION_TEMPLATE,
)
from piclaw.agents.runner import SubAgentRunner
from piclaw.agents.sa_tools import TOOL_DEFS as SA_TOOL_DEFS
from piclaw.agents.sa_tools import build_handlers as build_sa_handlers
from piclaw.llm.mgmt_tools import TOOL_DEFS as LLM_MGMT_TOOL_DEFS
from piclaw.llm.mgmt_tools import build_handlers as build_llm_mgmt_handlers
from piclaw.hardware import TOOL_DEFS as HW_TOOL_DEFS, HANDLERS as HW_HANDLERS
from piclaw import soul as soul_mod
from piclaw.tools import homeassistant as ha_mod

log = logging.getLogger("piclaw.agent")


@dataclass
class AgentTask:
    """Represents a request to the agent, managed in a queue."""

    user_input: str
    history: list[Message] | None = None
    on_token: Callable | None = None
    future: asyncio.Future = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )


# Base capabilities block (appended after the soul)
BASE_CAPABILITIES = """\
## Fähigkeiten

- Shell-Befehle ausführen (mit Sicherheits-Allowlist)
- WLAN und Netzwerkverbindungen verwalten
- GPIO-Pins lesen und steuern (Sensoren, LEDs, Relais)
- systemd-Services starten, stoppen, überwachen
- Wiederkehrende Hintergrundaufgaben planen
- System-Updates durchführen
- Webseiten abrufen und HTTP-Anfragen stellen
- Persistentes Memory durchsuchen und beschreiben
- Sub-Agenten erstellen, starten und überwachen
- LLM-Backends verwalten und konfigurieren

## Tool-Anweisungen (KRITISCH WICHTIG)

Du hast fertig implementierte Tools die du SOFORT aufrufen MUSST:
- marketplace_search: Durchsucht Kleinanzeigen.de, eBay.de, Web nach Inseraten.
- network_scan, port_scan, check_new_devices: Netzwerk-Analyse.
- shell_exec: Shell-Befehle ausfuehren.
- http_get: Webseiten abrufen.
- memory_search, memory_write: Erinnerungen verwalten.

REGELN - IMMER BEFOLGEN:
1. NIEMALS erklaeren was du tun wuerdest - sofort das passende Tool aufrufen.
2. NIEMALS sagen "ich habe keinen Zugriff auf X" - alle Tools sind installiert und bereit.
3. Bei jeder Marktplatz-Anfrage: marketplace_search SOFORT aufrufen.
4. FALSCH: "Ich empfehle dir auf kleinanzeigen.de zu suchen..."
5. RICHTIG: [ruft marketplace_search auf und zeigt Ergebnisse]

## Memory-Anweisungen

- Vor Antworten zu vergangenen Arbeiten oder Entscheidungen: memory_search nutzen.
- Wenn der Nutzer sagt "merke dir das" oder etwas Wichtiges entschieden wird: memory_write.
- Wichtige Ereignisse mit memory_log protokollieren.
- Memories gelten für lokalen und Cloud-KI-Modus gleichermaßen.

## Kontext

Datum/Zeit: {date}  |  Hostname: {hostname}  |  Agent: {name}
"""


class Agent:
    def __init__(self, cfg: PiClawConfig):
        self.cfg = cfg
        self.llm = create_backend(cfg)
        self.scheduler = Scheduler()
        self.scheduler.set_agent(self)
        self.qmd = QMDBackend()
        self.memory = MemoryMiddleware(self.qmd, self.llm)
        self.sa_registry = SubAgentRegistry()
        self.sa_runner: SubAgentRunner | None = None  # built after notify is set
        self._telegram_send = lambda text: None  # replaced by messaging hub
        self._build_tools()

        # Parallel processing queue (v0.14)
        self._queue: asyncio.Queue[AgentTask] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []

    def _build_tools(self):
        """Assemble all tool definitions and handlers."""
        self._tool_defs: list[ToolDefinition] = []
        self._handlers: dict[str, callable] = {}

        def _reg(defs, handlers):
            self._tool_defs.extend(defs)
            self._handlers.update(handlers)

        _reg(shell_mod.TOOL_DEFS, shell_mod.build_handlers(self.cfg.shell))
        _reg(network_mod.TOOL_DEFS, network_mod.HANDLERS)
        _reg(gpio_mod.TOOL_DEFS, gpio_mod.HANDLERS)
        _reg(services_mod.TOOL_DEFS, services_mod.build_handlers(self.cfg.services))
        _reg(updater_mod.TOOL_DEFS, updater_mod.build_handlers(self.cfg.updater))
        _reg(
            self.scheduler.TOOL_DEFS if hasattr(self.scheduler, "TOOL_DEFS") else [],
            self.scheduler.build_handlers(),
        )
        _reg(MEMORY_TOOL_DEFS, build_memory_handlers(self.qmd))
        _reg(AGENT_TOOL_DEFS, build_agent_handlers(self._telegram_send))
        _reg(LLM_MGMT_TOOL_DEFS, build_llm_mgmt_handlers(self.llm.registry, self.llm))

        # Hardware tools (pi_info, sensors, i2c_scan, thermal_status)
        _reg(HW_TOOL_DEFS, HW_HANDLERS)

        # Network Monitor tools (v0.15)
        from piclaw.tools import network_monitor as net_mon

        _reg(net_mon.TOOL_DEFS, net_mon.build_handlers())

        # Tandem Browser tools (v0.18)
        from piclaw.tools import tandem as tandem_mod

        _reg(tandem_mod.TOOL_DEFS, tandem_mod.build_handlers())

        # HTTP tool
        from piclaw.tools import http as http_mod

        _reg(http_mod.TOOL_DEFS, http_mod.HANDLERS)

        # Installer tools
        from piclaw.tools import installer as installer_mod

        _reg(installer_mod.TOOL_DEFS, installer_mod.build_handlers())

        # Home Assistant tools (nur wenn konfiguriert)
        self._ha_client = ha_mod.get_client()
        if self._ha_client:
            ha_tool_defs = [
                ToolDefinition(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["input_schema"],
                )
                for t in ha_mod.TOOL_DEFS
            ]
            ha_handlers = {
                t["name"]: (
                    lambda n: lambda **kw: ha_mod.handle_tool(n, kw, self._ha_client)
                )(t["name"])
                for t in ha_mod.TOOL_DEFS
            }
            _reg(ha_tool_defs, ha_handlers)
            log.info("Home Assistant tools registered (%d)", len(ha_tool_defs))

        # Routinen-Tools werden lazy registriert (ProactiveRunner startet nach __init__)
        # Siehe: _register_late_tools() wird vor dem ersten run() aufgerufen

        # Soul tools (read/write soul file)
        _reg(*self._build_soul_tools())

        # Marketplace tools (Kleinanzeigen, eBay, Websuche)
        from piclaw.tools.marketplace import marketplace_search, format_results
        from piclaw.llm.base import ToolDefinition as _TD

        _marketplace_tool = _TD(
            name="marketplace_search",
            description=(
                "Sucht auf Marktplätzen (Kleinanzeigen.de, eBay.de, Web) nach Inseraten. "
                "Beispiel: 'Suche nach Raspberry Pi 5 unter 100€ in Hamburg auf Kleinanzeigen'"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchbegriff"},
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Plattformen: kleinanzeigen, ebay, web",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximaler Preis in Euro",
                    },
                    "location": {
                        "type": "string",
                        "description": "Ort oder PLZ (für Kleinanzeigen)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max. Ergebnisse pro Plattform (default: 10)",
                    },
                    "radius_km": {
                        "type": "integer",
                        "description": "Suchradius in km um den angegebenen Ort (z.B. 20, 50, 100)",
                    },
                    "notify_all": {
                        "type": "boolean",
                        "description": "True = alle Funde zeigen, False = nur neue Funde (default: True)",
                    },
                },
                "required": ["query"],
            },
        )

        async def _marketplace_handler(**kw):
            # Query cleaning now happens internally in marketplace_search()
            result = await marketplace_search(
                query=kw.get("query", ""),
                platforms=kw.get("platforms", ["kleinanzeigen"]),
                max_price=kw.get("max_price"),
                location=kw.get("location"),
                radius_km=kw.get("radius_km"),
                max_results=int(kw.get("max_results", 10)),
                notify_all=kw.get("notify_all", True),
            )
            return format_results(result)

        _reg([_marketplace_tool], {"marketplace_search": _marketplace_handler})
        log.info("Marketplace-Tool registriert (Kleinanzeigen, eBay, Web)")

    def _build_soul_tools(self):
        """Inline soul management tools."""
        from piclaw.llm.base import ToolDefinition

        defs = [
            ToolDefinition(
                name="soul_read",
                description="Read the current soul file (personality, mission, guidelines).",
                parameters={"type": "object", "properties": {}},
            ),
            ToolDefinition(
                name="soul_write",
                description="Overwrite the soul file with new content. Use with care – this changes the agent's core personality.",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Full new soul file content (Markdown)",
                        },
                    },
                    "required": ["content"],
                },
            ),
            ToolDefinition(
                name="soul_append",
                description="Append a new section to the soul file without replacing existing content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "description": "New section to append",
                        },
                    },
                    "required": ["section"],
                },
            ),
        ]
        handlers = {
            "soul_read": lambda **_: soul_mod.load(),
            "soul_write": lambda content, **_: soul_mod.save(content),
            "soul_append": lambda section, **_: soul_mod.append(section),
        }
        return defs, handlers

    def _wire_sa_runner(self):
        """Build and wire the SubAgentRunner after notify is available.

        The notify lambda deliberately uses late binding (self._telegram_send)
        so that when api.py replaces _telegram_send after boot, sub-agents
        automatically pick up the real messaging-hub sender.
        """

        async def _notify(text: str):
            # Late-bound: always uses the current value of self._telegram_send,
            # not the no-op placeholder that existed at _wire_sa_runner() time.
            fn = self._telegram_send
            result = fn(text)
            if asyncio.iscoroutine(result):
                await result

        async def _memory_log(entry: str):
            # Write sub-agent output into QMD memory so the mainagent can
            # answer questions like "Was hat TempMonitor gestern gemeldet?"
            handler = self._handlers.get("memory_log")
            if handler:
                result = handler(content=entry)
                if asyncio.iscoroutine(result):
                    await result

        self.sa_runner = SubAgentRunner(
            registry=self.sa_registry,
            llm=self.llm,
            tool_defs=self._tool_defs,
            handlers=self._handlers,
            notify=_notify,
            memory_log=_memory_log,
        )
        # Register sub-agent tools
        sa_defs = SA_TOOL_DEFS
        sa_handlers = build_sa_handlers(self.sa_registry, self.sa_runner)
        self._tool_defs.extend(sa_defs)
        self._handlers.update(sa_handlers)

    # ── Tool dispatch ───────────────────────────────────────────────

    async def _dispatch(self, call: ToolCall) -> str:
        handler = self._handlers.get(call.name)
        if not handler:
            return f"[ERROR] Unknown tool: {call.name}"
        try:
            result = handler(**call.arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            tb = traceback.format_exc()
            self._save_crash(f"tool_{call.name}", tb)
            return f"[TOOL ERROR] {call.name}: {e}"

    # ── Lazy tool registration ────────────────────────────────────────

    def _register_late_tools(self) -> None:
        """Registriert Tools die beim __init__ noch nicht verfügbar waren (ProactiveRunner)."""
        if getattr(self, "_late_tools_registered", False):
            return
        self._late_tools_registered = True
        try:
            from piclaw import proactive as proactive_mod
            from piclaw.routines import TOOL_DEFS as ROUTINE_TOOL_DEFS
            from piclaw.routines import build_handlers as build_routine_handlers

            runner = proactive_mod.get_runner()
            if runner:
                for td in ROUTINE_TOOL_DEFS:
                    self._tool_defs.append(td)
                self._handlers.update(build_routine_handlers(runner.registry, runner))
                log.info("Routine tools lazy-registered (%d)", len(ROUTINE_TOOL_DEFS))
        except Exception as e:
            log.debug("Routine tools late-registration: %s", e)

    # ── Parallel queue workers ──────────────────────────────────────

    async def _worker_loop(self):
        """Processes tasks from the queue sequentially (per worker)."""
        while True:
            task = await self._queue.get()
            try:
                result = await self._run_internal(
                    task.user_input, task.history, task.on_token
                )
                task.future.set_result(result)
            except Exception as e:
                log.error("Worker error: %s", e)
                task.future.set_exception(e)
            finally:
                self._queue.task_done()

    def _start_workers(self, count: int = 2):
        """Starts background worker tasks."""
        if self._workers:
            return
        for i in range(count):
            t = create_background_task(self._worker_loop(), name=f"agent-worker-{i}")
            self._workers.append(t)
        log.info("Started %d agent queue workers.", count)

    # ── Main agentic loop ────────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        history: list[Message] | None = None,
        on_token=None,
    ) -> str:
        """Enqueue a request and wait for the result (Parallel Queue v0.14)."""
        self._register_late_tools()
        self._start_workers()  # Ensure workers are running

        # Detect @installer prefix
        if user_input.strip().startswith("@installer"):
            request = user_input.strip()[10:].strip()
            from piclaw.agents.watchdog import INSTALLER_LOCK_FILE

            INSTALLER_LOCK_FILE.write_text(request, encoding="utf-8")
            return await self._delegate_to_installer(request)

        task = AgentTask(user_input, history, on_token)
        await self._queue.put(task)
        return await task.future

    def _detect_monitor_intent(self, text: str) -> dict | None:
        """Erkennt natürliche Monitoring-Anfragen wie 'Sag mir wenn ein Pi 5 auftaucht'."""
        import re

        t = re.sub(r"\[.*?\]", " ", text).lower()

        monitor_kw = [
            "überwach", "beobacht", "benachrichtig", "informier", "meld",
            "sag mir wenn", "sag bescheid", "schick mir", "check regelmäßig",
            "halte ausschau", "halte die augen offen",
            "alert", "monitor", "watch", "notify", "wenn.*auftaucht",
            "sobald.*verfügbar", "falls.*angebot", "wenn.*inserat",
            "wenn.*neu", "stündlich", "regelmäßig", "automatisch",
        ]
        market_kw = [
            "kleinanzeigen", "ebay", "inserat", "anzeige", "kaufen",
            "marktplatz", "gebraucht", "preis", "euro", "angebot",
        ]

        if not any(k in t for k in monitor_kw):
            return None
        if not any(k in t for k in market_kw):
            return None

        # Intervall aus Text extrahieren (default 1h)
        interval_sec = 3600
        if any(k in t for k in ["30 min", "30min", "halbstündlich"]):
            interval_sec = 1800
        elif any(k in t for k in ["15 min", "15min"]):
            interval_sec = 900
        elif any(k in t for k in ["2 stund", "2h", "alle zwei"]):
            interval_sec = 7200
        elif any(k in t for k in ["täglich", "einmal am tag", "24h"]):
            interval_sec = 86400

        # Plattform
        platforms = []
        if any(k in t for k in ["kleinanzeigen", "kleinanzeigen.de"]):
            platforms.append("kleinanzeigen")
        if "ebay" in t and "kleinanzeigen" not in t:
            platforms.append("ebay")
        if "web" in t or "internet" in t:
            platforms.append("web")
        if not platforms:
            platforms = ["kleinanzeigen", "ebay"]

        # Query: Monitoring-Keywords + Rauschen VOR _detect_marketplace_intent entfernen
        clean_text = text
        for phrase in [
            "beobachte ob es", "beobachte ob", "schau ob es", "schau ob",
            "sag mir wenn", "sag bescheid wenn", "benachrichtige mich",
            "informiere mich", "überwache", "beobachte", "monitor",
            "halte ausschau", "check regelmäßig", "automatisch",
            "stündlich", "regelmäßig", "neue gibt", "neue auftauchen",
            "neue inserate", "neue angebote", "neues gibt", "gibt es neue",
            "gibt es", "ob es", "ob neue", "neue für", "nach neuen",
        ]:
            clean_text = re.sub(r"(?i)\b" + re.escape(phrase) + r"\b", " ", clean_text)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        mp = self._detect_marketplace_intent(clean_text)
        if not mp or not mp.get("query"):
            return None

        return {
            "query": mp["query"],
            "platforms": platforms,
            "location": mp.get("location"),
            "radius_km": mp.get("radius_km"),
            "max_price": mp.get("max_price"),
            "interval_sec": interval_sec,
        }

    async def _create_monitor_agent(self, params: dict) -> str:
        """Erstellt einen Monitoring-Sub-Agenten für stündliche Marktplatz-Suche."""
        import re, json

        query = params["query"]
        platforms = params.get("platforms", ["kleinanzeigen", "ebay"])
        location = params.get("location", "")
        radius_km = params.get("radius_km")
        max_price = params.get("max_price")
        interval_sec = params.get("interval_sec", 3600)

        # Menschenlesbare Beschreibung
        plat_str = " + ".join(p.capitalize() for p in platforms)
        loc_str = f" um {location}" if location else ""
        rad_str = f" ({radius_km}km Umkreis)" if radius_km else ""
        price_str = f", max. {max_price:.0f}€" if max_price else ""
        interval_str = (
            "stündlich" if interval_sec == 3600
            else f"alle {interval_sec // 60} Minuten" if interval_sec < 3600
            else f"alle {interval_sec // 3600} Stunden"
        )

        # Agent-Name: nur erste 2 Wörter der Query (verhindert hässliche Langnamen)
        name_words = query.split()[:2]
        safe_name = re.sub(r"[^a-zA-Z0-9]", "", " ".join(name_words).title().replace(" ", ""))[:20]
        agent_name = f"Monitor_{safe_name}"

        # Prüfen ob schon einer läuft
        existing = self.sa_registry.get(agent_name)
        if existing:
            return (
                f"⚠️ Es läuft bereits ein Monitoring-Agent für '{query}' "
                f"(ID: {existing.id}, schedule: {existing.schedule}).\n"
                f"Zum Ändern: 'Stopp den {agent_name}' oder 'Lösch den {agent_name}'."
            )

        # Mission-Prompt – Agent ruft marketplace_search direkt auf
        tool_call_params = {
            "query": query,
            "platforms": platforms,
            "notify_all": False,  # NUR neue Inserate melden
        }
        if location:
            tool_call_params["location"] = location
        if radius_km:
            tool_call_params["radius_km"] = radius_km
        if max_price:
            tool_call_params["max_price"] = max_price

        mission = (
            f"Du bist ein Marktplatz-Monitor. Suche {interval_str} nach neuen Inseraten.\n\n"
            f"Ruf marketplace_search auf mit diesen Parametern:\n"
            f"{json.dumps(tool_call_params, ensure_ascii=False, indent=2)}\n\n"
            f"WICHTIG: notify_all=False – nur NEUE Inserate melden, keine Wiederholungen.\n"
            f"Falls keine neuen Inserate gefunden wurden, sende KEINE Nachricht.\n"
            f"Falls neue Inserate gefunden wurden, formatiere sie übersichtlich."
        )

        agent_def = SubAgentDef(
            name=agent_name,
            description=f"Monitoring {plat_str}: '{query}'{loc_str}{rad_str}{price_str} – {interval_str}",
            mission=mission,
            tools=["marketplace_search"],
            schedule=f"interval:{interval_sec}",
            notify=True,   # Ergebnis → MessagingHub → Telegram
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent_def)

        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
            return (
                f"✅ Monitoring gestartet!\n"
                f"  🔍 Suche: '{query}' auf {plat_str}{loc_str}{rad_str}{price_str}\n"
                f"  ⏱ Intervall: {interval_str}\n"
                f"  📨 Neue Inserate → Telegram\n"
                f"  🆔 Agent-ID: {agent_id}\n\n"
                f"Ich melde mich sobald etwas Neues auftaucht!"
            )
        return "❌ Sub-agent runner nicht bereit."

    def _detect_marketplace_intent(self, text: str) -> dict | None:
        """Detect marketplace search intent and extract parameters directly."""
        import re

        # Vorab-Bereinigung von Chat-Präfixen wie "[you]"
        text_clean = re.sub(r"\[.*?\]", " ", text)
        t = text_clean.lower()

        search_kw = [
            "suche",
            "finde",
            "such",
            "find",
            "schau",
            "schaue",
            "durchsuche",
            "zeig",
            "liste",
            "search",
            "look for",
            "was kostet",
            "preis für",
            "gibt es",
        ]
        market_kw = [
            "kleinanzeigen",
            "ebay",
            "inserat",
            "anzeige",
            "kaufen",
            "marktplatz",
            "gebraucht",
            "preis",
            "euro",
            "schnäppchen",
            "angebot",
            "nähe",
            "umkreis",
            "plz",
            "ort",
        ]
        if not any(k in t for k in search_kw):
            return None
        if not any(k in t for k in market_kw):
            return None

        # Platform
        platforms = []
        if any(k in t for k in ["kleinanzeigen", "kleinanzeigen.de"]):
            platforms.append("kleinanzeigen")
        if "ebay" in t and "kleinanzeigen" not in t:
            platforms.append("ebay")
        if "web" in t or "internet" in t:
            platforms.append("web")
        if not platforms:
            platforms = ["kleinanzeigen", "ebay"]

        # PLZ (5 Ziffern)
        plz_match = re.search(r"\b(\d{5})\b", text_clean)
        location = plz_match.group(1) if plz_match else None

        # Radius
        radius_match = re.search(r"(\d+)\s*km", t)
        radius_km = int(radius_match.group(1)) if radius_match else None

        # Preis
        price_match = re.search(r"unter\s+(\d+)\s*|max\s+(\d+)\s*|bis\s+(\d+)\s*", t)
        max_price = None
        if price_match:
            max_price = float(next(g for g in price_match.groups() if g))

        # Query bereinigen
        query = text_clean
        # Plattform-Phrasen entfernen
        for phrase in [
            "kleinanzeigen.de",
            "ebay.de",
            "kleinanzeigen",
            "ebay",
            "zeige mir",
            "zeig mir",
            "was kostet",
            "preis für",
            "gibt es",
            "auf",
        ]:
            query = re.sub(r"(?i)\b" + re.escape(phrase) + r"\b", " ", query)
        # PLZ entfernen
        if plz_match:
            query = query.replace(plz_match.group(1), " ")
        # Radius-Angaben entfernen (z.B. "20km", "20 km")
        query = re.sub(r"\d+\s*km", " ", query, flags=re.IGNORECASE)
        # Stoppwörter entfernen
        stopwords = [
            "auf",
            "im",
            "in",
            "um",
            "von",
            "bis",
            "bitte",
            "suche",
            "finde",
            "such",
            "durchsuche",
            "liste",
            "umkreis",
            "radius",
            "einen",
            "eine",
            "ein",
            "mir",
            "dem",
            "der",
            "die",
            "das",
            "rosengarten",
            "hamburg",
            "berlin",
            "münchen",
            "köln",
            "frankfurt",
            "bremen",
            "hannover",
            "düsseldorf",
            "leipzig",
            "schnäppchen",
            "angebot",
            "angebote",
            "nach",
            "einem",
            "einer",
            "nähe",
            "nähe von",
            "in der",
            "nach einem",
        ]
        for w in stopwords:
            query = re.sub(r"(?i)(?<![\w])" + re.escape(w) + r"(?![\w])", " ", query)
        # .de Suffix entfernen
        query = re.sub(r"\.de\b", " ", query, flags=re.IGNORECASE)
        # Mehrfache Leerzeichen
        query = re.sub(r"\s+", " ", query).strip(" ,.-")

        if len(query) < 3:
            return None
        return {
            "query": query,
            "platforms": platforms,
            "location": location,
            "max_price": max_price,
            "radius_km": radius_km,
        }

    async def _delegate_to_installer(self, request: str) -> str:
        """Spawn a privileged InstallerAgent sub-agent."""
        from piclaw.agents.watchdog import INSTALLER_LOCK_FILE

        try:
            INSTALLER_LOCK_FILE.write_text(request, encoding="utf-8")
        except Exception as e:
            log.warning("Could not create installer lock: %s", e)
        agent_def = SubAgentDef(
            name="InstallerAgent",
            description=f"Installation: {request}",
            mission=INSTALLER_MISSION_TEMPLATE,
            tools=["shell", "installer_confirm"],
            schedule="once",
            privileged=True,
            trusted=True,
            notify=True,
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent_def)
        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
            return (
                f"✅ Installer-Subagent wurde gestartet (ID: {agent_id}).\n"
                f"Anfrage: {request}\n"
                "Der Agent wird einen Plan erstellen und dich um Bestätigung bitten."
            )
        return "❌ Sub-agent runner not ready."

    async def _delegate_to_search_assistant(self, request: str) -> str:
        """Spawn a SearchAssistant sub-agent."""
        from piclaw.agents.sa_registry import SEARCH_ASSISTANT_MISSION_TEMPLATE

        agent_def = SubAgentDef(
            name="SearchAssistant",
            description=f"Marketplace Search: {request}",
            mission=SEARCH_ASSISTANT_MISSION_TEMPLATE,
            tools=["marketplace_search"],
            schedule="once",
            notify=True,
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent_def)
        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
            return (
                f"✅ SearchAssistant-Subagent gestartet (ID: {agent_id}).\n"
                f"Anfrage: {request}\n"
                "Er wird nun nach Inseraten suchen und sich bei dir melden."
            )
        return "❌ Sub-agent runner not ready."

    async def _run_internal(
        self,
        user_input: str,
        history: list[Message] | None = None,
        on_token=None,
    ) -> str:
        import socket

        system = soul_mod.build_system_prompt(
            name=self.cfg.agent_name,
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            hostname=socket.gethostname(),
            base_capabilities=BASE_CAPABILITIES,
        )
        messages: list[Message] = [Message(role="system", content=system)]
        if history:
            messages.extend(history[-20:])
        messages.append(Message(role="user", content=user_input))

        # Agent-Status-Shortcut: "zeig Agenten", "welche Jobs laufen" etc.
        _t = user_input.lower()
        _agent_status_kw = [
            "zeig", "liste", "welche", "was", "status", "laufende", "aktive",
            "alle", "show", "list", "running",
        ]
        _agent_noun_kw = [
            "agent", "job", "monitor", "subagent", "sub-agent", "task", "aufgabe",
        ]
        if any(k in _t for k in _agent_status_kw) and any(k in _t for k in _agent_noun_kw):
            handler = self._handlers.get("agent_list")
            if handler:
                log.info("Agent-Status-Shortcut ausgelöst")
                return await handler()

        # Monitoring-Intent: "Überwache X auf eBay", "Sag mir wenn..." → Sub-Agent erstellen
        monitor_kwargs = self._detect_monitor_intent(user_input)
        if monitor_kwargs:
            log.info("Monitor intent detected: %s", monitor_kwargs)
            return await self._create_monitor_agent(monitor_kwargs)

        # Marketplace intent shortcut — call tool directly without relying on LLM tool-calling
        # This bypasses the Kimi K2 tool-calling reliability issue
        # Check history for previous marketplace context (for follow-ups like "erhöhe den Radius")
        _prev_mp_context = None
        if history:
            for m in reversed(history[-6:]):
                if m.role == "user":
                    prev_kw = self._detect_marketplace_intent(m.content)
                    if prev_kw:
                        _prev_mp_context = prev_kw
                        break

        mp_kwargs = self._detect_marketplace_intent(user_input)
        if mp_kwargs:
            log.info("Marketplace intent detected: %s", mp_kwargs)

            # If we have a clear query AND location/radius, execute directly
            if mp_kwargs.get("query") and (
                mp_kwargs.get("location") or mp_kwargs.get("radius_km")
            ):
                log.info("Executing marketplace shortcut for: '%s'", mp_kwargs["query"])
                handler = self._handlers.get("marketplace_search")
                if handler:
                    return await handler(**mp_kwargs, notify_all=True)

            # Otherwise delegate
            return await self._delegate_to_search_assistant(user_input)

        # Follow-up detection: "erhöhe", "vergrößer", "erweitere", "nochmal", "zeig mehr"
        if not mp_kwargs and _prev_mp_context:
            followup_kw = [
                "erhöh",
                "vergrößer",
                "erweiter",
                "nochmal",
                "mehr",
                "radius",
                "breiter",
                "größer",
                "weiter",
                "nochmal",
                "wiederhol",
            ]
            if any(k in user_input.lower() for k in followup_kw):
                mp_kwargs = dict(_prev_mp_context)
                # Update radius if mentioned
                import re

                new_radius = re.search(r"(\d+)\s*km", user_input)
                if new_radius:
                    mp_kwargs["radius_km"] = int(new_radius.group(1))
                # Update max_price if mentioned
                new_price = re.search(
                    r"unter\s+(\d+)\s*€|max\s+(\d+)\s*€|bis\s+(\d+)\s*€",
                    user_input.lower(),
                )
                if new_price:
                    mp_kwargs["max_price"] = float(
                        next(g for g in new_price.groups() if g)
                    )

        if mp_kwargs:
            log.info("Marketplace intent detected: %s", mp_kwargs)
            # Direct delegation to SearchAssistant (it will call the tool)
            # to avoid double-searching and inconsistent query cleaning.
            return await self._delegate_to_search_assistant(user_input)

        # Memory-Recall: kurzer Timeout damit Agent immer antwortet
        try:
            messages = await asyncio.wait_for(self.memory.enrich(messages), timeout=8.0)
        except TimeoutError:
            log.debug("Memory enrich timeout – weiter ohne Memory-Kontext")
        except Exception as _me:
            log.debug("Memory enrich error: %s", _me)

        MAX_STEPS = 15
        final_reply = "(empty response)"

        for step in range(MAX_STEPS):
            try:
                if on_token and step == 0:
                    collected = ""
                    async for token in self.llm.stream_chat(
                        messages, tools=self._tool_defs
                    ):
                        collected += token
                        await on_token(token)
                    # Only do a second chat() call if the streamed response
                    # looks like it might contain tool calls (starts with {, [, or <)
                    # Otherwise use the streamed content directly to avoid a
                    # redundant API call that triggers fallback warnings.
                    _might_have_tools = collected.strip().startswith(("{", "[", "<"))
                    if _might_have_tools:
                        response = await self.llm.chat(messages, tools=self._tool_defs)
                    else:
                        from piclaw.llm.base import LLMResponse

                        response = LLMResponse(
                            content=collected, tool_calls=[], finish_reason="stop"
                        )
                    if not response.tool_calls:
                        final_reply = response.content or collected
                        break
                else:
                    response = await self.llm.chat(messages, tools=self._tool_defs)
            except Exception as e:
                self._save_crash("llm_chat", traceback.format_exc())
                return f"❌ LLM error: {e}"

            messages.append(Message(role="assistant", content=response.content or ""))

            if not response.tool_calls:
                final_reply = response.content or "(empty response)"
                break

            for call in response.tool_calls:
                log.info("Tool: %s(%s)", call.name, list(call.arguments.keys()))
                result = await self._dispatch(call)
                log.debug("  → %.120s", result)
                messages.append(
                    Message(
                        role="tool",
                        content=result,
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                )
        else:
            final_reply = "⚠️ Agent reached max steps."

        create_background_task(self.memory.after_turn(user_input, final_reply))
        return final_reply

    # ── Lifecycle ────────────────────────────────────────────────────

    async def boot(self):
        """Boot LLM router, memory, heartbeat, and sub-agents."""
        log.info(
            "PiClaw Agent v0.14.x booting (Marketplace Search Assistant active)..."
        )
        await self.llm.boot()
        self._start_workers()
        self._wire_sa_runner()
        create_background_task(self._boot_memory(), name="memory-boot")
        create_background_task(heartbeat_loop(), name="heartbeat")
        create_background_task(self.sa_runner.start_all_scheduled(), name="sa-boot")
        log.info("Soul loaded from %s", soul_mod.get_path())

    async def _boot_memory(self):
        try:
            await self.qmd.setup_collections()
            # embed() wird nicht beim Boot gestartet – zu CPU-intensiv auf Pi
            # Stattdessen: stündlicher Cron-Job
            log.info("QMD setup done – embed deferred to hourly cron")
        except Exception as e:
            log.error("Memory boot failed: %s", e)

    def start_scheduler(self):
        self.scheduler.start_all()

    def _save_crash(self, ctx: str, tb: str):
        CRASH_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (CRASH_DIR / f"{ts}_{ctx}.txt").write_text(tb)
        log.error("Crash saved: %s_%s.txt", ts, ctx)

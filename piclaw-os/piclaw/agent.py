"""
PiClaw OS – Core Agent
"""

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime

import re

# Vorcompilierte Regex für Marketplace-Intent-Erkennung
# Web-Suche-Intent: allgemeine "wo kaufen / wo erhältlich"-Fragen ohne Marktplatz-Nennung
_RE_WEB_BUY_KW = re.compile(
    r"\b(wo\s+(kann|kann\s+ich|bekomme\s+ich|kaufe\s+ich|krieg\s+ich|ist|gibts|gibt\s+es)|"
    r"wo\s+(?:ist|sind)\s+(?:\w+\s+){0,4}(?:erhältlich|verfügbar|zu\s+kaufen|zu\s+haben)|"
    r"(?:wo|bei\s+wem)\s+(?:kaufen|bestellen|erwerben)|"
    r"where\s+(?:to\s+buy|can\s+i\s+(?:buy|get|order)))",
    re.IGNORECASE,
)
_RE_WEB_BUY_NO_MARKET = re.compile(
    r"(kleinanzeigen|willhaben|ebay|egun|troostwijk|zoll.?auktion|gebraucht|inserat)",
    re.IGNORECASE,
)

_RE_MP_SEARCH_KW = re.compile(
    r"(durchsuche|was kostet|preis für|look for|gibt es|schaue|search|suche|finde|schau|liste|such|find|zeig)",
    re.IGNORECASE,
)
_RE_MP_MARKET_KW = re.compile(
    r"(kleinanzeigen|schnäppchen|marktplatz|willhaben|egun|troostwijk|zoll.?auktion|gebraucht|inserat|anzeige|angebot|umkreis|kaufen|preis|ebay|euro|nähe|plz|ort)",
    re.IGNORECASE,
)

_KNOWN_CITIES = (
    # Österreich
    "Wien", "Graz", "Linz", "Salzburg", "Innsbruck", "Klagenfurt",
    "Villach", "Wels", "Steyr", "Dornbirn", "Feldkirch", "Bregenz",
    "Leoben", "Kapfenberg", "Eisenstadt", "St. Pölten", "Wiener Neustadt",
    "Krems", "Baden", "Mödling",
    # Deutschland
    "Hamburg", "Berlin", "München", "Köln", "Frankfurt", "Bremen",
    "Hannover", "Düsseldorf", "Leipzig", "Dresden", "Stuttgart",
    "Dortmund", "Essen", "Nürnberg", "Duisburg", "Bochum",
    "Wuppertal", "Bielefeld", "Bonn", "Mannheim", "Karlsruhe",
    "Rosengarten", "Augsburg", "Münster", "Wiesbaden",
)

_RE_CITIES = re.compile(
    r"(?i)\b(" + "|".join(re.escape(c) for c in sorted(_KNOWN_CITIES, key=len, reverse=True)) + r")\b"
)
_CITY_MAP = {c.lower(): c for c in _KNOWN_CITIES}

_RE_MONITOR_PHRASES = re.compile(
    r"(?i)\b(" + "|".join(re.escape(p) for p in sorted([
        "beobachte ob es", "beobachte ob", "schau ob es", "schau ob",
        "sag mir wenn", "sag bescheid wenn", "benachrichtige mich",
        "informiere mich", "überwache", "beobachte", "monitor",
        "halte ausschau", "check regelmäßig", "automatisch",
        "stündlich", "regelmäßig", "neue gibt", "neue auftauchen",
        "neue inserate", "neue angebote", "neues gibt", "gibt es neue",
        "gibt es", "ob es", "ob neue", "neue für", "nach neuen",
        "jede stunde", "jede halbe stunde", "alle stunde"
    ], key=len, reverse=True)) + r")\b"
)

_RE_AGENT_STATUS_KW = re.compile(r'(laufende|running|welche|status|aktive|liste|zeig|alle|show|list|was)')
_RE_AGENT_NOUN_KW = re.compile(r'(sub\-agent|subagent|monitor|aufgabe|agent|task|job)')
_RE_AGENT_STOP_KW = re.compile(r'(deaktiviere|halte\ an|stopp|beend|pause|stop)')
_RE_AGENT_START_KW = re.compile(r'(reaktiviere|aktiviere|starte|start)')
_RE_AGENT_REMOVE_KW = re.compile(r'(entfern|delete|remove|lösch)')
_RE_LLM_DISCOVER_KW = re.compile(r'(neue\ modelle\ finden|neue\ modelle\ suchen|backends\ entdecken|modelle\ entdecken|discover\ backends|backends\ finden|backends\ suchen|finde\ neue\ llm|neue\ backends|llm\ autonomie|llm\ discover|find\ new\ llm|llm\ suchen|llm\ finden|api\ finden|api\ suchen|gratis\ api|freie\ api|neue\ api|neue\ llm)')
_RE_MONITOR_KW = re.compile(r'(halte\ die\ augen\ offen|jede\ halbe\ stunde|check\ regelmäßig|halte\ ausschau|benachrichtig|sag\ mir\ wenn|sag\ bescheid|automatisch|jede\ stunde|alle\ stunde|schick\ mir|regelmäßig|informier|stündlich|überwach|beobacht|monitor|notify|alert|watch|meld)')
_RE_NET_MARKET_KW = re.compile(r'(?:kleinanzeigen|zoll\-auktion|sonnenschirm|zollauktion|troostwijk|marktplatz|willhaben|verkaufen|inserat|anzeige|fahrrad|wohnung|kaufen|ebay|egun|auto)')
_RE_NET_SPECIFIC_KW = re.compile(r'(?:unbekanntes\ gerät|wer\ ist\ im\ netz|neue\ verbindung|welche\ geräte|fremdes\ gerät|ip\ adresse|netzwerk|network|device|router|gerät|wlan|wifi|nmap|lan)')
_RE_NET_MONITOR_KW = re.compile(r'(?:überwach|beobacht|monitor|scan)')

_RE_PLATFORM_PHRASES = re.compile(
    r"(?i)\b(" + "|".join(re.escape(p) for p in sorted([
        "kleinanzeigen.de", "ebay.de", "willhaben.at", "kleinanzeigen",
        "ebay", "willhaben", "zeige mir", "zeig mir", "was kostet",
        "preis für", "gibt es", "auf"
    ], key=len, reverse=True)) + r")\b"
)

_RE_STOPWORDS = re.compile(
    r"(?i)(?<![\w])(" + "|".join(re.escape(p) for p in sorted([
        "auf", "im", "in", "um", "von", "bis", "bitte", "suche", "finde",
        "such", "durchsuche", "liste", "umkreis", "radius", "einen", "eine",
        "ein", "mir", "dem", "der", "die", "das", "schnäppchen", "angebot",
        "angebote", "nach", "einem", "einer", "nähe", "nähe von", "in der",
        "nach einem", "ob es neue anzeigen zu", "ob es neue inserate zu",
        "ob es neue", "neue anzeigen zu", "neue inserate zu",
        "neue angebote zu", "anzeigen zu", "inserate zu", "ob es", "neue",
        "anzeigen", "inserate", "gibt", "ob", "es", "zu", "für", "über", "wegen"
    ], key=len, reverse=True)) + r")(?![\w])"
)

# Vorcompilierte Regex für _detect_marketplace_intent Plattform-Erkennung (mit Word-Boundaries)
_RE_PLATFORM_KLEINANZEIGEN = re.compile(r"(?i)(?:^|(?<=\W))(kleinanzeigen|kleinanzeigen\.de)(?:(?=\W)|$)")
_RE_PLATFORM_EGUN = re.compile(r"(?i)(?:^|(?<=\W))(egun|egun\.de)(?:(?=\W)|$)")
_RE_PLATFORM_TROOSTWIJK = re.compile(r"(?i)(?:^|(?<=\W))(troostwijk|troost)(?:(?=\W)|$)")
_RE_PLATFORM_ZOLL = re.compile(r"(?i)(?:^|(?<=\W))(zollauktion|zoll-auktion|zoll auktion)(?:(?=\W)|$)")
_RE_PLATFORM_WILLHABEN = re.compile(r"(?i)(?:^|(?<=\W))willhaben(?:(?=\W)|$)")
_RE_PLATFORM_WEB = re.compile(r"(?i)(?:^|(?<=\W))(internet|web)(?:(?=\W)|$)")


from collections.abc import Callable

from piclaw.config import PiClawConfig, CRASH_DIR, CONFIG_DIR
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
    # future wird NICHT im dataclass-field erstellt – asyncio.get_running_loop()
    # darf nicht beim Import aufgerufen werden (kein Event Loop beim Modulload).
    # Stattdessen: None als Default, wird in __post_init__ gesetzt.
    future: asyncio.Future = field(default=None)

    def __post_init__(self):
        if self.future is None:
            self.future = asyncio.get_running_loop().create_future()


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
- marketplace_search: Durchsucht Kleinanzeigen.de, eBay.de nach Inseraten.
- parcel_add, parcel_status, parcel_remove: Paket-Sendungsverfolgung (DHL, Hermes, DPD, GLS, UPS).
- parcel_extract: Trackingnummern aus weitergeleiteten E-Mails/Texten extrahieren.
- ha_turn_on, ha_turn_off, ha_toggle, ha_get_state: Home Assistant Steuerung.
- network_scan, check_new_devices, wake_device: Netzwerk-Analyse und Wake-on-LAN.
- shell_exec: Shell-Befehle ausfuehren.
- memory_search, memory_write: Erinnerungen verwalten.

REGELN - IMMER BEFOLGEN:
1. NIEMALS erklaeren was du tun wuerdest - sofort das passende Tool aufrufen.
2. NIEMALS sagen "ich habe keinen Zugriff auf X" - alle Tools sind installiert und bereit.
3. Bei jeder Marktplatz-Anfrage: marketplace_search SOFORT aufrufen.
4. Bei Trackingnummern oder Paketfragen: parcel_add oder parcel_status SOFORT aufrufen.
5. FALSCH: "Ich empfehle dir auf kleinanzeigen.de zu suchen..."
6. RICHTIG: [ruft marketplace_search auf und zeigt Ergebnisse]

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

        # Request queue (parallele CLI + Telegram)
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

        # Network Monitor tools
        from piclaw.tools import network_monitor as net_mon
        _reg(net_mon.TOOL_DEFS, net_mon.build_handlers())

        # Tandem Browser tools (geplant v0.18)
        from piclaw.tools import tandem as tandem_mod

        _reg(tandem_mod.TOOL_DEFS, tandem_mod.build_handlers())

        # HTTP tool
        from piclaw.tools import http as http_mod

        _reg(http_mod.TOOL_DEFS, http_mod.HANDLERS)

        # Installer tools
        from piclaw.tools import installer as installer_mod

        _reg(installer_mod.TOOL_DEFS, installer_mod.build_handlers())

        # Paket-Tracking tools
        from piclaw.tools import parcel_tracking as parcel_mod

        _reg(parcel_mod.TOOL_DEFS, parcel_mod.HANDLERS)

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

        # Network Security tools – nach HA registrieren damit ha_client verfügbar ist
        from piclaw.tools import network_security as net_sec
        try:
            _reg(net_sec.TOOL_DEFS, net_sec.build_handlers(
                ha_client=self._ha_client,
                notify_fn=self._telegram_send,
            ))
            log.info("Network security tools registered")
        except Exception as _e:
            log.debug("Network security tools not loaded: %s", _e)

        # ── ClawHub-Tools ──────────────────────────────────────────
        try:
            from piclaw.tools import clawhub as clawhub_mod
            _reg(clawhub_mod.TOOL_DEFS, clawhub_mod.build_handlers())
            log.info("ClawHub tools registered")
        except Exception as _e:
            log.debug("ClawHub tools not loaded: %s", _e)

        # ── AgentMail-Tools ────────────────────────────────────────
        if self.cfg.agentmail.api_key:
            try:
                from piclaw.tools import agentmail as agentmail_mod
                _reg(agentmail_mod.TOOL_DEFS, agentmail_mod.build_handlers(self.cfg.agentmail))
                log.info("AgentMail tools registered (inbox=%s)",
                         self.cfg.agentmail.email_address or "not yet created")
            except Exception as _e:
                log.debug("AgentMail tools not loaded: %s", _e)

        # ── Kamera-Tools ───────────────────────────────────────────
        try:
            from piclaw.hardware import camera as camera_mod
            if camera_mod.is_available():
                _reg(camera_mod.TOOL_DEFS, camera_mod.build_handlers())
                log.info("Camera tools registered (%d cameras)", len(camera_mod.list_cameras()))
            else:
                log.debug("Keine Kamera gefunden – Camera-Tools deaktiviert")
        except Exception as _e:
            log.debug("Camera tools not loaded: %s", _e)

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
                "Sucht nach Gebraucht- und Privatverkauf-Inseraten auf Kleinanzeigen.de, eBay.de und ähnlichen Marktplätzen. "
                "NUR verwenden wenn der User explizit einen dieser Marktplätze nennt ODER nach Gebrauchtware / Privatverkauf sucht. "
                "NICHT verwenden für allgemeine 'wo kaufen'- oder 'wo erhältlich'-Fragen ohne Marktplatz-Nennung — dafür web_suche nutzen. "
                "Beispiel: 'Suche Raspberry Pi 5 auf Kleinanzeigen unter 80€ in München'"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchbegriff"},
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Plattformen: kleinanzeigen, ebay, egun, willhaben, troostwijk, zoll_auktion, web",
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
                max_results=int(kw.get("max_results") or 10),
                notify_all=kw.get("notify_all", True),
            )
            formatted = format_results(result)
            # Interne Silent-Tokens NICHT an den User zurückgeben!
            # __NO_NEW_RESULTS__ ist nur für Sub-Agent-Runner gedacht.
            if formatted in ("__NO_NEW_RESULTS__", "__NO_NEW_DEVICES__", "__SILENT__"):
                query = kw.get("query", "")
                loc = kw.get("location", "")
                loc_str = f" in {loc}" if loc else ""
                total = result.get("total_found", 0)
                if total > 0:
                    return (
                        f"Für '{query}'{loc_str} wurden {total} Inserate gefunden, "
                        f"aber alle waren bereits bekannt (keine neuen seit der letzten Suche)."
                    )
                return f"Keine Inserate für '{query}'{loc_str} gefunden."
            return formatted

        _reg([_marketplace_tool], {"marketplace_search": _marketplace_handler})
        log.info("Marketplace-Tool registriert (Kleinanzeigen, eBay, Web)")

        # ── Web-Suche Tool (allgemeine Internet-Suche, kein Marketplace) ──────
        try:
            from piclaw.tools import suche as suche_mod
            _reg(suche_mod.TOOL_DEFS, suche_mod.HANDLERS)
            log.info("Web-Suche Tool registriert (sources/price-Modus)")
        except Exception as _e:
            log.warning("Web-Suche Tool nicht geladen: %s", _e)

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

        async def _report_to_main(prompt: str) -> str:
            """Sub-Agent übergibt Aufgabe an Main Agent zur Formulierung."""
            try:
                return await self._run_internal(prompt)
            except Exception as e:
                log.warning("report_to_main Fehler: %s", e)
                return ""

        self.sa_runner = SubAgentRunner(
            registry=self.sa_registry,
            llm=self.llm,
            tool_defs=self._tool_defs,
            handlers=self._handlers,
            notify=_notify,
            memory_log=_memory_log,
            report_to_main=_report_to_main,
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
        """Enqueue a request and wait for the result."""
        self._register_late_tools()
        # _start_workers() absichtlich hier entfernt – wird in boot() gestartet.
        # run() vor boot() aufzurufen ist ein Fehler, kein Graceful-Fallback.

        # Detect @installer prefix
        if user_input.strip().startswith("@installer"):
            request = user_input.strip()[10:].strip()
            from piclaw.agents.watchdog import INSTALLER_LOCK_FILE

            INSTALLER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            INSTALLER_LOCK_FILE.write_text(request, encoding="utf-8")
            return await self._delegate_to_installer(request)

        task = AgentTask(user_input, history, on_token)
        await self._queue.put(task)
        return await task.future

    def _detect_cron_agent_intent(self, text: str) -> dict | None:
        """Erkennt Anfragen einen zeitgesteuerten Sub-Agenten zu erstellen."""

        t = text.lower()

        create_kw = ("erstell", "create", "mach", "baue", "neuen agenten",
                     "einen job", "einen task", "einen agenten")
        time_kw = ("uhr", "taeglich", "taegl", "jeden tag", "jede woche",
                   "morgens", "abends", "nachts", "cron", "um ")

        if not any(k in t for k in create_kw):
            return None
        if not any(k in t for k in time_kw):
            return None
        if _RE_MP_MARKET_KW.search(t):
            return None

        # Zeit extrahieren
        time_match = re.search(r"um\s+(\d{1,2})[:\.](\d{2})(?:\s*uhr)?", t)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
        else:
            time_match2 = re.search(r"um\s+(\d{1,2})\s*uhr", t)
            if time_match2:
                hour = int(time_match2.group(1))
                minute = 0
            else:
                return None

        cron_expr = f"{minute} {hour} * * *"

        # Aufgabe extrahieren: alles nach "der" bis zur Zeitangabe/täglich
        # Strategie: Suche nach dem Nomen das NACH "Uhr" kommt, oder dem ganzen Satz
        # Beispiel: "...um 07:15 Uhr die CPU Temperatur meldet" → "die CPU Temperatur meldet"
        after_time = re.search(
            r"um\s+\d{1,2}[:.]\d{0,2}\s*uhr?\s+(.+?)(?:\s*[.,]?\s*$)",
            text.lower()
        )
        if after_time:
            task = after_time.group(1).strip()
        else:
            # Fallback: alles nach "der täglich" oder "der jeden tag"
            task_match = re.search(
                r"(?:agenten?|job|task)\s+der\s+(?:jeden\s+tag\s+|täglich\s+|taeglich\s+)?(?:um\s+[\d:.]+\s*uhr?\s+)?(.+?)(?:\s*[.,]?\s*$)",
                text.lower()
            )
            task = task_match.group(1).strip() if task_match else text.strip()
        # Cleaning: Zeitrauschen entfernen
        task = re.sub(r"(täglich|jeden tag|um \d{1,2}[:.]\d{0,2}\s*uhr?)", "", task, flags=re.IGNORECASE).strip()
        task = re.sub(r"\s+", " ", task).strip() or text.strip()

        return {"cron_expr": cron_expr, "hour": hour, "minute": minute,
                "task": task, "original": text}

    def _detect_network_monitor_intent(self, text: str) -> bool:
        """Erkennt natürliche Netzwerk-Monitoring-Anfragen."""

        t = re.sub(r"\[.*?\]", " ", text).lower()

        # Marktplatz-Keywords → definitiv kein Netzwerk-Monitor
        if _RE_NET_MARKET_KW.search(t):
            return False

        # Netzwerk-spezifische Keywords müssen vorhanden sein
        return bool(_RE_NET_SPECIFIC_KW.search(t) and _RE_NET_MONITOR_KW.search(t))

    async def _create_cron_agent(self, intent: dict) -> str:
        """Erstellt einen zeitgesteuerten Sub-Agenten basierend auf erkanntem Intent."""
        from piclaw.agents.sa_registry import SubAgentDef

        hour = intent["hour"]
        minute = intent["minute"]
        cron_expr = intent["cron_expr"]
        task = intent["task"]

        name = f"CronJob_{hour:02d}{minute:02d}"
        # Tool-Auswahl basierend auf Aufgabe
        t = task.lower()
        if any(k in t for k in ("temperatur", "temp", "cpu", "hardware", "pi info", "wärme")):
            tools = ["thermal_status", "pi_info", "memory_log"]
            mission = (
                f"Du bist ein autonomer Hintergrund-Agent auf einem Raspberry Pi 5.\n"
                f"Deine Aufgabe: {task}\n\n"
                f"Vorgehensweise:\n"
                f"1. Ruf thermal_status auf um die CPU-Temperatur zu lesen.\n"
                f"2. Ruf pi_info auf fuer weitere Systeminfos.\n"
                f"3. Fasse das Ergebnis in 1-2 Saetzen auf DEUTSCH zusammen.\n"
                f"4. Protokolliere das Ergebnis mit memory_log.\n\n"
                f"WICHTIG: Antworte ausschliesslich auf Deutsch."
            )
        elif any(k in t for k in ("service", "dienst", "status")):
            tools = ["service_status", "service_list", "memory_log"]
            mission = (
                f"Du bist ein autonomer Hintergrund-Agent auf einem Raspberry Pi 5.\n"
                f"Deine Aufgabe: {task}\n\n"
                f"Nutze service_status und service_list um den Status zu pruefen.\n"
                f"Fasse das Ergebnis in 1-2 Saetzen zusammen."
            )
        else:
            # Standard-Fallback: Systembericht via direct_tool (kein LLM nötig!)
            # Spart ~3-5 LLM-Calls/Tag und schont das Groq/NIM Token-Budget.
            tools = ["system_report", "thermal_status", "pi_info", "memory_log"]
            mission = f"Direct tool mode: system_report"
            # direct_tool wird weiter unten gesetzt

        # direct_tool für Systembericht-Tasks (kein LLM-Loop nötig)
        _use_direct_tool = not any(
            k in t for k in ("service", "dienst", "status", "prozess")
        )
        _direct_tool_name = "system_report" if _use_direct_tool else ""

        # Collision check
        if self.sa_registry.get(name):
            name = f"{name}_2"

        agent = SubAgentDef(
            name=name,
            description=f"Taeglicher Job um {hour:02d}:{minute:02d} Uhr: {task}",
            mission=mission,
            tools=tools,
            schedule=f"cron:{cron_expr}",
            direct_tool=_direct_tool_name,   # leer → LLM-Loop; gesetzt → kein LLM
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent)
        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
        result = f"created {name}"

        if "created" in result.lower() or name.lower() in result.lower():
            return (
                f"Cron-Agent erstellt!\n"
                f"  Laeuft taeglich um {hour:02d}:{minute:02d} Uhr\n"
                f"  Aufgabe: {task}\n"
                f"  Name: {name}\n"
                f"  Cron: {cron_expr}\n\n"
                f"Der Agent startet beim naechsten geplanten Zeitpunkt automatisch."
            )
        return result

    async def _create_network_monitor_agent(self, interval_sec: int = 300) -> str:
        """Erstellt einen Sub-Agenten der das Netzwerk auf neue Geräte überwacht."""
        agent_name = "Monitor_Netzwerk"

        existing = self.sa_registry.get(agent_name)
        if existing:
            return (
                f"⚠️ Netzwerk-Monitor läuft bereits (ID: {existing.id}, "
                f"schedule: {existing.schedule}).\n"
                f"Zum Stoppen: 'Stopp den {agent_name}'"
            )

        interval_str = (
            f"alle {interval_sec // 60} Minuten" if interval_sec < 3600
            else "stündlich"
        )

        mission = (
            "Du bist ein Netzwerk-Sicherheitsmonitor fuer PiClaw OS.\n\n"
            "Schritt 1: Ruf das Tool 'check_new_devices' auf.\n\n"
            "Schritt 2: Werte das Ergebnis aus:\n\n"
            "FALL A – Das Tool meldet neue/unbekannte Geraete:\n"
            "  Antworte mit einem Bericht in diesem Format:\n"
            "  🚨 Neues Geraet im Netzwerk!\n"
            "  📍 IP: <ip>  🔌 MAC: <mac>  🏭 <vendor>  💻 <hostname>\n"
            "  Kurze Bewertung ob verdaechtig.\n\n"
            "FALL B – Das Tool gibt '__NO_NEW_DEVICES__' zurueck ODER meldet keine neuen Geraete:\n"
            "  Antworte mit EXAKT diesem Token und NICHTS ANDEREM:\n"
            "  __NO_NEW_DEVICES__\n\n"
            "WICHTIG: Bei FALL B darf deine Antwort NUR '__NO_NEW_DEVICES__' enthalten.\n"
            "Kein 'Alles ruhig', kein 'Netzwerk sauber', keine Erklaerung. NUR der Token."
        )

        agent_def = SubAgentDef(
            name=agent_name,
            description=f"Netzwerk-Monitoring: neue Geraete erkennen – {interval_str}",
            mission=mission,
            tools=["check_new_devices", "network_scan"],
            schedule=f"interval:{interval_sec}",
            notify=True,
            direct_tool="check_new_devices",  # kein LLM nötig – Tool direkt aufrufen
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent_def)

        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
            return (
                f"✅ Netzwerk-Monitor gestartet!\n"
                f"  🔍 Scannt {interval_str} nach neuen Geräten\n"
                f"  📨 Neue/unbekannte Geräte → Telegram\n"
                f"  🆔 Agent-ID: {agent_id}\n\n"
                f"Beim ersten Scan werden alle aktuell verbundenen Geräte als 'bekannt' gespeichert.\n"
                f"Danach wird nur bei neuen Geräten gemeldet."
            )
        return "❌ Sub-agent runner nicht bereit."

    async def _ha_shortcut(self, text: str) -> str | None:
        """
        Direkte HA-Ausführung ohne LLM – für einfache Schalt-Befehle.
        Erkennt: "Licht an/aus", "schalte X ein/aus", "mach X an/aus"
        Spart den gesamten LLM-Call + System-Prompt.
        """

        t = text.lower().strip()

        # Nur wenn HA konfiguriert
        from piclaw.tools import homeassistant as _ha_mod
        client = _ha_mod.get_client()
        if not client:
            return None

        # Intent erkennen
        on_kw  = ("ein", "an", "on", "einschalten", "anmachen", "anschalten", "einmachen")
        off_kw = ("aus", "off", "ausschalten", "ausmachen", "ausknipsen", "löschen")
        toggle_kw = ("toggle", "umschalten", "wechseln")
        cmd_kw = ("schalte", "mach", "mache", "stell", "stelle", "knips", "dreh",
                  "licht", "lampe", "leuchte", "steckdose", "schalter")

        # Muss mindestens ein Befehlswort enthalten
        if not any(k in t for k in cmd_kw):
            return None

        # Richtung bestimmen
        action = None
        if any(k in t for k in on_kw):
            action = "on"
        elif any(k in t for k in off_kw):
            action = "off"
        elif any(k in t for k in toggle_kw):
            action = "toggle"
        else:
            return None  # Kein klarer On/Off Intent

        # Raum/Gerät extrahieren – alles zwischen Befehlswort und Richtungswort
        # Stopwörter entfernen
        stop = {"das", "die", "den", "dem", "der", "im", "in", "am", "an", "bitte",
                "bitte", "mal", "doch", "jetzt", "sofort", "kurz", "einmal"}
        words = [w for w in re.sub(r"[^\w\s]", " ", t).split() if w not in stop]
        # Raum-Keywords suchen
        area_words = [w for w in words if w not in
                      on_kw + off_kw + toggle_kw +
                      ("schalte", "mach", "mache", "stell", "stelle",
                       "knips", "dreh", "licht", "lampe", "leuchte",
                       "steckdose", "schalter", "bitte")]
        area = " ".join(area_words).strip() if area_words else ""

        # Gerätetyp aus Query ableiten (licht/rolladen/...)
        device_hint = None
        if any(k in t for k in ("licht", "lampe", "leuchte", "beleuchtung")):
            device_hint = "light"
        elif any(k in t for k in ("rolladen", "rollladen", "rollo", "jalousie")):
            device_hint = "cover"
        elif "ventilator" in t:
            device_hint = "fan"
        elif "steckdose" in t:
            device_hint = "switch"

        # Entität suchen
        entity_id = None
        if area:
            entities = await client.get_states(area=area)
            # Schaltbare Domains
            entities = [e for e in entities
                        if e.domain in ("light", "switch", "cover", "fan")]

            # Nach Gerätetyp priorisieren
            if device_hint == "light":
                light_entities = [e for e in entities if e.domain == "light"]
                light_switches = [e for e in entities
                                  if e.domain == "switch"
                                  and any(k in e.entity_id.lower()
                                          for k in ("licht", "lampe", "leuchte"))]
                filtered = light_entities + light_switches
                if filtered:
                    entities = filtered
            elif device_hint == "cover":
                filtered = [e for e in entities if e.domain == "cover"]
                if filtered:
                    entities = filtered
            elif device_hint == "fan":
                filtered = [e for e in entities if e.domain == "fan"]
                if filtered:
                    entities = filtered
            elif device_hint == "switch":
                filtered = [e for e in entities
                            if e.domain == "switch"
                            and not any(k in e.entity_id.lower()
                                        for k in ("licht", "lampe", "leuchte", "strahler"))]
                if filtered:
                    entities = filtered

            if entities:
                entity_id = entities[0].entity_id

        if not entity_id:
            return None  # Kein Match → LLM übernimmt

        # Ausführen
        try:
            if action == "on":
                ok = await client.turn_on(entity_id)
                icon = "💡" if entity_id.startswith("light.") else "✅"
                return f"{icon} {entity_id} eingeschaltet." if ok else f"❌ Konnte {entity_id} nicht einschalten."
            elif action == "off":
                ok = await client.turn_off(entity_id)
                icon = "🌑" if entity_id.startswith("light.") else "✅"
                return f"{icon} {entity_id} ausgeschaltet." if ok else f"❌ Konnte {entity_id} nicht ausschalten."
            else:  # toggle
                ok = await client.toggle(entity_id)
                return f"🔄 {entity_id} umgeschaltet." if ok else "❌ Toggle fehlgeschlagen."
        except Exception as e:
            log.warning("HA-Shortcut Fehler: %s", e)
            return None  # LLM übernimmt bei Fehler

    # ── Troostwijk Auktions-Monitor ────────────────────────────────────────────

    _TW_COUNTRY_MAP: dict[str, str] = {
        # Deutsch
        "deutschland": "de", "german": "de", "germany": "de",
        "niederlande": "nl", "holland": "nl", "netherlands": "nl",
        "belgien": "be", "belgium": "be",
        "frankreich": "fr", "france": "fr",
        "österreich": "at", "austria": "at", "oesterreich": "at",
        "italien": "it", "italy": "it",
        "spanien": "es", "spain": "es",
        "schweden": "se", "sweden": "se",
        "dänemark": "dk", "daenemark": "dk", "denmark": "dk",
        "Polen": "pl", "poland": "pl",
        "tschechien": "cz", "czech": "cz",
        "ungarn": "hu", "hungary": "hu",
        "rumänien": "ro", "rumaenien": "ro", "romania": "ro",
        "kroatien": "hr", "croatia": "hr",
        "portugal": "pt",
        "finnland": "fi", "finland": "fi",
        "estland": "ee", "estonia": "ee",
        "griechenland": "gr", "greece": "gr",
        "irland": "ie", "ireland": "ie",
        "slowakei": "sk", "slovakia": "sk",
        "bulgarien": "bg", "bulgaria": "bg",
    }

    _TW_AUCTION_MONITOR_KW = (
        "neue auktionen", "neue auktion", "auktionen in", "auktion in",
        "troostwijk.*auktion", "auktionen.*troostwijk",
        "neue.*troostwijk", "troostwijk.*neu",
    )

    def _detect_tw_auction_monitor_intent(self, text: str) -> dict | None:
        """
        Erkennt Troostwijk-Auktions-Monitoring-Anfragen wie:
          'Überwache Troostwijk auf neue Auktionen in Deutschland'
          'Neue Auktionen in Hamburg auf Troostwijk – sag mir Bescheid'
          'Troostwijk Auktionen im Umkreis von 50km um 21224'
          'Überwache Troostwijk PLZ 21224, 100km Radius'

        Gibt zurück: {"country": "de", "city": "Hamburg"|None,
                      "plz": "21224"|None, "radius_km": 50|None,
                      "interval_sec": 3600}
        """
        t = re.sub(r"\[.*?\]", " ", text).lower()

        # Muss Troostwijk + Auktions-Kontext haben
        if not _RE_PLATFORM_TROOSTWIJK.search(t):
            return None
        if not any(k in t for k in ("auktion", "auction", "neue", "überwach", "monitor",
                                     "benachrichtig", "meld", "inform")):
            return None

        # Intervall (default: 1h)
        interval_sec = 3600
        if any(k in t for k in ("30 min", "30min", "halbstündlich")):
            interval_sec = 1800
        elif any(k in t for k in ("täglich", "24h", "einmal am tag")):
            interval_sec = 86400
        m_iv = re.search(r"(?:alle|jede)\s+(\d+)\s*(min|stund)", t)
        if m_iv:
            val, unit = int(m_iv.group(1)), m_iv.group(2)
            interval_sec = val * 3600 if "stund" in unit else max(val * 60, 300)

        # Land erkennen
        country = "de"  # default: Deutschland
        for name, code in self._TW_COUNTRY_MAP.items():
            if re.search(r"(?i)\b" + re.escape(name) + r"\b", text):
                country = code
                break

        # ── PLZ + Radius erkennen ─────────────────────────────────────
        # Muster: "21224 50km", "PLZ 21224, 100km Radius", "um 21224 im Umkreis von 50 km"
        plz = None
        radius_km = None

        plz_match = re.search(r"(?:plz\s*)?(?<![\d])(\d{5})(?![\d])", t)
        if plz_match:
            plz = plz_match.group(1)


        # Radius: "50km", "50 km", "Umkreis von 50km", "Radius 100km", "im Umkreis 30 km"
        radius_match = re.search(
            r"(?:umkreis|radius|entfernung)?\s*(?:von\s+)?(\d+)\s*km",
            t,
        )
        if radius_match:
            radius_km = int(radius_match.group(1))

        # PLZ ohne expliziten Radius → Default 50km
        if plz and not radius_km:
            radius_km = 50

        # Stadt erkennen (bekannte Städte aus allen TW-Ländern)
        _TW_CITIES = [
            # Deutschland
            "Hamburg", "Berlin", "München", "Köln", "Frankfurt", "Bremen",
            "Hannover", "Düsseldorf", "Leipzig", "Dresden", "Stuttgart",
            "Dortmund", "Essen", "Nürnberg", "Duisburg", "Bochum",
            "Wuppertal", "Bielefeld", "Bonn", "Mannheim", "Karlsruhe",
            "Augsburg", "Münster", "Wiesbaden", "Rosengarten",
            # Niederlande
            "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven",
            "Tilburg", "Groningen", "Almere", "Breda", "Nijmegen",
            # Belgien
            "Brüssel", "Bruxelles", "Antwerpen", "Gent", "Brügge", "Lüttich",
            # Österreich
            "Wien", "Graz", "Linz", "Salzburg", "Innsbruck",
            # Frankreich
            "Paris", "Lyon", "Marseille", "Bordeaux", "Toulouse",
        ]
        city = None
        for c in sorted(_TW_CITIES, key=len, reverse=True):
            if re.search(r"(?i)\b" + re.escape(c) + r"\b", text):
                city = c
                break

        # Stadt als PLZ-Ersatz: Wenn Stadt erkannt aber keine PLZ,
        # nutze Stadt als location (für Nominatim-Geocoding)
        # PLZ hat aber Priorität wenn beides vorhanden

        return {
            "country": country,
            "city": city,
            "plz": plz,
            "radius_km": radius_km,
            "interval_sec": interval_sec,
        }

    async def _create_tw_auction_monitor(self, params: dict) -> str:
        """
        Erstellt einen Troostwijk-Auktions-Monitor Sub-Agenten.
        Nutzt direct_tool='marketplace_monitor' mit platforms=['troostwijk_auctions'].
        Kein LLM in der Monitor-Schleife – rein tokenlos.

        Unterstützte Modi:
          1. Land-Filter:    country="de" (default)
          2. Stadt-Filter:   city="Hamburg"
          3. PLZ + Radius:   plz="21224", radius_km=50
        """
        import json as _json

        country      = params.get("country", "de")
        city         = params.get("city")          # optional
        plz          = params.get("plz")           # optional (5-stellige PLZ)
        radius_km    = params.get("radius_km")     # optional (km)
        interval_sec = params.get("interval_sec", 3600)

        # Ländercode → lesbarer Name für Agent-Description
        _country_names = {
            "de": "Deutschland", "nl": "Niederlande", "be": "Belgien",
            "fr": "Frankreich", "at": "Österreich", "it": "Italien",
            "es": "Spanien", "se": "Schweden", "dk": "Dänemark",
            "pl": "Polen", "cz": "Tschechien", "hu": "Ungarn",
            "hr": "Kroatien", "pt": "Portugal", "fi": "Finnland",
            "ee": "Estland", "gr": "Griechenland", "ro": "Rumänien",
        }
        country_name = _country_names.get(country, country.upper())

        # Location-String + Agentname je nach Modus
        if plz and radius_km:
            location_str = f"PLZ {plz}, {radius_km}km"
            safe_loc = f"PLZ{plz}_{radius_km}km"
        elif city:
            location_str = city
            safe_loc = re.sub(r"[^a-zA-Z0-9]", "", city)[:15]
        else:
            location_str = country_name
            safe_loc = re.sub(r"[^a-zA-Z0-9]", "", country_name)[:15]

        agent_name = f"Monitor_TW_{safe_loc}"

        existing = self.sa_registry.get(agent_name)
        if existing:
            return (
                f"Es läuft bereits ein Troostwijk-Auktions-Monitor für {location_str} "
                f"(ID: {existing.id}, schedule: {existing.schedule})."
            )

        if interval_sec == 3600:
            interval_str = "stündlich"
        elif interval_sec < 3600:
            interval_str = f"alle {interval_sec // 60} Minuten"
        else:
            interval_str = f"alle {interval_sec // 3600} Stunden"

        # mission_params: PLZ geht als location (wird in marketplace.py als PLZ erkannt)
        # Stadt geht ebenfalls als location (wird als city_filter erkannt)
        mission_location = plz if plz else city
        mission_params = {
            "query":      "",                         # troostwijk_auctions braucht keine Query
            "platforms":  ["troostwijk_auctions"],
            "location":   mission_location,           # PLZ oder Stadtname
            "country":    country,                    # ISO-Code für Länder-API-Filter
            "radius_km":  radius_km,                  # None oder int (km)
            "max_price":  None,
            "max_results": 24,
        }

        from piclaw.agents.sa_registry import SubAgentDef
        agent_def = SubAgentDef(
            name=agent_name,
            description=(
                f"Troostwijk Auktionen: {location_str} – {interval_str}"
            ),
            mission=_json.dumps(mission_params, ensure_ascii=False),
            tools=["marketplace_search"],
            schedule=f"interval:{interval_sec}",
            notify=True,
            direct_tool="marketplace_monitor",
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent_def)

        log.info(
            "TW-Auktions-Monitor '%s' erstellt – country=%s, city=%s, plz=%s, radius=%s, interval=%ds",
            agent_name, country, city, plz, radius_km, interval_sec,
        )

        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
            radius_info = f"\n📏 Umkreis: {radius_km} km um PLZ {plz}" if plz and radius_km else ""
            return (
                f"✅ Troostwijk-Auktions-Monitor gestartet!\n"
                f"📍 Region: {location_str}{radius_info}\n"
                f"⏱️ Intervall: {interval_str}\n"
                f"🏛️ Neue Auktionsereignisse → Telegram\n"
                f"Agent-ID: {agent_id}"
            )
        return f"Agent '{agent_name}' erstellt (ID: {agent_id}), Runner nicht bereit."

    def _detect_monitor_intent(self, text: str) -> dict | None:
        """Erkennt natürliche Monitoring-Anfragen wie 'Sag mir wenn ein Pi 5 auftaucht'."""

        t = re.sub(r"\[.*?\]", " ", text).lower()

        # Regex-Muster getrennt prüfen (funktionieren nicht mit einfachem `in`)
        _regex_patterns = [
            r"wenn.*auftaucht", r"sobald.*verfügbar", r"falls.*angebot",
            r"wenn.*inserat", r"wenn.*neu", r"jede.*stunde", r"alle.*stunde",
            r"jede.*halbe", r"alle\s+\d+\s*min",
        ]
        market_kw = (
            "kleinanzeigen", "ebay", "willhaben", "egun", "troostwijk", "zollauktion", "zoll-auktion",
            "inserat", "anzeige", "kaufen",
            "marktplatz", "gebraucht", "preis", "euro", "angebot",
        )

        _has_monitor_kw = bool(_RE_MONITOR_KW.search(t))
        if not _has_monitor_kw:
            # Regex-Patterns als Fallback prüfen
            _has_monitor_kw = any(re.search(p, t) for p in _regex_patterns)
        if not _has_monitor_kw:
            return None
        if not _RE_MP_MARKET_KW.search(t):
            return None

        # Intervall aus Text extrahieren (default 1h)
        interval_sec = 3600
        if any(k in t for k in ("30 min", "30min", "halbstündlich", "halbe stunde", "jede halbe")):
            interval_sec = 1800
        elif any(k in t for k in ("15 min", "15min")):
            interval_sec = 900
        elif any(k in t for k in ("2 stund", "2h", "alle zwei")):
            interval_sec = 7200
        elif any(k in t for k in ("täglich", "einmal am tag", "24h")):
            interval_sec = 86400
        # Explizite "alle N min/stunde" Extraktion
        _interval_match = re.search(r"(?:alle|jede)\s+(\d+)\s*(min|stund)", t)
        if _interval_match:
            _val = int(_interval_match.group(1))
            _unit = _interval_match.group(2)
            if "stund" in _unit:
                interval_sec = _val * 3600
            else:
                interval_sec = max(_val * 60, 300)  # min 5 min

        # Plattform
        platforms = []
        if _RE_PLATFORM_KLEINANZEIGEN.search(t):
            platforms.append("kleinanzeigen")
        if "ebay" in t and "kleinanzeigen" not in t:
            platforms.append("ebay")
        if _RE_PLATFORM_EGUN.search(t):
            platforms.append("egun")
        if _RE_PLATFORM_TROOSTWIJK.search(t):
            platforms.append("troostwijk")
        if _RE_PLATFORM_ZOLL.search(t):
            platforms.append("zoll_auktion")
        if "vdb" in t:
            platforms.append("vdb")
        if "ebay" in t and "kleinanzeigen" not in t:
            platforms.append("ebay")
        if _RE_PLATFORM_WILLHABEN.search(t):
            platforms.append("willhaben")
        if _RE_PLATFORM_WEB.search(t):
            platforms.append("web")
        if not platforms:
            platforms = ["kleinanzeigen", "ebay"]

        # Query: Monitoring-Keywords + Rauschen VOR _detect_marketplace_intent entfernen
        clean_text = text
        clean_text = _RE_MONITOR_PHRASES.sub(" ", clean_text)
        # Regex-Patterns (z.B. "alle 30 Minuten", "jede 2 Stunden")
        clean_text = re.sub(r"(?i)(?:alle|jede)\s+\d+\s*(?:min(?:uten)?|stund(?:en?)?)", " ", clean_text)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        # "suche" voranstellen damit _detect_marketplace_intent den Intent erkennt
        mp = self._detect_marketplace_intent("suche " + clean_text)
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
        """Erstellt einen Monitoring-Sub-Agenten fuer stündliche Marktplatz-Suche.

        Nutzt direct_tool='marketplace_monitor' - Parameter stehen als JSON
        direkt im mission-Feld von subagents.json. Vollstaendig neustart-sicher.
        """
        import json as _json

        query = params["query"]
        platforms = params.get("platforms", ["kleinanzeigen"])
        location = params.get("location") or None
        radius_km = params.get("radius_km")
        max_price = params.get("max_price")
        interval_sec = params.get("interval_sec", 3600)
        max_results = params.get("max_results", 10)

        plat_str = " + ".join(p.capitalize() for p in platforms)
        loc_str = " um " + str(location) if location else ""
        rad_str = " (" + str(radius_km) + "km)" if radius_km else ""
        price_str = ", max. " + str(int(max_price)) + "EUR" if max_price else ""
        if interval_sec == 3600:
            interval_str = "stuendlich"
        elif interval_sec < 3600:
            interval_str = "alle " + str(interval_sec // 60) + " Minuten"
        else:
            interval_str = "alle " + str(interval_sec // 3600) + " Stunden"

        name_words = query.split()[:2]
        safe_name = re.sub(r"[^a-zA-Z0-9]", "", " ".join(name_words).title().replace(" ", ""))[:20]
        agent_name = "Monitor_" + safe_name

        existing = self.sa_registry.get(agent_name)
        if existing:
            return (
                "Es laeuft bereits ein Monitoring-Agent fuer '"
                + query + "' (ID: " + existing.id
                + ", schedule: " + existing.schedule + ")."
            )

        mission_params = {
            "query": query,
            "platforms": list(platforms),
            "location": location,
            "radius_km": radius_km,
            "max_price": max_price,
            "max_results": max_results,
        }

        agent_def = SubAgentDef(
            name=agent_name,
            description="Monitoring " + plat_str + ": '" + query + "'" + loc_str + rad_str + price_str + " - " + interval_str,
            mission=_json.dumps(mission_params, ensure_ascii=False),
            tools=["marketplace_search"],
            schedule="interval:" + str(interval_sec),
            notify=True,
            direct_tool="marketplace_monitor",
            created_by="mainagent",
        )
        agent_id = self.sa_registry.add(agent_def)

        log.info(
            "marketplace_monitor Agent '%s' erstellt – query=%s, platforms=%s, loc=%s, r=%s",
            agent_name, query, platforms, location, radius_km,
        )

        if self.sa_runner:
            await self.sa_runner.start_agent(agent_id)
            return (
                "Monitoring gestartet: '" + query + "' auf " + plat_str
                + loc_str + rad_str + price_str
                + "\nIntervall: " + interval_str
                + "\nNeue Inserate -> Telegram. Agent-ID: " + agent_id
            )
        return "Sub-agent runner nicht bereit."

    # ── Parcel Tracking Intent ───────────────────────────────────────

    # Regex für Trackingnummer-Erkennung in natürlicher Sprache
    _RE_PARCEL_TRACKING_NR = re.compile(
        r"(?:^|\s)"
        r"(1Z[A-Z0-9]{16}|00\d{10,18}|JJD\d{12,18}|JVGL\d{10,16}"
        r"|TBA\d{10,14}|\d{10,20})"
        r"(?:\s|$)",
        re.IGNORECASE,
    )
    _RE_PARCEL_KW = re.compile(
        r"(?i)\b(?:track|tracke|verfolge|paket|sendung|lieferung|paketstatus"
        r"|wo ist (?:mein |das )?paket|pakete|sendungsverfolgung"
        r"|trackingnummer|sendungsnummer|paketverfolgung)\b"
    )

    def _detect_parcel_intent(self, text: str) -> dict | None:
        """
        Erkennt Paket-Tracking-Intents:
        - "Tracke 00340434161094042557"
        - "Wo ist mein Paket?"
        - "Pakete" / "Paketstatus"
        - Weitergeleitete E-Mail mit Trackingnummer
        """
        t = text.strip()
        t_lower = t.lower()

        # 1. Explizite Trackingnummer im Text → parcel_add
        tn_match = self._RE_PARCEL_TRACKING_NR.search(t)
        if tn_match and self._RE_PARCEL_KW.search(t_lower):
            return {"action": "add", "tracking_number": tn_match.group(1).strip()}

        # Trackingnummer ohne Keyword, aber klar als Tracking gemeint
        # (nur Nummer, oder "00340..." am Anfang)
        if tn_match and len(t.split()) <= 3:
            tn = tn_match.group(1).strip()
            # Nur wenn es wie eine echte Trackingnummer aussieht
            if len(tn) >= 12 or tn.upper().startswith(("1Z", "JJD", "JVGL", "TBA", "00")):
                return {"action": "add", "tracking_number": tn}

        # 2. Status-Abfrage: "Wo ist mein Paket?", "Pakete", "Paketstatus"
        status_kw = (
            "wo ist mein paket", "wo ist das paket", "paketstatus",
            "meine pakete", "pakete anzeigen", "sendungsstatus",
            "paketübersicht", "lieferstatus",
        )
        if any(k in t_lower for k in status_kw):
            return {"action": "status"}
        # Einzelwort "pakete"
        if t_lower.strip() in ("pakete", "paket", "sendungen"):
            return {"action": "status"}

        # 3. Weitergeleitete E-Mail erkennen (langer Text mit Trackingnummern)
        if len(t) > 100 and self._RE_PARCEL_TRACKING_NR.search(t):
            # Enthält typische Versand-Keywords?
            mail_kw = ("versand", "versendet", "shipped", "tracking", "sendungsnummer",
                       "lieferung", "bestellung", "order", "dhl", "hermes", "dpd", "ups", "gls")
            if any(k in t_lower for k in mail_kw):
                return {"action": "extract", "text": t}

        return None

    def _detect_marketplace_intent(self, text: str) -> dict | None:
        """Detect marketplace search intent and extract parameters directly."""

        # Vorab-Bereinigung von Chat-Präfixen wie "[you]"
        text_clean = re.sub(r"\[.*?\]", " ", text)
        t = text_clean.lower()

        if not _RE_MP_SEARCH_KW.search(t):
            return None
        if not _RE_MP_MARKET_KW.search(t):
            return None
        # Platform
        platforms = []
        if _RE_PLATFORM_KLEINANZEIGEN.search(t):
            platforms.append("kleinanzeigen")
        if _RE_PLATFORM_EGUN.search(t):
            platforms.append("egun")          # FIX: egun vor ebay prüfen (ebay-Fallback würde sonst greifen)
        if _RE_PLATFORM_TROOSTWIJK.search(t):
            platforms.append("troostwijk")
        if _RE_PLATFORM_ZOLL.search(t):
            platforms.append("zoll_auktion")
        if "vdb" in t:
            platforms.append("vdb")
        if "ebay" in t and "kleinanzeigen" not in t:
            platforms.append("ebay")
        if _RE_PLATFORM_WILLHABEN.search(t):
            platforms.append("willhaben")
        if _RE_PLATFORM_WEB.search(t):
            platforms.append("web")
        if not platforms:
            platforms = ["kleinanzeigen", "ebay"]

        # PLZ (5 Ziffern)
        plz_match = re.search(r"\b(\d{5})\b", text_clean)
        location = plz_match.group(1) if plz_match else None

        # Städtenamen erkennen (Österreich + Deutschland)
        city_match = _RE_CITIES.search(text_clean)
        city_name = _CITY_MAP[city_match.group(1).lower()] if city_match else None

        if not location and city_name:
            location = city_name

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
        query = _RE_PLATFORM_PHRASES.sub(" ", query)
        # .at und .de Domain-Suffixe entfernen
        query = re.sub(r"\.(at|de)\b", " ", query, flags=re.IGNORECASE)
        # PLZ + Stadtname aus Query entfernen
        if plz_match:
            query = query.replace(plz_match.group(1), " ")
        if city_name:
            # Nur den explizit extrahierten Ortsnamen aus der Query entfernen
            query = re.sub(rf"\b{re.escape(city_name)}\b", " ", query, flags=re.IGNORECASE)
        # Radius-Angaben entfernen (z.B. "20km", "20 km")
        query = re.sub(r"\d+\s*km", " ", query, flags=re.IGNORECASE)
        # Stoppwörter entfernen
        query = _RE_STOPWORDS.sub(" ", query)
        # .de Suffix entfernen
        query = re.sub(r"\.de\b", " ", query, flags=re.IGNORECASE)
        # Mehrfache Leerzeichen
        query = re.sub(r"\s+", " ", query).strip(" ,.-")
        # Kaliber fuer VDB aus Query extrahieren
        if "vdb" in platforms:
            _cal_m = re.search(r"(?:im\s+)?kaliber\s+([0-9x.][^\s,;|]{1,15})", query, re.IGNORECASE)
            if _cal_m:
                _cal_str = _cal_m.group(1).strip()
                query = re.sub(r"(?:im\s+)?kaliber\s+[0-9x.][^\s,;|]{0,15}", " ", query, flags=re.IGNORECASE).strip()
                query = query + "|caliber:" + _cal_str

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
            INSTALLER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
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
        if _RE_AGENT_STATUS_KW.search(_t) and _RE_AGENT_NOUN_KW.search(_t):
            handler = self._handlers.get("agent_list")
            if handler:
                log.info("Agent-Status-Shortcut ausgelöst")
                return await handler()

        # Agent-Stop/Start/Remove-Shortcut: "Stopp den Monitor_X", "Lösch den X" etc.
        # Geschützte Agenten (Sicherheitsarchitektur) sind via sa_tools._PROTECTED_AGENTS gesichert
        import re as _re
        _agent_name_match = _re.search(
            r"\b(Monitor_\w+|SearchAssistant|[A-Z][a-zA-Z0-9_]{4,}|[0-9a-f]{6,12})\b", user_input
        )
        if _agent_name_match:
            _agent_name = _agent_name_match.group(1)
            if _RE_AGENT_STOP_KW.search(_t):
                handler = self._handlers.get("agent_stop")
                if handler:
                    log.info("Agent-Stop-Shortcut: %s", _agent_name)
                    return await handler(name=_agent_name)
            elif _RE_AGENT_REMOVE_KW.search(_t):
                handler = self._handlers.get("agent_remove")
                if handler:
                    log.info("Agent-Remove-Shortcut: %s", _agent_name)
                    return await handler(name=_agent_name)
            elif _RE_AGENT_START_KW.search(_t):
                handler = self._handlers.get("agent_start")
                if handler:
                    log.info("Agent-Start-Shortcut: %s", _agent_name)
                    return await handler(name=_agent_name)

        # ── HA-Shortcut: Licht/Schalter ohne LLM ──────────────────────
        # Spart den gesamten LLM-Call für einfache Schalt-Befehle
        _ha_result = await self._ha_shortcut(user_input)
        if _ha_result is not None:
            log.info("HA-Shortcut ausgeführt (kein LLM): %s", _ha_result[:50])
            return _ha_result

        # ── LLM-Discover-Shortcut: Ohne LLM direkt ausführen ─────────
        # Kritisch: Genau wenn alle Cloud-Backends down sind und man neue
        # braucht, ist das lokale Modell zu schwach für Tool-Calling.
        # Deshalb: Regex-basierter Shortcut → direkt llm_discover() aufrufen.
        _t_llm = user_input.lower()
        if _RE_LLM_DISCOVER_KW.search(_t_llm):
            log.info("LLM-Discover-Shortcut ausgeführt (kein LLM nötig)")
            if "llm_discover" in self._handlers:
                result = await self._handlers["llm_discover"]()
                return result
            # Fallback: direkt aus mgmt_tools
            from piclaw.llm.mgmt_tools import build_handlers as _build_llm_h
            _handlers = _build_llm_h(self.llm.registry, self.llm)
            return await _handlers["llm_discover"]()

        # Cron-Agent-Intent: "Erstelle einen Agenten der täglich um X Uhr Y tut"
        _cron_intent = self._detect_cron_agent_intent(user_input)
        if _cron_intent:
            return await self._create_cron_agent(_cron_intent)

        # Netzwerk-Monitor-Intent: "Überwache mein Netzwerk", "neue Geräte erkennen" etc.
        if self._detect_network_monitor_intent(user_input):
            import re as _re2
            _t2 = user_input.lower()
            # Intervall aus Text
            _interval = 300  # default 5 Min
            if any(k in _t2 for k in ("stündlich", "1 stunde", "60 min")):
                _interval = 3600
            elif any(k in _t2 for k in ("10 min", "10min")):
                _interval = 600
            elif any(k in _t2 for k in ("30 min", "30min")):
                _interval = 1800
            _m = _re2.search(r"(\d+)\s*min", _t2)
            if _m:
                _interval = int(_m.group(1)) * 60
            log.info("Netzwerk-Monitor-Intent erkannt, interval=%ds", _interval)
            return await self._create_network_monitor_agent(_interval)

        # Troostwijk Auktions-Monitor: "Überwache neue Auktionen in Deutschland"
        # Muss VOR _detect_monitor_intent geprüft werden (kein Artikel-Query nötig)
        tw_auction_params = self._detect_tw_auction_monitor_intent(user_input)
        if tw_auction_params:
            log.info("TW-Auktions-Monitor-Intent erkannt: %s", tw_auction_params)
            return await self._create_tw_auction_monitor(tw_auction_params)

        # Monitoring-Intent: „Überwache X auf eBay", „Sag mir wenn…" → Sub-Agent erstellen
        monitor_kwargs = self._detect_monitor_intent(user_input)
        if monitor_kwargs:
            log.info("Monitor intent detected: %s", monitor_kwargs)
            return await self._create_monitor_agent(monitor_kwargs)

        # Paket-Tracking-Intent: "Tracke 00340...", "Wo ist mein Paket?", forwarded E-Mail
        _parcel_intent = self._detect_parcel_intent(user_input)
        if _parcel_intent:
            action = _parcel_intent["action"]
            log.info("Parcel-Tracking-Intent erkannt: %s", _parcel_intent)
            if action == "add":
                handler = self._handlers.get("parcel_add")
                if handler:
                    return await handler(
                        tracking_number=_parcel_intent["tracking_number"],
                    )
            elif action == "status":
                handler = self._handlers.get("parcel_status")
                if handler:
                    return await handler()
            elif action == "extract":
                handler = self._handlers.get("parcel_extract")
                if handler:
                    return await handler(text=_parcel_intent["text"])

        # Web-Suche-Shortcut: "wo kaufen/erhältlich" ohne Marktplatz → direkt web_suche
        # Direktimport als Fallback falls Handler-Registry leer (z.B. stiller Import-Fehler)
        if _RE_WEB_BUY_KW.search(user_input) and not _RE_WEB_BUY_NO_MARKET.search(user_input):
            _ws_handler = self._handlers.get("web_suche")
            if _ws_handler is None:
                try:
                    from piclaw.tools.suche import web_suche as _web_suche_fn
                    _ws_handler = lambda **kw: _web_suche_fn(
                        query=kw.get("query", ""), mode=kw.get("mode", "sources")
                    )
                    log.warning("Web-Suche-Shortcut: Handler via Direktimport geladen")
                except Exception as _e:
                    log.error("Web-Suche-Shortcut: Direktimport fehlgeschlagen: %s", _e)
            if _ws_handler is not None:
                log.info("Web-Suche-Shortcut: '%s'", user_input[:60])
                return await _ws_handler(query=user_input, mode="sources")

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

            # Direkt ausführen wenn: query + (location/radius ODER spezifische Plattform genannt)
            _specific_platform = any(
                p in user_input.lower()
                for p in ["willhaben", "kleinanzeigen", "ebay", "egun", "troostwijk", "zoll_auktion"]
            )
            if mp_kwargs.get("query") and (
                mp_kwargs.get("location") or mp_kwargs.get("radius_km") or _specific_platform
            ):
                log.info("Executing marketplace shortcut for: '%s'", mp_kwargs["query"])
                handler = self._handlers.get("marketplace_search")
                if handler:
                    return await handler(**mp_kwargs, notify_all=True)

            # Otherwise delegate
            return await self._delegate_to_search_assistant(user_input)

        # Follow-up detection: "erhöhe", "vergrößer", "erweitere", "nochmal", "zeig mehr"
        if not mp_kwargs and _prev_mp_context:
            followup_kw = (
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
            )
            if any(k in user_input.lower() for k in followup_kw):
                mp_kwargs = dict(_prev_mp_context)
                # Update radius if mentioned
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
                if on_token and step == 0 and not self._tool_defs:
                    # Stream nur wenn KEINE Tools definiert sind (reiner Text-Response).
                    # Mit Tools MUSS chat() genutzt werden, da stream_chat keine
                    # tool_calls zurückgibt und das Modell sonst halluziniert
                    # statt Tools aufzurufen.
                    collected = ""
                    async for token in self.llm.stream_chat(
                        messages, tools=None
                    ):
                        collected += token
                        await on_token(token)
                    from piclaw.llm.base import LLMResponse

                    response = LLMResponse(
                        content=collected, tool_calls=[], finish_reason="stop"
                    )
                    if not response.tool_calls:
                        final_reply = response.content or collected
                        break
                else:
                    # Letzte Runde (keine weiteren Tools erwartet) → streamen wenn möglich
                    _last_step = step > 0 and on_token
                    if _last_step:
                        try:
                            collected = ""
                            async for token in self.llm.stream_chat(messages, tools=self._tool_defs):
                                collected += token
                                await on_token(token)
                            from piclaw.llm.base import LLMResponse as _LLMResponse
                            response = _LLMResponse(content=collected, tool_calls=[], finish_reason="stop")
                        except Exception:
                            # Fallback auf normalen Chat wenn Streaming fehlschlägt
                            response = await self.llm.chat(messages, tools=self._tool_defs)
                    else:
                        response = await self.llm.chat(messages, tools=self._tool_defs)
            except Exception as e:
                self._save_crash("llm_chat", traceback.format_exc())
                return f"❌ LLM error: {e}"

            messages.append(Message(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls if response.tool_calls else None,
            ))

            if not response.tool_calls:
                final_reply = response.content or "(empty response)"
                break

            for call in response.tool_calls:
                log.info("Tool: %s(%s)", call.name, list(call.arguments.keys()))
                # Fortschritt an WebSocket senden – User sieht welches Tool läuft
                if on_token:
                    _tool_label = {
                        "marketplace_search": "🔍 Suche auf Marktplätzen…",
                        "ha_turn_on":         "💡 Schalte ein…",
                        "ha_turn_off":        "💡 Schalte aus…",
                        "ha_set_temperature": "🌡 Setze Temperatur…",
                        "ha_get_state":       "📡 Lese Gerätestatus…",
                        "memory_search":      "🧠 Durchsuche Erinnerungen…",
                        "memory_write":       "💾 Speichere in Gedächtnis…",
                        "shell_exec":         "⚙️ Führe Befehl aus…",
                        "service_status":     "🔧 Prüfe Dienst…",
                        "service_start":      "🔧 Starte Dienst…",
                        "wifi_scan":          "📡 Scanne WLAN…",
                        "check_new_devices":  "🌐 Scanne Netzwerk…",
                        "wake_device":        "⚡ Sende Wake-on-LAN…",
                        "http_get":           "🌐 Lade URL…",
                        "agent_list":         "🤖 Lade Agenten…",
                        "agent_create":       "🤖 Erstelle Agenten…",
                    }.get(call.name, f"⚙️ {call.name}…")
                    await on_token(f"\n`{_tool_label}`\n")
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

    async def boot(self, start_sub_agents: bool = True):
        """Boot LLM router, memory, heartbeat, and sub-agents.

        Args:
            start_sub_agents: Sub-Agenten (Scheduler) starten.
                              False in api.py – der Daemon übernimmt das.
                              True in daemon.py (default).
        """
        log.info(
            "PiClaw Agent v0.15.4 booting (HA + Smart Routing + Health Monitor)..."
        )
        await self.llm.boot()
        self._start_workers()
        self._wire_sa_runner()
        create_background_task(self._boot_memory(), name="memory-boot")
        create_background_task(heartbeat_loop(), name="heartbeat")

        if start_sub_agents:
            # ── Sicherheits-Agenten sicherstellen ──────────────────
            # Monitor_Netzwerk ist geschützt und muss immer laufen.
            # Falls er aus der Registry fehlt (manuelle Bereinigung etc.)
            # wird er automatisch neu angelegt bevor der Scheduler startet.
            from piclaw.agents.sa_tools import _PROTECTED_AGENTS
            for protected_name in _PROTECTED_AGENTS:
                if not self.sa_registry.get(protected_name):
                    log.warning(
                        "Geschützter Agent '%s' fehlt in Registry – wird automatisch neu angelegt.",
                        protected_name
                    )
                    if protected_name == "Monitor_Netzwerk":
                        create_background_task(
                            self._create_network_monitor_agent(300),
                            name="recreate-network-monitor"
                        )

            # Paket-Monitor automatisch anlegen falls nicht vorhanden
            if not self.sa_registry.get("Monitor_Pakete"):
                from piclaw.agents.sa_registry import SubAgentDef
                _parcel_agent = SubAgentDef(
                    name="Monitor_Pakete",
                    description="Paket-Tracking: prüft alle aktiven Pakete auf Statusänderungen",
                    mission="Prüft alle aktiven Pakete auf Statusänderungen",
                    schedule="interval:1800",  # alle 30 Min
                    tools=["parcel_status"],
                    notify=True,
                    direct_tool="parcel_monitor",
                    created_by="auto-boot",
                )
                self.sa_registry.add(_parcel_agent)
                log.info("Monitor_Pakete Sub-Agent automatisch angelegt (30 Min Intervall)")

            create_background_task(self.sa_runner.start_all_scheduled(), name="sa-boot")
            log.info("Sub-agent scheduler started.")
        else:
            log.info("Sub-agent scheduler skipped (managed by daemon).")
        log.info("Soul loaded from %s", soul_mod.get_path())

    async def _boot_memory(self):
        try:
            await self.qmd.setup_collections()
            # embed() wird nicht beim Boot gestartet – zu CPU-intensiv auf Pi
            # Stattdessen: stündlicher Cron-Job
            log.info("QMD setup done – embed deferred to hourly cron")
        except Exception as e:
            log.error("Memory boot failed: %s", e)

    # ── Marketplace Monitor Persistence ──────────────────────────────
    # Persistiert Suchparameter damit direct_tool Handler nach
    # Daemon-Neustart rekonstruiert werden können.





    def start_scheduler(self):
        self.scheduler.start_all()

    def _save_crash(self, ctx: str, tb: str):
        CRASH_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (CRASH_DIR / f"{ts}_{ctx}.txt").write_text(tb)
        log.error("Crash saved: %s_%s.txt", ts, ctx)
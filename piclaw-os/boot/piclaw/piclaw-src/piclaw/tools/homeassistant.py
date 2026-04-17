"""
PiClaw OS – Home Assistant Connector (v0.12)
============================================

Verbindet den PiClaw-Agenten mit einer laufenden Home Assistant Instanz
(auf einem anderen Pi, NAS, oder beliebigem Netzwerkhost).

Features:
  - REST API: Zustände lesen, Services aufrufen, Automationen triggern
  - WebSocket: Echtzeit-Events empfangen (Bewegung, Tür, Temperatur...)
  - Push-Benachrichtigungen: HA-Events → Telegram/Discord/WhatsApp
  - Entity-Discovery: automatische Übersicht aller Geräte und Bereiche
  - Sprachnatürliche Befehle: Agent versteht "Mach das Licht aus"

Konfiguration in config.toml:
  [homeassistant]
  url      = "http://homeassistant.local:8123"
  token    = "eyJ..."   # Long-Lived Access Token aus HA
  notify_on_events = ["motion", "door", "alarm"]   # Push-Events

Long-Lived Token in HA erstellen:
  Profil → Sicherheit → Langlebige Zugriffstoken → Token erstellen
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable, Awaitable

import aiohttp
from piclaw.taskutils import create_background_task

logger = logging.getLogger(__name__)


# ── Konfiguration ─────────────────────────────────────────────────


@dataclass
class HAConfig:
    url: str = "http://homeassistant.local:8123"
    token: str = ""
    verify_ssl: bool = False
    timeout: int = 10
    # Welche Event-Typen sollen als Push-Nachricht weitergeleitet werden
    notify_on_events: list[str] = field(
        default_factory=lambda: [
            "motion_detected",
            "door_opened",
            "alarm_triggered",
            "smoke_detected",
            "flood_detected",
        ]
    )
    # Bereiche/Räume für schnelle Zuweisung
    area_aliases: dict[str, str] = field(default_factory=dict)


# ── Datenmodelle ──────────────────────────────────────────────────


@dataclass
class HAEntity:
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str = ""
    last_updated: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".")[0]

    @property
    def name(self) -> str:
        return self.attributes.get("friendly_name", self.entity_id)

    @property
    def unit(self) -> str:
        return self.attributes.get("unit_of_measurement", "")

    def describe(self) -> str:
        """Menschenlesbare Kurzversion."""
        val = f"{self.state}{self.unit}"
        name = self.name
        extra = []
        if self.domain == "light":
            if self.state == "on":
                bri = self.attributes.get("brightness")
                if bri:
                    extra.append(f"Helligkeit {round(bri / 255 * 100)}%")
                color = self.attributes.get("rgb_color")
                if color:
                    extra.append(f"Farbe RGB{tuple(color)}")
        elif self.domain == "climate":
            current = self.attributes.get("current_temperature")
            target = self.attributes.get("temperature")
            if current:
                extra.append(f"Ist: {current}°C")
            if target:
                extra.append(f"Soll: {target}°C")
        elif self.domain == "media_player":
            media = self.attributes.get("media_title")
            if media:
                extra.append(media)

        suffix = f"  ({', '.join(extra)})" if extra else ""
        return f"{name}: {val}{suffix}"


# ── REST API Client ───────────────────────────────────────────────


class HomeAssistantClient:
    """Async HTTP-Client für die HA REST API."""

    def __init__(self, cfg: HAConfig):
        self.cfg = cfg
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.cfg.token}",
            "Content-Type": "application/json",
        }

    async def _session_(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                ssl=False if not self.cfg.verify_ssl else None
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.cfg.timeout),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Verbindungstest ───────────────────────────────────────────

    async def ping(self) -> tuple[bool, str]:
        """Testet ob HA erreichbar ist. Gibt (ok, version_oder_fehler) zurück."""
        try:
            session = await self._session_()
            async with session.get(
                f"{self.cfg.url}/api/",
                headers=self._headers(),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return True, data.get("version", "OK")
                return False, f"HTTP {r.status}"
        except aiohttp.ClientConnectorError:
            return False, f"Nicht erreichbar: {self.cfg.url}"
        except Exception as e:
            return False, str(e)[:100]

    # ── Zustände lesen ────────────────────────────────────────────

    async def get_state(self, entity_id: str) -> HAEntity | None:
        """Liest den Zustand einer einzelnen Entität."""
        try:
            session = await self._session_()
            async with session.get(
                f"{self.cfg.url}/api/states/{entity_id}",
                headers=self._headers(),
            ) as r:
                if r.status == 404:
                    return None
                r.raise_for_status()
                data = await r.json()
                return HAEntity(
                    entity_id=data["entity_id"],
                    state=data["state"],
                    attributes=data.get("attributes", {}),
                    last_changed=data.get("last_changed", ""),
                    last_updated=data.get("last_updated", ""),
                )
        except Exception as e:
            logger.warning("get_state(%s) Fehler: %s", entity_id, e)
            return None

    async def get_states(
        self,
        domain: str | None = None,
        area: str | None = None,
        limit: int = 50,
    ) -> list[HAEntity]:
        """Liest alle (oder gefilterte) Zustände."""
        try:
            session = await self._session_()
            async with session.get(
                f"{self.cfg.url}/api/states",
                headers=self._headers(),
            ) as r:
                r.raise_for_status()
                items = await r.json()

            entities = [
                HAEntity(
                    entity_id=d["entity_id"],
                    state=d["state"],
                    attributes=d.get("attributes", {}),
                    last_changed=d.get("last_changed", ""),
                )
                for d in items
            ]

            if domain:
                entities = [e for e in entities if e.domain == domain]
            if area:
                # HA speichert area_id im Attribut, alternativ nach Namensmuster filtern
                area_lower = area.lower()
                entities = [
                    e
                    for e in entities
                    if area_lower in e.name.lower()
                    or area_lower in e.entity_id.lower()
                    or area_lower in str(e.attributes.get("area_id", "")).lower()
                ]

            return entities[:limit]
        except Exception as e:
            logger.warning("get_states() Fehler: %s", e)
            return []

    # ── Services aufrufen ─────────────────────────────────────────

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | list[str] | None = None,
        data: dict | None = None,
    ) -> bool:
        """
        Ruft einen HA-Service auf.
        Beispiel: call_service("light", "turn_on", "light.wohnzimmer", {"brightness": 200})
        """
        payload: dict[str, Any] = {}
        if entity_id:
            payload["entity_id"] = entity_id
        if data:
            payload.update(data)

        try:
            session = await self._session_()
            async with session.post(
                f"{self.cfg.url}/api/services/{domain}/{service}",
                headers=self._headers(),
                json=payload,
            ) as r:
                if r.status in (200, 201):
                    logger.info(
                        "HA service %s.%s -> %s: OK", domain, service, entity_id
                    )
                    return True
                text = await r.text()
                logger.warning(
                    "HA service %s.%s Fehler %s: %s",
                    domain,
                    service,
                    r.status,
                    text[:200],
                )
                return False
        except Exception as e:
            logger.error("call_service(%s.%s) Fehler: %s", domain, service, e)
            return False

    # ── Shortcuts für häufige Operationen ─────────────────────────

    async def turn_on(self, entity_id: str, **kwargs) -> bool:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_on", entity_id, kwargs or None)

    async def turn_off(self, entity_id: str) -> bool:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_off", entity_id)

    async def toggle(self, entity_id: str) -> bool:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "toggle", entity_id)

    async def set_temperature(
        self, entity_id: str, temperature: float, hvac_mode: str | None = None
    ) -> bool:
        data: dict[str, Any] = {"temperature": temperature}
        if hvac_mode:
            data["hvac_mode"] = hvac_mode
        return await self.call_service("climate", "set_temperature", entity_id, data)

    async def set_brightness(self, entity_id: str, brightness_pct: int) -> bool:
        return await self.call_service(
            "light",
            "turn_on",
            entity_id,
            {"brightness_pct": max(0, min(100, brightness_pct))},
        )

    async def media_command(self, entity_id: str, command: str) -> bool:
        """command: play_pause | next_track | previous_track | volume_up | volume_down"""
        return await self.call_service("media_player", command, entity_id)

    async def notify(
        self, message: str, title: str = "PiClaw", target: str | None = None
    ) -> bool:
        """Sendet eine Nachricht über HA-Notify (z.B. HA-App auf dem Handy)."""
        service = target or "notify"
        return await self.call_service(
            "notify",
            service,
            data={
                "message": message,
                "title": title,
            },
        )

    async def trigger_automation(self, automation_id: str) -> bool:
        return await self.call_service("automation", "trigger", automation_id)

    async def run_script(self, script_id: str) -> bool:
        return await self.call_service("script", "turn_on", script_id)

    # ── Zusammenfassungen ─────────────────────────────────────────

    async def summary(self, domains: list[str] | None = None) -> str:
        """Erstellt eine kompakte Übersicht aller relevanten Entitäten."""
        watch_domains = domains or [
            "light",
            "switch",
            "climate",
            "sensor",
            "binary_sensor",
            "media_player",
            "cover",
        ]
        lines: list[str] = ["Home Assistant – Übersicht:\n"]

        for domain in watch_domains:
            entities = await self.get_states(domain=domain)
            if not entities:
                continue
            label = {
                "light": "💡 Lichter",
                "switch": "🔌 Schalter",
                "climate": "🌡 Klima",
                "sensor": "📊 Sensoren",
                "binary_sensor": "🚪 Binär-Sensoren",
                "media_player": "🔊 Medien",
                "cover": "🪟 Rollos",
            }.get(domain, domain)
            lines.append(f"  {label}:")
            for e in entities[:8]:
                lines.append(f"    • {e.describe()}")

        return "\n".join(lines) if len(lines) > 1 else "Keine Entitäten gefunden."

    async def get_areas(self) -> list[str]:
        """Gibt bekannte Bereiche/Räume zurück (aus Entity-Attributen)."""
        entities = await self.get_states()
        areas: set[str] = set()
        for e in entities:
            area = e.attributes.get("area_id") or e.attributes.get("room")
            if area:
                areas.add(area)
        return sorted(areas)


# ── WebSocket Event-Listener ──────────────────────────────────────


class HAEventListener:
    """
    Verbindet sich per WebSocket mit HA und leitet Events weiter.
    Ermöglicht Push-Nachrichten: Bewegung erkannt → Telegram.
    """

    def __init__(
        self,
        cfg: HAConfig,
        on_event: Callable[[str, dict], Awaitable[None]],
    ):
        self.cfg = cfg
        self._on_event = on_event
        self._stop = asyncio.Event()
        self._ws = None
        self._msg_id = 1

    async def run(self) -> None:
        """Hauptschleife mit automatischem Reconnect."""
        delay = 5.0
        retries = 0
        while not self._stop.is_set():
            try:
                await self._connect()
                delay = 5.0  # reset on successful connect
                retries = 0
            except Exception as e:
                retries += 1
                log_fn = logger.warning if retries <= 3 else logger.debug
                log_fn(
                    "HA WebSocket Fehler #%d: %s – Retry in %.0fs", retries, e, delay
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, 300)  # max 5 min zwischen retries

    async def _connect(self) -> None:
        ws_url = self.cfg.url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/websocket"

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                ws_url, ssl=None if self.cfg.verify_ssl else False
            ) as ws:
                self._ws = ws
                logger.info("HA WebSocket verbunden: %s", ws_url)

                # Authentifizierung
                auth_req = await ws.receive_json()
                if auth_req.get("type") != "auth_required":
                    raise ValueError(f"Unexpected HA WS message: {auth_req}")

                await ws.send_json({"type": "auth", "access_token": self.cfg.token})
                auth_ok = await ws.receive_json()
                if auth_ok.get("type") != "auth_ok":
                    raise PermissionError(f"HA Auth fehlgeschlagen: {auth_ok}")

                logger.info(
                    "HA WebSocket authentifiziert (HA v%s)",
                    auth_ok.get("ha_version", "?"),
                )

                # State-Change Events abonnieren
                await ws.send_json(
                    {
                        "id": self._msg_id,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }
                )
                self._msg_id += 1

                # Events empfangen
                async for msg in ws:
                    if self._stop.is_set():
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            if data.get("type") == "event":
                                await self._handle_event(data["event"])
                        except Exception as e:
                            logger.debug("HA WS Parse-Fehler: %s", e)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break

    async def _handle_event(self, event: dict) -> None:
        """Filtert Events und leitet relevante weiter."""
        if event.get("event_type") != "state_changed":
            return

        data = event.get("data", {})
        entity = data.get("entity_id", "")
        new_st = data.get("new_state") or {}
        old_st = data.get("old_state") or {}
        new_val = new_st.get("state", "")
        old_val = old_st.get("state", "")

        if new_val == old_val:
            return

        # Prüfe ob dieses Event eine Push-Nachricht auslösen soll
        should_notify = False
        event_type = ""

        # Bewegungsmelder
        if entity.startswith("binary_sensor.") and "motion" in entity:
            if new_val == "on" and "motion_detected" in self.cfg.notify_on_events:
                should_notify = True
                event_type = "motion_detected"

        # Türsensor
        elif entity.startswith("binary_sensor.") and any(
            k in entity for k in ("door", "window", "tuer", "fenster")
        ):
            if new_val == "on" and "door_opened" in self.cfg.notify_on_events:
                should_notify = True
                event_type = "door_opened"

        # Alarm
        elif entity.startswith("alarm_control_panel."):
            if (
                "triggered" in new_val
                and "alarm_triggered" in self.cfg.notify_on_events
            ):
                should_notify = True
                event_type = "alarm_triggered"

        # Rauchmelder
        elif entity.startswith("binary_sensor.") and "smoke" in entity:
            if new_val == "on" and "smoke_detected" in self.cfg.notify_on_events:
                should_notify = True
                event_type = "smoke_detected"

        # Wassermelder
        elif entity.startswith("binary_sensor.") and (
            "flood" in entity or "water" in entity
        ):
            if new_val == "on" and "flood_detected" in self.cfg.notify_on_events:
                should_notify = True
                event_type = "flood_detected"

        if should_notify:
            friendly = new_st.get("attributes", {}).get("friendly_name", entity)
            await self._on_event(
                event_type,
                {
                    "entity_id": entity,
                    "name": friendly,
                    "state": new_val,
                    "old_state": old_val,
                },
            )

    def stop(self) -> None:
        self._stop.set()


# ── Agent-Tools ───────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "ha_get_state",
        "description": (
            "Liest den aktuellen Zustand einer Home Assistant Entität "
            "(Licht, Thermostat, Sensor, Schalter etc.). "
            "Verwende dies um Fragen wie 'Ist das Licht an?' oder "
            "'Wie warm ist es im Wohnzimmer?' zu beantworten."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "HA Entity-ID, z.B. light.wohnzimmer oder sensor.temperatur_bad",
                }
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "ha_list_entities",
        "description": (
            "Listet alle Entitäten eines Typs auf (Lichter, Schalter, Sensoren etc.) "
            "oder alle Entitäten in einem bestimmten Raum/Bereich. "
            "Nützlich um herauszufinden welche Geräte verfügbar sind."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Typ: light, switch, climate, sensor, binary_sensor, media_player, cover, automation, script",
                },
                "area": {
                    "type": "string",
                    "description": "Raum oder Bereich filtern, z.B. 'Wohnzimmer' oder 'Schlafzimmer'",
                },
            },
        },
    },
    {
        "name": "ha_turn_on",
        "description": (
            "Schaltet ein Gerät in Home Assistant ein: Licht, Schalter, etc. "
            "Für Lichter können optional Helligkeit (0-100%) und Farbe angegeben werden."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "Entity-ID des Geräts"},
                "brightness_pct": {
                    "type": "integer",
                    "description": "Helligkeit 0-100 (nur für Lichter)",
                },
                "color_name": {
                    "type": "string",
                    "description": "Farbe auf Englisch: red, blue, green, warm_white etc.",
                },
                "color_temp": {
                    "type": "integer",
                    "description": "Farbtemperatur in Kelvin (2700=warm, 6500=kalt)",
                },
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "ha_turn_off",
        "description": "Schaltet ein Gerät in Home Assistant aus.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "Entity-ID des Geräts"}
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "ha_toggle",
        "description": "Schaltet ein Gerät um (an→aus oder aus→an).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "Entity-ID des Geräts"}
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "ha_set_temperature",
        "description": "Stellt die Zieltemperatur eines Thermostats oder Klimageräts ein.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Entity-ID des Thermostats",
                },
                "temperature": {
                    "type": "number",
                    "description": "Zieltemperatur in °C",
                },
                "hvac_mode": {
                    "type": "string",
                    "description": "Modus: heat, cool, heat_cool, off, auto, fan_only",
                },
            },
            "required": ["entity_id", "temperature"],
        },
    },
    {
        "name": "ha_media",
        "description": "Steuert einen Media Player in HA (Musik, TV, Sonos etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "command": {
                    "type": "string",
                    "description": "play_pause | next_track | previous_track | volume_up | volume_down | media_stop",
                },
            },
            "required": ["entity_id", "command"],
        },
    },
    {
        "name": "ha_summary",
        "description": (
            "Erstellt eine vollständige Übersicht aller Home Assistant Geräte und deren Status. "
            "Nützlich für Fragen wie 'Was läuft gerade?' oder 'Zeig mir alles'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Welche Typen anzeigen, z.B. ['light', 'climate']. Leer = alles.",
                }
            },
        },
    },
    {
        "name": "ha_trigger_automation",
        "description": "Löst eine HA-Automation manuell aus.",
        "input_schema": {
            "type": "object",
            "properties": {
                "automation_id": {
                    "type": "string",
                    "description": "Entity-ID der Automation, z.B. automation.abendmodus",
                }
            },
            "required": ["automation_id"],
        },
    },
    {
        "name": "ha_run_script",
        "description": "Startet ein HA-Skript.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script_id": {
                    "type": "string",
                    "description": "Entity-ID des Skripts, z.B. script.guten_morgen",
                }
            },
            "required": ["script_id"],
        },
    },
    {
        "name": "ha_call_service",
        "description": (
            "Ruft einen beliebigen Home Assistant Service auf. "
            "Verwende dies für fortgeschrittene Aktionen die kein eigenes Tool haben."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service-Domain, z.B. light, climate, notify",
                },
                "service": {
                    "type": "string",
                    "description": "Service-Name, z.B. turn_on, set_temperature",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Ziel-Entität (optional)",
                },
                "data": {"type": "object", "description": "Zusätzliche Service-Daten"},
            },
            "required": ["domain", "service"],
        },
    },
]


async def handle_tool(name: str, params: dict, client: HomeAssistantClient) -> str:
    """Dispatcht einen Tool-Aufruf des LLM an den HA-Client."""

    if not client.cfg.token:
        return "Home Assistant nicht konfiguriert. Bitte HA-URL und Token in der Konfiguration eintragen."

    if name == "ha_get_state":
        entity = await client.get_state(params["entity_id"])
        if entity is None:
            return f"Entität '{params['entity_id']}' nicht gefunden. Tipp: ha_list_entities zum Suchen."
        return entity.describe()

    elif name == "ha_list_entities":
        entities = await client.get_states(
            domain=params.get("domain"),
            area=params.get("area"),
        )
        if not entities:
            return "Keine Entitäten gefunden."
        lines = [f"Entitäten ({len(entities)}):"]
        for e in entities[:20]:
            lines.append(f"  • {e.entity_id}  →  {e.describe()}")
        if len(entities) > 20:
            lines.append(f"  … und {len(entities) - 20} weitere")
        return "\n".join(lines)

    elif name == "ha_turn_on":
        entity_id = params["entity_id"]
        # Fuzzy-Auflösung: wenn kein Punkt → Suche nach friendly_name/entity_id
        if "." not in entity_id:
            matches = await client.get_states(area=entity_id)
            # Nur schaltbare Domains
            matches = [e for e in matches if e.domain in ("light","switch","cover","fan","media_player")]
            if not matches:
                return f"✗ Kein Gerät gefunden für '{entity_id}'. Nutze ha_list_entities um verfügbare Geräte zu sehen."
            entity_id = matches[0].entity_id
        kwargs: dict[str, Any] = {}
        if "brightness_pct" in params:
            kwargs["brightness_pct"] = params["brightness_pct"]
        if "color_name" in params:
            kwargs["color_name"] = params["color_name"]
        if "color_temp" in params:
            kwargs["color_temp_kelvin"] = params["color_temp"]
        ok = await client.turn_on(entity_id, **kwargs)
        return (
            f"✓ {entity_id} eingeschaltet."
            if ok
            else f"✗ Konnte {entity_id} nicht einschalten."
        )

    elif name == "ha_turn_off":
        entity_id = params["entity_id"]
        # Fuzzy-Auflösung
        if "." not in entity_id:
            matches = await client.get_states(area=entity_id)
            matches = [e for e in matches if e.domain in ("light","switch","cover","fan","media_player")]
            if not matches:
                return f"✗ Kein Gerät gefunden für '{entity_id}'. Nutze ha_list_entities um verfügbare Geräte zu sehen."
            entity_id = matches[0].entity_id
        ok = await client.turn_off(entity_id)
        return (
            f"✓ {entity_id} ausgeschaltet."
            if ok
            else f"✗ Konnte {entity_id} nicht ausschalten."
        )

    elif name == "ha_toggle":
        entity_id = params["entity_id"]
        ok = await client.toggle(entity_id)
        if ok:
            state = await client.get_state(entity_id)
            new_state = state.state if state else "?"
            return f"✓ {entity_id} umgeschaltet → jetzt: {new_state}"
        return f"✗ Toggle fehlgeschlagen: {entity_id}"

    elif name == "ha_set_temperature":
        ok = await client.set_temperature(
            params["entity_id"],
            float(params["temperature"]),
            params.get("hvac_mode"),
        )
        temp = params["temperature"]
        return (
            f"✓ Temperatur auf {temp}°C gesetzt."
            if ok
            else "✗ Temperatur konnte nicht gesetzt werden."
        )

    elif name == "ha_media":
        ok = await client.media_command(params["entity_id"], params["command"])
        return (
            f"✓ {params['command']} ausgeführt." if ok else "✗ Befehl fehlgeschlagen."
        )

    elif name == "ha_summary":
        return await client.summary(domains=params.get("domains"))

    elif name == "ha_trigger_automation":
        ok = await client.trigger_automation(params["automation_id"])
        return (
            f"✓ Automation '{params['automation_id']}' ausgelöst."
            if ok
            else "✗ Fehlgeschlagen."
        )

    elif name == "ha_run_script":
        ok = await client.run_script(params["script_id"])
        return (
            f"✓ Skript '{params['script_id']}' gestartet."
            if ok
            else "✗ Fehlgeschlagen."
        )

    elif name == "ha_call_service":
        ok = await client.call_service(
            params["domain"],
            params["service"],
            entity_id=params.get("entity_id"),
            data=params.get("data"),
        )
        label = f"{params['domain']}.{params['service']}"
        return (
            f"✓ Service {label} aufgerufen."
            if ok
            else f"✗ Service {label} fehlgeschlagen."
        )

    return f"Unbekanntes HA-Tool: {name}"


# ── Singleton + Lifecycle ─────────────────────────────────────────

_client: HomeAssistantClient | None = None
_listener: HAEventListener | None = None


def get_client() -> HomeAssistantClient | None:
    return _client


def _make_config() -> HAConfig | None:
    """Liest HA-Konfiguration aus config.toml."""
    try:
        from piclaw.config import CONFIG_FILE
        import tomllib

        if not CONFIG_FILE.exists():
            return None
        with open(CONFIG_FILE, "rb") as f:
            raw = tomllib.load(f)
        ha_raw = raw.get("homeassistant", {})
        if not ha_raw.get("url") and not ha_raw.get("token"):
            return None
        return HAConfig(
            url=ha_raw.get("url", "http://homeassistant.local:8123").rstrip("/"),
            token=ha_raw.get("token", ""),
            verify_ssl=ha_raw.get("verify_ssl", False),
            notify_on_events=ha_raw.get(
                "notify_on_events",
                [
                    "motion_detected",
                    "door_opened",
                    "alarm_triggered",
                    "smoke_detected",
                    "flood_detected",
                ],
            ),
        )
    except Exception as e:
        logger.debug("HA-Config laden: %s", e)
        return None


async def start(
    notify_callback: Callable[[str, str], Awaitable[None]] | None = None,
) -> HomeAssistantClient | None:
    """
    Startet HA-Client und optionalen Event-Listener.
    notify_callback(channel, message) wird bei Push-Events aufgerufen.
    """
    global _client, _listener

    cfg = _make_config()
    if cfg is None or not cfg.token:
        logger.info("Home Assistant nicht konfiguriert – HA-Tools deaktiviert")
        return None

    _client = HomeAssistantClient(cfg)

    # Verbindungstest
    ok, info = await _client.ping()
    if ok:
        logger.info("Home Assistant verbunden: %s (v%s)", cfg.url, info)
    else:
        logger.warning(
            "Home Assistant nicht erreichbar: %s – Tools trotzdem registriert", info
        )

    # Event-Listener starten wenn Callback vorhanden
    if notify_callback and cfg.notify_on_events:

        async def _on_event(event_type: str, data: dict):
            msgs = {
                "motion_detected": f"🚶 Bewegung erkannt: {data.get('name', data['entity_id'])}",
                "door_opened": f"🚪 Geöffnet: {data.get('name', data['entity_id'])}",
                "alarm_triggered": f"🚨 ALARM: {data.get('name', data['entity_id'])} – {data.get('state')}",
                "smoke_detected": f"🔥 RAUCH erkannt: {data.get('name', data['entity_id'])}",
                "flood_detected": f"💧 WASSER erkannt: {data.get('name', data['entity_id'])}",
            }
            msg = msgs.get(event_type, f"HA Event: {event_type} – {data}")
            await notify_callback("all", msg)

        _listener = HAEventListener(cfg, _on_event)
        create_background_task(_listener.run(), name="ha_event_listener")
        logger.info(
            "HA Event-Listener gestartet (%d Event-Typen)", len(cfg.notify_on_events)
        )

    return _client


async def stop():
    if _listener:
        _listener.stop()
    if _client:
        await _client.close()

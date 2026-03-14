"""
PiClaw OS – MQTT Messaging-Adapter (v0.10)

MQTT ist der IoT-Industriestandard. Dieser Adapter verbindet PiClaw
mit einem MQTT-Broker (z.B. Mosquitto, Home Assistant, AWS IoT).

Features:
  - Subscribe auf Topics → Nachrichten an den Agenten
  - Publish: Agent kann auf Topics publizieren
  - Home Assistant Integration: Auto-Discovery + Sensor-Werte
  - QoS 0/1/2 konfigurierbar
  - TLS-Unterstützung
  - Reconnect mit Backoff

Konfiguration in config.toml:
  [mqtt]
  broker   = "homeassistant.local"   # oder IP
  port     = 1883                     # 8883 für TLS
  username = ""
  password = ""
  topic_in  = "piclaw/in"             # Agent empfängt hier
  topic_out = "piclaw/out"            # Agent sendet hier
  ha_discovery = true                 # Home Assistant Auto-Discovery
  tls      = false
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


# ── Konfiguration ────────────────────────────────────────────────
@dataclass
class MqttConfig:
    broker: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    topic_in: str = "piclaw/in"
    topic_out: str = "piclaw/out"
    topic_sensors: str = "piclaw/sensors"
    topic_metrics: str = "piclaw/metrics"
    ha_discovery: bool = True
    ha_prefix: str = "homeassistant"
    client_id: str = "piclaw"
    keepalive: int = 60
    qos: int = 1
    tls: bool = False
    tls_ca_cert: str = ""
    reconnect_min_delay: float = 1.0
    reconnect_max_delay: float = 60.0


# ── Adapter ──────────────────────────────────────────────────────
class MqttAdapter:
    """
    MQTT-Adapter für den PiClaw Messaging-Hub.
    Nutzt aiomqtt (async, modernes API).
    """

    def __init__(self, cfg: MqttConfig, on_message: Callable[[str, str], Awaitable[None]]):
        self.cfg = cfg
        self._on_message = on_message
        self._client = None
        self._connected = False
        self._stop = asyncio.Event()
        self._publish_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._stats = {"rx": 0, "tx": 0, "reconnects": 0, "last_connect": None}

    async def run(self) -> None:
        """Hauptschleife mit automatischem Reconnect."""
        delay = self.cfg.reconnect_min_delay
        while not self._stop.is_set():
            try:
                await self._connect_and_loop()
                delay = self.cfg.reconnect_min_delay  # reset bei Erfolg
            except Exception as e:
                self._connected = False
                logger.warning("MQTT Verbindungsfehler: %s – Retry in %.0fs", e, delay)
                self._stats["reconnects"] += 1
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    break
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.cfg.reconnect_max_delay)

    async def _connect_and_loop(self) -> None:
        try:
            import aiomqtt
        except ImportError:
            logger.error("aiomqtt nicht installiert: pip install aiomqtt")
            await asyncio.sleep(60)
            return

        tls_params = None
        if self.cfg.tls:
            import ssl
            tls_params = aiomqtt.TLSParameters(
                ca_certs=self.cfg.tls_ca_cert or None,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )

        async with aiomqtt.Client(
            hostname=self.cfg.broker,
            port=self.cfg.port,
            username=self.cfg.username or None,
            password=self.cfg.password or None,
            identifier=self.cfg.client_id,
            keepalive=self.cfg.keepalive,
            tls_params=tls_params,
        ) as client:
            self._client = client
            self._connected = True
            self._stats["last_connect"] = int(time.time())
            logger.info("MQTT verbunden: %s:%d", self.cfg.broker, self.cfg.port)

            # Abonnements
            await client.subscribe(self.cfg.topic_in, qos=self.cfg.qos)
            await client.subscribe(f"{self.cfg.topic_in}/+", qos=self.cfg.qos)
            logger.info("MQTT abonniert: %s", self.cfg.topic_in)

            # HA Auto-Discovery veröffentlichen
            if self.cfg.ha_discovery:
                await self._publish_ha_discovery(client)

            # Eingehende Nachrichten + outgoing Queue parallel
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._receive_loop(client))
                tg.create_task(self._send_loop(client))

    async def _receive_loop(self, client) -> None:
        import aiomqtt
        async for message in client.messages:
            try:
                text = message.payload.decode("utf-8")
                topic = str(message.topic)
                logger.debug("MQTT rx [%s]: %s", topic, text[:100])
                self._stats["rx"] += 1

                # JSON-Nachricht parsen falls möglich
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and "text" in data:
                        text = data["text"]
                except json.JSONDecodeError:
                    pass

                await self._on_message(topic, text)
            except Exception as e:
                logger.warning("MQTT Empfangsfehler: %s", e)

    async def _send_loop(self, client) -> None:
        while not self._stop.is_set():
            try:
                topic, payload, qos = await asyncio.wait_for(
                    self._publish_queue.get(), timeout=1.0
                )
                await client.publish(topic, payload=payload, qos=qos)
                self._stats["tx"] += 1
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning("MQTT Send-Fehler: %s", e)

    async def send(self, text: str, topic: str | None = None) -> bool:
        """Sendet eine Nachricht auf das Out-Topic."""
        if not self._connected:
            return False
        target = topic or self.cfg.topic_out
        payload = json.dumps({"text": text, "ts": int(time.time())}, ensure_ascii=False)
        try:
            await asyncio.wait_for(
                self._publish_queue.put((target, payload, self.cfg.qos)),
                timeout=2.0,
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def publish_sensor(self, sensor_name: str, value: float, unit: str = "") -> bool:
        """Publiziert einen Sensorwert auf dem Sensor-Topic."""
        topic = f"{self.cfg.topic_sensors}/{sensor_name}"
        payload = json.dumps({
            "name": sensor_name,
            "value": value,
            "unit": unit,
            "ts": int(time.time()),
        })
        try:
            await asyncio.wait_for(
                self._publish_queue.put((topic, payload, self.cfg.qos)),
                timeout=2.0,
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def publish_metrics(self, metrics: dict[str, float]) -> bool:
        """Publiziert Systemmetriken (CPU, RAM, Temp etc.)."""
        payload = json.dumps({**metrics, "ts": int(time.time())})
        try:
            await asyncio.wait_for(
                self._publish_queue.put((self.cfg.topic_metrics, payload, 0)),
                timeout=2.0,
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def _publish_ha_discovery(self, client) -> None:
        """
        Veröffentlicht Home Assistant MQTT Auto-Discovery Konfigurationen.
        HA erkennt PiClaw dann automatisch als Gerät.
        """
        device = {
            "identifiers": [self.cfg.client_id],
            "name": "PiClaw OS",
            "model": "Raspberry Pi 5",
            "manufacturer": "PiClaw",
            "sw_version": "0.10.0",
        }

        sensors = [
            ("cpu_temp",    "CPU Temperatur",  "temperature",   "°C",  "mdi:thermometer"),
            ("cpu_percent", "CPU Last",         None,           "%",   "mdi:chip"),
            ("ram_percent", "RAM Nutzung",      None,           "%",   "mdi:memory"),
            ("disk_percent","Disk Nutzung",     None,           "%",   "mdi:harddisk"),
        ]

        for sensor_id, name, device_class, unit, icon in sensors:
            config_topic = f"{self.cfg.ha_prefix}/sensor/{self.cfg.client_id}_{sensor_id}/config"
            state_topic = f"{self.cfg.topic_metrics}"
            payload = {
                "name": name,
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.{sensor_id} }}}}",
                "unit_of_measurement": unit,
                "icon": icon,
                "unique_id": f"{self.cfg.client_id}_{sensor_id}",
                "device": device,
            }
            if device_class:
                payload["device_class"] = device_class

            try:
                await client.publish(
                    config_topic,
                    payload=json.dumps(payload),
                    qos=1,
                    retain=True,
                )
            except Exception as e:
                logger.debug("HA Discovery publish fehlgeschlagen: %s", e)

        logger.info("MQTT: Home Assistant Auto-Discovery veröffentlicht")

    def stop(self) -> None:
        self._stop.set()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "connected": self._connected,
            "broker": f"{self.cfg.broker}:{self.cfg.port}",
        }


# ── Fabrik ───────────────────────────────────────────────────────

def create_adapter(config_dict: dict, on_message) -> MqttAdapter | None:
    """Erstellt einen MqttAdapter aus einem Konfigurations-Dict."""
    if not config_dict.get("broker"):
        return None
    cfg = MqttConfig(
        broker=config_dict.get("broker", "localhost"),
        port=int(config_dict.get("port", 1883)),
        username=config_dict.get("username", ""),
        password=config_dict.get("password", ""),
        topic_in=config_dict.get("topic_in", "piclaw/in"),
        topic_out=config_dict.get("topic_out", "piclaw/out"),
        ha_discovery=config_dict.get("ha_discovery", True),
        tls=config_dict.get("tls", False),
        tls_ca_cert=config_dict.get("tls_ca_cert", ""),
    )
    return MqttAdapter(cfg, on_message)

"""
LLM Health Monitor – Selbstheilung für kaputte LLM-Backends.

Läuft stündlich als Background-Task. Erkennt ausgefallene Modelle
und ersetzt sie automatisch durch verfügbare Alternativen.

Heilungs-Logik:
  404 (Modell weg)   → Provider-Modelliste abrufen → bestes Match finden → updaten
  429 (Rate-Limit)   → Priorität temporär senken, nach 1h wieder erhöhen
  500/Timeout        → 3 Fehlschläge → deaktivieren + Notify
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

log = logging.getLogger(__name__)

# Bekannte Provider-Endpunkte für Modell-Discovery
_PROVIDER_MODEL_ENDPOINTS = {
    "api.groq.com":            "https://api.groq.com/openai/v1/models",
    "integrate.api.nvidia.com": "https://integrate.api.nvidia.com/v1/models",
    "api.together.xyz":        "https://api.together.xyz/v1/models",
    "api.cerebras.ai":         "https://api.cerebras.ai/v1/models",
    "api.mistral.ai":          "https://api.mistral.ai/v1/models",
}

# Modell-Präferenzen je Provider (Fallback-Kette)
_PROVIDER_PREFERRED_MODELS = {
    "api.groq.com": [
        "llama-3.3-70b-versatile",
        "llama-3.3-70b-specdec",
        "llama-3.1-70b-versatile",
        "gemma2-9b-it",
    ],
    "integrate.api.nvidia.com": [
        "meta/llama-4-maverick-17b-128e-instruct",
        "meta/llama-4-scout-17b-16e-instruct",
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-70b-instruct",
        "mistralai/mixtral-8x7b-instruct-v0.1",
    ],
}


@dataclass
class BackendHealth:
    name: str
    consecutive_failures: int = 0
    last_error: str = ""
    last_checked: float = 0.0
    rate_limited_until: float = 0.0
    original_priority: int | None = None


class LLMHealthMonitor:
    """
    Überwacht LLM-Backends und repariert sie automatisch.
    """

    def __init__(
        self,
        registry,                           # LLMRegistry Instanz
        multirouter,                        # MultiLLMRouter Instanz
        notify: Callable[[str], Awaitable[None]] | None = None,
        check_interval: int = 3600,        # Sekunden zwischen Checks
        failure_threshold: int = 3,        # Fehlschläge vor Deaktivierung
    ):
        self.registry = registry
        self.router = multirouter
        self.notify = notify
        self.check_interval = check_interval
        self.failure_threshold = failure_threshold
        self._health: dict[str, BackendHealth] = {}
        self._stop = asyncio.Event()

    async def start(self, stop_event: asyncio.Event | None = None):
        """Background-Loop starten."""
        if stop_event:
            self._stop = stop_event
        log.info("LLM Health Monitor gestartet (Interval: %ds)", self.check_interval)
        # Erster Check nach 10 Minuten (Boot abwarten)
        await asyncio.sleep(600)
        while not self._stop.is_set():
            try:
                await self.run_check()
            except Exception as e:
                log.error("Health-Check Fehler: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.check_interval)
                break
            except asyncio.TimeoutError:
                pass

    async def run_check(self):
        """Alle Backends prüfen und ggf. reparieren."""
        backends = self.registry.list_all() if hasattr(self.registry, "list_all") else []
        if not backends:
            return

        log.info("LLM Health-Check: %d Backends", len(backends))
        repaired = []
        deactivated = []

        for backend in backends:
            if not backend.enabled:
                continue

            h = self._health.setdefault(backend.name, BackendHealth(name=backend.name))

            # Rate-Limit-Sperre aufheben wenn Zeit abgelaufen
            if h.rate_limited_until and time.time() > h.rate_limited_until:
                if h.original_priority is not None:
                    self.registry.update(backend.name, priority=h.original_priority)
                    log.info("Backend '%s': Rate-Limit aufgehoben, Priorität wiederhergestellt", backend.name)
                h.rate_limited_until = 0.0
                h.original_priority = None

            # Health-Test
            error_code, error_msg = await self._test_backend(backend)
            h.last_checked = time.time()

            if error_code is None:
                # Gesund – Fehlerzähler zurücksetzen
                if h.consecutive_failures > 0:
                    log.info("Backend '%s': wieder gesund nach %d Fehlern", backend.name, h.consecutive_failures)
                h.consecutive_failures = 0
                h.last_error = ""
                continue

            h.consecutive_failures += 1
            h.last_error = error_msg
            log.warning("Backend '%s': Fehler %s (%d/%d) – %s",
                        backend.name, error_code, h.consecutive_failures,
                        self.failure_threshold, error_msg[:80])

            if error_code == 404:
                # Modell nicht mehr verfügbar → Auto-Repair
                fixed = await self._auto_repair_404(backend)
                if fixed:
                    repaired.append(f"✅ {backend.name}: Modell ersetzt → {fixed}")
                    h.consecutive_failures = 0
                else:
                    deactivated.append(f"⚠️ {backend.name}: Kein Ersatz gefunden, deaktiviert")
                    self.registry.update(backend.name, enabled=False)

            elif error_code == 429:
                # Rate-Limit → Priorität temporär senken
                h.original_priority = h.original_priority or backend.priority
                h.rate_limited_until = time.time() + 3600
                new_prio = max(1, backend.priority - 5)
                self.registry.update(backend.name, priority=new_prio)
                log.info("Backend '%s': Rate-limitiert, Priorität %d→%d für 1h",
                         backend.name, backend.priority, new_prio)

            elif h.consecutive_failures >= self.failure_threshold:
                # Zu viele Fehler → deaktivieren
                self.registry.update(backend.name, enabled=False)
                deactivated.append(f"❌ {backend.name}: Nach {h.consecutive_failures} Fehlern deaktiviert")

        # Telegram-Bericht bei Änderungen
        if repaired or deactivated:
            msg = "🔧 *LLM Health Monitor* – Auto-Repair\n\n"
            if repaired:
                msg += "\n".join(repaired) + "\n"
            if deactivated:
                msg += "\n".join(deactivated) + "\n"
            log.info("Health Monitor: %s", msg.replace("*", ""))
            if self.notify:
                try:
                    await self.notify(msg)
                except Exception as e:
                    log.warning("Health-Monitor Notify: %s", e)

    async def _test_backend(self, backend) -> tuple[int | None, str]:
        """
        Backend testen. Gibt (error_code, message) zurück, oder (None, "") wenn OK.
        """
        try:
            import aiohttp
            from piclaw.llm.base import Message

            url = f"{backend.base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": backend.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            }
            headers = {
                "Authorization": f"Bearer {backend.api_key}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status == 200:
                        return None, ""
                    body = await r.text()
                    return r.status, body[:200]
        except asyncio.TimeoutError:
            return 408, "Timeout"
        except Exception as e:
            return 500, str(e)

    async def _auto_repair_404(self, backend) -> str | None:
        """
        Modell nicht gefunden → Provider-Modelliste abrufen → bestes Replacement wählen.
        Gibt den neuen Modell-Namen zurück oder None.
        """
        import aiohttp
        from urllib.parse import urlparse

        host = urlparse(backend.base_url).netloc
        models_url = _PROVIDER_MODEL_ENDPOINTS.get(host)
        if not models_url:
            log.warning("Auto-Repair: Kein Modell-Endpunkt bekannt für '%s'", host)
            return None

        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    models_url,
                    headers={"Authorization": f"Bearer {backend.api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()

            available = [m["id"] for m in data.get("data", [])]
            if not available:
                return None

            # Preferred list für diesen Provider
            preferred = _PROVIDER_PREFERRED_MODELS.get(host, [])

            # 1. Versuch: Preferred-Liste durchgehen
            for pref in preferred:
                if pref in available:
                    self.registry.update(backend.name, model=pref)
                    log.info("Auto-Repair '%s': %s → %s (preferred list)",
                             backend.name, backend.model, pref)
                    return pref

            # 2. Versuch: Ähnlichkeitssuche (Domain + Größe)
            current = backend.model.lower()
            # Extrahiere Größen-Hint aus aktuellem Modell (70b, 8b, etc.)
            import re
            size_match = re.search(r"(\d+)b", current)
            size_hint = size_match.group(1) if size_match else ""

            # Filtere nach ähnlichen Instruktions-Modellen
            candidates = [
                m for m in available
                if "instruct" in m.lower()
                and (size_hint in m if size_hint else True)
                and "embed" not in m.lower()
                and "vision" not in m.lower()
            ]
            if candidates:
                best = candidates[0]
                self.registry.update(backend.name, model=best)
                log.info("Auto-Repair '%s': %s → %s (similarity match)",
                         backend.name, backend.model, best)
                return best

        except Exception as e:
            log.warning("Auto-Repair '%s' Fehler: %s", backend.name, e)

        return None


# ── Singleton ──────────────────────────────────────────────────────

_monitor: LLMHealthMonitor | None = None


def get_monitor() -> LLMHealthMonitor | None:
    return _monitor


def start_monitor(registry, multirouter, notify=None) -> LLMHealthMonitor:
    global _monitor
    _monitor = LLMHealthMonitor(registry, multirouter, notify=notify)
    return _monitor

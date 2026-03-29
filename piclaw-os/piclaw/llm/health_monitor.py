"""
LLM Health Monitor – Selbstheilung für kaputte LLM-Backends.

v2 (Session 7): Echtzeit-Heilung statt stündlicher Checks.

Kern-Mechanik:
  - Multirouter meldet 429/Fehler in Echtzeit via report_error()
  - Monitor reagiert sofort: Priorität senken, Retry-After parsen
  - Wenn ALLE API-Backends down → Telegram-Alarm
  - Dynamischer Check-Intervall: 5min wenn degraded, 60min wenn gesund
  - Groq TPD-Limit (Tokens per Day): automatisch bis Mitternacht sperren

Heilungs-Logik:
  404 (Modell weg)   → Provider-Modelliste abrufen → bestes Match → updaten
  429 (Rate-Limit)   → Retry-After parsen → Priorität senken → automatisch wiederherstellen
  429 (TPD-Limit)    → Bis Mitternacht UTC sperren → Telegram-Alarm
  500/Timeout        → 3 Fehlschläge → deaktivieren + Notify
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
        "kimi-k2-instruct",
    ],
    "integrate.api.nvidia.com": [
        "meta/llama-4-maverick-17b-128e-instruct",
        "meta/llama-4-scout-17b-16e-instruct",
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-70b-instruct",
        "mistralai/mixtral-8x7b-instruct-v0.1",
    ],
}

# Regex für Groq TPD-Limit Erkennung
_RE_TPD = re.compile(r"tokens per day", re.IGNORECASE)
_RE_RETRY_AFTER = re.compile(r"try again in (\d+)m(\d+(?:\.\d+)?)s", re.IGNORECASE)
_RE_RETRY_SECONDS = re.compile(r"retry.after[\":\s]+(\d+)", re.IGNORECASE)


@dataclass
class BackendHealth:
    name: str
    consecutive_failures: int = 0
    last_error: str = ""
    last_error_code: int = 0
    last_checked: float = 0.0
    rate_limited_until: float = 0.0
    original_priority: int | None = None
    is_tpd_limited: bool = False  # Tokens-per-Day Limit (24h Sperre)


class LLMHealthMonitor:
    """
    Überwacht LLM-Backends und repariert sie automatisch.
    Bietet sowohl periodische Checks als auch Echtzeit-Meldungen.
    """

    # Intervalle
    INTERVAL_HEALTHY = 3600    # 1h wenn alles gut
    INTERVAL_DEGRADED = 300    # 5min wenn Backends degraded
    INITIAL_DELAY = 60         # 1min nach Boot (statt 10min)

    def __init__(
        self,
        registry,                           # LLMRegistry Instanz
        multirouter,                        # MultiLLMRouter Instanz
        notify: Callable[[str], Awaitable[None]] | None = None,
        failure_threshold: int = 3,        # Fehlschläge vor Deaktivierung
    ):
        self.registry = registry
        self.router = multirouter
        self.notify = notify
        self.failure_threshold = failure_threshold
        self._health: dict[str, BackendHealth] = {}
        self._stop = asyncio.Event()
        self._all_api_down_notified = False  # Nur einmal benachrichtigen

    # ── Echtzeit-Meldung vom Multirouter ──────────────────────────

    def report_error(self, backend_name: str, error_code: int, error_msg: str):
        """
        Wird vom Multirouter aufgerufen wenn ein Backend einen Fehler liefert.
        Reagiert SOFORT statt auf den nächsten Check-Zyklus zu warten.
        """
        h = self._health.setdefault(backend_name, BackendHealth(name=backend_name))
        h.consecutive_failures += 1
        h.last_error = error_msg[:200]
        h.last_error_code = error_code

        if error_code == 429:
            self._handle_rate_limit(backend_name, error_msg)

        # Prüfen ob ALLE API-Backends jetzt down sind
        self._check_all_backends_down()

    def report_success(self, backend_name: str):
        """Backend hat erfolgreich geantwortet."""
        h = self._health.get(backend_name)
        if h and h.consecutive_failures > 0:
            log.info("Backend '%s': wieder gesund nach %d Fehlern",
                     backend_name, h.consecutive_failures)
            h.consecutive_failures = 0
            h.last_error = ""
            h.last_error_code = 0
            self._all_api_down_notified = False

    # ── 429 Handling ──────────────────────────────────────────────

    def _handle_rate_limit(self, backend_name: str, error_msg: str):
        """Analysiert 429 Error und setzt passende Sperre."""
        h = self._health[backend_name]
        backend = self.registry.get(backend_name)
        if not backend:
            return

        # Retry-After aus Header/Body parsen
        retry_seconds = self._parse_retry_after(error_msg)

        # TPD-Limit erkennen (Groq: "tokens per day")
        if _RE_TPD.search(error_msg):
            h.is_tpd_limited = True
            # Bis Mitternacht UTC + 5min Puffer sperren
            now = datetime.utcnow()
            midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=5, second=0, microsecond=0
            )
            retry_seconds = max(retry_seconds, (midnight - now).total_seconds())
            log.warning(
                "Backend '%s': TPD-Limit erreicht – gesperrt bis %s UTC (%.0fmin)",
                backend_name, midnight.strftime("%H:%M"), retry_seconds / 60
            )
        else:
            h.is_tpd_limited = False

        # Sperre setzen
        h.rate_limited_until = time.time() + retry_seconds
        h.original_priority = h.original_priority or backend.priority

        # Priorität auf 0 senken (wird bei Recovery wiederhergestellt)
        self.registry.update(backend_name, priority=0)
        log.info(
            "Backend '%s': Rate-limitiert, Priorität %d→0 für %.0fmin",
            backend_name, backend.priority, retry_seconds / 60
        )

        # Telegram wenn TPD-Limit
        if h.is_tpd_limited and self.notify:
            hours_left = retry_seconds / 3600
            msg = (
                f"⚠️ *LLM Health Monitor*\n\n"
                f"Backend `{backend_name}` hat das **Tages-Token-Limit** erreicht.\n"
                f"Modell: `{backend.model}`\n"
                f"Sperre: ~{hours_left:.1f}h (bis Mitternacht UTC)\n"
                f"Andere Backends übernehmen automatisch."
            )
            asyncio.ensure_future(self._safe_notify(msg))

    def _parse_retry_after(self, error_msg: str) -> float:
        """Extrahiert Retry-After Sekunden aus Fehlermeldung."""
        # Format: "try again in 5m45.6s"
        m = _RE_RETRY_AFTER.search(error_msg)
        if m:
            minutes = int(m.group(1))
            seconds = float(m.group(2))
            return minutes * 60 + seconds

        # Format: "retry-after: 360" (Header-Wert)
        m = _RE_RETRY_SECONDS.search(error_msg)
        if m:
            return float(m.group(1))

        # Default: 10 Minuten
        return 600

    # ── Alle Backends down? ──────────────────────────────────────

    def _check_all_backends_down(self):
        """Prüft ob ALLE API-Backends ausgefallen sind und warnt."""
        if self._all_api_down_notified:
            return

        all_backends = self.registry.list_all() if hasattr(self.registry, "list_all") else []
        api_backends = [b for b in all_backends if b.provider not in ("local",)]

        if not api_backends:
            return

        all_down = all(
            self._health.get(b.name, BackendHealth(b.name)).consecutive_failures >= 1
            or self._health.get(b.name, BackendHealth(b.name)).rate_limited_until > time.time()
            for b in api_backends
        )

        if all_down and self.notify:
            self._all_api_down_notified = True
            status_lines = []
            for b in api_backends:
                h = self._health.get(b.name, BackendHealth(b.name))
                if h.rate_limited_until > time.time():
                    remaining = (h.rate_limited_until - time.time()) / 60
                    reason = "TPD-Limit" if h.is_tpd_limited else "Rate-Limit"
                    status_lines.append(f"  ⏳ `{b.name}`: {reason} (~{remaining:.0f}min)")
                elif h.consecutive_failures > 0:
                    status_lines.append(f"  ❌ `{b.name}`: {h.consecutive_failures}x Fehler")
                else:
                    status_lines.append(f"  ⬜ `{b.name}`: unbekannt")

            msg = (
                "🚨 *LLM Health Monitor – ALLE API-Backends down!*\n\n"
                + "\n".join(status_lines) + "\n\n"
                "⚙️ Lokales Modell (gemma-2b) übernimmt.\n"
                "Tool-Calling ist eingeschränkt.\n"
                "Backends werden automatisch wiederhergestellt."
            )
            asyncio.ensure_future(self._safe_notify(msg))
            log.warning("ALLE API-Backends ausgefallen – lokaler Fallback aktiv")

    # ── Background Loop ──────────────────────────────────────────

    async def start(self, stop_event: asyncio.Event | None = None):
        """Background-Loop starten."""
        if stop_event:
            self._stop = stop_event
        log.info("LLM Health Monitor gestartet (Interval: dynamisch)")
        await asyncio.sleep(self.INITIAL_DELAY)
        while not self._stop.is_set():
            try:
                await self.run_check()
            except Exception as e:
                log.error("Health-Check Fehler: %s", e)

            # Dynamischer Intervall: schneller wenn Backends degraded
            interval = self._current_interval()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    def _current_interval(self) -> int:
        """Gibt den aktuellen Check-Intervall zurück (dynamisch)."""
        # Wenn Backends rate-limited oder fehlerhaft → schneller prüfen
        for h in self._health.values():
            if h.rate_limited_until > time.time():
                return self.INTERVAL_DEGRADED
            if h.consecutive_failures >= 1:
                return self.INTERVAL_DEGRADED
        return self.INTERVAL_HEALTHY

    async def run_check(self):
        """Alle Backends prüfen und ggf. reparieren."""
        backends = self.registry.list_all() if hasattr(self.registry, "list_all") else []
        if not backends:
            return

        log.info("LLM Health-Check: %d Backends", len(backends))
        repaired = []
        deactivated = []
        recovered = []

        for backend in backends:
            h = self._health.setdefault(backend.name, BackendHealth(name=backend.name))

            # ── Rate-Limit Recovery ────────────────────────────────
            if h.rate_limited_until and time.time() > h.rate_limited_until:
                if h.original_priority is not None:
                    self.registry.update(backend.name, priority=h.original_priority)
                    log.info(
                        "Backend '%s': Rate-Limit abgelaufen, Priorität %d wiederhergestellt",
                        backend.name, h.original_priority
                    )
                    recovered.append(
                        f"✅ `{backend.name}`: Rate-Limit abgelaufen – wiederhergestellt (Prio {h.original_priority})"
                    )
                h.rate_limited_until = 0.0
                h.original_priority = None
                h.is_tpd_limited = False
                h.consecutive_failures = 0
                self._all_api_down_notified = False

                # Re-enable falls deaktiviert
                if not backend.enabled:
                    self.registry.update(backend.name, enabled=True)
                    log.info("Backend '%s': Re-enabled nach Rate-Limit Recovery", backend.name)

            # Noch rate-limited? Nicht erneut testen.
            if h.rate_limited_until > time.time():
                remaining = (h.rate_limited_until - time.time()) / 60
                log.debug("Backend '%s': noch %.0fmin rate-limited", backend.name, remaining)
                continue

            if not backend.enabled:
                continue

            # ── Health-Test ─────────────────────────────────────────
            error_code, error_msg = await self._test_backend(backend)
            h.last_checked = time.time()

            if error_code is None:
                if h.consecutive_failures > 0:
                    log.info("Backend '%s': wieder gesund nach %d Fehlern",
                             backend.name, h.consecutive_failures)
                    recovered.append(f"✅ `{backend.name}`: wieder erreichbar")
                h.consecutive_failures = 0
                h.last_error = ""
                continue

            h.consecutive_failures += 1
            h.last_error = error_msg
            log.warning("Backend '%s': Fehler %s (%d/%d) – %s",
                        backend.name, error_code, h.consecutive_failures,
                        self.failure_threshold, error_msg[:80])

            if error_code == 404:
                fixed = await self._auto_repair_404(backend)
                if fixed:
                    repaired.append(f"🔧 `{backend.name}`: Modell ersetzt → `{fixed}`")
                    h.consecutive_failures = 0
                else:
                    deactivated.append(f"⚠️ `{backend.name}`: Kein Ersatz gefunden, deaktiviert")
                    self.registry.update(backend.name, enabled=False)

            elif error_code == 429:
                self._handle_rate_limit(backend.name, error_msg)

            elif h.consecutive_failures >= self.failure_threshold:
                self.registry.update(backend.name, enabled=False)
                deactivated.append(
                    f"❌ `{backend.name}`: Nach {h.consecutive_failures} Fehlern deaktiviert"
                )

        # Telegram-Bericht bei Änderungen
        changes = repaired + recovered + deactivated
        if changes:
            msg = "🔧 *LLM Health Monitor*\n\n" + "\n".join(changes)
            log.info("Health Monitor: %s", msg.replace("*", "").replace("`", ""))
            await self._safe_notify(msg)

    async def _test_backend(self, backend) -> tuple[int | None, str]:
        """Backend testen. Gibt (error_code, message) oder (None, "") wenn OK."""
        try:
            import aiohttp

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
                    return r.status, body[:300]
        except asyncio.TimeoutError:
            return 408, "Timeout"
        except Exception as e:
            return 500, str(e)

    async def _auto_repair_404(self, backend) -> str | None:
        """Modell nicht gefunden → Provider-Modelliste → bestes Replacement."""
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

            preferred = _PROVIDER_PREFERRED_MODELS.get(host, [])

            # 1. Preferred-Liste
            for pref in preferred:
                if pref in available:
                    self.registry.update(backend.name, model=pref)
                    log.info("Auto-Repair '%s': %s → %s (preferred)",
                             backend.name, backend.model, pref)
                    return pref

            # 2. Ähnlichkeitssuche
            current = backend.model.lower()
            size_match = re.search(r"(\d+)b", current)
            size_hint = size_match.group(1) if size_match else ""

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
                log.info("Auto-Repair '%s': %s → %s (similarity)",
                         backend.name, backend.model, best)
                return best

        except Exception as e:
            log.warning("Auto-Repair '%s' Fehler: %s", backend.name, e)

        return None

    async def _safe_notify(self, msg: str):
        """Telegram-Benachrichtigung mit Error-Handling."""
        if self.notify:
            try:
                await self.notify(msg)
            except Exception as e:
                log.warning("Health-Monitor Notify: %s", e)

    # ── Status für API/Dashboard ─────────────────────────────────

    def status_dict(self) -> dict:
        """Status aller Backends für Dashboard."""
        result = {}
        for name, h in self._health.items():
            remaining = max(0, h.rate_limited_until - time.time()) if h.rate_limited_until else 0
            result[name] = {
                "failures": h.consecutive_failures,
                "last_error": h.last_error[:80],
                "rate_limited": remaining > 0,
                "rate_limited_minutes": round(remaining / 60, 1),
                "is_tpd_limited": h.is_tpd_limited,
            }
        return result


# ── Singleton ──────────────────────────────────────────────────────

_monitor: LLMHealthMonitor | None = None


def get_monitor() -> LLMHealthMonitor | None:
    return _monitor


def start_monitor(registry, multirouter, notify=None) -> LLMHealthMonitor:
    global _monitor
    _monitor = LLMHealthMonitor(registry, multirouter, notify=notify)
    return _monitor

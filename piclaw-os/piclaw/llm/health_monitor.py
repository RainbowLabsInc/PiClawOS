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

from piclaw.taskutils import create_background_task
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Awaitable

log = logging.getLogger(__name__)

# ── KOSTENLOSE MODELLE – WHITELIST ────────────────────────────────────────────
# ⚠️  NUR Modelle die auf dem jeweiligen Free-Tier OHNE KOSTEN nutzbar sind.
#     Dameon darf NIEMALS kostenpflichtige Modelle/Abos nutzen.
#     Bei Änderungen: Prüfen ob das Modell wirklich kostenlos ist!
# ──────────────────────────────────────────────────────────────────────────────

# Bekannte Provider-Endpunkte für Modell-Discovery
_PROVIDER_MODEL_ENDPOINTS = {
    "api.groq.com":             "https://api.groq.com/openai/v1/models",
    "integrate.api.nvidia.com": "https://integrate.api.nvidia.com/v1/models",
    "api.cerebras.ai":          "https://api.cerebras.ai/v1/models",
    "openrouter.ai":            "https://openrouter.ai/api/v1/models",
    # Together.ai: $5 Startguthaben, danach kostenpflichtig → NICHT enthalten
    # Mistral: Free-Tier limitiert, paid by default → NICHT enthalten
}

# ── Provider-Signup-URLs für autonome Schlüssel-Suche (v0.16) ──────────────
# Format: {host: (signup_url, key_env_name, free_tier_info)}
_PROVIDER_SIGNUP_URLS = {
    "api.groq.com": (
        "https://console.groq.com/keys",
        "GROQ_API_KEY",
        "Kostenlos: 30 req/min, 6000 req/Tag für llama-3.3-70b-versatile",
    ),
    "integrate.api.nvidia.com": (
        "https://build.nvidia.com",
        "NVIDIA_API_KEY",
        "Kostenlos: 1000 req/Tag für llama-4-maverick und llama-3.3-70b",
    ),
    "api.cerebras.ai": (
        "https://cloud.cerebras.ai",
        "CEREBRAS_API_KEY",
        "Kostenlos: Developer-Tier, 8k req/Tag",
    ),
    "openrouter.ai": (
        "https://openrouter.ai/keys",
        "OPENROUTER_API_KEY",
        "Kostenlos: Rate-Limit je Modell, einige Modelle permanent kostenlos",
    ),
}

# Nur Modelle die NACHWEISLICH KOSTENLOS sind (Free-Tier)
# Wird von Auto-Discovery und Auto-Repair als Whitelist verwendet
# Letzte Aktualisierung: April 2026
_FREE_TIER_MODELS = {
    "api.groq.com": [
        # Groq Free Tier: Rate-Limits, aber keine Kosten
        "openai/gpt-oss-120b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3-32b",
        "llama-3.3-70b-versatile",
        "llama-3.3-70b-specdec",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
        "kimi-k2-instruct",
    ],
    "integrate.api.nvidia.com": [
        # NVIDIA NIM: Free-Tier mit 1000 Requests/Tag
        "meta/llama-4-maverick-17b-128e-instruct",
        "meta/llama-4-scout-17b-16e-instruct",
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-70b-instruct",
        "mistralai/mixtral-8x7b-instruct-v0.1",
        "deepseek-ai/deepseek-r1",
    ],
    "api.cerebras.ai": [
        # Cerebras: Kostenloser Developer-Tier, extrem schnell
        "llama-3.3-70b",
        "llama-3.1-8b",
        "llama-4-scout-17b-16e",
    ],
    "openrouter.ai": [
        # OpenRouter: Einige Modelle permanent kostenlos
        "meta-llama/llama-3.3-70b-instruct:free",
        "microsoft/phi-3-medium-128k-instruct:free",
        "google/gemma-2-9b-it:free",
        "mistralai/mistral-7b-instruct:free",
        "deepseek/deepseek-r1:free",
    ],
}

# Rückwärts-kompatibel: _PROVIDER_PREFERRED_MODELS = _FREE_TIER_MODELS
_PROVIDER_PREFERRED_MODELS = _FREE_TIER_MODELS

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
        self._warned_no_notification_email = False  # AgentMail-Backup: nur 1× warnen
        self._last_discovery_time: float = 0.0  # Unix-Timestamp der letzten Discovery
        self.DISCOVERY_INTERVAL = 86400  # 24h – proaktive Discovery

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
            # Bis Mitternacht UTC + 5min Puffer sperren.
            # datetime.utcnow() ist seit Python 3.12 deprecated →
            # datetime.now(timezone.utc) ist die korrekte, aware Alternative.
            from datetime import timezone as _tz
            now = datetime.now(_tz.utc).replace(tzinfo=None)  # naive UTC für Arithmetik
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
            create_background_task(self._safe_notify(msg), name="llm-notify")

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

    # ── Alle Backends down? → Auto-Discovery ───────────────────

    def _check_all_backends_down(self):
        """Prüft ob ALLE API-Backends ausgefallen sind → startet Auto-Discovery."""
        all_backends = self.registry.list_all() if hasattr(self.registry, "list_all") else []
        # Nur aktivierte Backends zählen – deaktivierte haben 0 Fehler und
        # würden sonst fälschlicherweise als "up" gewertet.
        api_backends = [b for b in all_backends if b.provider not in ("local",) and b.enabled]

        if not api_backends:
            return

        all_down = all(
            self._health.get(b.name, BackendHealth(b.name)).consecutive_failures >= 1
            or self._health.get(b.name, BackendHealth(b.name)).rate_limited_until > time.time()
            for b in api_backends
        )

        if all_down:
            # Auto-Discovery starten (async, im Hintergrund)
            create_background_task(self._auto_discover_backends(api_backends), name="llm-auto-discover")

            if not self._all_api_down_notified and self.notify:
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
                    "🔍 Auto-Discovery läuft – suche alternative Backends..."
                )
                create_background_task(self._safe_notify(msg), name="llm-notify")
                log.warning("ALLE API-Backends ausgefallen – Auto-Discovery gestartet")

    # ── Auto-Discovery: Neue Backends auf bekannten Providern finden ──

    async def _auto_discover_backends(self, down_backends):
        """
        Wenn alle Backends down sind: Auf bekannten Providern nach
        alternativen Modellen suchen und automatisch registrieren.

        Strategie:
          1. Provider mit API-Key gruppieren
          2. Für jeden Provider: verfügbare Modelle abrufen
          3. Modelle testen die wir noch NICHT nutzen
          4. Funktionierende als neue Backends registrieren
          5. Telegram-Meldung
        """
        from urllib.parse import urlparse

        # API-Keys nach Provider-Host gruppieren
        provider_keys: dict[str, tuple[str, str]] = {}  # host → (api_key, base_url)
        for b in down_backends:
            if not b.base_url or not b.api_key:
                continue
            host = urlparse(b.base_url).netloc
            if host not in provider_keys:
                provider_keys[host] = (b.api_key, b.base_url)

        if not provider_keys:
            log.info("Auto-Discovery: Keine Provider mit API-Keys gefunden")
            return

        # Aktuell genutzte Modelle sammeln (um Duplikate zu vermeiden)
        used_models = {b.model for b in down_backends}

        # Provider-spezifische Rate-Limits prüfen
        # Wenn ALLE Backends eines Providers TPD-limitiert sind, überspringe den Provider
        tpd_hosts = set()
        for b in down_backends:
            h = self._health.get(b.name, BackendHealth(b.name))
            if h.is_tpd_limited:
                host = urlparse(b.base_url).netloc
                tpd_hosts.add(host)

        discovered = []

        for host, (api_key, base_url) in provider_keys.items():
            # Provider komplett TPD-limitiert → überspringen
            if host in tpd_hosts:
                log.info("Auto-Discovery: %s übersprungen (TPD-Limit auf allen Modellen)", host)
                continue

            models_url = _PROVIDER_MODEL_ENDPOINTS.get(host)
            if not models_url:
                continue

            log.info("Auto-Discovery: Prüfe %s...", host)

            try:
                available = await self._fetch_available_models(models_url, api_key)
                if not available:
                    continue

                # ⚠️ NUR Modelle aus der FREE_TIER_MODELS Whitelist!
                # Niemals unbekannte Modelle registrieren – die könnten kosten.
                whitelist = _FREE_TIER_MODELS.get(host, [])
                candidates = [
                    m for m in whitelist
                    if m not in used_models and m in available
                ]

                if not candidates:
                    log.info("Auto-Discovery %s: keine freien ungenutzten Modelle", host)
                    continue

                # Kandidaten testen
                for model in candidates:
                    if model not in available:
                        continue

                    ok = await self._test_model(base_url, api_key, model)
                    if ok:
                        # Neues Backend registrieren – NUR Free-Tier Modelle!
                        new_name = self._generate_backend_name(host, model)
                        from piclaw.llm.registry import BackendConfig
                        new_backend = BackendConfig(
                            name=new_name,
                            provider="openai",  # Alle bekannten Provider sind OpenAI-kompatibel
                            model=model,
                            api_key=api_key,
                            base_url=base_url,
                            tags=["general", "auto-discovered", "free-tier"],
                            priority=6,  # Mittlere Priorität
                            temperature=0.7,
                            notes=f"Auto-discovered (FREE TIER) by Health Monitor ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
                        )
                        self.registry.add(new_backend)
                        discovered.append((new_name, model, host))
                        log.info(
                            "Auto-Discovery: ✅ Neues Backend '%s' registriert (%s auf %s)",
                            new_name, model, host
                        )
                        # Ein funktionierendes Backend pro Provider reicht
                        break

            except Exception as e:
                log.warning("Auto-Discovery %s Fehler: %s", host, e)

        # Telegram-Meldung
        if discovered:
            lines = [f"🔍 *LLM Auto-Discovery* – {len(discovered)} Backend(s) gefunden!\n"]
            for name, model, host in discovered:
                lines.append(f"  ✅ `{name}`: `{model}`\n     Provider: {host}")
            lines.append("\nDiese Backends übernehmen automatisch.")
            await self._safe_notify("\n".join(lines))
            self._all_api_down_notified = False  # Reset – wir haben jetzt Alternativen
        else:
            log.info("Auto-Discovery: Keine neuen Backends gefunden – prüfe neue Provider")
            # Keine Alternativen auf bestehenden Providern → neue Provider vorschlagen
            await self._suggest_new_providers(provider_keys)

    async def _fetch_available_models(self, models_url: str, api_key: str) -> list[str]:
        """Ruft die Modell-Liste eines Providers ab."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    models_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            log.debug("Model list fetch failed: %s", e)
            return []

    async def _test_model(self, base_url: str, api_key: str, model: str) -> bool:
        """Testet ob ein spezifisches Modell auf einem Provider funktioniert."""
        import aiohttp
        try:
            url = f"{base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with: OK"}],
                "max_tokens": 5,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        return True
                    body = await r.text()
                    log.debug("Model test %s: HTTP %d – %s", model, r.status, body[:100])
                    return False
        except Exception as e:
            log.debug("Model test %s failed: %s", model, e)
            return False

    def _generate_backend_name(self, host: str, model: str) -> str:
        """Generiert einen eindeutigen Backend-Namen."""
        # "api.groq.com" + "kimi-k2-instruct" → "auto-groq-kimi-k2"
        provider_short = {
            "api.groq.com": "groq",
            "integrate.api.nvidia.com": "nvidia",
            "api.together.xyz": "together",
            "api.cerebras.ai": "cerebras",
            "api.mistral.ai": "mistral",
        }.get(host, host.split(".")[0])

        model_short = model.split("/")[-1][:20]  # Letzter Teil, max 20 Zeichen
        name = f"auto-{provider_short}-{model_short}"
        # Duplikate vermeiden
        if self.registry.get(name):
            name += f"-{int(time.time()) % 10000}"
        return name

    # ── Provider-Vorschläge ──────────────────────────────────────

    # ⚠️  NUR Provider die NACHWEISLICH KOSTENLOS sind (kein Startguthaben,
    #     kein automatisches Upgrade, kein Abo).
    #     Together.ai ($5 Credit → danach kostenpflichtig) → NICHT enthalten
    #     Mistral (Free-Tier unklar, paid-by-default) → NICHT enthalten
    _FREE_PROVIDERS = {
        "groq": {
            "host": "api.groq.com",
            "name": "Groq",
            "signup": "https://console.groq.com",
            "free_tier": "100k Tokens/Tag, 30 RPM – dauerhaft kostenlos",
        },
        "nvidia": {
            "host": "integrate.api.nvidia.com",
            "name": "NVIDIA NIM",
            "signup": "https://build.nvidia.com",
            "free_tier": "1000 Requests/Tag – dauerhaft kostenlos",
        },
        "cerebras": {
            "host": "api.cerebras.ai",
            "name": "Cerebras",
            "signup": "https://cloud.cerebras.ai",
            "free_tier": "Llama 3.3 70B, extrem schnell – dauerhaft kostenlos",
        },
    }

    async def _suggest_new_providers(self, existing_hosts: dict):
        """Schlägt neue Provider vor wenn auf bestehenden nichts mehr geht."""
        # Welche Provider sind NICHT konfiguriert?
        existing_set = set(existing_hosts.keys())
        missing = []
        for key, info in self._FREE_PROVIDERS.items():
            if info["host"] not in existing_set:
                missing.append(info)

        if not missing:
            log.info("Alle bekannten Provider sind bereits konfiguriert")
            return

        # Vorschlag via Telegram + AgentMail
        lines = [
            "🔑 *LLM Health Monitor – Neue Provider verfügbar*\n",
            "Alle bestehenden Backends sind erschöpft.",
            f"Es gibt {len(missing)} Provider die du noch nicht nutzt:\n",
        ]
        for p in missing:
            lines.append(f"  🆓 *{p['name']}* – {p['free_tier']}")
            lines.append(f"     Anmeldung: {p['signup']}")

        lines.append("\nDu kannst dich anmelden und den API-Key hinzufügen:")
        lines.append("`piclaw llm add` oder via Dashboard.")
        lines.append("\n⚠️ *NUR kostenlose Free-Tier nutzen – KEIN Abo abschließen!*")

        # Wenn AgentMail konfiguriert, kann Dameon bei der Anmeldung helfen
        try:
            from piclaw.config import load as _cfg_load
            _cfg = _cfg_load()
            if _cfg.agentmail.email_address:
                lines.append(f"\n📧 Dameons E-Mail: `{_cfg.agentmail.email_address}`")
                lines.append("Du kannst diese E-Mail bei der Registrierung verwenden.")
        except Exception:
            pass

        await self._safe_notify("\n".join(lines))

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
                # Status für API-Prozess in Datei schreiben (Cross-Prozess-Kommunikation)
                try:
                    from piclaw.llm.health_monitor import write_status_file
                    await asyncio.to_thread(write_status_file, self)
                except Exception as _wse:
                    log.debug("Status-Datei schreiben: %s", _wse)
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

        # ── Auto-Discovery Cleanup ─────────────────────────────────
        # Wenn Original-Backends wieder gesund sind, auto-discovered entfernen
        if recovered:
            auto_backends = [
                b for b in backends
                if b.name.startswith("auto-") and "auto-discovered" in b.tags
            ]
            original_healthy = any(
                not b.name.startswith("auto-")
                and b.enabled
                and self._health.get(b.name, BackendHealth(b.name)).consecutive_failures == 0
                and self._health.get(b.name, BackendHealth(b.name)).rate_limited_until <= time.time()
                for b in backends
                if b.provider != "local"
            )
            if original_healthy and auto_backends:
                for ab in auto_backends:
                    self.registry.remove(ab.name)
                    self._health.pop(ab.name, None)
                    log.info("Auto-Cleanup: '%s' entfernt (Original-Backend wieder gesund)", ab.name)
                await self._safe_notify(
                    f"🧹 *Auto-Cleanup*: {len(auto_backends)} temporäre Backend(s) entfernt – "
                    f"Original-Backends wieder verfügbar."
                )

        # ── Proaktive Discovery (täglich) ──────────────────────────
        # Nicht nur bei Ausfällen, sondern regelmäßig nach neuen Free-Tier-Modellen suchen
        if time.time() - self._last_discovery_time > self.DISCOVERY_INTERVAL:
            self._last_discovery_time = time.time()
            create_background_task(
                self._proactive_discovery(), name="llm-proactive-discovery"
            )

    async def _proactive_discovery(self):
        """
        Läuft täglich: Prüft alle bekannten Provider auf neue kostenlose Modelle.
        Registriert neue Modelle automatisch mit niedriger Priorität.
        Benachrichtigt über Telegram wenn neue Modelle gefunden wurden.
        """
        log.info("Proaktive LLM-Discovery gestartet")
        from urllib.parse import urlparse

        all_backends = self.registry.list_all() if hasattr(self.registry, "list_all") else []
        used_models = {b.model for b in all_backends}
        used_names = {b.name for b in all_backends}

        # API-Keys nach Provider-Host gruppieren
        provider_keys: dict[str, tuple[str, str]] = {}
        for b in all_backends:
            if not b.base_url or not b.api_key or b.provider == "local":
                continue
            host = urlparse(b.base_url).netloc
            if host not in provider_keys:
                provider_keys[host] = (b.api_key, b.base_url)

        discovered = []

        for host, (api_key, base_url) in provider_keys.items():
            models_url = _PROVIDER_MODEL_ENDPOINTS.get(host)
            if not models_url:
                continue

            try:
                available = await self._fetch_available_models(models_url, api_key)
                if not available:
                    continue

                whitelist = _FREE_TIER_MODELS.get(host, [])
                candidates = [m for m in whitelist if m not in used_models and m in available]

                for model in candidates:
                    ok = await self._test_model(base_url, api_key, model)
                    if ok:
                        new_name = self._generate_backend_name(host, model)
                        if new_name in used_names:
                            continue
                        from piclaw.llm.registry import BackendConfig
                        new_backend = BackendConfig(
                            name=new_name,
                            provider="openai",
                            model=model,
                            api_key=api_key,
                            base_url=base_url,
                            tags=["general", "auto-discovered", "free-tier"],
                            priority=4,
                            temperature=0.7,
                            notes=f"Proactive discovery ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
                        )
                        self.registry.add(new_backend)
                        self._health[new_name] = BackendHealth(name=new_name)
                        discovered.append((new_name, model, host))
                        used_names.add(new_name)
                        used_models.add(model)
                        log.info("Proaktive Discovery: ✅ '%s' registriert (%s)", new_name, model)
            except Exception as e:
                log.debug("Proaktive Discovery %s Fehler: %s", host, e)

        # Providers ohne Key vorschlagen
        missing_providers = []
        known_hosts = set(provider_keys.keys())
        for host, (signup_url, env_name, info) in _PROVIDER_SIGNUP_URLS.items():
            if host not in known_hosts:
                host_short = {
                    "api.groq.com": "Groq", "integrate.api.nvidia.com": "NVIDIA NIM",
                    "api.cerebras.ai": "Cerebras", "openrouter.ai": "OpenRouter",
                }.get(host, host)
                missing_providers.append((host_short, signup_url, info))

        if discovered or missing_providers:
            lines = [f"🔍 *Proaktive LLM-Discovery* ({datetime.now().strftime('%d.%m.%Y %H:%M')})\n"]
            if discovered:
                lines.append(f"✅ {len(discovered)} neue Backend(s) registriert:")
                for name, model, host in discovered:
                    lines.append(f"  `{name}`: {model}")
            if missing_providers:
                lines.append(f"\n🆓 {len(missing_providers)} Provider ohne API-Key:")
                for name, url, info in missing_providers:
                    lines.append(f"  *{name}*: {info}")
                    lines.append(f"  → {url}")
            await self._safe_notify("\n".join(lines))
        else:
            log.info("Proaktive Discovery: Keine neuen Modelle gefunden")


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

            # NUR Modelle aus der Whitelist (= _FREE_TIER_MODELS)
            # ⚠️ Keine Ähnlichkeitssuche – unbekannte Modelle könnten kosten!
            for pref in preferred:
                if pref in available:
                    self.registry.update(backend.name, model=pref)
                    log.info("Auto-Repair '%s': %s → %s (free-tier whitelist)",
                             backend.name, backend.model, pref)
                    return pref

            log.warning(
                "Auto-Repair '%s': Kein kostenloses Ersatzmodell auf %s gefunden",
                backend.name, host
            )

        except Exception as e:
            log.warning("Auto-Repair '%s' Fehler: %s", backend.name, e)

        return None

    async def _safe_notify(self, msg: str):
        """Benachrichtigung via Telegram + AgentMail-Backup."""
        # Primär: Telegram/MessagingHub
        if self.notify:
            try:
                await self.notify(msg)
            except Exception as e:
                log.warning("Health-Monitor Notify (Telegram): %s", e)

        # Backup: AgentMail (wenn konfiguriert)
        try:
            from piclaw.config import load as _load_cfg
            _cfg = _load_cfg()
            if not (_cfg.agentmail.api_key and _cfg.agentmail.inbox_id):
                return
            recipient = _cfg.agentmail.notification_email.strip()
            if not recipient:
                if not self._warned_no_notification_email:
                    log.info(
                        "AgentMail-Backup übersprungen: notification_email nicht konfiguriert "
                        "(in config.toml unter [agentmail] setzen, um Health-Mails zu erhalten)"
                    )
                    self._warned_no_notification_email = True
                return

            from piclaw.tools.agentmail import agentmail_send_email
            # Markdown-Formatierung entfernen für E-Mail
            clean_msg = msg.replace("*", "").replace("`", "").replace("_", "")

            await agentmail_send_email(
                cfg=_cfg.agentmail,
                inbox_id=_cfg.agentmail.inbox_id,
                to=[recipient],
                subject="PiClaw Health Monitor",
                text=clean_msg,
            )
        except Exception as _e:
            log.debug("AgentMail backup notify: %s", _e)

    async def request_api_key_signup(self, provider_name: str, signup_url: str) -> str | None:
        """
        Informiert den Nutzer über einen neuen Provider mit konkreten Schritten.

        Vollautomatische Web-Registrierung ist wegen CAPTCHA nicht zuverlässig.
        Stattdessen: klare Anleitung + piclaw-Befehl zum Aktivieren nach manuellem Signup.
        """
        # Provider-Info aus _PROVIDER_SIGNUP_URLS holen
        provider_info = None
        for host, info in _PROVIDER_SIGNUP_URLS.items():
            if provider_name.lower() in host or host in signup_url:
                provider_info = info
                break

        signup_url_final = provider_info[0] if provider_info else signup_url
        free_info = provider_info[2] if provider_info else ""
        base_url_hint = signup_url_final.rsplit("/keys", 1)[0] + "/v1" if "/keys" in signup_url_final else signup_url_final

        try:
            from piclaw.config import load as _cfg_load
            _cfg = _cfg_load()
            email_hint = (
                f"📧 Nutze Dameons E-Mail: `{_cfg.agentmail.email_address}`\n"
                if getattr(_cfg.agentmail, "email_address", None) else ""
            )
        except Exception:
            email_hint = ""

        msg = (
            f"🔑 *LLM Health Monitor – Neuer Provider vorgeschlagen*\n\n"
            f"**{provider_name}** – {free_info}\n\n"
            f"📋 Anmeldung: {signup_url_final}\n"
            f"{email_hint}\n"
            f"Nach der Registrierung per Chat aktivieren:\n"
            f"_'Füge {provider_name} API-Key hinzu: DEIN_KEY'_\n\n"
            f"Oder CLI: `piclaw llm add --name {provider_name.lower()} "
            f"--provider openai --api-key KEY --base-url {base_url_hint}`"
        )
        await self._safe_notify(msg)
        log.info("Signup-Vorschlag gesendet für Provider '%s'", provider_name)
        return None

    # ── Status für API/Dashboard ─────────────────────────────────

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

# Statusdatei für Cross-Prozess-Kommunikation (daemon → api)
_STATUS_FILE_NAME = "llm_health_status.json"


def _status_file_path():
    try:
        from piclaw.config import CONFIG_DIR
        return CONFIG_DIR / _STATUS_FILE_NAME
    except Exception:
        from pathlib import Path
        return Path("/etc/piclaw") / _STATUS_FILE_NAME


def write_status_file(monitor: "LLMHealthMonitor") -> None:
    """Schreibt aktuellen Monitor-Status in Datei (für API-Prozess lesbar)."""
    import json
    import time as _time
    try:
        status = {
            "available": True,
            "ts": int(_time.time()),
            "backends": monitor.status_dict(),
        }
        p = _status_file_path()
        p.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    except Exception as _e:
        log.debug("write_status_file: %s", _e)


def read_status_file() -> dict:
    """Liest Monitor-Status aus Datei (vom API-Prozess aufgerufen)."""
    import json
    import time as _time
    try:
        p = _status_file_path()
        if not p.exists():
            return {"available": False, "message": "Health Monitor nicht aktiv"}
        data = json.loads(p.read_text(encoding="utf-8"))
        age_s = int(_time.time()) - data.get("ts", 0)
        if age_s > 600:  # >10min alt = veraltet
            return {"available": False, "message": f"Health Monitor Status veraltet ({age_s}s)"}
        return data
    except Exception as _e:
        return {"available": False, "error": str(_e)}


def get_monitor() -> "LLMHealthMonitor | None":
    return _monitor


def start_monitor(registry, multirouter, notify=None) -> "LLMHealthMonitor":
    global _monitor
    _monitor = LLMHealthMonitor(registry, multirouter, notify=notify)
    return _monitor

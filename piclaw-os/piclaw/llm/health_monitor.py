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
from datetime import datetime, timedelta, UTC
from collections.abc import Callable, Awaitable

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
    # Google Gemini ist seit Dez 2024 OpenAI-kompatibel; großzügigstes Free-Tier (1500 RPD)
    "generativelanguage.googleapis.com": "https://generativelanguage.googleapis.com/v1beta/openai/models",
    # GitHub Models: OpenAI-kompatibel, Auth via GitHub PAT (models:read scope)
    "models.github.ai":          "https://models.github.ai/catalog/models",
    # Together.ai: $5 Startguthaben, danach kostenpflichtig → NICHT enthalten
    # Mistral: nur 2 RPM Free-Tier, zu langsam für Agentic-Loops → NICHT enthalten
    # xAI Grok: nur Trial-Credits → NICHT enthalten
    # Cloudflare Workers AI: Account-ID in URL bricht das /v1/models-Pattern → separat
}

# ── Provider-Signup-URLs für autonome Schlüssel-Suche (v0.16) ──────────────
# Format: {host: (signup_url, key_env_name, free_tier_info)}
_PROVIDER_SIGNUP_URLS = {
    "api.groq.com": (
        "https://console.groq.com/keys",
        "GROQ_API_KEY",
        "Kostenlos: 30 RPM / 14400 RPD auf llama-3.3-70b-versatile, gpt-oss-120b, qwen3-32b",
    ),
    "integrate.api.nvidia.com": (
        "https://build.nvidia.com",
        "NVIDIA_API_KEY",
        "Kostenlos: 1000–5000 Credits/Tag, 100+ Modelle inkl. Nemotron-Ultra-253b, DeepSeek-V3.1",
    ),
    "api.cerebras.ai": (
        "https://cloud.cerebras.ai",
        "CEREBRAS_API_KEY",
        "Kostenlos: 1M Tokens/Tag, 30 RPM, ~2600 t/s; Qwen3-235B mit 64K Context auf Free-Tier",
    ),
    "openrouter.ai": (
        "https://openrouter.ai/keys",
        "OPENROUTER_API_KEY",
        "Kostenlos: 20 RPM / 200 RPD auf :free-Modelle (Qwen3-Coder, GLM-4.5, DeepSeek-R1, …)",
    ),
    "generativelanguage.googleapis.com": (
        "https://aistudio.google.com/app/apikey",
        "GEMINI_API_KEY",
        "Kostenlos: 15 RPM / 1500 RPD auf Gemini 2.5 Flash, 30 RPM auf Flash-Lite",
    ),
    "models.github.ai": (
        "https://github.com/settings/tokens",
        "GITHUB_TOKEN",
        "Kostenlos via GitHub PAT (scope: models:read) – gpt-4o-mini, llama-3.3, phi-4, mistral",
    ),
}

# Nur Modelle die NACHWEISLICH KOSTENLOS sind (Free-Tier)
# Wird von Auto-Discovery und Auto-Repair als Whitelist verwendet
# Letzte Aktualisierung: Juni 2026 — Provider-Docs gegengeprüft
_FREE_TIER_MODELS = {
    "api.groq.com": [
        # Groq Free Tier: 30 RPM / 14 400 RPD
        # Quelle: https://console.groq.com/docs/models (Juni 2026)
        # ── Production ──
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        # ── Preview (für Evaluation, aber API funktioniert) ──
        "qwen/qwen3.6-27b",
        # ── Entfernt: nicht mehr in Groq-Catalog (Juni 2026) ──
        # - meta-llama/llama-4-maverick-17b-128e-instruct (deprecated)
        # - moonshotai/kimi-k2-instruct (deprecated)
        # - gemma2-9b-it (deprecated)
        # ── Entfernt: gegen GET /openai/v1/models geprüft (26.07.2026) ──
        # - meta-llama/llama-4-scout-17b-16e-instruct → 404 model_not_found;
        #   war das Modell von groq-fallback und hat es lahmgelegt
        # - qwen/qwen3-32b → nicht mehr im Catalog
    ],
    "integrate.api.nvidia.com": [
        # NVIDIA NIM Free API: 40 RPM, 100+ Modelle
        # Quelle: GET /v1/models, live gegengeprueft 23.08.2026.
        # Jeder Eintrag hier wurde mit einem echten chat/completions-Call
        # verifiziert - Katalog-Praesenz allein genuegt nicht: 
        # nvidia/llama-3.1-nemotron-ultra-253b-v1 steht im Katalog, liefert
        # aber 404 "Function not found".
        # Reihenfolge = Auto-Repair-Praeferenz (erster Treffer gewinnt).
        # ── Meta ──
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-70b-instruct",
        "meta/llama-3.1-8b-instruct",
        # ── Nemotron (NVIDIA) ──
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-nano-30b-a3b",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        # ── DeepSeek ──
        "deepseek-ai/deepseek-v4-flash-0731",
        # ── Entfernt: 410 Gone / End-of-Life (verifiziert 23.08.2026) ──
        # - meta/llama-4-maverick-17b-128e-instruct  → EOL, war das Modell
        #   von 'nemotron-nvidia' und hat es dauerhaft lahmgelegt
        # - meta/llama-4-scout-17b-16e-instruct      → EOL
        # ── Entfernt: nicht mehr im Katalog ──
        # - meta/llama-3.1-405b-instruct
        # - deepseek-ai/deepseek-r1, deepseek-ai/deepseek-v3.1
        # - qwen/qwen3-coder-480b-a35b-instruct
        # ── Entfernt: Tippfehler, konnte nie matchen ──
        # - nvidia/llama-3_1-nemotron-ultra-253b-v1  (Unterstriche statt Punkte;
        #   die korrekte ID nvidia/llama-3.1-nemotron-ultra-253b-v1 liefert 404)
        # ── Entfernt: zu langsam fuer die Probe ──
        # - nvidia/llama-3.3-nemotron-super-49b-v1   (18.4s gemessen; die
        #   Nachfolge-Version v1.5 antwortet in ~0.5s)
    ],
    "api.cerebras.ai": [
        # Cerebras Inference: 1M Tokens/Tag, 30 RPM, ~2600-3000 t/s
        # Quelle: https://inference-docs.cerebras.ai/models/overview (Juni 2026)
        # ── Production (stable) ──
        "gpt-oss-120b",
        "llama-3.1-8b",                # production-tier laut docs
        "llama-4-scout-17b-16e-instruct",
        # ── Preview ──
        "zai-glm-4.7",                 # neu, 355B params, ~1000 t/s
        # ── Entfernt: deprecated 2026-02-16 ──
        # - llama-3.3-70b
        # - qwen-3-32b
        # - qwen-3-235b-a22b-instruct-2507 (nicht mehr im Catalog)
    ],
    "openrouter.ai": [
        # OpenRouter: 20 RPM / 200 RPD auf :free
        # Quelle: https://openrouter.ai/api/v1/models gefiltert auf prompt=0
        # KOMPLETT NEU — alle alten :free-Endpoints sind weggefallen (Juni 2026)
        "nvidia/nemotron-3-ultra-550b-a55b:free",          # 1M context, ultra-tier
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # 256k, multimodal
        "cohere/north-mini-code:free",                     # 256k, coding-spezialisiert
        "poolside/laguna-m.1:free",                        # 262k, agentic coding
        "poolside/laguna-xs.2:free",                       # 262k, schnell
        # ── Entfernt: nicht mehr free (Juni 2026) ──
        # - meta-llama/llama-3.3-70b-instruct:free
        # - qwen/qwen3-coder:free
        # - nvidia/llama-3.3-nemotron-super-49b-v1:free
        # - deepseek/deepseek-chat-v3.1:free
        # - deepseek/deepseek-r1:free
        # - z-ai/glm-4.5-air:free
        # - google/gemma-3-27b-it:free
        # - mistralai/mistral-small-3.2-24b-instruct:free
    ],
    "generativelanguage.googleapis.com": [
        # Google Gemini Free Tier (Stand Juni 2026):
        # Pro-Modelle sind seit April 2026 paid-only. Free = Flash + Flash-Lite.
        # Quelle: https://ai.google.dev/gemini-api/docs/models
        "gemini-3.5-flash",            # neueste stable, ⭐ Empfehlung
        "gemini-3.1-flash-lite",       # höhere RPM für leichte Tasks
        "gemini-3-flash-preview",      # preview-tier, evaluation
        "gemini-2.5-flash",            # bewährter Fallback
        "gemini-2.5-flash-lite",
    ],
    "models.github.ai": [
        # GitHub Models: niedrige RPD aber breite Modell-Auswahl
        # Quelle: github.com/marketplace?type=models (Juni 2026)
        "openai/gpt-4.1-mini",
        "openai/gpt-4o-mini",
        "openai/gpt-5-mini",                   # falls verfügbar (neu)
        "meta/llama-3.3-70b-instruct",
        "microsoft/phi-4",
        "microsoft/phi-4-mini",
        "mistral-ai/mistral-small-2503",
        "cohere/cohere-command-r-08-2024",
    ],
}

# Rückwärts-kompatibel: _PROVIDER_PREFERRED_MODELS = _FREE_TIER_MODELS
_PROVIDER_PREFERRED_MODELS = _FREE_TIER_MODELS

# Regex für Groq TPD-Limit Erkennung
_RE_TPD = re.compile(r"tokens per day", re.IGNORECASE)
# Groq schreibt je nach Wartezeit "try again in 5m45.6s" ODER "try again
# in 6.765s". Die Minuten-Gruppe muss optional sein - sonst greift keine
# der beiden Regeln und der Default von 10min parkt ein Backend, das in
# 7 Sekunden wieder bereit waere (beobachtet 23.08.2026 an groq-actions).
_RE_RETRY_AFTER = re.compile(
    r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", re.IGNORECASE
)
_RE_RETRY_SECONDS = re.compile(r"retry.after[\":\s]+(\d+)", re.IGNORECASE)

# HTTP 413 – "Request too large": der Provider meldet ein Input-Budget, das
# kleiner ist als unser Prompt. Das ist KEIN Verfügbarkeitsproblem, sondern
# eine strukturelle Kapazitätsgrenze: ein Retry mit demselben Prompt scheitert
# garantiert wieder. Beispiel (Groq Free-Tier, 24.07.2026):
#   "Request too large for model `openai/gpt-oss-120b` … on tokens per minute
#    (TPM): Limit 8000, Requested 11122, please reduce your message size"
_RE_TPM_LIMIT = re.compile(r"\bLimit\s+(\d+)", re.IGNORECASE)
_RE_TPM_REQUESTED = re.compile(r"\bRequested\s+(\d+)", re.IGNORECASE)

# HTTP 503 - "ResourceExhausted: Worker local total request limit reached
# (21/16)". NVIDIA NIM meldet so einen ueberbuchten Shared-Worker im
# Free-Tier. Das ist eine Kapazitaetsgrenze wie 429/413, KEIN Ausfall: das
# Backend antwortet Minuten spaeter voellig normal. Als Fehler gezaehlt trieb
# es 'openai-default' regelmaessig in die Deaktivierung (Vorfall 23.08.2026).
_RE_CAPACITY = re.compile(
    r"ResourceExhausted|Worker local total request limit|"
    r"no healthy upstream|temporarily unavailable|overloaded",
    re.IGNORECASE,
)

# Health-Probe-Timeouts. 15s war zu knapp: meta/llama-3.3-70b-instruct auf
# NVIDIA NIM braucht warm ~8s und bei belegtem Worker deutlich laenger. Das
# wurde als 408 "Timeout" gezaehlt und erzeugte das Flapping ueberhaupt erst.
PROBE_TIMEOUT_TOTAL = 45
PROBE_TIMEOUT_CONNECT = 10

# Backoff, wenn ein Provider Kapazitaetsprobleme meldet (503/ueberlastet).
CAPACITY_BACKOFF_SECONDS = 300


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
    # Wurde fuer dieses Backend je eine Stoerungs-Meldung verschickt? Nur
    # dann ist eine Entwarnung eine Nachricht wert - sonst meldet der
    # Monitor Erholungen von Ausfaellen, die nie jemand gesehen hat.
    outage_notified: bool = False


class LLMHealthMonitor:
    """
    Überwacht LLM-Backends und repariert sie automatisch.
    Bietet sowohl periodische Checks als auch Echtzeit-Meldungen.
    """

    # Intervalle
    INTERVAL_HEALTHY = 3600    # 1h wenn alles gut
    INTERVAL_DEGRADED = 300    # 5min wenn Backends degraded
    INITIAL_DELAY = 60         # 1min nach Boot (statt 10min)

    # Deaktivierte Backends werden jeden N-ten Zyklus erneut geprobt.
    # Bei INTERVAL_HEALTHY=1h also ca. alle 6h. Der erste Zyklus nach dem
    # Boot probt immer (siehe run_check) – ein Restart soll Recovery
    # beschleunigen, nicht verhindern.
    DISABLED_RETRY_EVERY = 6

    # Obergrenze für auto-discovered Backends. Der Pool ist als Notfall-
    # Reserve gedacht, nicht als Dauerzustand: ohne Deckel wuchs er durch
    # die tägliche Discovery auf 16 Einträge (Stand 25.07.2026).
    MAX_AUTO_BACKENDS = 4

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
        # Aus der Statusdatei uebernehmen. Ohne das steht der Wert nach jedem
        # Restart auf 0, die "taegliche" Discovery lief also bei JEDEM
        # Neustart: ~10 Test-Calls gegen die Provider plus ein frischer
        # auto-*-Pool, den der Cleanup erst eine Stunde spaeter abraeumt.
        # Genau so wuchs der Pool am 25.07.2026 auf 16 Eintraege.
        self._last_discovery_time = _read_last_discovery_ts()
        self._cycle_count = 0  # run_check-Zähler, steuert den Disabled-Retry

    # ── Notify-Hilfe ──────────────────────────────────────────────

    def _notify_soon(self, msg: str, name: str):
        """Feuert eine Notify als Background-Task, falls ein Loop läuft.

        `report_error` wird aus synchronem Code aufgerufen (Multirouter-
        Except-Zweig, CLI, Tests). Ohne laufenden Event-Loop wirft
        asyncio.create_task RuntimeError – die Meldung ist dann nicht
        wichtig genug, um den Aufrufer zu reißen.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            log.debug("Notify übersprungen (kein Event-Loop): %s", msg[:60])
            return
        create_background_task(self._safe_notify(msg), name=name)

    @staticmethod
    def _is_capacity_error(error_code: int | None, error_msg: str) -> bool:
        """503/„kein freier Worker" = Auslastung, nicht Ausfall.

        Der Provider sagt hier „gerade nicht, versuch es spaeter" - genau wie
        bei 429, nur ohne Retry-After. Als Ausfall gezaehlt fuehrt das zur
        Deaktivierung eines Backends, das Minuten spaeter normal antwortet.
        """
        # 503 Service Unavailable, 502/504 Gateway (Upstream voll oder weg),
        # 529 "site is overloaded" (u.a. NVIDIA NIM, beobachtet 23.08.2026 an
        # auto-nvidia-deepseek - wurde bis dahin nur ueber den Meldungstext
        # erkannt, also nur solange der Provider einen brauchbaren Body
        # mitschickt).
        if error_code in (502, 503, 504, 529):
            return True
        return bool(error_msg and _RE_CAPACITY.search(error_msg))

    # ── Echtzeit-Meldung vom Multirouter ──────────────────────────

    def report_error(self, backend_name: str, error_code: int, error_msg: str):
        """
        Wird vom Multirouter aufgerufen wenn ein Backend einen Fehler liefert.
        Reagiert SOFORT statt auf den nächsten Check-Zyklus zu warten.
        """
        h = self._health.setdefault(backend_name, BackendHealth(name=backend_name))

        # 413 ist kein Ausfall, sondern eine Kapazitätsgrenze – der Zähler
        # darf nicht hochlaufen, sonst deaktiviert der Monitor ein völlig
        # gesundes Backend nur weil unser Prompt zu groß war.
        if error_code == 413:
            h.last_error = error_msg[:200]
            h.last_error_code = error_code
            self._handle_request_too_large(backend_name, error_msg)
            return

        # 503/ueberlastet: gleiche Logik wie 413 - kein Strike, aber kurz
        # zurueckstellen, damit der Router waehrenddessen andere Backends
        # nimmt statt in dieselbe volle Warteschlange zu laufen.
        if self._is_capacity_error(error_code, error_msg):
            h.last_error = error_msg[:200]
            h.last_error_code = error_code
            h.rate_limited_until = time.time() + CAPACITY_BACKOFF_SECONDS
            log.info(
                "Backend '%s': Provider ausgelastet (%s) - %.0fmin zurueckgestellt",
                backend_name, error_code, CAPACITY_BACKOFF_SECONDS / 60,
            )
            return

        h.consecutive_failures += 1
        h.last_error = error_msg[:200]
        h.last_error_code = error_code

        if error_code == 429:
            self._handle_rate_limit(backend_name, error_msg)

        # Prüfen ob ALLE API-Backends jetzt down sind
        self._check_all_backends_down()

    # ── 413 Handling ──────────────────────────────────────────────

    def _handle_request_too_large(self, backend_name: str, error_msg: str):
        """Merkt sich das gemeldete Input-Budget des Backends.

        Ein 413 heißt: dieses Backend kann Requests unserer Größe grundsätzlich
        nicht bedienen. Deaktivieren wäre falsch (das Backend ist gesund und
        für kleine Requests nutzbar), Retry wäre sinnlos (derselbe Prompt
        scheitert wieder). Stattdessen persistieren wir das Limit, damit
        MultiLLMRouter._select_backend das Backend für zu große Requests von
        vornherein überspringt.
        """
        backend = self.registry.get(backend_name)
        if not backend:
            return

        m_limit = _RE_TPM_LIMIT.search(error_msg)
        if not m_limit:
            log.warning(
                "Backend '%s': 413 ohne erkennbares Limit – Meldung: %s",
                backend_name, error_msg[:120],
            )
            return

        limit = int(m_limit.group(1))
        m_req = _RE_TPM_REQUESTED.search(error_msg)
        requested = int(m_req.group(1)) if m_req else 0

        if backend.max_input_tokens == limit:
            return  # schon bekannt, nicht erneut schreiben/melden

        self.registry.update(backend_name, max_input_tokens=limit)
        log.warning(
            "Backend '%s': Input-Budget %d Tokens (Request war %d) – "
            "wird für größere Requests künftig übersprungen",
            backend_name, limit, requested,
        )
        self._notify_soon(
            f"📏 *LLM Health Monitor*\n\n"
            f"Backend `{backend_name}` meldet ein Input-Limit von "
            f"**{limit} Tokens** (Request war {requested}).\n"
            f"Es wird für größere Anfragen künftig übersprungen, bleibt "
            f"für kleine aber nutzbar.",
            name="llm-notify-413",
        )

    def report_success(self, backend_name: str):
        """Backend hat erfolgreich geantwortet.

        Setzt den vollen Health-State zurück – nicht nur die Failure-Zähler.
        Vorher blieb rate_limited_until/is_tpd_limited stehen, sodass ein
        längst gesundes Backend als "rate-limited" markiert bleiben konnte
        bis zum nächsten Monitor-Tick.
        """
        h = self._health.get(backend_name)
        if not h:
            return
        was_degraded = (
            h.consecutive_failures > 0
            or h.rate_limited_until > 0.0
            or h.is_tpd_limited
        )
        if was_degraded:
            log.info("Backend '%s': wieder gesund (failures=%d, rl=%.0f, tpd=%s)",
                     backend_name, h.consecutive_failures,
                     h.rate_limited_until, h.is_tpd_limited)
        h.consecutive_failures = 0
        h.last_error = ""
        h.last_error_code = 0
        h.rate_limited_until = 0.0
        h.is_tpd_limited = False
        self._all_api_down_notified = False
        # Genau eine Entwarnung pro gemeldeter Stoerung. Ohne das blieb eine
        # verschickte Ausfall-Meldung unaufgeloest, weil run_check die
        # Erholung nicht mehr sieht (report_success hat den Zaehler schon
        # genullt) - der Nutzer sah nur die Stoerung, nie das Ende.
        if h.outage_notified:
            h.outage_notified = False
            self._notify_soon(
                f"✅ *LLM Health Monitor*\n\nBackend `{backend_name}` "
                f"antwortet wieder normal.",
                name="llm-notify-recovered",
            )

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
            now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC für Arithmetik
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
        h.original_priority = h.original_priority or backend.original_priority or backend.priority

        # Priorität auf 0 senken (wird bei Recovery wiederhergestellt).
        # original_priority wandert MIT in die Registry: ohne persistierten
        # Wert bleibt die Priorität nach einem Restart dauerhaft auf 0 stehen,
        # weil der In-Memory-Health-State dann leer ist.
        self.registry.update(
            backend_name, priority=0, original_priority=h.original_priority
        )
        log.info(
            "Backend '%s': Rate-limitiert, Priorität %d→0 für %.0fmin",
            backend_name, backend.priority, retry_seconds / 60
        )

        # Telegram wenn TPD-Limit
        if h.is_tpd_limited and self.notify:
            h.outage_notified = True
            hours_left = retry_seconds / 3600
            msg = (
                f"⚠️ *LLM Health Monitor*\n\n"
                f"Backend `{backend_name}` hat das **Tages-Token-Limit** erreicht.\n"
                f"Modell: `{backend.model}`\n"
                f"Sperre: ~{hours_left:.1f}h (bis Mitternacht UTC)\n"
                f"Andere Backends übernehmen automatisch."
            )
            self._notify_soon(msg, name="llm-notify")

    def _parse_retry_after(self, error_msg: str) -> float:
        """Extrahiert Retry-After Sekunden aus Fehlermeldung."""
        # Format: "try again in 5m45.6s" oder "try again in 6.765s"
        m = _RE_RETRY_AFTER.search(error_msg)
        if m:
            minutes = int(m.group(1)) if m.group(1) else 0
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

        # Schwelle bewusst = failure_threshold: mit ">= 1" reichte EIN
        # transienter Fehler pro Backend, um den 🚨-Alarm samt Auto-Discovery
        # auszuloesen. Bei fuenf Backends an zwei ueberlasteten Providern ist
        # das ein Zustand, der im Normalbetrieb staendig kurz eintritt.
        all_down = all(
            self._health.get(b.name, BackendHealth(b.name)).consecutive_failures
            >= self.failure_threshold
            or self._health.get(b.name, BackendHealth(b.name)).rate_limited_until > time.time()
            for b in api_backends
        )

        if all_down:
            # Auto-Discovery starten (async, im Hintergrund). Wie bei
            # _notify_soon: report_error kommt auch aus synchronem Code
            # (Multirouter-Except-Zweig, CLI, Tests). Ohne laufenden Loop
            # wirft create_task RuntimeError und reisst den Aufrufer mit.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                log.debug("Auto-Discovery uebersprungen (kein Event-Loop)")
            else:
                create_background_task(
                    self._auto_discover_backends(api_backends),
                    name="llm-auto-discover",
                )

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
                self._notify_soon(msg, name="llm-notify")
                for b in api_backends:
                    self._health.setdefault(
                        b.name, BackendHealth(b.name)
                    ).outage_notified = True
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
            "openrouter.ai": "openrouter",
            "generativelanguage.googleapis.com": "gemini",
            "models.github.ai": "github",
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
            "free_tier": "30 RPM / 14400 RPD – dauerhaft kostenlos",
        },
        "nvidia": {
            "host": "integrate.api.nvidia.com",
            "name": "NVIDIA NIM",
            "signup": "https://build.nvidia.com",
            "free_tier": "1000–5000 Credits/Tag – dauerhaft kostenlos",
        },
        "cerebras": {
            "host": "api.cerebras.ai",
            "name": "Cerebras",
            "signup": "https://cloud.cerebras.ai",
            "free_tier": "1M Tokens/Tag, 30 RPM, ~2600 t/s – dauerhaft kostenlos",
        },
        "openrouter": {
            "host": "openrouter.ai",
            "name": "OpenRouter",
            "signup": "https://openrouter.ai/keys",
            "free_tier": "20 RPM / 200 RPD auf :free-Modelle – dauerhaft kostenlos",
        },
        "gemini": {
            "host": "generativelanguage.googleapis.com",
            "name": "Google Gemini",
            "signup": "https://aistudio.google.com/app/apikey",
            "free_tier": "15 RPM / 1500 RPD auf Gemini 2.5 Flash – großzügigstes Free-Tier am Markt",
        },
        "github": {
            "host": "models.github.ai",
            "name": "GitHub Models",
            "signup": "https://github.com/settings/tokens (scope: models:read)",
            "free_tier": "Niedrige RPD, aber gpt-4o-mini, llama-3.3, phi-4, mistral verfügbar",
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
            except TimeoutError:
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

        self._cycle_count += 1
        log.info(
            "LLM Health-Check: %d Backends (%d aktiv, Zyklus %d)",
            len(backends),
            sum(1 for b in backends if b.enabled),
            self._cycle_count,
        )
        repaired = []
        deactivated = []
        recovered = []

        for backend in backends:
            h = self._health.setdefault(backend.name, BackendHealth(name=backend.name))

            # ── Rate-Limit Recovery (Wave 3.6: test-before-restore) ─────────
            # Vorher wurde die Priorität sofort wiederhergestellt, sobald
            # rate_limited_until abgelaufen war – auch wenn das Provider-
            # Limit noch nicht zurückgesetzt war. Concurrent chat()-Calls
            # konnten in dem schmalen Fenster wieder ein 429 einfangen.
            # Jetzt: erst einen stillen Probe-Call schicken, nur bei Erfolg
            # die Priorität restaurieren; bei Mißerfolg den Sperr-Timer
            # nochmal 5 Minuten verlängern.
            if h.rate_limited_until and time.time() > h.rate_limited_until:
                probe_code, probe_err = await self._test_backend(backend)
                h.last_checked = time.time()
                if probe_code is None:
                    # Probe OK → voll wiederherstellen.
                    # Die geparkte Priorität kommt bevorzugt aus der Registry,
                    # damit sie auch nach einem Restart noch bekannt ist.
                    parked = (
                        h.original_priority
                        if h.original_priority is not None
                        else backend.original_priority
                    )
                    if parked is not None:
                        self.registry.update(
                            backend.name, priority=parked, original_priority=None
                        )
                        log.info(
                            "Backend '%s': Rate-Limit abgelaufen + Probe OK – Priorität %d wiederhergestellt",
                            backend.name, parked
                        )
                        recovered.append(
                            f"✅ `{backend.name}`: Rate-Limit abgelaufen – wiederhergestellt (Prio {parked})"
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
                    # Probe schon erledigt – nicht erneut testen unten
                    continue
                else:
                    # Probe fehlgeschlagen → Sperre +5min, original priority bleibt geparkt
                    h.rate_limited_until = time.time() + 300
                    log.warning(
                        "Backend '%s': Rate-Limit-Probe fehlgeschlagen (%s) – "
                        "+5min weiter gesperrt",
                        backend.name, probe_code,
                    )
                    continue

            # Noch rate-limited? Nicht erneut testen.
            if h.rate_limited_until > time.time():
                remaining = (h.rate_limited_until - time.time()) / 60
                log.debug("Backend '%s': noch %.0fmin rate-limited", backend.name, remaining)
                continue

            if not backend.enabled:
                # Deaktivierte Backends wurden früher übersprungen und damit
                # NIE wieder getestet – ein einmal deaktiviertes Backend war
                # endgültig tot. Jetzt: jeden N-ten Zyklus (und immer im
                # ersten Zyklus nach dem Boot) still anproben und bei Erfolg
                # reaktivieren.
                #
                # auto-* bleiben ausgenommen: die sind als Wegwerf-Reserve
                # gedacht und werden vom Auto-Cleanup unten entsorgt, nicht
                # wiederbelebt.
                if backend.name.startswith("auto-"):
                    continue
                if not (
                    self._cycle_count == 1
                    or self._cycle_count % self.DISABLED_RETRY_EVERY == 0
                ):
                    continue
                repaired_model = None
                probe_code, probe_err = await self._test_backend(backend)
                h.last_checked = time.time()
                if probe_code in (404, 410):
                    # Deaktiviert UND das Modell existiert nicht mehr: die
                    # Probe kann per Definition nie gruen werden, das Backend
                    # bliebe fuer immer tot. Genau das war der Zustand von
                    # 'nemotron-nvidia' seit dem llama-4-EOL (410, 23.08.2026)
                    # - jeder sechste Zyklus loggte "bleibt deaktiviert",
                    # ohne dass je ein Ersatz gesucht wurde.
                    fixed = await self._auto_repair_404(backend)
                    if not fixed:
                        log.info(
                            "Backend '%s': bleibt deaktiviert (Modell weg: %s, "
                            "kein Ersatz gefunden)", backend.name, probe_code,
                        )
                        continue
                    probe_code, probe_err = await self._test_backend(
                        self.registry.get(backend.name)
                    )
                    if probe_code is not None:
                        log.info(
                            "Backend '%s': Ersatzmodell '%s' antwortet nicht "
                            "(Probe: %s) - bleibt deaktiviert",
                            backend.name, fixed, probe_code,
                        )
                        continue
                    repaired_model = fixed
                elif probe_code is not None:
                    log.info(
                        "Backend '%s': bleibt deaktiviert (Probe: %s)",
                        backend.name, probe_code,
                    )
                    continue
                parked = (
                    h.original_priority
                    if h.original_priority is not None
                    else backend.original_priority
                )
                updates = {"enabled": True}
                if parked is not None:
                    updates["priority"] = parked
                    updates["original_priority"] = None
                self.registry.update(backend.name, **updates)
                h.consecutive_failures = 0
                h.last_error = ""
                h.original_priority = None
                self._all_api_down_notified = False
                log.info(
                    "Backend '%s': Probe erfolgreich – reaktiviert%s",
                    backend.name,
                    f" (Prio {parked} wiederhergestellt)" if parked is not None else "",
                )
                h.outage_notified = False
                if repaired_model:
                    recovered.append(
                        f"🔧 `{backend.name}`: Modell ersetzt → "
                        f"`{repaired_model}` – reaktiviert"
                    )
                else:
                    recovered.append(
                        f"✅ `{backend.name}`: wieder erreichbar – reaktiviert"
                    )
                continue

            # ── Health-Test ─────────────────────────────────────────
            error_code, error_msg = await self._test_backend(backend)
            h.last_checked = time.time()

            # 413 im Health-Test: der Probe-Prompt ist winzig, ein 413 hier
            # bedeutet ein absurd kleines Budget. Nicht als Ausfall zählen.
            if error_code == 413:
                self._handle_request_too_large(backend.name, error_msg)
                continue

            # 503/ueberlastet: der Provider hat gerade keinen freien Worker.
            # Kurz zurueckstellen statt als Ausfall zaehlen - sonst sammelt
            # ein voellig gesundes Backend Strikes, bis es deaktiviert wird.
            if self._is_capacity_error(error_code, error_msg):
                h.rate_limited_until = time.time() + CAPACITY_BACKOFF_SECONDS
                log.info(
                    "Backend '%s': Provider ausgelastet (%s) - %.0fmin zurueckgestellt",
                    backend.name, error_code, CAPACITY_BACKOFF_SECONDS / 60,
                )
                continue

            if error_code is None:
                if h.consecutive_failures > 0:
                    log.info("Backend '%s': wieder gesund nach %d Fehlern",
                             backend.name, h.consecutive_failures)
                    # Nur melden, wenn der Ausfall auch gemeldet wurde. Ein
                    # einzelner Probe-Fehler zwischen zwei Zyklen ist kein
                    # Ereignis - vorher erzeugte jeder Blip eine Entwarnung
                    # fuer eine Stoerung, die nie verschickt worden war
                    # (17 Telegram-Meldungen in 2 Tagen, 23.08.2026).
                    if h.outage_notified:
                        recovered.append(f"✅ `{backend.name}`: wieder erreichbar")
                        h.outage_notified = False
                h.consecutive_failures = 0
                h.last_error = ""
                # Verwaiste Priorität-Parkung aufräumen: nach einem Restart ist
                # h.rate_limited_until leer, der Rate-Limit-Zweig oben greift
                # also nicht mehr – ein gesundes Backend bliebe sonst dauerhaft
                # auf Priorität 0 stehen, weil nur dieser Zweig je restauriert
                # hat. Der persistierte Wert ist hier die einzige Quelle.
                if backend.original_priority is not None and not h.rate_limited_until:
                    self.registry.update(
                        backend.name,
                        priority=backend.original_priority,
                        original_priority=None,
                    )
                    log.info(
                        "Backend '%s': geparkte Priorität %d wiederhergestellt "
                        "(Sperre war nach Restart nicht mehr aktiv)",
                        backend.name, backend.original_priority,
                    )
                    recovered.append(
                        f"✅ `{backend.name}`: Priorität {backend.original_priority} wiederhergestellt"
                    )
                continue

            h.consecutive_failures += 1
            h.last_error = error_msg
            log.warning("Backend '%s': Fehler %s (%d/%d) – %s",
                        backend.name, error_code, h.consecutive_failures,
                        self.failure_threshold, error_msg[:80])

            # 410 "Gone" = Modell hat sein End-of-Life erreicht (NVIDIA NIM
            # meldet so ausgemusterte Modelle). Fachlich identisch zu 404:
            # das Modell kommt nicht zurueck, ein Ersatz muss her. Vorher
            # fiel 410 in den generischen Zweig - 'nemotron-nvidia' war
            # dadurch seit dem EOL dauerhaft deaktiviert (23.08.2026).
            if error_code in (404, 410):
                fixed = await self._auto_repair_404(backend)
                if fixed:
                    repaired.append(f"🔧 `{backend.name}`: Modell ersetzt → `{fixed}`")
                    h.consecutive_failures = 0
                    # Repariert = erledigt; keine spaetere Entwarnung noetig.
                    h.outage_notified = False
                else:
                    deactivated.append(f"⚠️ `{backend.name}`: Kein Ersatz gefunden, deaktiviert")
                    self.registry.update(backend.name, enabled=False)
                    h.outage_notified = True

            elif error_code == 429:
                self._handle_rate_limit(backend.name, error_msg)

            elif h.consecutive_failures >= self.failure_threshold:
                self.registry.update(backend.name, enabled=False)
                h.outage_notified = True
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
        # Läuft in JEDEM Zyklus, nicht mehr nur wenn ein Nicht-auto-Backend
        # gerade recovered ist. Die alte Kopplung an `non_auto_recovered` war
        # eine Selbstverriegelung: waren alle statischen Backends deaktiviert,
        # konnte keines mehr recovern (deaktivierte wurden nie getestet), also
        # lief der Cleanup nie, also wuchs der Auto-Pool mit jeder täglichen
        # Discovery weiter – bis auf 16 Einträge am 25.07.2026.
        #
        # Zwei Stufen:
        #   1. Original-Backend gesund → gesamten Auto-Pool entsorgen (alte Absicht)
        #   2. Sonst → Pool auf MAX_AUTO_BACKENDS deckeln, ältester zuerst raus
        auto_backends = [
            b for b in backends
            if b.name.startswith("auto-") and "auto-discovered" in b.tags
        ]
        if auto_backends:
            original_healthy = any(
                not b.name.startswith("auto-")
                and b.enabled
                and self._health.get(b.name, BackendHealth(b.name)).consecutive_failures == 0
                and self._health.get(b.name, BackendHealth(b.name)).rate_limited_until <= time.time()
                for b in backends
                if b.provider != "local"
            )
            if original_healthy:
                doomed, reason = auto_backends, "Original-Backend wieder gesund"
            else:
                # Deaktivierte zuerst opfern, danach die ältesten (Registry-
                # Reihenfolge = Einfügereihenfolge, JSON-Roundtrip erhält sie).
                surplus = len(auto_backends) - self.MAX_AUTO_BACKENDS
                ranked = sorted(auto_backends, key=lambda b: b.enabled)
                doomed = ranked[:surplus] if surplus > 0 else []
                reason = f"Pool-Deckel {self.MAX_AUTO_BACKENDS}"
            for ab in doomed:
                self.registry.remove(ab.name)
                self._health.pop(ab.name, None)
                log.info("Auto-Cleanup: '%s' entfernt (%s)", ab.name, reason)
            if doomed:
                await self._safe_notify(
                    f"🧹 *Auto-Cleanup*: {len(doomed)} temporäre Backend(s) entfernt – "
                    f"{reason}."
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
        """Backend testen, mit einem Retry bei transienten Codes.

        Messung 23.08.2026 gegen NVIDIA NIM: dasselbe Modell antwortete in
        vier Laeufen mit 2.4s / 2.1s / Timeout / 47.7s. Ein einzelner
        Probe-Versuch sagt unter solcher Provider-Last nichts ueber die
        Gesundheit des Backends aus - er erzeugt nur Fehlalarme. Ein
        zweiter Versuch kostet wenig und faengt den Grossteil davon ab.
        """
        code, msg = await self._probe_once(backend)
        if code in (408, 503):
            await asyncio.sleep(2)
            code2, msg2 = await self._probe_once(backend)
            if code2 is None:
                log.debug("Backend '%s': Probe-Retry erfolgreich (erst %s)",
                          backend.name, code)
                return None, ""
            return code2, msg2
        return code, msg

    async def _probe_once(self, backend) -> tuple[int | None, str]:
        """Ein einzelner Probe-Request. (None, "") = OK."""
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
                    timeout=aiohttp.ClientTimeout(
                        total=PROBE_TIMEOUT_TOTAL,
                        connect=PROBE_TIMEOUT_CONNECT,
                    ),
                ) as r:
                    if r.status == 200:
                        return None, ""
                    body = await r.text()
                    return r.status, body[:300]
        except TimeoutError:
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


def _read_last_discovery_ts() -> float:
    """Letzten Discovery-Zeitpunkt aus der Statusdatei lesen. 0.0 = unbekannt."""
    import json
    try:
        p = _status_file_path()
        if not p.exists():
            return 0.0
        return float(json.loads(p.read_text(encoding="utf-8")).get(
            "last_discovery_ts", 0.0
        ))
    except Exception as _e:
        log.debug("last_discovery_ts nicht lesbar: %s", _e)
        return 0.0


def write_status_file(monitor: "LLMHealthMonitor") -> None:
    """Schreibt aktuellen Monitor-Status in Datei (für API-Prozess lesbar).

    Atomarer Write: erst in <name>.tmp schreiben, dann os.replace().
    Verhindert korrupte JSON bei Crash mitten im Write.
    """
    import json
    import os
    import time as _time
    try:
        status = {
            "available": True,
            "ts": int(_time.time()),
            "backends": monitor.status_dict(),
            # Ueberlebt den Restart, damit die taegliche Discovery auch
            # taeglich laeuft und nicht bei jedem Neustart erneut.
            "last_discovery_ts": monitor._last_discovery_time,
        }
        p = _status_file_path()
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as _e:
        log.warning("write_status_file failed: %s", _e)


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

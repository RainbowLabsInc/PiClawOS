"""
Regressionstests für Melde-Disziplin und Provider-Auslastung.

Vorfall 23.08.2026: Der Nutzer bekam über Telegram permanent
"LLM Health Monitor"-Meldungen. Ursache war kein kaputtes Backend, sondern
eine Melde-Asymmetrie plus zu strenge Fehlerwertung:

  - NVIDIA NIM (Free-Tier) schwankt stark. Gemessen wurde dasselbe Modell in
    vier aufeinanderfolgenden Läufen mit 2.4s / 2.1s / Timeout / 47.7s, dazu
    503 "ResourceExhausted: Worker local total request limit reached (21/16)".
  - Der Probe-Timeout lag bei 15s → reguläre Antworten zählten als 408.
  - Ein einzelner solcher Blip erzeugte KEINE Störungsmeldung, im Folgezyklus
    aber eine Entwarnung "✅ wieder erreichbar" – 17 Nachrichten in zwei Tagen
    für Ausfälle, die nie gemeldet worden waren.
  - `nemotron-nvidia` war seit dem llama-4-End-of-Life dauerhaft deaktiviert,
    weil der Provider 410 statt 404 liefert und nur 404 den Auto-Repair anwirft.
"""

import time
import pytest
from unittest.mock import AsyncMock, patch


def _make_backend(name, **kw):
    from piclaw.llm.registry import BackendConfig

    defaults = dict(
        provider="openai",
        model="test-model",
        tags=["general"],
        priority=5,
        api_key="k",
        base_url="https://example.invalid/v1",
    )
    defaults.update(kw)
    return BackendConfig(name=name, **defaults)


@pytest.fixture
def registry(tmp_path):
    from piclaw.llm import registry as registry_mod

    with patch.object(registry_mod, "REGISTRY_FILE", tmp_path / "llm_registry.json"):
        yield registry_mod.LLMRegistry()


@pytest.fixture
def monitor(registry):
    from piclaw.llm.health_monitor import LLMHealthMonitor

    return LLMHealthMonitor(registry=registry, multirouter=None, notify=None)


# ── 1. Melde-Disziplin ────────────────────────────────────────────


class TestNotificationDiscipline:
    """Entwarnungen nur für Störungen, die auch gemeldet wurden."""

    @pytest.mark.asyncio
    async def test_transient_blip_sends_no_notification(self, registry):
        """Ein Fehler, der sich vor der Deaktivierung erledigt, ist kein Ereignis."""
        from piclaw.llm.health_monitor import LLMHealthMonitor

        notify = AsyncMock()
        mon = LLMHealthMonitor(registry=registry, multirouter=None, notify=notify)
        registry.add(_make_backend("openai-default", priority=7))

        mon._test_backend = AsyncMock(return_value=(500, "boom"))
        await mon.run_check()  # 1 Fehler, unter der Schwelle
        mon._test_backend = AsyncMock(return_value=(None, ""))
        await mon.run_check()  # wieder gesund

        assert registry.get("openai-default").enabled is True
        assert notify.await_count == 0, (
            "Ein einzelner Blip darf keine Meldung erzeugen - weder Störung "
            f"noch Entwarnung. Gesendet wurde: {notify.await_args_list}"
        )

    @pytest.mark.asyncio
    async def test_real_outage_gets_one_down_and_one_up(self, registry):
        """Deaktivierung meldet, Reaktivierung entwarnt - je genau einmal."""
        from piclaw.llm.health_monitor import LLMHealthMonitor

        notify = AsyncMock()
        mon = LLMHealthMonitor(registry=registry, multirouter=None, notify=notify)
        registry.add(_make_backend("openai-default", priority=7))

        mon._test_backend = AsyncMock(return_value=(500, "boom"))
        for _ in range(mon.failure_threshold):
            await mon.run_check()

        assert registry.get("openai-default").enabled is False
        assert notify.await_count == 1, "Genau eine Störungsmeldung erwartet"
        assert "deaktiviert" in notify.await_args_list[0].args[0]

        # Reaktivierung passiert erst im Retry-Zyklus
        mon._cycle_count = mon.DISABLED_RETRY_EVERY - 1
        mon._test_backend = AsyncMock(return_value=(None, ""))
        await mon.run_check()

        assert registry.get("openai-default").enabled is True
        assert notify.await_count == 2, "Genau eine Entwarnung erwartet"
        assert "wieder erreichbar" in notify.await_args_list[1].args[0]

    def test_report_success_closes_a_reported_outage(self, registry, monitor):
        """Ein echter Request, der wieder klappt, beendet die Meldung."""
        from piclaw.llm.health_monitor import BackendHealth

        registry.add(_make_backend("openai-default"))
        h = monitor._health.setdefault(
            "openai-default", BackendHealth("openai-default")
        )
        h.consecutive_failures = 3
        h.outage_notified = True

        sent = []
        monitor._notify_soon = lambda msg, name: sent.append(msg)
        monitor.report_success("openai-default")

        assert h.outage_notified is False
        assert len(sent) == 1 and "antwortet wieder normal" in sent[0], (
            "Ohne Entwarnung bleibt eine verschickte Störungsmeldung für den "
            "Nutzer dauerhaft offen."
        )

    def test_report_success_stays_quiet_without_reported_outage(
        self, registry, monitor
    ):
        from piclaw.llm.health_monitor import BackendHealth

        registry.add(_make_backend("openai-default"))
        h = monitor._health.setdefault(
            "openai-default", BackendHealth("openai-default")
        )
        h.consecutive_failures = 1  # Blip, nie gemeldet

        sent = []
        monitor._notify_soon = lambda msg, name: sent.append(msg)
        monitor.report_success("openai-default")

        assert sent == []


# ── 2. Auslastung ist kein Ausfall ────────────────────────────────


class TestCapacityErrorsAreNotOutages:
    def test_resource_exhausted_does_not_count_as_failure(self, registry, monitor):
        registry.add(_make_backend("openai-default"))

        monitor.report_error(
            "openai-default",
            503,
            "ResourceExhausted: Worker local total request limit reached (21/16)",
        )

        h = monitor._health["openai-default"]
        assert h.consecutive_failures == 0, (
            "NVIDIA meldet mit 503 einen überbuchten Shared-Worker. Als Strike "
            "gezählt deaktiviert das ein Backend, das Minuten später normal "
            "antwortet."
        )
        assert h.rate_limited_until > time.time(), "Backend muss zurückgestellt werden"

    @pytest.mark.parametrize("code", [502, 503, 504, 529])
    def test_overload_status_codes_are_capacity(self, registry, monitor, code):
        """529 kam am 23.08.2026 von NVIDIA und wurde nur ueber den
        Meldungstext erkannt - also nur, solange ein brauchbarer Body
        mitkommt. Der Status allein muss reichen."""
        registry.add(_make_backend("b%d" % code))
        monitor.report_error("b%d" % code, code, "")
        h = monitor._health["b%d" % code]
        assert h.consecutive_failures == 0
        assert h.rate_limited_until > time.time()

    def test_capacity_message_detected_without_503_status(self, registry, monitor):
        registry.add(_make_backend("groq-actions"))
        monitor.report_error("groq-actions", 500, "upstream connect: overloaded")
        assert monitor._health["groq-actions"].consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_run_check_backs_off_instead_of_disabling(self, registry, monitor):
        registry.add(_make_backend("openai-default"))
        monitor._test_backend = AsyncMock(
            return_value=(503, "ResourceExhausted: Worker local total request limit")
        )

        for _ in range(monitor.failure_threshold + 2):
            await monitor.run_check()

        assert registry.get("openai-default").enabled is True, (
            "Ein dauerhaft ausgelasteter Provider darf nicht zur Deaktivierung "
            "des Backends führen."
        )

    def test_genuine_server_error_still_counts(self, registry, monitor):
        registry.add(_make_backend("openai-default"))
        monitor.report_error("openai-default", 500, "internal server error")
        assert monitor._health["openai-default"].consecutive_failures == 1


# ── 3. Probe-Retry ────────────────────────────────────────────────


class TestProbeRetry:
    """Unter Provider-Last sagt ein einzelner Probe-Versuch nichts aus."""

    @pytest.mark.asyncio
    async def test_timeout_then_success_counts_as_healthy(self, registry, monitor):
        registry.add(_make_backend("openai-default"))
        monitor._probe_once = AsyncMock(side_effect=[(408, "Timeout"), (None, "")])

        code, _ = await monitor._test_backend(registry.get("openai-default"))

        assert code is None, (
            "Gemessen: dasselbe Modell antwortete in vier Läufen mit "
            "2.4s/2.1s/Timeout/47.7s. Ein Retry fängt genau diesen Fall ab."
        )
        assert monitor._probe_once.await_count == 2

    @pytest.mark.asyncio
    async def test_hard_error_is_not_retried(self, registry, monitor):
        registry.add(_make_backend("openai-default"))
        monitor._probe_once = AsyncMock(return_value=(404, "model_not_found"))

        code, _ = await monitor._test_backend(registry.get("openai-default"))

        assert code == 404
        assert monitor._probe_once.await_count == 1, "404 ist eindeutig"


# ── 4. End-of-Life-Modelle ────────────────────────────────────────


class TestEndOfLifeModel:
    """HTTP 410 = Modell ausgemustert, fachlich identisch zu 404."""

    @pytest.mark.asyncio
    async def test_410_triggers_auto_repair(self, registry, monitor):
        registry.add(
            _make_backend(
                "nemotron-nvidia",
                model="meta/llama-4-maverick-17b-128e-instruct",
                base_url="https://integrate.api.nvidia.com/v1",
            )
        )
        monitor._test_backend = AsyncMock(
            return_value=(410, "Gone: the model has reached its end of life")
        )
        monitor._auto_repair_404 = AsyncMock(return_value="meta/llama-3.3-70b-instruct")

        await monitor.run_check()

        monitor._auto_repair_404.assert_awaited_once()
        assert registry.get("nemotron-nvidia").enabled is True

    @pytest.mark.asyncio
    async def test_disabled_backend_with_dead_model_gets_repaired(
        self, registry, monitor
    ):
        """Deaktiviert + Modell weg = Probe kann nie gruen werden.

        Der Disabled-Zweig loggte nur "bleibt deaktiviert" und suchte nie
        einen Ersatz - 'nemotron-nvidia' war dadurch dauerhaft tot.
        """
        registry.add(
            _make_backend(
                "nemotron-nvidia",
                enabled=False,
                model="meta/llama-4-maverick-17b-128e-instruct",
                base_url="https://integrate.api.nvidia.com/v1",
            )
        )

        async def _probe(backend):
            # Erst 410 (totes Modell), nach dem Repair gruen
            if backend.model == "meta/llama-4-maverick-17b-128e-instruct":
                return 410, "Gone: end of life"
            return None, ""

        async def _repair(backend):
            registry.update(backend.name, model="meta/llama-3.3-70b-instruct")
            return "meta/llama-3.3-70b-instruct"

        monitor._test_backend = _probe
        monitor._auto_repair_404 = _repair
        await monitor.run_check()

        b = registry.get("nemotron-nvidia")
        assert b.enabled is True, "Nach erfolgreichem Repair muss reaktiviert werden"
        assert b.model == "meta/llama-3.3-70b-instruct"

    @pytest.mark.asyncio
    async def test_disabled_backend_stays_disabled_without_replacement(
        self, registry, monitor
    ):
        registry.add(_make_backend("nemotron-nvidia", enabled=False))
        monitor._test_backend = AsyncMock(return_value=(410, "Gone"))
        monitor._auto_repair_404 = AsyncMock(return_value=None)

        await monitor.run_check()

        assert registry.get("nemotron-nvidia").enabled is False

    def test_multirouter_extracts_410(self):
        from piclaw.llm.multirouter import MultiLLMRouter

        code = MultiLLMRouter._extract_error_code(
            MultiLLMRouter, Exception("Error code: 410 - model reached end of life")
        )
        assert code == 410

    def test_nvidia_whitelist_has_no_retired_models(self):
        """Die EOL-Modelle dürfen nicht zurück in die Whitelist wandern -
        sonst repariert der Auto-Repair auf ein totes Modell."""
        from piclaw.llm.health_monitor import _FREE_TIER_MODELS

        nvidia = _FREE_TIER_MODELS["integrate.api.nvidia.com"]
        for retired in (
            "meta/llama-4-maverick-17b-128e-instruct",
            "meta/llama-4-scout-17b-16e-instruct",
        ):
            assert retired not in nvidia, f"{retired} ist seit 07/2026 EOL (410)"
        assert "nvidia/llama-3_1-nemotron-ultra-253b-v1" not in nvidia, (
            "Unterstrich-Schreibweise konnte nie gegen den Katalog matchen"
        )


# ── 5. Alarm-Schwelle ─────────────────────────────────────────────


class TestAllBackendsDownThreshold:
    def test_single_failure_per_backend_is_not_an_outage(self, registry, monitor):
        for name in ("openai-default", "groq-actions", "groq-fallback"):
            registry.add(_make_backend(name))

        sent = []
        monitor._notify_soon = lambda msg, name: sent.append(msg)
        monitor.notify = AsyncMock()

        for name in ("openai-default", "groq-actions", "groq-fallback"):
            monitor.report_error(name, 500, "boom")

        assert sent == [], (
            "Mit Schwelle >=1 löste ein einzelner Fehler je Backend den Alarm "
            "samt Auto-Discovery aus - an ausgelasteten Providern ein Dauerzustand."
        )

    @pytest.mark.asyncio
    async def test_alarm_still_fires_when_all_backends_are_really_down(
        self, registry, monitor
    ):
        for name in ("openai-default", "groq-actions"):
            registry.add(_make_backend(name))

        sent = []
        monitor._notify_soon = lambda msg, name: sent.append(msg)
        monitor.notify = AsyncMock()

        for _ in range(monitor.failure_threshold):
            for name in ("openai-default", "groq-actions"):
                monitor.report_error(name, 500, "boom")

        assert any("ALLE API-Backends down" in m for m in sent)


# ── 6. Retry-After-Parsing ────────────────────────────────────────


class TestRetryAfterParsing:
    """Groq nennt die Wartezeit mal mit, mal ohne Minuten-Anteil.

    Beobachtet 23.08.2026 direkt nach einem Restart: Groq antwortete mit
    "Please try again in 6.765s", die Regex verlangte aber zwingend einen
    "Xm"-Anteil. Kein Match, kein Header -> Default 10min. Damit stand
    'groq-actions' (Prio 10, der schnelle Pfad fuer deutsche Aktionen) fuer
    600 Sekunden auf Prio 0, obwohl es nach 7 Sekunden wieder bereit war.
    """

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("Please try again in 6.765s.", 6.765),
            ("try again in 12s", 12.0),
            ("try again in 5m45.6s", 345.6),
            ("try again in 2m0s", 120.0),
            ("retry-after: 360", 360.0),
        ],
    )
    def test_parses_both_groq_formats(self, monitor, msg, expected):
        assert monitor._parse_retry_after(msg) == pytest.approx(expected)

    def test_unknown_format_falls_back_to_default(self, monitor):
        assert monitor._parse_retry_after("slow down") == 600

    def test_short_rate_limit_does_not_park_backend_for_ten_minutes(
        self, registry, monitor
    ):
        registry.add(_make_backend("groq-actions", priority=10))

        monitor.report_error(
            "groq-actions",
            429,
            "Rate limit reached for model `openai/gpt-oss-120b` on tokens per "
            "minute (TPM): Limit 8000, Used 4542, Requested 4360. Please try "
            "again in 6.765s.",
        )

        h = monitor._health["groq-actions"]
        wait = h.rate_limited_until - time.time()
        assert wait < 30, (
            f"Sperre von {wait:.0f}s fuer ein 6.8s-Rate-Limit - der schnelle "
            "Aktions-Pfad faellt dadurch unnoetig lange aus."
        )
        assert registry.get("groq-actions").original_priority == 10, (
            "Ohne persistierte original_priority bleibt das Backend nach "
            "einem Restart dauerhaft auf Prio 0."
        )


# ── 7. Discovery-Zeitstempel ueberlebt den Restart ────────────────


class TestDiscoveryTimestampPersists:
    """Die "taegliche" Discovery lief bei JEDEM Neustart.

    `_last_discovery_time` stand nach dem Start auf 0.0, also war
    `time.time() - 0 > 86400` immer wahr. Beobachtet 23.08.2026: zwei
    Service-Restarts kurz nacheinander loesten zwei volle Discovery-Runden
    aus (~10 Test-Calls gegen die Provider) und legten einen auto-*-Pool an,
    den der Cleanup erst im naechsten Zyklus - bis zu eine Stunde spaeter -
    abraeumt. Genau so wuchs der Pool am 25.07.2026 auf 16 Eintraege.
    """

    def test_timestamp_is_written_to_status_file(self, registry, monitor, tmp_path):
        from piclaw.llm import health_monitor as hm

        monitor._last_discovery_time = 1_700_000_000.0
        target = tmp_path / "llm_health_status.json"

        with patch.object(hm, "_status_file_path", lambda: target):
            hm.write_status_file(monitor)

        import json

        assert json.loads(target.read_text())["last_discovery_ts"] == 1_700_000_000.0

    def test_timestamp_is_restored_on_boot(self, registry, tmp_path):
        import json
        from piclaw.llm import health_monitor as hm

        target = tmp_path / "llm_health_status.json"
        target.write_text(json.dumps({"last_discovery_ts": 1_700_000_000.0}))

        with patch.object(hm, "_status_file_path", lambda: target):
            fresh = hm.LLMHealthMonitor(
                registry=registry, multirouter=None, notify=None
            )

        assert fresh._last_discovery_time == 1_700_000_000.0, (
            "Ohne den persistierten Wert laeuft nach jedem Restart eine "
            "volle Discovery-Runde."
        )

    def test_missing_status_file_is_not_fatal(self, registry, tmp_path):
        from piclaw.llm import health_monitor as hm

        with patch.object(hm, "_status_file_path", lambda: tmp_path / "weg.json"):
            fresh = hm.LLMHealthMonitor(
                registry=registry, multirouter=None, notify=None
            )

        assert fresh._last_discovery_time == 0.0

    def test_corrupt_status_file_is_not_fatal(self, registry, tmp_path):
        from piclaw.llm import health_monitor as hm

        target = tmp_path / "llm_health_status.json"
        target.write_text("{kaputt")

        with patch.object(hm, "_status_file_path", lambda: target):
            fresh = hm.LLMHealthMonitor(
                registry=registry, multirouter=None, notify=None
            )

        assert fresh._last_discovery_time == 0.0

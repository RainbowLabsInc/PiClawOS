"""
Regressionstests für die LLM-Backend-Selbstheilung.

Hintergrund (Vorfall 24./25.07.2026): Auf dem Pi waren alle fünf statischen
Backends `enabled: false`, im Betrieb lief nur noch ein auto-discovered
Llama-3.1-8B. Ursache war eine Selbstverriegelung aus drei Teilen:

  1. `run_check` übersprang deaktivierte Backends komplett → sie wurden nie
     wieder getestet und konnten nie reaktiviert werden.
  2. Der einzige Re-Enable-Pfad hing am In-Memory-`BackendHealth`, das ein
     Service-Restart verwirft.
  3. Der Auto-Discovery-Cleanup war an `non_auto_recovered` gekoppelt – wenn
     nichts recovern kann, läuft er nie, und der Auto-Pool wuchs auf 16.

Dazu kam HTTP 413 ("Request too large", Groq-Free-Tier TPM 8000 gegen ~11k
Prompt-Tokens), das als generischer 500er gezählt wurde und gesunde Backends
in die Deaktivierung trieb.
"""

import time
import pytest
from unittest.mock import AsyncMock, patch


# ── Helpers ───────────────────────────────────────────────────────


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
    """Frische LLMRegistry auf tmp_path (conftest patcht REGISTRY_FILE global,
    hier zusätzlich pro Test isoliert)."""
    from piclaw.llm import registry as registry_mod

    with patch.object(registry_mod, "REGISTRY_FILE", tmp_path / "llm_registry.json"):
        yield registry_mod.LLMRegistry()


@pytest.fixture
def monitor(registry):
    from piclaw.llm.health_monitor import LLMHealthMonitor

    return LLMHealthMonitor(registry=registry, multirouter=None, notify=None)


# ── 1. Recovery deaktivierter Backends ────────────────────────────


class TestDisabledBackendRecovery:
    """Der Kern-Bug: einmal deaktiviert = für immer tot."""

    @pytest.mark.asyncio
    async def test_disabled_backend_is_reenabled_after_successful_probe(
        self, registry, monitor
    ):
        registry.add(_make_backend("groq-actions", enabled=False, priority=10))

        monitor._test_backend = AsyncMock(return_value=(None, ""))
        await monitor.run_check()

        assert registry.get("groq-actions").enabled is True, (
            "Ein deaktiviertes Backend, das auf einen Probe-Call antwortet, "
            "muss reaktiviert werden – sonst bleibt es dauerhaft tot."
        )

    @pytest.mark.asyncio
    async def test_disabled_backend_stays_disabled_when_probe_fails(
        self, registry, monitor
    ):
        registry.add(_make_backend("groq-fallback", enabled=False))

        monitor._test_backend = AsyncMock(return_value=(404, "model_not_found"))
        await monitor.run_check()

        assert registry.get("groq-fallback").enabled is False

    @pytest.mark.asyncio
    async def test_first_cycle_after_boot_always_probes(self, registry, monitor):
        """Ein Restart soll Recovery beschleunigen, nicht verhindern."""
        registry.add(_make_backend("openai-default", enabled=False))

        monitor._test_backend = AsyncMock(return_value=(None, ""))
        assert monitor._cycle_count == 0
        await monitor.run_check()

        assert monitor._cycle_count == 1
        assert monitor._test_backend.await_count == 1
        assert registry.get("openai-default").enabled is True

    @pytest.mark.asyncio
    async def test_disabled_backend_not_probed_every_cycle(self, registry, monitor):
        """Zwischen den Proben liegen DISABLED_RETRY_EVERY Zyklen – ein
        dauerhaft kaputtes Backend darf nicht jeden Zyklus Netzwerk kosten."""
        registry.add(_make_backend("nemotron-nvidia", enabled=False))
        monitor._test_backend = AsyncMock(return_value=(500, "boom"))

        for _ in range(monitor.DISABLED_RETRY_EVERY):
            await monitor.run_check()

        # Zyklus 1 (Boot) und Zyklus DISABLED_RETRY_EVERY → genau 2 Proben
        assert monitor._test_backend.await_count == 2

    @pytest.mark.asyncio
    async def test_disabled_auto_backend_is_not_revived(self, registry, monitor):
        """auto-* sind Wegwerf-Reserve: der Cleanup entsorgt sie, der
        Recovery-Pfad belebt sie nicht wieder."""
        registry.add(
            _make_backend(
                "auto-groq-gpt-oss-20b",
                enabled=False,
                tags=["general", "auto-discovered"],
            )
        )
        monitor._test_backend = AsyncMock(return_value=(None, ""))
        await monitor.run_check()

        remaining = registry.get("auto-groq-gpt-oss-20b")
        assert remaining is None or remaining.enabled is False


# ── 2. Persistierte Prioritäts-Parkung ────────────────────────────


class TestParkedPriorityPersistence:
    """original_priority muss einen Prozess-Restart überleben."""

    def test_rate_limit_persists_original_priority(self, registry, monitor):
        registry.add(_make_backend("groq-actions", priority=10))

        monitor._health.setdefault(
            "groq-actions",
            __import__(
                "piclaw.llm.health_monitor", fromlist=["BackendHealth"]
            ).BackendHealth(name="groq-actions"),
        )
        monitor._handle_rate_limit("groq-actions", "rate limit, try again in 1m0.0s")

        stored = registry.get("groq-actions")
        assert stored.priority == 0
        assert stored.original_priority == 10, (
            "Ohne persistierte original_priority bleibt die Priorität nach "
            "einem Restart dauerhaft auf 0."
        )

    @pytest.mark.asyncio
    async def test_healthy_backend_recovers_orphaned_parked_priority(
        self, registry, monitor
    ):
        """Restart-Szenario: Sperre abgelaufen, In-Memory-State leer,
        Priorität steht noch geparkt auf 0."""
        registry.add(
            _make_backend("groq-actions", priority=0, original_priority=10)
        )
        assert not monitor._health  # frischer Prozess

        monitor._test_backend = AsyncMock(return_value=(None, ""))
        await monitor.run_check()

        stored = registry.get("groq-actions")
        assert stored.priority == 10
        assert stored.original_priority is None

    @pytest.mark.asyncio
    async def test_reenabled_backend_restores_parked_priority(
        self, registry, monitor
    ):
        registry.add(
            _make_backend(
                "openai-default", enabled=False, priority=0, original_priority=7
            )
        )
        monitor._test_backend = AsyncMock(return_value=(None, ""))
        await monitor.run_check()

        stored = registry.get("openai-default")
        assert stored.enabled is True
        assert stored.priority == 7
        assert stored.original_priority is None


# ── 3. HTTP 413 – Kapazitätsgrenze, kein Ausfall ──────────────────


_GROQ_413 = (
    "OpenAI/NIM API error 413: {\"error\":{\"message\":\"Request too large for "
    "model `openai/gpt-oss-120b` in organization `org_x` service tier "
    "`on_demand` on tokens per minute (TPM): Limit 8000, Requested 11122, "
    "please reduce your message size and try again.\",\"type\":\"tokens\","
    "\"code\":\"rate_limit_exceeded\"}}"
)


class TestRequestTooLarge:

    def test_413_records_budget_and_does_not_count_as_failure(
        self, registry, monitor
    ):
        registry.add(_make_backend("auto-groq-qwen3-32b"))

        monitor.report_error("auto-groq-qwen3-32b", 413, _GROQ_413)

        assert registry.get("auto-groq-qwen3-32b").max_input_tokens == 8000
        assert monitor._health["auto-groq-qwen3-32b"].consecutive_failures == 0, (
            "413 ist eine Kapazitätsgrenze. Als Ausfall gezählt deaktiviert "
            "der Monitor nach drei Versuchen ein gesundes Backend."
        )

    def test_413_does_not_park_priority(self, registry, monitor):
        registry.add(_make_backend("auto-groq-qwen3-32b", priority=4))
        monitor.report_error("auto-groq-qwen3-32b", 413, _GROQ_413)
        stored = registry.get("auto-groq-qwen3-32b")
        assert stored.priority == 4
        assert stored.original_priority is None

    def test_413_without_parsable_limit_is_ignored(self, registry, monitor):
        registry.add(_make_backend("x"))
        monitor.report_error("x", 413, "Request too large, no numbers here")
        assert registry.get("x").max_input_tokens == 0

    def test_extract_error_code_recognises_413(self):
        from piclaw.llm.multirouter import MultiLLMRouter

        code = MultiLLMRouter._extract_error_code(None, Exception(_GROQ_413))
        assert code == 413, (
            "Ohne 413-Erkennung landet der Fehler im generischen 500-Zweig "
            "und zählt in die Deaktivierung."
        )


class TestPromptBudgetSkip:

    def test_estimate_counts_tool_definitions(self):
        from piclaw.llm.base import Message, ToolDefinition
        from piclaw.llm.multirouter import estimate_prompt_tokens

        msgs = [Message(role="user", content="x" * 400)]
        bare = estimate_prompt_tokens(msgs)
        with_tools = estimate_prompt_tokens(
            msgs,
            [
                ToolDefinition(
                    name="agent_remove",
                    description="d" * 400,
                    parameters={"type": "object", "properties": {}},
                )
            ],
        )
        assert with_tools > bare, (
            "Die Tool-Schemas machen den Großteil des PiClaw-Prompts aus und "
            "müssen in die Schätzung eingehen."
        )

    def test_estimate_survives_unserialisable_parameters(self):
        from piclaw.llm.base import Message, ToolDefinition
        from piclaw.llm.multirouter import estimate_prompt_tokens

        tool = ToolDefinition(
            name="t", description="d", parameters={"bad": object()}
        )
        assert estimate_prompt_tokens([Message(role="user", content="hi")], [tool]) > 0


# ── 4. Auto-Discovery-Cleanup ─────────────────────────────────────


class TestAutoCleanup:

    @pytest.mark.asyncio
    async def test_full_purge_when_original_backend_healthy(
        self, registry, monitor
    ):
        registry.add(_make_backend("groq-actions", priority=10))
        for i in range(3):
            registry.add(
                _make_backend(
                    f"auto-groq-{i}", tags=["general", "auto-discovered"]
                )
            )

        monitor._test_backend = AsyncMock(return_value=(None, ""))
        await monitor.run_check()

        names = {b.name for b in registry.list_all()}
        assert names == {"groq-actions"}

    @pytest.mark.asyncio
    async def test_pool_is_capped_when_no_original_is_healthy(
        self, registry, monitor
    ):
        """Der Fall, der auf dem Pi zu 16 Backends führte: kein statisches
        Backend gesund, also lief der alte Cleanup nie."""
        registry.add(_make_backend("groq-actions", enabled=False))
        for i in range(8):
            registry.add(
                _make_backend(
                    f"auto-groq-{i}", tags=["general", "auto-discovered"]
                )
            )

        # Statisches Backend bleibt kaputt, auto-* antworten
        async def _probe(backend):
            return (None, "") if backend.name.startswith("auto-") else (500, "down")

        monitor._test_backend = _probe
        await monitor.run_check()

        autos = [b for b in registry.list_all() if b.name.startswith("auto-")]
        assert len(autos) == monitor.MAX_AUTO_BACKENDS

    @pytest.mark.asyncio
    async def test_cap_sacrifices_disabled_autos_first(self, registry, monitor):
        registry.add(_make_backend("groq-actions", enabled=False))
        for i in range(monitor.MAX_AUTO_BACKENDS):
            registry.add(
                _make_backend(
                    f"auto-live-{i}", tags=["general", "auto-discovered"]
                )
            )
        registry.add(
            _make_backend(
                "auto-dead-0", enabled=False, tags=["general", "auto-discovered"]
            )
        )

        async def _probe(backend):
            return (None, "") if backend.name.startswith("auto-") else (500, "down")

        monitor._test_backend = _probe
        await monitor.run_check()

        names = {b.name for b in registry.list_all()}
        assert "auto-dead-0" not in names
        assert len([n for n in names if n.startswith("auto-live-")]) == (
            monitor.MAX_AUTO_BACKENDS
        )

    @pytest.mark.asyncio
    async def test_no_autos_no_crash(self, registry, monitor):
        registry.add(_make_backend("groq-actions"))
        monitor._test_backend = AsyncMock(return_value=(None, ""))
        await monitor.run_check()
        assert {b.name for b in registry.list_all()} == {"groq-actions"}


# ── 5. Registry-Feld-Kompatibilität ───────────────────────────────


class TestBackendConfigCompat:
    """Alte llm_registry.json-Dateien kennen die neuen Felder nicht."""

    def test_legacy_json_without_new_fields_loads(self, tmp_path):
        import json
        from piclaw.llm import registry as registry_mod

        legacy = {
            "groq-actions": {
                "name": "groq-actions",
                "provider": "openai",
                "model": "llama-3.3-70b-versatile",
                "tags": ["action", "german"],
                "priority": 10,
                "enabled": True,
            }
        }
        f = tmp_path / "llm_registry.json"
        f.write_text(json.dumps(legacy), encoding="utf-8")

        with patch.object(registry_mod, "REGISTRY_FILE", f):
            reg = registry_mod.LLMRegistry()
            b = reg.get("groq-actions")
            assert b is not None
            assert b.original_priority is None
            assert b.max_input_tokens == 0

    def test_string_values_are_coerced(self):
        b = _make_backend("x", max_input_tokens="8000", original_priority="7")
        assert b.max_input_tokens == 8000
        assert b.original_priority == 7

    def test_update_can_clear_parked_priority(self, registry):
        registry.add(_make_backend("x", original_priority=7))
        registry.update("x", original_priority=None)
        assert registry.get("x").original_priority is None


# ── 6. Groq-Whitelist ─────────────────────────────────────────────


def test_groq_whitelist_has_no_retired_models():
    """llama-4-scout war das Modell von groq-fallback und liefert seit
    Juli 2026 404 – es darf nicht in der Auto-Repair-Whitelist stehen,
    sonst repariert der Monitor auf ein totes Modell."""
    from piclaw.llm.health_monitor import _FREE_TIER_MODELS

    groq = _FREE_TIER_MODELS["api.groq.com"]
    assert "meta-llama/llama-4-scout-17b-16e-instruct" not in groq
    assert "qwen/qwen3-32b" not in groq
    assert "llama-3.3-70b-versatile" in groq

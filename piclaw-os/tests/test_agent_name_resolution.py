"""
Regressionstests für die Sub-Agent-Namensauflösung.

Vorfall 24./25.07.2026: Ein Monitoring-Agent für "Schweißgeräten Rosengarten"
landete als `Monitor_SchweigertenRosengar` in der Registry – die
Namensgenerierung filterte Umlaute ersatzlos weg. Danach war er per Chat nicht
mehr löschbar:

  24.07 15:12:04  "Lösche Monitor Schweißgerät"  → Shortcut nahm "Monitor"
  24.07 15:12:15  "Lösche Schweißgerät"          → LLM rief sensor_remove
  25.07 18:11:28  (Web-UI)                        → Shortcut nahm "Agent"
  25.07 18:11:35  "1c696495"                      → erst über die ID ging es

Drei Ursachen, hier alle abgedeckt: verlustbehaftete Namensgenerierung,
ein Shortcut der generische Substantive greift und hart abbricht, und eine
Registry die nur exakt vergleicht.
"""

import pytest
from unittest.mock import patch


# ── Transliteration ───────────────────────────────────────────────


class TestTransliteration:

    def test_umlauts_are_expanded_not_dropped(self):
        from piclaw.textutils import ascii_name

        assert ascii_name("Schweißgeräte") == "Schweissgeraete"

    def test_the_actual_incident_name(self):
        """Der Name, der real in der Registry landete."""
        from piclaw.textutils import ascii_name

        query = "Schweißgeräten Rosengarten"
        words = query.split()[:2]
        got = ascii_name(" ".join(words).title().replace(" ", ""))
        assert got != "SchweigertenRosengar"
        assert got.startswith("Schweissgeraeten")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Müller", "Mueller"),
            ("Köln", "Koeln"),
            ("Århus", "Aarhus"),
            ("Málaga", "Malaga"),
            ("Besançon", "Besancon"),
            ("Ærø", "Aeroe"),
        ],
    )
    def test_european_place_names(self, raw, expected):
        from piclaw.textutils import ascii_name

        assert ascii_name(raw) == expected

    def test_max_len_is_respected(self):
        from piclaw.textutils import ascii_name

        assert len(ascii_name("Schweißgeräte", max_len=5)) == 5

    def test_empty_and_pure_symbols(self):
        from piclaw.textutils import ascii_name, normalize

        assert ascii_name("") == ""
        assert ascii_name("!!!###") == ""
        assert normalize("") == ""
        assert normalize(None) == ""

    def test_normalize_makes_variants_comparable(self):
        from piclaw.textutils import normalize

        forms = [
            "Monitor_Schweissgeraete",
            "monitor schweißgeräte",
            "MONITOR-SCHWEISSGERAETE",
            "MonitorSchweissgeraete",
        ]
        assert len({normalize(f) for f in forms}) == 1


# ── Registry-Auflösung ────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path):
    from piclaw.agents import sa_registry as mod

    with patch.object(mod, "SA_REGISTRY_FILE", tmp_path / "subagents.json"):
        yield mod.SubAgentRegistry()


def _add(registry, name):
    from piclaw.agents.sa_registry import SubAgentDef

    agent = SubAgentDef(
        name=name, description=f"{name} desc", mission="m", tools=[]
    )
    registry.add(agent)
    return agent


class TestRegistryResolution:

    def test_exact_id_and_name_still_win(self, registry):
        a = _add(registry, "Monitor_Pakete")
        assert registry.get(a.id) is not None
        assert registry.get("Monitor_Pakete").id == a.id
        assert registry.get("monitor_pakete").id == a.id

    def test_umlaut_query_finds_transliterated_agent(self, registry):
        a = _add(registry, "Monitor_Schweissgeraete")
        assert registry.get("Monitor_Schweißgeräte").id == a.id
        assert registry.get("monitor schweißgeräte").id == a.id

    def test_substring_resolves_the_incident_case(self, registry):
        """Genau der Fall vom 24.07.: Nutzer sagt "Schweißgerät",
        der Agent heißt Monitor_SchweissgeraetenRosengarten."""
        a = _add(registry, "Monitor_SchweissgeraetenRosengarten")
        assert registry.get("Schweissgeraeten").id == a.id
        assert registry.get("Schweißgeräten").id == a.id

    def test_ambiguous_substring_returns_none_instead_of_guessing(self, registry):
        _add(registry, "Monitor_Makita")
        _add(registry, "Monitor_MakitaAkku")
        assert registry.get("Makita") is None, (
            "Bei Mehrdeutigkeit darf nicht geraten werden – sonst löscht der "
            "Shortcut den falschen Agenten."
        )

    def test_find_candidates_lists_ambiguous_matches(self, registry):
        _add(registry, "Monitor_Makita")
        _add(registry, "Monitor_MakitaAkku")
        names = {a.name for a in registry.find_candidates("Makita")}
        assert names == {"Monitor_Makita", "Monitor_MakitaAkku"}

    def test_unknown_name_resolves_to_none(self, registry):
        _add(registry, "Monitor_Pakete")
        assert registry.get("Waschmaschine") is None
        assert registry.find_candidates("Waschmaschine") == []

    def test_empty_needle_is_not_a_wildcard(self, registry):
        _add(registry, "Monitor_Pakete")
        assert registry.get("") is None
        assert registry.get("!!!") is None
        assert registry.find_candidates("") == []

    def test_remove_via_resolved_name(self, registry):
        _add(registry, "Monitor_SchweissgeraetenRosengarten")
        agent = registry.get("Schweißgeräten")
        assert registry.remove(agent.id) is True
        assert registry.get("Schweißgeräten") is None


# ── Shortcut-Kandidatenerkennung ──────────────────────────────────


class _FakeRegistry:
    """Minimal-Registry, die nur die Namensauflösung nachbildet."""

    def __init__(self, names):
        from piclaw.textutils import normalize

        self._names = list(names)
        self._normalize = normalize

    def get(self, needle):
        if not needle:
            return None
        n = self._normalize(needle)
        if not n:
            return None
        exact = [x for x in self._names if self._normalize(x) == n]
        if exact:
            return object()
        matches = [x for x in self._names if n in self._normalize(x)]
        return object() if len(matches) == 1 else None


def _resolve(names, text):
    """Ruft Agent._resolve_agent_reference ohne vollen Agent-Aufbau auf."""
    from piclaw.agent import Agent

    fake = object.__new__(Agent)
    fake.sa_registry = _FakeRegistry(names)
    return Agent._resolve_agent_reference(fake, text)


class TestShortcutCandidateResolution:

    def test_generic_noun_is_not_taken_as_agent_name(self):
        """Der Kern-Bug: "Agenten"/"Monitor" wurden als Agentname genommen."""
        assert _resolve(["Monitor_Pakete"], "Lösche den Schweißgeräte Agenten") is None
        assert _resolve(["Monitor_Pakete"], "Lösche Monitor Schweißgerät") is None

    def test_umlaut_name_is_recognised_as_candidate(self):
        """Der alte Regex brach an ß/ä ab, das Wort kandidierte gar nicht."""
        got = _resolve(
            ["Monitor_SchweissgeraetenRosengarten"],
            "Lösche den Schweißgeräte Agenten",
        )
        assert got is not None
        assert "Schwei" in got

    def test_explicit_monitor_name_wins(self):
        got = _resolve(["Monitor_Pakete"], "stoppe Monitor_Pakete bitte")
        assert got == "Monitor_Pakete"

    def test_agent_id_is_recognised(self):
        """Der Weg, der am 25.07. als einziger funktionierte."""
        assert _resolve(["1c696495"], "lösch 1c696495") == "1c696495"

    def test_unresolvable_returns_none_so_caller_falls_through_to_llm(self):
        assert _resolve(["Monitor_Pakete"], "Lösche den Waschmaschinen Agenten") is None

    def test_no_registry_is_handled(self):
        from piclaw.agent import Agent

        fake = object.__new__(Agent)
        fake.sa_registry = None
        assert Agent._resolve_agent_reference(fake, "lösche X") is None


class TestImperativeVerbIsNotTheAgentName:
    """Das Verb steht am Satzanfang und ist damit der erste Kandidat.

    Solange die Registry exakt verglich, ging das gut – seit sie tolerant
    per Substring auflöst (56dfd31), kann "Stoppe" auf einen Agenten
    passen, der gar nicht gemeint war.
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Lösche den Agenten Schweissgeraete", "Schweissgeraete"),
            ("Stoppe den Agenten CronJob_0715", "CronJob_0715"),
            ("Lösche den Sub-Agenten Wetter", "Wetter"),
            ("Loesche den Agenten Schweissgeraete", "Schweissgeraete"),
            ("Entferne bitte den Monitor Wetter", "Wetter"),
        ],
    )
    def test_named_agent_wins_over_verb_and_noun(self, text, expected):
        names = ["Schweissgeraete", "CronJob_0715", "Wetter"]
        assert _resolve(names, text) == expected

    def test_verb_does_not_hit_an_unrelated_agent(self):
        """"Stoppe" ist Substring von "Monitor_Stoppelfeld" – ohne
        Verb-Filter würde der falsche Agent gestoppt."""
        names = ["Monitor_Stoppelfeld", "Monitor_Wetter"]
        assert _resolve(names, "Stoppe den Agenten Wetter") == "Wetter"


class TestLowercaseInput:
    """Per Telegram kommt fast alles klein – Stufe 1 findet dort nichts."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("lösche den agenten schweissgeraete", "schweissgeraete"),
            ("loesche den agenten schweissgeraete", "schweissgeraete"),
            ("stoppe den agenten wetter", "wetter"),
            ("stopp monitor_wetter", "monitor_wetter"),
        ],
    )
    def test_lowercase_names_are_resolved(self, text, expected):
        names = ["Monitor_Schweissgeraete", "Monitor_Wetter"]
        assert _resolve(names, text) == expected

    def test_generic_only_input_still_falls_through_to_llm(self):
        assert _resolve(["Monitor_Wetter"], "lösche den agenten") is None
        assert _resolve(["Monitor_Wetter"], "stoppe bitte alles sofort") is None

    def test_uppercase_name_still_wins_over_lowercase_noise(self):
        """Stufe 1 vor Stufe 2: der Eigenname schlägt das Füllwort."""
        names = ["Monitor_Wetter", "Monitor_Pakete"]
        assert _resolve(names, "stoppe bitte den Wetter agenten") == "Wetter"


class TestRemoveKeywordAsciiVariant:
    """ASCII-Tastaturen schicken "Loesche" – das fiel komplett durch."""

    @pytest.mark.parametrize(
        "text",
        [
            "lösche den agenten wetter",
            "loesche den agenten wetter",
            "Loesche den Agenten Wetter",
            "entferne den agenten wetter",
            "delete agent wetter",
        ],
    )
    def test_remove_keyword_matches(self, text):
        from piclaw.agent import _RE_AGENT_REMOVE_KW

        assert _RE_AGENT_REMOVE_KW.search(text.lower()) is not None

    def test_remove_keyword_does_not_match_unrelated_text(self):
        from piclaw.agent import _RE_AGENT_REMOVE_KW

        assert _RE_AGENT_REMOVE_KW.search("wie ist das wetter") is None


# ── Schutz geschützter Agenten ────────────────────────────────────


class TestProtectedAgentsStillProtected:

    @pytest.mark.asyncio
    async def test_fuzzy_reference_cannot_bypass_protection(self, registry):
        """Die tolerante Auflösung darf den Schutz nicht aushebeln:
        "netzwerk" löst zu Monitor_Netzwerk auf und muss abgelehnt werden."""
        from piclaw.agents.sa_tools import build_handlers

        _add(registry, "Monitor_Netzwerk")

        class _Runner:
            _tasks = {}

            async def stop_agent(self, name):
                return "stopped"

        handlers = build_handlers(registry, _Runner())

        for probe in ("Monitor_Netzwerk", "netzwerk", "Netzwerk"):
            result = await handlers["agent_remove"](name=probe)
            assert "geschützter Sicherheits-Agent" in result, probe
            assert registry.get("Monitor_Netzwerk") is not None

            result = await handlers["agent_stop"](name=probe)
            assert "geschützter Sicherheits-Agent" in result, probe


# ── Selbstkorrigierende Fehlermeldungen ───────────────────────────


class TestSelfCorrectingErrors:

    @pytest.mark.asyncio
    async def test_not_found_lists_available_names(self, registry):
        from piclaw.agents.sa_tools import build_handlers

        _add(registry, "Monitor_Pakete")
        _add(registry, "Monitor_Makita")

        class _Runner:
            _tasks = {}

        handlers = build_handlers(registry, _Runner())
        result = await handlers["agent_remove"](name="Waschmaschine")

        assert "Monitor_Pakete" in result and "Monitor_Makita" in result, (
            "Ohne die Namensliste bleibt dem LLM nur Raten – am 24.07. wählte "
            "es daraufhin sensor_remove statt agent_remove."
        )

    @pytest.mark.asyncio
    async def test_ambiguous_name_reports_candidates(self, registry):
        from piclaw.agents.sa_tools import build_handlers

        _add(registry, "Monitor_Makita")
        _add(registry, "Monitor_MakitaAkku")

        class _Runner:
            _tasks = {}

        handlers = build_handlers(registry, _Runner())
        result = await handlers["agent_remove"](name="Makita")

        assert "nicht eindeutig" in result
        assert "Monitor_Makita" in result and "Monitor_MakitaAkku" in result

    @pytest.mark.asyncio
    async def test_empty_registry_message(self, registry):
        from piclaw.agents.sa_tools import build_handlers

        class _Runner:
            _tasks = {}

        handlers = build_handlers(registry, _Runner())
        result = await handlers["agent_remove"](name="Irgendwas")
        assert "keine Sub-Agenten definiert" in result


# ── Tool-Fehler-Logging ───────────────────────────────────────────


class TestToolFailureDetection:

    @pytest.mark.parametrize(
        "result",
        [
            "Sub-Agent 'Agenten' nicht gefunden.",
            "Sub-Agent 'Makita' ist nicht eindeutig. Gemeint sein könnte: …",
            "⛔ 'Monitor_Netzwerk' ist ein geschützter Sicherheits-Agent",
            "[sensor_remove error] no such sensor",
            "❌ Sub-agent runner not ready.",
        ],
    )
    def test_failures_are_detected(self, result):
        from piclaw.agent import _looks_like_tool_failure

        assert _looks_like_tool_failure(result) is True

    @pytest.mark.parametrize(
        "result",
        [
            "Sub-Agent 'Monitor_Pakete' gelöscht.",
            "Sub-Agents (3):\n  ✅ [abc123] Monitor_Pakete",
            "Temperatur: 47.2°C",
        ],
    )
    def test_successes_are_not_flagged(self, result):
        from piclaw.agent import _looks_like_tool_failure

        assert _looks_like_tool_failure(result) is False

    def test_empty_result_is_not_a_failure(self):
        from piclaw.agent import _looks_like_tool_failure

        assert _looks_like_tool_failure("") is False

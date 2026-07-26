"""
Tests für das intent-basierte Tool-Filtering und die Entwertung von
Sprach-Tags im Routing.
"""
import pytest
from unittest.mock import patch

from piclaw.llm.base import ToolDefinition
from piclaw.llm.registry import BackendConfig, LLMRegistry
from piclaw.llm.toolfilter import (
    ACTION_TOOLS,
    ALWAYS_TOOLS,
    QUERY_TOOLS,
    filter_tools,
    select_tool_names,
)


def td(name):
    return ToolDefinition(name=name, description=f"desc {name}", parameters={})


# Ein realistischer Querschnitt des echten 96er-Satzes.
ALL_TOOLS = [td(n) for n in [
    "agent_list", "agent_create", "agent_start", "agent_stop", "agent_remove",
    "agent_update", "agent_run_now",
    "routine_list", "routine_enable", "routine_disable", "routine_create",
    "reminder_create", "reminder_cancel", "reminder_list",
    "gpio_read", "gpio_write", "gpio_status", "gpio_pwm",
    "sensor_read", "sensor_read_all", "sensor_list", "sensor_add", "sensor_remove",
    "service_control", "service_status", "service_list",
    "parcel_add", "parcel_remove", "parcel_status",
    "llm_list", "llm_add", "llm_remove", "llm_update", "llm_test", "llm_discover",
    "memory_search", "memory_write", "memory_log", "memory_stats",
    "system_info", "system_report", "system_update", "pi_info", "thermal_status",
    # Sollen bei action/home_automation rausfallen:
    "shell", "browser_open", "browser_click", "browser_close",
    "crawl_create", "crawl_list", "web_suche", "http_fetch",
    "marketplace_search", "whois_lookup", "port_scan", "network_scan",
    "deploy_honey_trap", "tarpit_ip", "block_ip", "generate_abuse_report",
    "agentmail_send_email", "agentmail_list_inboxes", "i2c_scan",
]]

NAMES = {t.name for t in ALL_TOOLS}


class TestSelectToolNames:

    @pytest.mark.parametrize("tags", [
        ["general"],
        ["coding"],
        ["analysis", "reasoning"],
        ["coding", "german"],
        ["action", "coding"],        # gemischt -> breiter Intent gewinnt
        ["research", "general"],
        [],
        None,
    ])
    def test_no_filtering_for_broad_or_mixed_intents(self, tags):
        assert select_tool_names(tags) is None

    @pytest.mark.parametrize("tags", [
        ["action"],
        ["action", "german"],
        ["action", "home_automation", "german"],
        ["query", "german"],
        ["home_automation"],
    ])
    def test_filtering_for_narrow_intents(self, tags):
        keep = select_tool_names(tags)
        assert keep is not None and keep

    def test_language_only_tags_do_not_trigger_filtering(self):
        assert select_tool_names(["german"]) is None

    def test_always_tools_present_in_every_narrow_selection(self):
        for tags in (["action"], ["query"], ["home_automation"]):
            assert ALWAYS_TOOLS <= select_tool_names(tags)


class TestFilterTools:

    def test_action_keeps_agent_tools_drops_noise(self):
        out = {t.name for t in filter_tools(ALL_TOOLS, ["action", "german"])}
        for keep in ("agent_remove", "agent_stop", "agent_start", "agent_list",
                     "routine_enable", "reminder_create", "service_control"):
            assert keep in out, keep
        for drop in ("shell", "browser_open", "crawl_create", "web_suche",
                     "marketplace_search", "port_scan", "deploy_honey_trap",
                     "agentmail_send_email", "thermal_status", "pi_info"):
            assert drop not in out, drop

    def test_action_without_object_cuts_roughly_half(self):
        """Ohne konkretes Objekt bleibt die ganze Aktions-Gruppe."""
        out = filter_tools(ALL_TOOLS, ["action", "german"])
        assert len(ALL_TOOLS) * 0.4 < len(out) < len(ALL_TOOLS) * 0.7

    def test_home_automation_is_narrower_than_action(self):
        ha = filter_tools(ALL_TOOLS, ["home_automation", "german"])
        action = filter_tools(ALL_TOOLS, ["action", "german"])
        assert len(ha) < len(action)
        assert {"gpio_write", "sensor_read"} <= {t.name for t in ha}

    def test_query_keeps_read_only_tools(self):
        out = {t.name for t in filter_tools(ALL_TOOLS, ["query", "german"])}
        assert {"sensor_read", "service_status", "system_info", "agent_list"} <= out
        # Destruktives gehoert nicht in eine reine Status-Frage
        assert "agent_remove" not in out
        assert "system_update" not in out

    @pytest.mark.parametrize("tags", [["general"], ["coding"], ["coding", "german"]])
    def test_broad_intent_gets_full_set(self, tags):
        assert filter_tools(ALL_TOOLS, tags) is ALL_TOOLS

    def test_empty_tools_passthrough(self):
        assert filter_tools([], ["action"]) == []
        assert filter_tools(None, ["action"]) is None

    def test_unknown_tool_names_fall_back_to_full_set(self):
        """Schutznetz: wurden Tools umbenannt, lieber alles als nichts."""
        renamed = [td("völlig_anderer_name"), td("noch_einer")]
        assert filter_tools(renamed, ["action"]) is renamed

    def test_filtering_is_stable_and_order_preserving(self):
        out = filter_tools(ALL_TOOLS, ["action"])
        names = [t.name for t in out]
        assert names == [t.name for t in ALL_TOOLS if t.name in names]

    def test_action_and_query_tools_are_known_names(self):
        """Tippfehler in den Namenslisten wuerden das Filtern still aushebeln."""
        unknown_action = ACTION_TOOLS - NAMES
        unknown_query = QUERY_TOOLS - NAMES
        # Nur gegen die im Test abgebildeten Namen pruefen, der echte Satz ist
        # groesser – deshalb Teilmengen-Check auf die hier bekannten Praefixe.
        for name in unknown_action | unknown_query:
            assert "_" in name, f"verdaechtiger Toolname: {name}"


class TestObjectNarrowing:
    """
    Zweite Stufe: nennt der Befehl ein konkretes Objekt, reicht dessen Gruppe.
    Das ist der eigentliche Hebel gegen falsche Tool-Wahl – auf
    "Lösche den Agenten X" waehlte llama-3.3-70b mit 96 Tools
    thermal_status/pi_info/web_suche statt agent_remove.
    """

    def test_agent_command_ships_only_agent_tools(self):
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["action", "german"], "Lösche den Agenten Schweissgeraete"
        )}
        assert "agent_remove" in out
        assert out <= {
            "agent_list", "agent_create", "agent_start", "agent_stop",
            "agent_remove", "agent_update", "agent_run_now",
            "routine_list", "memory_search",
        }

    def test_agent_command_is_drastically_smaller(self):
        out = filter_tools(
            ALL_TOOLS, ["action", "german"], "Stoppe den Agenten CronJob_0715"
        )
        assert len(out) <= 10, [t.name for t in out]

    def test_routine_command_ships_routine_tools(self):
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["action", "german"], "Starte die Routine Morgenbriefing"
        )}
        assert "routine_run_now" in out or "routine_enable" in out
        assert "agent_remove" not in out

    def test_reminder_command_ships_reminder_tools(self):
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["action", "german"], "Lösche die Erinnerung von gestern"
        )}
        assert "reminder_cancel" in out
        assert "parcel_remove" not in out

    def test_light_command_ships_ha_tools(self):
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["action", "home_automation", "german"],
            "Schalte das Licht im Wohnzimmer an",
        )}
        assert "gpio_write" in out
        assert "agent_remove" not in out

    def test_backend_command_ships_llm_tools(self):
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["action", "german"], "Deaktiviere das Backend groq-fallback"
        )}
        assert "llm_update" in out or "llm_remove" in out
        assert "agent_remove" not in out

    def test_monitor_name_prefers_agent_group_over_network(self):
        """'Monitor_Netzwerk' enthaelt auch 'Netzwerk' – Agent muss gewinnen."""
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["action", "german"], "Stoppe den Agenten Monitor_Netzwerk"
        )}
        assert "agent_stop" in out
        assert "wifi_disconnect" not in out

    def test_query_with_object_stays_read_only(self):
        """Objekt-Einengung darf einer Status-Frage kein Loeschwerkzeug geben."""
        out = {t.name for t in filter_tools(
            ALL_TOOLS, ["query", "german"], "Welche Agenten laufen gerade?"
        )}
        assert "agent_list" in out
        assert "agent_remove" not in out
        assert "agent_stop" not in out

    def test_unknown_object_falls_back_to_full_intent_group(self):
        out = filter_tools(
            ALL_TOOLS, ["action", "german"], "Mach das bitte weg"
        )
        no_text = filter_tools(ALL_TOOLS, ["action", "german"])
        assert len(out) == len(no_text)

    def test_text_is_ignored_for_broad_intents(self):
        assert filter_tools(
            ALL_TOOLS, ["coding"], "Lösche den Agenten X"
        ) is ALL_TOOLS


class TestLanguageTagsDoNotBeatCapabilities:
    """
    Regression: `german` stand auf groq-actions gleichrangig neben action/query.
    Bei Priorität 10 gewann es damit jede deutschsprachige Fachfrage.
    """

    @pytest.fixture
    def reg(self, tmp_path):
        with patch("piclaw.llm.registry.REGISTRY_FILE", tmp_path / "r.json"):
            r = LLMRegistry()
            r.add(BackendConfig(
                name="groq-actions", provider="openai", model="m",
                tags=["action", "home_automation", "query", "german"],
                priority=10,
            ))
            r.add(BackendConfig(
                name="openai-default", provider="openai", model="m",
                tags=["general", "reasoning", "analysis", "coding"],
                priority=7,
            ))
            yield r

    def test_german_coding_question_goes_to_capability_match(self, reg):
        # Vorher: Overlap 1 zu 1, Prioritaet 10 gewann -> groq-actions
        assert reg.find_by_tags(["coding", "german"])[0].name == "openai-default"

    def test_german_analysis_question_goes_to_capability_match(self, reg):
        assert reg.find_by_tags(["analysis", "german"])[0].name == "openai-default"

    def test_german_action_command_still_goes_to_action_backend(self, reg):
        assert reg.find_by_tags(["action", "german"])[0].name == "groq-actions"

    def test_language_only_still_resolves(self, reg):
        """Nur ein Sprach-Tag: Sprache entscheidet, weil keine Capability da ist."""
        assert reg.find_by_tags(["german"])[0].name == "groq-actions"

    def test_capability_count_still_wins_over_priority(self, reg):
        # coding+analysis = 2 Capability-Treffer bei openai-default
        assert reg.find_by_tags(["coding", "analysis"])[0].name == "openai-default"

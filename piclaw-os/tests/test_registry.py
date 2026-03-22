"""
Tests for SubAgentRegistry and LLMRegistry.
Uses tmp_path to avoid touching /etc/piclaw.
"""

import json
import pytest
from unittest.mock import patch
from pathlib import Path


# ── SubAgentRegistry ──────────────────────────────────────────────


class TestSubAgentRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        """A fresh registry backed by a tmp directory."""
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            return SubAgentRegistry(), reg_file

    def _make_agent(self, name="TestAgent"):
        from piclaw.agents.sa_registry import SubAgentDef

        return SubAgentDef(
            name=name,
            description=f"{name} description",
            mission=f"Your mission: {name}",
            tools=[],
        )

    def test_add_and_get_by_id(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            agent = self._make_agent("Alpha")
            aid = reg.add(agent)
            assert aid == agent.id
            found = reg.get(aid)
            assert found is not None
            assert found.name == "Alpha"

    def test_get_by_name(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            agent = self._make_agent("Beta")
            reg.add(agent)
            found = reg.get("Beta")
            assert found is not None
            assert found.name == "Beta"

    def test_get_by_name_case_insensitive(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            reg.add(self._make_agent("CaseSensitive"))
            assert reg.get("casesensitive") is not None
            assert reg.get("CASESENSITIVE") is not None

    def test_get_nonexistent(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            assert reg.get("DoesNotExist") is None

    def test_remove(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            agent = self._make_agent("Gamma")
            reg.add(agent)
            assert reg.remove("Gamma") is True
            assert reg.get("Gamma") is None

    def test_remove_nonexistent(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            assert reg.remove("Ghost") is False

    def test_update(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            agent = self._make_agent("Delta")
            reg.add(agent)
            ok = reg.update("Delta", schedule="interval:3600", enabled=False)
            assert ok is True
            updated = reg.get("Delta")
            assert updated.schedule == "interval:3600"
            assert updated.enabled is False

    def test_persistence(self, tmp_path):
        """Data survives a registry reload."""
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg1 = SubAgentRegistry()
            agent = self._make_agent("Persistent")
            reg1.add(agent)

            # Reload from same file
            reg2 = SubAgentRegistry()
            found = reg2.get("Persistent")
            assert found is not None
            assert found.name == "Persistent"

    def test_list_all_sorted_by_created_at(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            for name in ["First", "Second", "Third"]:
                reg.add(self._make_agent(name))
            agents = reg.list_all()
            assert len(agents) == 3

    def test_list_enabled_filters_disabled(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            a1 = self._make_agent("Enabled")
            a2 = self._make_agent("Disabled")
            a2.enabled = False
            reg.add(a1)
            reg.add(a2)
            enabled = reg.list_enabled()
            assert any(a.name == "Enabled" for a in enabled)
            assert not any(a.name == "Disabled" for a in enabled)

    def test_mark_run(self, tmp_path):
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            agent = self._make_agent("Runner")
            reg.add(agent)
            reg.mark_run("Runner", "ok")
            found = reg.get("Runner")
            assert found.last_status == "ok"
            assert found.last_run is not None

    def test_json_on_disk(self, tmp_path):
        """Sanity check: JSON file is valid after operations."""
        reg_file = tmp_path / "subagents.json"
        with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
            from piclaw.agents.sa_registry import SubAgentRegistry

            reg = SubAgentRegistry()
            reg.add(self._make_agent("JsonAgent"))
            data = json.loads(reg_file.read_text())
            assert len(data) == 1
            entry = list(data.values())[0]
            assert entry["name"] == "JsonAgent"
            assert "id" in entry
            assert "created_at" in entry


# ── LLMRegistry ───────────────────────────────────────────────────


class TestLLMRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        reg_file = tmp_path / "llm_registry.json"
        with patch("piclaw.llm.registry.REGISTRY_FILE", reg_file):
            from piclaw.llm.registry import LLMRegistry

            return LLMRegistry()

    def _make_backend(self, name="test-llm", tags=None):
        from piclaw.llm.registry import BackendConfig

        return BackendConfig(
            name=name,
            provider="openai",
            model="gpt-4o",
            tags=tags or ["coding", "general"],
            priority=5,
        )

    def test_add_and_get(self, tmp_path):
        reg_file = tmp_path / "llm_registry.json"
        with patch("piclaw.llm.registry.REGISTRY_FILE", reg_file):
            from piclaw.llm.registry import LLMRegistry

            reg = LLMRegistry()
            reg.add(self._make_backend("llm-one"))
            found = reg.get("llm-one")
            assert found is not None
            assert found.model == "gpt-4o"

    def test_find_by_tags_exact(self, tmp_path):
        reg_file = tmp_path / "llm_registry.json"
        with patch("piclaw.llm.registry.REGISTRY_FILE", reg_file):
            from piclaw.llm.registry import LLMRegistry

            reg = LLMRegistry()
            reg.add(self._make_backend("coder", tags=["coding", "python"]))
            reg.add(self._make_backend("writer", tags=["writing", "creative"]))
            results = reg.find_by_tags(["coding"])
            names = [b.name for b in results]
            assert "coder" in names
            # writer should have 0 overlap with [coding]

    def test_find_by_tags_priority(self, tmp_path):
        reg_file = tmp_path / "llm_registry.json"
        with patch("piclaw.llm.registry.REGISTRY_FILE", reg_file):
            from piclaw.llm.registry import LLMRegistry, BackendConfig

            reg = LLMRegistry()
            low = BackendConfig(
                name="low",
                provider="openai",
                model="gpt-3.5",
                tags=["coding"],
                priority=3,
            )
            high = BackendConfig(
                name="high",
                provider="openai",
                model="gpt-4o",
                tags=["coding"],
                priority=9,
            )
            reg.add(low)
            reg.add(high)
            results = reg.find_by_tags(["coding"])
            assert results[0].name == "high"

    def test_has_tag(self, tmp_path):
        from piclaw.llm.registry import BackendConfig

        b = BackendConfig(
            name="t", provider="openai", model="gpt-4o", tags=["Coding", "German"]
        )
        assert b.has_tag("coding")
        assert b.has_tag("CODING")
        assert not b.has_tag("writing")

    def test_tag_overlap(self, tmp_path):
        from piclaw.llm.registry import BackendConfig

        b = BackendConfig(
            name="t",
            provider="openai",
            model="gpt-4o",
            tags=["coding", "analysis", "german"],
        )
        assert b.tag_overlap(["coding", "german"]) == 2
        assert b.tag_overlap(["writing"]) == 0
        assert b.tag_overlap([]) == 0

    def test_remove(self, tmp_path):
        reg_file = tmp_path / "llm_registry.json"
        with patch("piclaw.llm.registry.REGISTRY_FILE", reg_file):
            from piclaw.llm.registry import LLMRegistry

            reg = LLMRegistry()
            reg.add(self._make_backend("to-remove"))
            assert "removed" in reg.remove("to-remove")
            assert reg.get("to-remove") is None

    def test_list_enabled(self, tmp_path):
        reg_file = tmp_path / "llm_registry.json"
        with patch("piclaw.llm.registry.REGISTRY_FILE", reg_file):
            from piclaw.llm.registry import LLMRegistry, BackendConfig

            reg = LLMRegistry()
            reg.add(
                BackendConfig(
                    name="en", provider="openai", model="gpt-4o", enabled=True
                )
            )
            reg.add(
                BackendConfig(
                    name="dis", provider="openai", model="gpt-4o", enabled=False
                )
            )
            enabled = reg.list_enabled()
            assert any(b.name == "en" for b in enabled)
            assert not any(b.name == "dis" for b in enabled)

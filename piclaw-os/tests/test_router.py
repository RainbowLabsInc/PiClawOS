"""
Tests for LLM routing logic (MultiLLMRouter + LLMRegistry).
Uses mocked backends – no real LLM calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from piclaw.llm.registry import BackendConfig, LLMRegistry


def make_backend(name, tags, priority=5, enabled=True):
    return BackendConfig(
        name=name,
        provider="openai",
        model="gpt-4o",
        tags=tags,
        priority=priority,
        enabled=enabled,
    )


class TestBackendConfig:
    def test_has_tag_case_insensitive(self):
        b = make_backend("x", ["Coding", "GERMAN"])
        assert b.has_tag("coding")
        assert b.has_tag("german")
        assert not b.has_tag("writing")

    def test_tag_overlap_counts_correctly(self):
        b = make_backend("x", ["coding", "analysis", "german"])
        assert b.tag_overlap(["coding", "german", "writing"]) == 2
        assert b.tag_overlap([]) == 0
        assert b.tag_overlap(["math"]) == 0

    def test_tag_overlap_case_insensitive(self):
        b = make_backend("x", ["Coding"])
        assert b.tag_overlap(["CODING"]) == 1


class TestLLMRegistryFindByTags:
    @pytest.fixture
    def reg(self, tmp_path):
        with patch("piclaw.llm.registry.REGISTRY_FILE", tmp_path / "r.json"):
            from piclaw.llm.registry import LLMRegistry

            reg = LLMRegistry()
            reg.add(make_backend("coder", ["coding", "python"], priority=8))
            reg.add(make_backend("general", ["general"], priority=5))
            reg.add(make_backend("writer", ["writing", "creative"], priority=6))
            reg.add(make_backend("disabled", ["coding"], enabled=False))
            return reg

    def test_find_returns_matching_backends(self, reg):
        results = reg.find_by_tags(["coding"])
        names = [b.name for b in results]
        assert "coder" in names

    def test_disabled_backends_excluded(self, reg):
        results = reg.find_by_tags(["coding"])
        names = [b.name for b in results]
        assert "disabled" not in names

    def test_results_sorted_by_overlap_then_priority(self, reg):
        results = reg.find_by_tags(["coding"])
        # coder has more coding overlap and higher priority
        assert results[0].name == "coder"

    def test_empty_tags_returns_all_enabled(self, reg):
        results = reg.find_by_tags([])
        names = [b.name for b in results]
        assert "disabled" not in names
        assert len(names) >= 3

    def test_no_match_falls_back_to_all_enabled(self, reg):
        results = reg.find_by_tags(["nonexistent-tag"])
        # Should still return enabled backends
        assert len(results) >= 1


class TestClassifierRouterIntegration:
    """Smoke test: classifier → registry → backend selection."""

    def test_coding_request_routes_to_coder(self, tmp_path):
        with patch("piclaw.llm.registry.REGISTRY_FILE", tmp_path / "r.json"):
            from piclaw.llm.registry import LLMRegistry
            from piclaw.llm.classifier import TaskClassifier

            reg = LLMRegistry()
            reg.add(make_backend("coder", ["coding"], priority=9))
            reg.add(make_backend("general", ["general"], priority=3))

            clf = TaskClassifier()
            result = clf.classify_sync("Write a Python function to parse JSON")
            candidates = reg.find_by_tags(result.tags)

            assert len(candidates) >= 1
            # coder should be ranked first (highest overlap + priority)
            assert candidates[0].name == "coder"

    def test_general_request_still_gets_backend(self, tmp_path):
        with patch("piclaw.llm.registry.REGISTRY_FILE", tmp_path / "r.json"):
            from piclaw.llm.registry import LLMRegistry
            from piclaw.llm.classifier import TaskClassifier

            reg = LLMRegistry()
            reg.add(make_backend("general", ["general"], priority=5))

            clf = TaskClassifier()
            result = clf.classify_sync("hello there")
            candidates = reg.find_by_tags(result.tags)

            assert len(candidates) >= 1

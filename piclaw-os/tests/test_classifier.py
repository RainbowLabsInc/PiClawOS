"""
Tests for the Task Classifier (Stage 1 – pattern matching).
No LLM required – fully offline.
"""

import pytest
from piclaw.llm.classifier import TaskClassifier, ClassificationResult


@pytest.fixture
def clf():
    """Classifier without LLM (pattern-only)."""
    return TaskClassifier(llm_for_classification=None)


class TestPatternMatching:
    def test_coding_python(self, clf):
        r = clf.classify_sync("Write a Python function to read a CSV file")
        assert "coding" in r.tags
        assert r.confidence >= 0.80
        assert r.method == "pattern"

    def test_coding_build_api(self, clf):
        r = clf.classify_sync("Build a REST API endpoint using FastAPI")
        assert "coding" in r.tags

    def test_debugging(self, clf):
        r = clf.classify_sync("There's a traceback in my script, can you debug it?")
        assert "debugging" in r.tags
        assert r.confidence >= 0.80

    def test_debug_error_keyword(self, clf):
        r = clf.classify_sync("fix this error: AttributeError on line 42")
        assert "debugging" in r.tags

    def test_translation(self, clf):
        r = clf.classify_sync("translate this text to German")
        assert "translation" in r.tags
        assert r.confidence >= 0.85

    def test_translation_direction(self, clf):
        r = clf.classify_sync("Übersetze das auf Englisch")
        assert "translation" in r.tags

    def test_german_language_detection(self, clf):
        r = clf.classify_sync("Kannst du mir bitte helfen das zu verstehen?")
        assert "german" in r.tags

    def test_math(self, clf):
        r = clf.classify_sync("calculate the integral of x^2 from 0 to 1")
        assert "math" in r.tags

    def test_creative_writing(self, clf):
        r = clf.classify_sync("write a short poem about the sea")
        assert "creative" in r.tags or "writing" in r.tags

    def test_summarization(self, clf):
        r = clf.classify_sync("summarize this article for me")
        assert "summarization" in r.tags

    def test_analysis(self, clf):
        r = clf.classify_sync("compare the pros and cons of using SQLite vs PostgreSQL")
        assert "analysis" in r.tags

    def test_raspberry_pi_specific(self, clf):
        r = clf.classify_sync("Read the GPIO pin 17 on the Raspberry Pi")
        assert "technical" in r.tags or "coding" in r.tags

    def test_default_fallback(self, clf):
        r = clf.classify_sync("hello")
        assert "general" in r.tags
        assert r.method == "default"
        assert r.confidence < 0.65

    def test_multiple_tags(self, clf):
        r = clf.classify_sync("debug this Python regex algorithm")
        # Should pick up multiple signals
        assert len(r.tags) >= 1

    def test_result_structure(self, clf):
        r = clf.classify_sync("write code")
        assert isinstance(r, ClassificationResult)
        assert isinstance(r.tags, list)
        assert isinstance(r.confidence, float)
        assert 0.0 <= r.confidence <= 1.0
        assert r.method in ("pattern", "default", "llm")

    def test_top_tags_limit(self, clf):
        # Even with many signals, should cap at 4 tags
        r = clf.classify_sync(
            "debug this Python code, analyze the algorithm, translate to German, summarize the result"
        )
        assert len(r.tags) <= 4


class TestEdgeCases:
    def test_empty_string(self, clf):
        r = clf.classify_sync("")
        assert "general" in r.tags

    def test_very_long_text(self, clf):
        r = clf.classify_sync("debug " * 1000)
        assert "debugging" in r.tags

    def test_case_insensitive(self, clf):
        r1 = clf.classify_sync("PYTHON function")
        r2 = clf.classify_sync("python function")
        assert "coding" in r1.tags
        assert "coding" in r2.tags

    def test_unicode(self, clf):
        r = clf.classify_sync("Kannst du mir dabei helfen? 🤔")
        # Should not crash, should detect german
        assert isinstance(r.tags, list)

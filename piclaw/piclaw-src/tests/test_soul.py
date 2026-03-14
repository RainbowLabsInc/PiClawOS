"""
Tests for piclaw.soul – load, save, append, default creation.
Uses tmp_path to avoid touching /etc/piclaw.
"""
import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture
def soul_path(tmp_path):
    """Returns a tmp soul file path, patches the module to use it."""
    sp = tmp_path / "SOUL.md"
    with patch("piclaw.soul.SOUL_FILE", sp):
        yield sp


class TestSoulLoad:

    def test_load_creates_default_when_missing(self, soul_path):
        from piclaw import soul
        content = soul.load()
        assert len(content) > 0
        assert soul_path.exists()

    def test_load_existing_content(self, soul_path):
        soul_path.write_text("# My custom soul\n\nBe a poet.")
        from piclaw import soul
        content = soul.load()
        assert "My custom soul" in content
        assert "Be a poet" in content

    def test_load_returns_string(self, soul_path):
        from piclaw import soul
        assert isinstance(soul.load(), str)


class TestSoulSave:

    def test_save_writes_to_file(self, soul_path):
        from piclaw import soul
        result = soul.save("# New soul\n\nHello world")
        assert "gespeichert" in result.lower() or "saved" in result.lower() or result
        assert "New soul" in soul_path.read_text()

    def test_save_overwrites_existing(self, soul_path):
        soul_path.write_text("# Old content")
        from piclaw import soul
        soul.save("# Replaced content")
        assert "Replaced" in soul_path.read_text()
        assert "Old" not in soul_path.read_text()

    def test_save_and_reload(self, soul_path):
        from piclaw import soul
        soul.save("# Round-trip test\n\nContent here.")
        loaded = soul.load()
        assert "Round-trip test" in loaded


class TestSoulAppend:

    def test_append_adds_section(self, soul_path):
        soul_path.write_text("# Existing")
        from piclaw import soul
        soul.append("## New Section\n\nAdded content.")
        content = soul_path.read_text()
        assert "Existing" in content
        assert "New Section" in content
        assert "Added content" in content

    def test_append_creates_if_missing(self, soul_path):
        from piclaw import soul
        soul.append("## Appended to new file")
        assert "Appended to new file" in soul_path.read_text()


class TestSoulGetPath:

    def test_get_path_returns_path_object(self, soul_path):
        from piclaw import soul
        p = soul.get_path()
        assert isinstance(p, Path)


class TestSoulDefaultContent:

    def test_default_soul_not_empty(self, soul_path):
        from piclaw import soul
        content = soul.load()
        assert len(content.strip()) > 100  # meaningful content

    def test_default_soul_has_structure(self, soul_path):
        from piclaw import soul
        content = soul.load()
        # Default soul should have at least one Markdown heading
        assert "#" in content


class TestSoulBuildSystemPrompt:

    def test_build_system_prompt_includes_soul(self, soul_path):
        soul_path.write_text("# My Soul\n\nI am a poet.")
        from piclaw import soul
        prompt = soul.build_system_prompt(
            name="PiClaw", date="2026-01-01", hostname="piclaw.local",
            base_capabilities="Tools for {name} on {hostname} at {date}",
        )
        assert "My Soul" in prompt
        assert "I am a poet" in prompt
        assert "Tools" in prompt

    def test_soul_appears_before_capabilities(self, soul_path):
        soul_path.write_text("SOUL_MARKER")
        from piclaw import soul
        prompt = soul.build_system_prompt(
            name="Pi", date="2026", hostname="host",
            base_capabilities="CAPS_MARKER on {hostname} at {date} for {name}",
        )
        soul_pos = prompt.index("SOUL_MARKER")
        caps_pos = prompt.index("CAPS_MARKER")
        assert soul_pos < caps_pos

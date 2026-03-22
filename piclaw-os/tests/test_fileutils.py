import pytest
import json
import logging
from unittest.mock import patch
from pathlib import Path
from piclaw.fileutils import safe_write_json


def test_safe_write_json_success(tmp_path: Path):
    """Test successful JSON write."""
    test_file = tmp_path / "test_success.json"
    data = {"key": "value", "number": 42}

    assert safe_write_json(test_file, data) is True
    assert test_file.exists()

    with open(test_file, encoding="utf-8") as f:
        loaded_data = json.load(f)
    assert loaded_data == data


def test_safe_write_json_type_error(tmp_path: Path, caplog):
    """Test JSON write failure due to un-serializable data (TypeError)."""
    test_file = tmp_path / "test_type_error.json"

    # A set is not JSON serializable by default
    data = {"key": set([1, 2, 3])}

    with caplog.at_level(logging.ERROR, logger="piclaw.fileutils"):
        assert safe_write_json(test_file, data) is False

    assert not test_file.exists()
    assert "JSON-Write fehlgeschlagen" in caplog.text


def test_safe_write_json_os_error_with_label(tmp_path: Path, caplog):
    """Test JSON write failure due to an OSError and verify label formatting."""
    test_file = tmp_path / "test_os_error.json"
    data = {"key": "value"}

    # Simulate an OSError during atomic_write_json
    with patch(
        "piclaw.fileutils.atomic_write_json", side_effect=OSError("Permission denied")
    ):
        with caplog.at_level(logging.ERROR, logger="piclaw.fileutils"):
            assert safe_write_json(test_file, data, label="Config File") is False

    assert "JSON-Write fehlgeschlagen (Config File): Permission denied" in caplog.text


def test_safe_write_json_value_error(tmp_path: Path, caplog):
    """Test JSON write failure due to ValueError."""
    test_file = tmp_path / "test_value_error.json"
    data = {"key": "value"}

    # Simulate a ValueError during atomic_write_json (e.g. from json encoder for circular reference or similar)
    with patch(
        "piclaw.fileutils.atomic_write_json",
        side_effect=ValueError("Circular reference detected"),
    ):
        with caplog.at_level(logging.ERROR, logger="piclaw.fileutils"):
            assert safe_write_json(test_file, data) is False

    assert "JSON-Write fehlgeschlagen" in caplog.text
    assert "Circular reference detected" in caplog.text

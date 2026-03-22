import pytest
import json
import logging
from unittest.mock import patch
from pathlib import Path
from piclaw.fileutils import safe_write_json, atomic_write_text
import os
import tempfile

def test_safe_write_json_success(tmp_path: Path):
    """Test successful JSON write."""
    test_file = tmp_path / "test_success.json"
    data = {"key": "value", "number": 42}

    assert safe_write_json(test_file, data) is True
    assert test_file.exists()

    with open(test_file, "r", encoding="utf-8") as f:
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
    with patch("piclaw.fileutils.atomic_write_json", side_effect=OSError("Permission denied")):
        with caplog.at_level(logging.ERROR, logger="piclaw.fileutils"):
            assert safe_write_json(test_file, data, label="Config File") is False

    assert "JSON-Write fehlgeschlagen (Config File): Permission denied" in caplog.text

def test_safe_write_json_value_error(tmp_path: Path, caplog):
    """Test JSON write failure due to ValueError."""
    test_file = tmp_path / "test_value_error.json"
    data = {"key": "value"}

    # Simulate a ValueError during atomic_write_json (e.g. from json encoder for circular reference or similar)
    with patch("piclaw.fileutils.atomic_write_json", side_effect=ValueError("Circular reference detected")):
        with caplog.at_level(logging.ERROR, logger="piclaw.fileutils"):
            assert safe_write_json(test_file, data) is False

    assert "JSON-Write fehlgeschlagen" in caplog.text
    assert "Circular reference detected" in caplog.text

def test_atomic_write_text_success(tmp_path: Path):
    """Test successful atomic text write."""
    test_file = tmp_path / "subdir" / "test_success.txt"
    content = "Hello, world! 🌍"

    atomic_write_text(test_file, content)

    assert test_file.exists()
    with open(test_file, "r", encoding="utf-8") as f:
        assert f.read() == content

def test_atomic_write_text_cleanup_on_error(tmp_path: Path):
    """Test that temporary file is cleaned up if replace fails."""
    test_file = tmp_path / "test_error.txt"
    content = "Error test"

    # We need to capture the temporary file name to verify it was deleted.
    # We can patch os.replace to raise an exception.
    original_mkstemp = tempfile.mkstemp
    tmp_file_path = None

    def mock_mkstemp(*args, **kwargs):
        nonlocal tmp_file_path
        fd, path = original_mkstemp(*args, **kwargs)
        tmp_file_path = path
        return fd, path

    with patch("tempfile.mkstemp", side_effect=mock_mkstemp):
        with patch("piclaw.fileutils.os.replace", side_effect=OSError("Replace failed")):
            with pytest.raises(OSError, match="Replace failed"):
                atomic_write_text(test_file, content)

    # Verify the temporary file was created and then deleted
    assert tmp_file_path is not None
    assert not Path(tmp_file_path).exists()

def test_atomic_write_text_cleanup_error_ignored(tmp_path: Path):
    """Test that an OSError during cleanup (unlink) does not mask the original exception."""
    test_file = tmp_path / "test_double_error.txt"
    content = "Double error test"

    with patch("piclaw.fileutils.os.replace", side_effect=ValueError("Original error")):
        with patch("piclaw.fileutils.os.unlink", side_effect=OSError("Cleanup failed")):
            # The original ValueError should be raised, not the OSError from unlink
            with pytest.raises(ValueError, match="Original error"):
                atomic_write_text(test_file, content)

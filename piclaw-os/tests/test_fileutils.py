import logging
from pathlib import Path
from unittest.mock import patch

from piclaw.fileutils import safe_write_text

def test_safe_write_text_success(tmp_path: Path):
    """Test successful execution of safe_write_text."""
    file_path = tmp_path / "test_success.txt"
    content = "Hello, PiClaw!"

    result = safe_write_text(file_path, content)

    assert result is True
    assert file_path.read_text(encoding="utf-8") == content

def test_safe_write_text_failure_no_label(tmp_path: Path, caplog):
    """Test failure of safe_write_text without a label provided."""
    file_path = tmp_path / "test_failure.txt"
    content = "This should fail"

    # Simulate an OSError during atomic_write_text
    with patch("piclaw.fileutils.atomic_write_text", side_effect=OSError("Permission denied")):
        with caplog.at_level(logging.ERROR):
            result = safe_write_text(file_path, content)

    assert result is False
    assert not file_path.exists()

    # Verify the log message correctly formats the error without a label
    assert "Disk-Write fehlgeschlagen: Permission denied" in caplog.text

def test_safe_write_text_failure_with_label(tmp_path: Path, caplog):
    """Test failure of safe_write_text with a label provided."""
    file_path = tmp_path / "test_failure_label.txt"
    content = "This should fail too"

    with patch("piclaw.fileutils.atomic_write_text", side_effect=OSError("No space left on device")):
        with caplog.at_level(logging.ERROR):
            result = safe_write_text(file_path, content, label="Cache")

    assert result is False
    assert not file_path.exists()

    # Verify the log message correctly formats the error with the label
    assert "Disk-Write fehlgeschlagen (Cache): No space left on device" in caplog.text

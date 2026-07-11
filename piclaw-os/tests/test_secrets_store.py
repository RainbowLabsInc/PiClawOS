"""
Regressionstests für den gehärteten Secret-Store.

Vorher: SECRETS_FILE.write_bytes ohne Atomik – ein Crash mitten im Write
konnte ALLE Secrets korrumpieren; set_secret war ein ungelocktes
Read-Modify-Write über drei Writer (api, daemon, CLI).
"""

import pytest

pytest.importorskip("cryptography")


@pytest.fixture
def secrets_env(tmp_path, monkeypatch):
    import piclaw.secrets as sec
    monkeypatch.setattr(sec, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(sec, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(sec, "_get_pi_serial", lambda: "test-serial-0000")
    # Key-Cache zurücksetzen – andere Tests/Serial dürfen nicht hineinbluten
    monkeypatch.setattr(sec, "_derived_key_cache", None)
    return sec


def test_set_secret_roundtrip(secrets_env):
    sec = secrets_env
    sec.set_secret("llm.api_key", "geheim-123")
    assert sec.get_secret("llm.api_key") == "geheim-123"


def test_set_secret_preserves_foreign_keys(secrets_env):
    """Interleaved Writer: der zweite set_secret darf den ersten nicht verlieren."""
    sec = secrets_env
    sec.set_secret("llm.api_key", "wert-a")
    sec.set_secret("telegram.bot_token", "wert-b")

    assert sec.get_secret("llm.api_key") == "wert-a"
    assert sec.get_secret("telegram.bot_token") == "wert-b"
    assert sorted(sec.list_keys()) == ["llm.api_key", "telegram.bot_token"]


def test_delete_secret(secrets_env):
    sec = secrets_env
    sec.set_secret("llm.api_key", "wert")
    sec.set_secret("llm.api_key", "")  # leerer Wert = löschen
    assert sec.get_secret("llm.api_key", default="leer") == "leer"
    assert sec.list_keys() == []


def test_delete_missing_key_writes_nothing(secrets_env, tmp_path):
    sec = secrets_env
    sec.set_secret("gibt.es.nicht", "")
    assert not (tmp_path / "secrets.enc").exists()


def test_save_raw_produces_cleanly_decryptable_file(secrets_env, tmp_path):
    """Atomik-Smoke-Test: Datei ist nach dem Write vollständig entschlüsselbar
    und es bleiben keine .tmp_-Reste liegen."""
    sec = secrets_env
    sec._save_raw({"a.b": "c" * 10_000})
    assert sec._load_raw() == {"a.b": "c" * 10_000}
    assert list(tmp_path.glob(".tmp_*")) == []

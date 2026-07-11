"""
Regressionstests für config.save(): atomarer TOML-Write + Erhalt der
Nicht-Dataclass-Sektionen (homeassistant, mqtt, parcel_tracking).

Vorher: plain open()+tomli_w.dump – ein Crash mitten im Write konnte die
Haupt-Config zerreißen.
"""

import tomllib

import pytest


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    import piclaw.config as cfg_mod
    path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", path)
    # ensure_dirs() soll nicht in /etc/piclaw schreiben wollen
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    return path


def test_save_produces_parseable_toml(config_file):
    from piclaw.config import PiClawConfig, save

    cfg = PiClawConfig()
    cfg.agent_name = "TestClaw"
    save(cfg)

    data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    assert data["agent_name"] == "TestClaw"
    assert "llm" in data and "api" in data


def test_save_preserves_foreign_sections(config_file):
    """homeassistant/mqtt/parcel_tracking werden vom Wizard direkt in die
    Datei geschrieben und sind nicht Teil der Dataclass – save() muss sie
    aus der bestehenden Datei übernehmen."""
    from piclaw.config import PiClawConfig, save

    config_file.write_text(
        '[homeassistant]\nurl = "http://ha.local:8123"\n\n'
        '[parcel_tracking]\ndhl_api_key = ""\n',
        encoding="utf-8",
    )

    save(PiClawConfig())

    data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    assert data["homeassistant"]["url"] == "http://ha.local:8123"
    assert "parcel_tracking" in data


def test_save_leaves_no_tmp_files(config_file, tmp_path):
    from piclaw.config import PiClawConfig, save

    save(PiClawConfig())
    assert list(tmp_path.glob(".tmp_*")) == []

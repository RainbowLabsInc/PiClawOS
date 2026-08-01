"""
Schreiben der Heimatadresse in die config.toml.

Der Grund für einen eigenen Schreiber statt config.save(): save() rendert die
komplette Datei neu, und load() injiziert vorher die entschlüsselten Werte aus
secrets.enc. Auf einer Installation mit `@enc:`-Platzhaltern würden diese
dadurch durch Klartext-Secrets ersetzt. Genau das nageln die Tests hier fest.
"""

import tomllib

import pytest

from piclaw.shopping.location import write_home_address

BESTAND = """\
agent_name = "PiClaw"
log_level = "INFO"

[api]
secret_key = "@enc:gAAAAABsupergeheim"
port = 7842

[homeassistant]
url = "http://homeassistant.local:8123"
token = "@enc:gAAAAABnochgeheimer"
"""


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    import piclaw.config as config_mod

    pfad = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", pfad)
    return pfad


def _laden(pfad):
    return tomllib.loads(pfad.read_text(encoding="utf-8"))


# ── Anlegen ──────────────────────────────────────────────────────────────


def test_legt_sektion_an_wenn_sie_fehlt(cfg):
    cfg.write_text(BESTAND, encoding="utf-8")

    write_home_address("Musterweg", "12a", "20095", "Hamburg")

    daten = _laden(cfg)
    assert daten["shopping"]["home_street"] == "Musterweg"
    assert daten["shopping"]["home_house_number"] == "12a"
    assert daten["shopping"]["home_zip"] == "20095"
    assert daten["shopping"]["home_city"] == "Hamburg"
    assert daten["shopping"]["home_country"] == "de"


def test_funktioniert_auch_ohne_bestehende_datei(cfg):
    write_home_address("Musterweg", "1", "20095", "Hamburg")

    assert _laden(cfg)["shopping"]["home_street"] == "Musterweg"


# ── Bestand bleibt erhalten ──────────────────────────────────────────────


def test_verschluesselte_secrets_bleiben_platzhalter(cfg):
    """Der eigentliche Grund für diesen Schreiber."""
    cfg.write_text(BESTAND, encoding="utf-8")

    write_home_address("Musterweg", "12a", "20095", "Hamburg")

    text = cfg.read_text(encoding="utf-8")
    assert '"@enc:gAAAAABsupergeheim"' in text
    assert '"@enc:gAAAAABnochgeheimer"' in text


def test_andere_sektionen_bleiben_unveraendert(cfg):
    cfg.write_text(BESTAND, encoding="utf-8")

    write_home_address("Musterweg", "12a", "20095", "Hamburg")

    daten = _laden(cfg)
    assert daten["api"]["port"] == 7842
    assert daten["homeassistant"]["url"] == "http://homeassistant.local:8123"
    assert daten["agent_name"] == "PiClaw"


def test_uebrige_shopping_keys_ueberleben(cfg):
    cfg.write_text(BESTAND + """
[shopping]
home_street = "Alteweg"
home_zip = "10115"
radius_km = 15
providers = ["marktguru"]
price_drop_pct = 0.2
""", encoding="utf-8")

    write_home_address("Neueweg", "5", "20095", "Hamburg")

    shopping = _laden(cfg)["shopping"]
    assert shopping["home_street"] == "Neueweg"
    assert shopping["home_zip"] == "20095"
    assert shopping["radius_km"] == 15          # nicht angefasst
    assert shopping["providers"] == ["marktguru"]
    assert shopping["price_drop_pct"] == 0.2


def test_kommentare_in_der_sektion_bleiben(cfg):
    cfg.write_text("""\
[shopping]
# Umkreis bewusst klein gehalten
radius_km = 5
""", encoding="utf-8")

    write_home_address("Musterweg", "1", "20095", "Hamburg")

    assert "# Umkreis bewusst klein gehalten" in cfg.read_text(encoding="utf-8")


# ── Aktualisieren ────────────────────────────────────────────────────────


def test_ueberschreibt_ohne_zu_duplizieren(cfg):
    write_home_address("Alteweg", "1", "10115", "Berlin")
    write_home_address("Neueweg", "2", "20095", "Hamburg")

    text = cfg.read_text(encoding="utf-8")
    assert text.count("[shopping]") == 1
    assert text.count("home_street") == 1
    assert _laden(cfg)["shopping"]["home_city"] == "Hamburg"


def test_explizite_koordinaten_werden_entfernt(cfg):
    """Sie hätten Vorrang und würden die neue Adresse aushebeln."""
    cfg.write_text("""\
[shopping]
home_latitude = 52.52
home_longitude = 13.40
radius_km = 10
""", encoding="utf-8")

    write_home_address("Musterweg", "1", "20095", "Hamburg")

    shopping = _laden(cfg)["shopping"]
    assert "home_latitude" not in shopping
    assert "home_longitude" not in shopping
    assert shopping["radius_km"] == 10


def test_radius_wird_nur_auf_wunsch_gesetzt(cfg):
    write_home_address("Musterweg", "1", "20095", "Hamburg")
    assert "radius_km" not in _laden(cfg)["shopping"]

    write_home_address("Musterweg", "1", "20095", "Hamburg", radius_km=7.5)
    assert _laden(cfg)["shopping"]["radius_km"] == 7.5


def test_land_wird_kleingeschrieben(cfg):
    write_home_address("Musterweg", "1", "20095", "Hamburg", country="DE")

    assert _laden(cfg)["shopping"]["home_country"] == "de"


# ── Sonderzeichen ────────────────────────────────────────────────────────


def test_anfuehrungszeichen_im_strassennamen(cfg):
    write_home_address('Zum "Alten" Hof', "1", "20095", "Hamburg")

    assert _laden(cfg)["shopping"]["home_street"] == 'Zum "Alten" Hof'


def test_umlaute_bleiben_erhalten(cfg):
    write_home_address("Grüner Weg", "3", "80331", "München")

    shopping = _laden(cfg)["shopping"]
    assert shopping["home_street"] == "Grüner Weg"
    assert shopping["home_city"] == "München"


def test_leere_adresse_leert_die_felder(cfg):
    write_home_address("Musterweg", "1", "20095", "Hamburg")

    write_home_address()

    shopping = _laden(cfg)["shopping"]
    assert shopping["home_street"] == ""
    assert shopping["home_zip"] == ""


def test_ergebnis_bleibt_gueltiges_toml(cfg):
    cfg.write_text(BESTAND, encoding="utf-8")

    write_home_address("Musterweg", "12a", "20095", "Hamburg", radius_km=12)

    tomllib.loads(cfg.read_text(encoding="utf-8"))  # wirft bei kaputtem TOML

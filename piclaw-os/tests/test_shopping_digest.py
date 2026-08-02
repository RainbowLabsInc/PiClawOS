"""
Tägliche Zusammenfassung, Zeitplan, Abhaken und Angebotsvorschau.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest

from piclaw.shopping import digest
from piclaw.shopping.providers.base import Offer
from piclaw.shopping.store import PricePoint, ShoppingDB

DAY = 86_400


@pytest.fixture
def db(tmp_path):
    return ShoppingDB(tmp_path / "shopping.db")


# ── Zeitplan ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tage, zeit, erwartet", [
    ("1,2,4", "07:00", "cron:0 7 * * 1,2,4"),
    ("0,6", "18:30", "cron:30 18 * * 0,6"),
    ("1,2,3,4,5,6", "06:15", "cron:15 6 * * 1,2,3,4,5,6"),
    ("3", "23:59", "cron:59 23 * * 3"),
])
def test_cron_aus_tagen_und_uhrzeit(tage, zeit, erwartet):
    assert digest.cron_expression(tage, zeit) == erwartet


@pytest.mark.parametrize("tage, zeit", [
    ("", "07:00"),          # keine Tage
    ("9,x", "07:00"),       # unmögliche Tage
    ("1,2,4", "kaputt"),    # unlesbare Zeit
    ("1,2,4", "99:99"),     # unmögliche Zeit
])
def test_ungueltige_eingaben_fallen_zurueck_statt_zu_werfen(tage, zeit):
    """Ein kaputter Ausdruck ließe den Sub-Agenten still nie laufen."""
    ausdruck = digest.cron_expression(tage, zeit)

    assert ausdruck.startswith("cron:")
    teile = ausdruck[len("cron:"):].split()
    assert len(teile) == 5


def test_wochentage_werden_sortiert_und_entdoppelt():
    assert digest.cron_expression("4,1,1,2", "07:00") == "cron:0 7 * * 1,2,4"


def test_croniter_versteht_den_ausdruck():
    """Gegenprobe gegen die Bibliothek, die ihn tatsächlich auswertet."""
    croniter = pytest.importorskip("croniter").croniter

    ausdruck = digest.cron_expression("1,4", "07:30")[len("cron:"):]
    naechster = croniter(ausdruck, datetime(2026, 8, 2, 12, 0)).get_next(datetime)

    assert naechster.weekday() in (0, 3)      # Montag oder Donnerstag
    assert (naechster.hour, naechster.minute) == (7, 30)


# ── Abhaken ──────────────────────────────────────────────────────────────


def test_abhaken_und_zurueck(db):
    item = db.add_item("Butter")
    assert db.get_item(item.id).is_bought() is False

    db.set_bought(item.id, 14)
    assert db.get_item(item.id).is_bought() is True

    db.set_bought(item.id, 0)
    assert db.get_item(item.id).is_bought() is False


def test_abhaken_laeuft_ab(db):
    item = db.add_item("Butter")
    db.set_bought(item.id, 1)

    geholt = db.get_item(item.id)
    assert geholt.is_bought(now=int(time.time())) is True
    assert geholt.is_bought(now=int(time.time()) + 2 * DAY) is False


def test_abgehakter_artikel_bleibt_auf_der_liste(db):
    """Er ruht nur – gelöscht würde die Preisreihe mitgehen."""
    item = db.add_item("Butter")
    db.set_bought(item.id, 14)

    assert len(db.list_items()) == 1


# ── Digest ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_leere_liste_ergibt_keine_nachricht(db):
    text, _ = await digest.build(session=object(), db=db, user_id=None)

    assert text == ""


@pytest.mark.asyncio
async def test_abgehakte_artikel_kommen_nicht_in_den_digest(db, monkeypatch):
    item = db.add_item("Butter")
    db.set_bought(item.id, 14)

    async def _keine_aufloesung(session, cfg=None, db=None, force=False):
        raise AssertionError("darf gar nicht erst aufgelöst werden")

    monkeypatch.setattr(digest.location, "resolve", _keine_aufloesung)

    text, _ = await digest.build(session=object(), db=db, user_id=None)

    assert text == ""


def test_fingerabdruck_erkennt_aenderung(db):
    assert db.digest_changed(None, "abc") is True

    db.digest_sent(None, "abc")
    assert db.digest_changed(None, "abc") is False
    assert db.digest_changed(None, "xyz") is True


def test_fingerabdruck_ist_pro_nutzer(db):
    db.digest_sent("patrick", "abc")

    assert db.digest_changed("patrick", "abc") is False
    assert db.digest_changed("viola", "abc") is True


def test_datumszeile_deutsch():
    assert digest._datumszeile(datetime(2026, 8, 3)) == "Montag, 3. August"
    assert digest._datumszeile(datetime(2026, 12, 24)) == "Donnerstag, 24. Dezember"


# ── Vorschau ─────────────────────────────────────────────────────────────


def _offer(tage_bis_start, tage_bis_ende=7):
    jetzt = datetime.now(UTC)
    return Offer(
        title="Butter", price=0.99, retailer="REWE", retailer_key="rewe",
        valid_from=(jetzt + timedelta(days=tage_bis_start)).isoformat(),
        valid_to=(jetzt + timedelta(days=tage_bis_ende)).isoformat(),
    )


def test_kommendes_angebot_wird_erkannt():
    kommend = _offer(2)

    assert kommend.starts_later is True
    assert kommend.is_active() is False
    assert kommend.starts_on                     # z.B. "Mi, 05.08."


def test_laufendes_angebot_ist_keine_vorschau():
    laufend = _offer(-1)

    assert laufend.starts_later is False
    assert laufend.is_active() is True
    assert laufend.starts_on == ""


def test_abgelaufenes_angebot_ist_weder_aktiv_noch_vorschau():
    alt = Offer(title="X", price=1.0,
                valid_from="2020-01-01T00:00:00Z", valid_to="2020-01-07T00:00:00Z")

    assert alt.is_active() is False
    assert alt.starts_later is False


def test_ohne_datum_keine_vorschau():
    assert Offer(title="X", price=1.0).starts_later is False


# ── Preisrutsche im Digest ───────────────────────────────────────────────


def test_gemeldete_alerts_kommen_nicht_erneut(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    db.record_prices([PricePoint(pid, 0.90, int(time.time()))])
    alert_id = db.add_alert(pid, 0.90, 1.10, 0.18)

    assert len(db.pending_alerts()) == 1
    db.mark_alerts_notified([alert_id])
    assert db.pending_alerts() == []

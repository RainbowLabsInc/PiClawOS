"""
Einkaufslisten-Store (SQLite).

Schwerpunkt liegt auf den Invarianten, von denen die Preisanalyse abhängt:
Produkt-Identität, ein Preispunkt pro Produkt und Tag, korrekte Retention.
"""

import time

import pytest

from piclaw.shopping.store import PricePoint, ShoppingDB, address_hash

DAY = 86_400


@pytest.fixture
def db(tmp_path):
    return ShoppingDB(tmp_path / "shopping.db")


# ── Artikel ──────────────────────────────────────────────────────────────


def test_add_und_list(db):
    db.add_item("Butter", qty="250g", max_price=1.5)
    db.add_item("Kaffee")

    items = db.list_items()

    assert [i.name for i in items] == ["Butter", "Kaffee"]
    assert items[0].qty == "250g"
    assert items[0].max_price == 1.5
    assert items[1].max_price is None


def test_search_term_faellt_auf_name_zurueck(db):
    ohne = db.add_item("Butter")
    mit = db.add_item("Tabs", query="geschirrspül")

    assert ohne.search_term == "Butter"
    assert mit.search_term == "geschirrspül"


def test_find_item_by_name_ignoriert_gross_klein(db):
    db.add_item("Butter")

    assert db.find_item_by_name("BUTTER") is not None
    assert db.find_item_by_name("  butter  ") is not None
    assert db.find_item_by_name("Buttermilch") is None


def test_owner_scoping(db):
    db.add_item("Annas Milch", owner_id="anna")
    db.add_item("Patricks Butter", owner_id="patrick")
    db.add_item("Haushaltskram", owner_id=None)

    # None = System/Scheduler sieht alles
    assert len(db.list_items(owner_id=None)) == 3
    # Nutzer sieht eigene plus globale, nicht die des anderen
    annas = {i.name for i in db.list_items(owner_id="anna")}
    assert annas == {"Annas Milch", "Haushaltskram"}


def test_remove_item(db):
    item = db.add_item("Butter")

    assert db.remove_item(item.id) is True
    assert db.remove_item(item.id) is False
    assert db.list_items() == []


def test_produkte_verschwinden_mit_dem_artikel(db):
    """ON DELETE CASCADE – sonst bleiben verwaiste Preisreihen liegen."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Milbona Butter", "milbona butter")
    db.record_price(pid, 1.49)

    db.remove_item(item.id)

    assert db.list_products(item.id) == []
    assert db.history(pid) == []


# ── Produkt-Identität ────────────────────────────────────────────────────


def test_upsert_product_legt_nicht_doppelt_an(db):
    item = db.add_item("Butter")

    first = db.upsert_product(item.id, "lidl", "Milbona Butter", "milbona butter")
    second = db.upsert_product(item.id, "lidl", "Milbona Butter", "milbona butter")

    assert first == second
    assert len(db.list_products(item.id)) == 1


def test_verschiedene_produkte_bleiben_getrennt(db):
    """Sonst wäre jeder andere Treffer ein vermeintlicher Preisverfall."""
    item = db.add_item("Butter")

    a = db.upsert_product(item.id, "lidl", "Kerrygold Butter", "kerrygold butter")
    b = db.upsert_product(item.id, "lidl", "Gut&Günstig Butter", "gut gunstig butter")
    c = db.upsert_product(item.id, "rewe", "Kerrygold Butter", "kerrygold butter")

    assert len({a, b, c}) == 3


def test_upsert_frischt_last_seen_auf(db):
    item = db.add_item("Butter")
    now = int(time.time())

    pid = db.upsert_product(item.id, "lidl", "Butter", "butter", ts=now - 10 * DAY)
    db.upsert_product(item.id, "lidl", "Butter", "butter", ts=now)

    product = db.list_products(item.id)[0]
    assert product.id == pid
    assert product.first_seen == now - 10 * DAY
    assert product.last_seen == now


# ── Preispunkte ──────────────────────────────────────────────────────────


def test_history_kommt_aufsteigend(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    now = int(time.time())
    db.record_price(pid, 1.10, ts=now)
    db.record_price(pid, 1.20, ts=now - 2 * DAY)
    db.record_price(pid, 1.30, ts=now - 4 * DAY)

    assert [p for _, p in db.history(pid)] == [1.30, 1.20, 1.10]


def test_ein_preispunkt_pro_produkt_und_tag(db):
    """Zweiter Lauf am selben Tag darf den Tag nicht doppelt zählen."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    now = int(time.time())

    assert db.record_prices([PricePoint(pid, 1.50, now)]) == 1
    assert db.record_prices([PricePoint(pid, 1.20, now + 60)]) == 1  # günstiger
    assert db.record_prices([PricePoint(pid, 1.40, now + 120)]) == 0  # teurer

    history = db.history(pid)
    assert len(history) == 1
    assert history[0][1] == 1.20  # der günstigste des Tages gewinnt


def test_verschiedene_tage_bleiben_erhalten(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    now = int(time.time())

    db.record_prices([PricePoint(pid, 1.10, now - 2 * DAY)])
    db.record_prices([PricePoint(pid, 1.20, now - DAY)])
    db.record_prices([PricePoint(pid, 0.90, now)])

    assert [p for _, p in db.history(pid)] == [1.10, 1.20, 0.90]


def test_item_history_nimmt_taeglich_den_guenstigsten(db):
    """Die Sparkline zeigt: was hätte der Artikel an dem Tag mindestens gekostet."""
    item = db.add_item("Butter")
    teuer = db.upsert_product(item.id, "rewe", "Kerrygold", "kerrygold")
    guenstig = db.upsert_product(item.id, "lidl", "Milbona", "milbona")
    now = int(time.time())

    db.record_prices([PricePoint(teuer, 2.29, now), PricePoint(guenstig, 1.49, now)])

    history = db.item_history(item.id)
    assert len(history) == 1
    assert history[0][1] == 1.49


def test_best_current_ignoriert_alte_preise(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    db.record_price(pid, 0.99, ts=int(time.time()) - 30 * DAY)

    assert db.best_current(item.id) is None
    assert db.best_current(item.id, max_age_s=40 * DAY)["price"] == 0.99


def test_grundpreis_wird_aus_groesse_und_preis_berechnet(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Kerrygold", "kerrygold",
                            unit_size=0.25, unit_label="kg")
    db.record_price(pid, 1.79)

    best = db.best_current(item.id)
    assert best["unit_price"] == pytest.approx(7.16, abs=0.01)
    assert best["unit_price_text"] == "7,16 €/kg"
    assert best["size_text"] == "250 g"


def test_gefallener_preis_ergibt_neuen_grundpreis(db):
    """Gespeichert wird die Größe, nicht der Grundpreis – der folgt dem Preis."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Kerrygold", "kerrygold",
                            unit_size=0.25, unit_label="kg")
    db.record_price(pid, 0.99)

    assert db.best_current(item.id)["unit_price"] == pytest.approx(3.96, abs=0.01)


def test_bester_grundpreis_kann_anderes_produkt_sein(db):
    """Der Kern des Features: der Absolutpreis führt hier in die Irre."""
    item = db.add_item("Butter")
    klein = db.upsert_product(item.id, "lidl", "250g Butter", "klein",
                              unit_size=0.25, unit_label="kg")
    gross = db.upsert_product(item.id, "rewe", "400g Butter", "gross",
                              unit_size=0.40, unit_label="kg")
    db.record_price(klein, 1.79)   # 7,16 €/kg
    db.record_price(gross, 2.49)   # 6,23 €/kg

    assert db.best_current(item.id)["product_id"] == klein        # billiger absolut
    assert db.best_unit_price(item.id)["product_id"] == gross     # billiger pro kg


def test_produkte_ohne_groesse_fallen_beim_grundpreis_raus(db):
    item = db.add_item("Butter")
    ohne = db.upsert_product(item.id, "lidl", "Butter", "butter")
    db.record_price(ohne, 0.99)

    assert db.best_current(item.id) is not None
    assert db.best_unit_price(item.id) is None
    assert db.best_current(item.id)["unit_price"] is None
    assert db.best_current(item.id)["unit_price_text"] == ""


def test_bekannte_groesse_wird_nicht_geleert(db):
    """Liefert eine Quelle die Größe später nicht mit, bleibt sie erhalten."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter",
                            unit_size=0.25, unit_label="kg")

    db.upsert_product(item.id, "lidl", "Butter", "butter")

    produkt = db.list_products(item.id)[0]
    assert produkt.id == pid
    assert produkt.unit_size == pytest.approx(0.25)
    assert produkt.unit_label == "kg"


def test_migration_ergaenzt_spalten_in_bestandsdatenbank(tmp_path):
    """Eine DB ohne die Grundpreis-Spalten darf nicht neu aufgebaut werden."""
    import sqlite3

    pfad = tmp_path / "alt.db"
    con = sqlite3.connect(pfad)
    con.executescript("""
        CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
            query TEXT DEFAULT '', qty TEXT DEFAULT '', max_price REAL,
            owner_id TEXT, muted INTEGER DEFAULT 0, created_at INTEGER);
        CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER, retailer TEXT, title TEXT, title_norm TEXT,
            unit TEXT DEFAULT '', first_seen INTEGER, last_seen INTEGER,
            UNIQUE(item_id, retailer, title_norm));
        INSERT INTO items VALUES (1,'Butter','','',NULL,NULL,0,1);
        INSERT INTO products VALUES (1,1,'lidl','Butter','butter','',1,1);
    """)
    con.commit()
    con.close()

    db = ShoppingDB(pfad)

    produkte = db.list_products(1)
    assert len(produkte) == 1              # Bestand erhalten
    assert produkte[0].unit_size is None
    assert ShoppingDB(pfad).list_products(1)  # zweiter Lauf bricht nicht


def test_best_current_nennt_haendler_und_titel(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Milbona Weidebutter", "milbona weidebutter")
    db.record_price(pid, 1.59)

    best = db.best_current(item.id)
    assert best["retailer"] == "lidl"
    assert best["title"] == "Milbona Weidebutter"
    assert best["price"] == 1.59


# ── Normalpreis-Schätzung ────────────────────────────────────────────────


def test_streichpreis_schlaegt_historie(db):
    """Der Streichpreis ist der einzige echte Normalpreis in den Daten."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    now = int(time.time())
    db.record_prices([PricePoint(pid, 1.10, now - 2 * DAY)])
    db.record_prices([PricePoint(pid, 0.99, now, old_price=1.99)])

    preis, quelle = db.normal_price_estimate(item.id)

    assert preis == 1.99
    assert quelle == "streichpreis"


def test_ohne_streichpreis_zaehlt_der_hoechste_beobachtete(db):
    """Angebote tauchen unter den Regalpreis – das Maximum kommt ihm am nächsten."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    now = int(time.time())
    for i, p in enumerate([1.49, 1.79, 0.99, 1.29, 1.19, 1.39]):
        db.record_prices([PricePoint(pid, p, now - (6 - i) * DAY)])

    preis, quelle = db.normal_price_estimate(item.id)

    assert preis == 1.79
    assert quelle == "historie"


def test_ein_tag_historie_ergibt_keine_schaetzung(db):
    """Das Maximum heutiger Aktionspreise ist kein Normalpreis.

    Es läge systematisch darunter und würde den Warenkorb-Vergleich in die
    falsche Richtung verschieben – lieber gar keine Zahl.
    """
    item = db.add_item("Butter")
    a = db.upsert_product(item.id, "lidl", "Butter", "a")
    b = db.upsert_product(item.id, "rewe", "Butter", "b")
    now = int(time.time())
    db.record_prices([PricePoint(a, 0.99, now), PricePoint(b, 2.49, now)])

    assert db.normal_price_estimate(item.id) == (None, "")


def test_streichpreis_gilt_auch_ohne_lange_historie(db):
    """Er ist ein echter Normalpreis, kein Schätzwert – ein Tag genügt."""
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    db.record_prices([PricePoint(pid, 0.99, int(time.time()), old_price=1.99)])

    assert db.normal_price_estimate(item.id) == (1.99, "streichpreis")


def test_ohne_daten_keine_schaetzung(db):
    """Lieber keine Zahl als eine erfundene."""
    item = db.add_item("Butter")

    assert db.normal_price_estimate(item.id) == (None, "")


def test_schaetzung_ueber_mehrere_haendler(db):
    item = db.add_item("Butter")
    a = db.upsert_product(item.id, "lidl", "Butter", "a")
    b = db.upsert_product(item.id, "rewe", "Butter", "b")
    now = int(time.time())
    for i in range(6):
        db.record_prices([PricePoint(a, 0.99, now - i * DAY),
                          PricePoint(b, 2.49, now - i * DAY)])

    assert db.normal_price_estimate(item.id) == (2.49, "historie")


# ── Alerts ───────────────────────────────────────────────────────────────


def test_alert_lebenszyklus(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")

    alert_id = db.add_alert(pid, price=0.90, baseline=1.10, drop_pct=0.18)

    assert db.last_alert(pid)["price"] == 0.90
    pending = db.pending_alerts()
    assert len(pending) == 1
    assert pending[0]["item_name"] == "Butter"

    assert db.mark_alerts_notified([alert_id]) == 1
    assert db.pending_alerts() == []
    assert db.last_alert(pid)["price"] == 0.90  # bleibt für die Dedup-Prüfung


# ── Caches ───────────────────────────────────────────────────────────────


def test_address_hash_normalisiert(db):
    assert address_hash("Musterweg", "12A", "20095", "Hamburg") == \
        address_hash("  musterweg ", "12a", "20095", " HAMBURG ")
    assert address_hash("Musterweg", "12a") != address_hash("Musterweg", "13a")


def test_home_cache(db):
    db.save_home("hash1", 53.55, 9.99, "building", "20095")

    home = db.get_home("hash1")
    assert home["lat"] == 53.55
    assert home["precision"] == "building"
    assert db.get_home("anderer-hash") is None


def test_stores_cache_laeuft_ab(db):
    db.save_stores("hash1", 10, [{"retailer_key": "lidl", "distance_km": 1.2}])

    assert len(db.get_stores("hash1", 10)) == 1
    assert db.get_stores("hash1", 5) is None          # anderer Radius
    assert db.get_stores("anderer", 10) is None       # andere Adresse
    assert db.get_stores("hash1", 10, max_age_days=0) is None  # abgelaufen


# ── Wartung ──────────────────────────────────────────────────────────────


def test_purge_old_loescht_nur_jenseits_der_retention(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    now = int(time.time())
    db.record_prices([PricePoint(pid, 1.10, now - 500 * DAY)])
    db.record_prices([PricePoint(pid, 1.20, now - 10 * DAY)])

    deleted = db.purge_old(now=now)

    assert deleted == 1
    assert [p for _, p in db.history(pid)] == [1.20]


def test_init_ist_idempotent(tmp_path):
    path = tmp_path / "shopping.db"
    first = ShoppingDB(path)
    first.add_item("Butter")

    second = ShoppingDB(path)

    assert len(second.list_items()) == 1


def test_stats(db):
    item = db.add_item("Butter")
    pid = db.upsert_product(item.id, "lidl", "Butter", "butter")
    db.record_price(pid, 1.10)

    stats = db.stats()
    assert stats["items"] == 1
    assert stats["products"] == 1
    assert stats["price_points"] == 1
    assert stats["oldest_price_ts"] is not None

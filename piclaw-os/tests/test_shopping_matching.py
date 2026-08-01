"""
Titel-Normalisierung, Produkt-Identität und Händler-Zuordnung.

Die Testfälle sind echte Titel aus marktguru- und Lidl-Antworten.
"""

import pytest

from piclaw.shopping.matching import (
    matches_item,
    normalize_retailer,
    normalize_title,
    product_key,
    retailer_label,
)


# ── Titel-Normalisierung ─────────────────────────────────────────────────


def test_umlaute_werden_ausgeschrieben():
    assert normalize_title("Müller", "Käse") == "mueller kaese"


def test_mengenangaben_fliegen_raus():
    """Sonst reißt die Reihe ab, wenn der Händler von 250 g auf 2x125 g wechselt."""
    assert normalize_title("Butter", "Je 250 g") == "butter"
    assert normalize_title("Butter", "je 2 x 125 g") == "butter"
    assert normalize_title("Cola", "1,5 l Flasche") == "cola"


def test_fuellwoerter_fliegen_raus():
    assert normalize_title(
        "Kerrygold", "Original Irische Butter", "Versch. Sorten. Gekühlt. Je 250 g"
    ) == "kerrygold original irische butter"


def test_gross_klein_egal():
    assert normalize_title("BUTTER") == normalize_title("Butter") == "butter"


def test_dubletten_werden_entfernt():
    assert normalize_title("Kaffee", "Kaffee Gold") == "kaffee gold"


def test_leere_eingabe():
    assert normalize_title("") == ""
    assert normalize_title("250 g") == ""


# ── Produkt-Identität ────────────────────────────────────────────────────


def test_verschiedene_marken_sind_verschiedene_produkte():
    a = normalize_title("Kerrygold", "Original Irische Butter")
    b = normalize_title("Gut&Günstig", "Butter")

    assert a != b
    assert product_key("Lidl", a) != product_key("Lidl", b)


def test_gleiches_produkt_bei_verschiedenen_haendlern_ist_getrennt():
    title = normalize_title("Kerrygold", "Butter")

    assert product_key("Lidl", title) != product_key("REWE", title)


def test_produktschluessel_ist_stabil_ueber_schreibweisen():
    """Der Händler kommt mal als 'REWE', mal als 'REWE Center'."""
    title = normalize_title("Kerrygold", "Butter")

    assert product_key("REWE", title) == product_key("REWE Center", title)


# ── Relevanzprüfung ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "marke, titel, suche, erwartet",
    [
        # Treffer: exaktes Wort oder Kompositum mit dem Suchwort als Kopf
        ("Weihenstephan", "Butter", "butter", True),
        ("Kerrygold", "Original Irische Butter", "butter", True),
        ("Milbona", "Weidebutter", "butter", True),
        ("Pringles", "Chips", "chips", True),
        ("Mövenpick", "Kaffee Der Himmlische", "kaffee", True),
        # Kein Treffer: anderes Produkt, obwohl das Suchwort vorkommt
        ("Hamfelder Hof", "Buttermilch Drink", "butter", False),
        ("Rama", "Brotaufstrich", "butter", False),
        ("Sanella", "Streichfett", "butter", False),
        ("Emmi", "Caffè Latte", "kaffee", False),
    ],
)
def test_matches_item(marke, titel, suche, erwartet):
    assert matches_item(normalize_title(marke, titel), suche) is erwartet


def test_buttermilch_ist_keine_butter():
    """Der Fall, der die Preisreihe verdorben hat – explizit festgenagelt.

    Ohne diese Regel erschien 0,99 € Buttermilch als günstigster Butterpreis.
    """
    assert not matches_item(normalize_title("Hamfelder Hof", "Buttermilch"), "butter")


def test_leerer_suchbegriff_laesst_alles_durch():
    assert matches_item("irgendwas", "")


def test_kompositum_mit_suchwort_vorn_faellt_durch():
    """Bekannte Grenze der Regel – deshalb gibt es Item.query als Notausgang.

    'Geschirrspültabs' und 'Kaffeepads' sind sachlich Treffer, haben das
    Suchwort aber vorn statt als Kopf. Ein rein stringbasierter Test kann sie
    nicht von 'Buttermilch' unterscheiden; wer sie braucht, hinterlegt einen
    eigenen Suchbegriff (dann greift der Filter gar nicht).
    """
    assert not matches_item(normalize_title("", "Geschirrspültabs"), "geschirrspül")
    assert not matches_item(normalize_title("Senseo", "Kaffeepads"), "kaffee")


def test_strict_matching_haengt_am_eigenen_suchbegriff():
    from piclaw.shopping.store import Item

    assert Item(name="Butter").strict_matching is True
    assert Item(name="Tabs", query="geschirrspül").strict_matching is False


def test_mehrwortsuche_reicht_ein_treffer():
    titel = normalize_title("Elinas", "Griechischer Joghurt")

    assert matches_item(titel, "griechischer joghurt")
    assert matches_item(titel, "joghurt")


# ── Händler-Zuordnung ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name, erwartet",
    [
        ("REWE", "rewe"),
        ("REWE Center", "rewe"),
        ("ALDI Nord", "aldi-nord"),
        ("ALDI SÜD", "aldi-sued"),
        ("Netto Marken-Discount", "netto-discount"),
        ("Netto", "netto"),
        ("PENNY", "penny"),
        ("Lidl", "lidl"),
        ("E center", "edeka"),
        ("EDEKA Frischemarkt", "edeka"),
        ("Kaufland", "kaufland"),
        ("Budnikowsky", "budni"),
        ("dm", "dm"),
        ("Rossmann", "rossmann"),
        ("Irgendein Hofladen", ""),
        ("", ""),
    ],
)
def test_normalize_retailer(name, erwartet):
    assert normalize_retailer(name) == erwartet


def test_netto_discount_vor_netto():
    """Reihenfolge zählt – sonst schluckt das allgemeinere Muster den Discounter."""
    assert normalize_retailer("Netto Marken-Discount") == "netto-discount"
    assert normalize_retailer("Netto Marken Discount") == "netto-discount"


def test_retailer_label():
    assert retailer_label("netto-discount") == "Netto Marken-Discount"
    assert retailer_label("aldi-sued") == "ALDI SÜD"
    assert retailer_label("", "Hofladen Meier") == "Hofladen Meier"

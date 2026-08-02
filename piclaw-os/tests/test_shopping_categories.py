"""
Relevanz über Warenkategorien statt Titel-Wortvergleich.

Alle Fälle sind echte Beobachtungen aus marktguru-Antworten (08/2026). Der
frühere Wortvergleich warf systematisch zu viel weg: zu "kaffee" kamen 33
Treffer, alle in der Kategorie Kaffee – er behielt 12. Gleichzeitig ließ er
Fehltreffer durch, die eine andere Kategorie hatten.
"""

import pytest

from piclaw.shopping.matching import (
    dominant_category,
    filter_relevant,
    matches_item,
    normalize_title,
    relevant_categories,
)
from piclaw.shopping.providers.base import Offer


def angebot(titel, kategorie_id, kategorie, rank, marke=""):
    return Offer(title=titel, brand=marke, price=1.0,
                 category_id=kategorie_id, category=kategorie, rank=rank)


# Echte Antwort auf "toast": Brote vorn, Toaster ab Position 3.
TOAST = [
    angebot("Toastbrot", 475, "Brot", 0, "Golden Toast"),
    angebot("Sandwich", 475, "Brot", 1, "Golden Toast"),
    angebot("American Sandwich", 474, "Brötchen", 2, "Golden Toast"),
    angebot("Toaster", 467, "Küchengeräte", 3, "Philips"),
    angebot("Doppellangschlitz-Toaster", 467, "Küchengeräte", 4, "SilverCrest"),
    angebot("Toaster HD2581/10", 467, "Küchengeräte", 5, "Philips"),
    angebot("Toastbrot", 475, "Brot", 6, "Harry Brot"),
]

# Echte Antwort auf "nutella": zwei Kategorien, beide richtig.
NUTELLA = [
    angebot("Nutella", 625, "Schokoaufstrich", 0, "Ferrero"),
    angebot("Nutella & Go", 155, "Kekse", 1, "Ferrero"),
    angebot("Nutella B-ready", 155, "Kekse", 2, "Ferrero"),
    angebot("Nutella Nuss-Nugat Creme", 625, "Schokoaufstrich", 3, "Ferrero"),
]


# ── Der Rang entscheidet, nicht die Häufigkeit ───────────────────────────


def test_toaster_fallen_raus_obwohl_gleich_haeufig():
    """Brot 3x und Küchengeräte 3x – nach Häufigkeit wäre es unentschieden.

    Die Quelle sortiert nach Relevanz: Brote stehen auf 0-2, Toaster erst
    ab 3. Deshalb zählt der Rang.
    """
    behalten = filter_relevant(TOAST, "toast")

    titel = [o.title for o in behalten]
    assert "Toastbrot" in titel
    assert not any("Toaster" in t for t in titel)
    assert len(behalten) == 4


def test_toastbrot_kommt_zurueck():
    """Der Wortvergleich verwarf es – "toastbrot" endet nicht auf "toast"."""
    assert not matches_item(normalize_title("Harry Brot", "Toastbrot"), "toast")

    assert any(o.title == "Toastbrot" for o in filter_relevant(TOAST, "toast"))


def test_zweite_kategorie_bleibt_wenn_sie_oben_steht():
    """Nutella & Go liegt unter Kekse, ist aber Treffer 1."""
    behalten = filter_relevant(NUTELLA, "nutella")

    assert len(behalten) == 4
    assert {o.category for o in behalten} == {"Schokoaufstrich", "Kekse"}


def test_preis_sortierung_zerstoert_die_rangfolge_nicht():
    """search_all sortiert am Ende nach Preis – der Rang muss erhalten sein."""
    durcheinander = sorted(TOAST, key=lambda o: o.title)

    behalten = filter_relevant(durcheinander, "toast")

    assert not any("Toaster" in o.title for o in behalten)


# ── Anker ────────────────────────────────────────────────────────────────


def test_dominante_kategorie_ist_die_des_besten_treffers():
    assert dominant_category(TOAST) == (475, "Brot")
    assert dominant_category(NUTELLA) == (625, "Schokoaufstrich")


def test_dominante_kategorie_ohne_daten():
    assert dominant_category([]) == (None, "")
    assert dominant_category([Offer(title="X", price=1.0)]) == (None, "")


def test_rangfenster_begrenzt_die_kategorien():
    assert relevant_categories(TOAST) == {475, 474}
    assert relevant_categories(NUTELLA) == {625, 155}


# ── Fehltreffer, die der Wortvergleich durchließ ─────────────────────────


def test_fehltreffer_mit_passendem_wort_faellt_ueber_die_kategorie_raus():
    """"KoRo Bio Nut Butter Cups" ist ein Snack, kein Butterangebot."""
    butter = [
        angebot("Original Irische Butter", 166, "Butter", 0, "Kerrygold"),
        angebot("Extra", 166, "Butter", 1, "Kerrygold"),
        angebot("Weidebutter", 166, "Butter", 2, "Milbona"),
        angebot("Nut Butter Cups", 132, "Veganes", 3, "KoRo"),
        angebot("Buttermilch Dessert", 164, "Joghurt", 4, "Frischli"),
        angebot("Butterkäse", 163, "Käse", 5, "Bauer"),
    ]

    # Der Wortvergleich liess den Snack durch …
    assert matches_item(normalize_title("KoRo", "Nut Butter Cups"), "butter")

    behalten = filter_relevant(butter, "butter")
    titel = [o.title for o in behalten]
    assert titel == ["Original Irische Butter", "Extra", "Weidebutter"]


def test_kerrygold_extra_bleibt_obwohl_butter_im_titel_fehlt():
    """Der Wortvergleich verwarf es – die Kategorie kennt es als Butter."""
    butter = [
        angebot("Original Irische Butter", 166, "Butter", 0, "Kerrygold"),
        angebot("Extra Ungesalzen", 166, "Butter", 1, "Kerrygold"),
    ]

    assert not matches_item(normalize_title("Kerrygold", "Extra Ungesalzen"), "butter")
    assert len(filter_relevant(butter, "butter")) == 2


# ── Quellen ohne Kategorien ──────────────────────────────────────────────


def test_ohne_kategorie_greift_der_wortvergleich():
    """Lidl liefert keine Kategorien – dort bleibt der Titelabgleich."""
    lidl = [
        Offer(title="Milbona Weidebutter", brand="Milbona", price=1.5),
        Offer(title="Lay's Chips", brand="Lay's", price=1.0),
    ]

    behalten = filter_relevant(lidl, "butter")

    assert [o.title for o in behalten] == ["Milbona Weidebutter"]


def test_ohne_kategorie_gelockert_wenn_andere_kategorien_haben():
    """Gemischte Liste: Kategorie-Treffer plus ein kategorieloser Lidl-Fund."""
    gemischt = [
        angebot("Toastbrot", 475, "Brot", 0, "Golden Toast"),
        Offer(title="Toastbrötchen", brand="Lidl", price=1.0),
    ]

    behalten = filter_relevant(gemischt, "toast")

    assert len(behalten) == 2


def test_leere_liste():
    assert filter_relevant([], "butter") == []


# ── Kategorie lernen ─────────────────────────────────────────────────────


class _FakeDB:
    def __init__(self):
        self.gesetzt = None

    def set_category(self, item_id, kid, kname):
        self.gesetzt = (item_id, kid, kname)


def _item(category="", category_id=None):
    from piclaw.shopping.store import Item

    return Item(id=1, name="Toast", category=category, category_id=category_id)


def test_kategorie_wird_aus_der_ungefilterten_liste_gelernt():
    """Der Fall, der live danebenging.

    Nachts beim Wechsel der Angebotswoche waren die Brote abgelaufen; auf
    der aktiv-gefilterten Liste blieb ein Toaster übrig und "Toast" lernte
    die Kategorie Küchengeräte. Gelernt wird deshalb aus allen Treffern,
    unabhängig von der Gültigkeit.
    """
    from piclaw.shopping.sampler import _lerne_kategorie

    db = _FakeDB()
    _lerne_kategorie(db, _item(), TOAST)

    assert db.gesetzt == (1, 475, "Brot")


def test_einzelner_treffer_kippt_eine_bekannte_kategorie_nicht():
    from piclaw.shopping.sampler import _lerne_kategorie

    db = _FakeDB()
    _lerne_kategorie(db, _item("Brot", 475),
                     [angebot("Toaster", 467, "Küchengeräte", 0)])

    assert db.gesetzt is None


def test_ohne_bekannte_kategorie_reicht_ein_treffer():
    """Beim ersten Mal ist wenig Beleg besser als gar keiner."""
    from piclaw.shopping.sampler import _lerne_kategorie

    db = _FakeDB()
    _lerne_kategorie(db, _item(), [angebot("Toastbrot", 475, "Brot", 0)])

    assert db.gesetzt == (1, 475, "Brot")


def test_ohne_kategorien_wird_nichts_gelernt():
    from piclaw.shopping.sampler import _lerne_kategorie

    db = _FakeDB()
    _lerne_kategorie(db, _item(), [Offer(title="X", price=1.0)])

    assert db.gesetzt is None


def test_kategorie_verfolgung_aendert_den_suchbegriff():
    """"Tempo" findet nur Tempo, "Toilettenpapier" auch Zewa und Hakle."""
    from piclaw.shopping.store import Item

    item = Item(id=1, name="Tempo", category="Toilettenpapier")
    assert item.search_term == "Tempo"

    item.track_category = True
    assert item.search_term == "Toilettenpapier"


def test_umlaute_im_kategoriebegriff_bleiben_erhalten():
    """Keine Kosmetik: "küchenrolle" liefert 9 Treffer, "kuechenrolle" null."""
    from piclaw.shopping.store import Item

    item = Item(id=1, name="Zewa", category="Küchenrolle", track_category=True)

    assert item.search_term == "Küchenrolle"


@pytest.mark.parametrize("wort, suche, strikt, erwartet", [
    ("weidebutter", "butter", True, True),    # Kompositum-Kopf
    ("buttermilch", "butter", True, False),   # Kopf ist Milch
    ("toastbrot", "toast", True, False),      # Token vorn – strikt: nein
    ("toastbrot", "toast", False, True),      # gelockert: ja
    ("kaffeepads", "kaffee", False, True),
    ("butter", "butter", True, True),
])
def test_wortvergleich_strikt_und_gelockert(wort, suche, strikt, erwartet):
    from piclaw.shopping.matching import _word_matches

    assert _word_matches(wort, suche, strikt) is erwartet

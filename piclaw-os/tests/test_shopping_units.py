"""
Grundpreise (€/kg, €/l, €/Stück).

Alle Zahlen stammen aus echten marktguru- und Lidl-Antworten (08/2026).
Gespeichert wird die Packungsgröße, nicht der Grundpreis – so bleiben auch
historische Preispunkte korrekt umrechenbar.
"""

import pytest

from piclaw.shopping import units


# ── marktguru: Größe aus Grundpreis ──────────────────────────────────────


@pytest.mark.parametrize(
    "preis, grundpreis, einheit, erwartete_groesse",
    [
        (1.79, 7.16, "kg", 0.250),    # Kerrygold 250 g
        (1.99, 4.97, "kg", 0.400),    # Rama 400-g-Becher
        (1.39, 5.56, "kg", 0.250),    # Weihenstephan
        (2.29, 5.72, "kg", 0.400),    # Arla XXL
        (1.49, 7.45, "kg", 0.200),    # Arla 200 g
        (3.69, 14.76, "kg", 0.250),   # Meggle
    ],
)
def test_groesse_aus_grundpreis(preis, grundpreis, einheit, erwartete_groesse):
    groesse, basis = units.size_from_reference(preis, grundpreis, einheit)

    assert groesse == pytest.approx(erwartete_groesse, abs=0.005)
    assert basis == "kg"


def test_liter_und_stueck():
    assert units.size_from_reference(1.50, 1.00, "l")[1] == "l"
    assert units.size_from_reference(2.00, 0.20, "Stk")[1] == "Stk"


@pytest.mark.parametrize("grundpreis", [0, None, -1])
def test_ohne_grundpreis_keine_groesse(grundpreis):
    assert units.size_from_reference(1.79, grundpreis, "kg") == (None, "")


def test_unbekannte_einheit():
    assert units.size_from_reference(1.79, 7.16, "Zentner") == (None, "")


def test_unplausible_groesse_wird_verworfen():
    """Nur echte Ausreißer, keine legitimen Großgebinde.

    50 kg oder 20 l kommen vor (Heizöl, Tierfutter, Blumenerde) und müssen
    durchgehen; erst jenseits von 1000 Basiseinheiten ist es ein Datenfehler.
    """
    assert units.size_from_reference(100.0, 2.0, "kg")[0] == pytest.approx(50)
    assert units.size_from_reference(5000.0, 2.0, "kg") == (None, "")  # 2500 kg
    assert units.size_from_reference(1.0, 100000.0, "kg") == (None, "")  # 0,00001 kg


# ── Lidl: Größe aus "1 kg = X" ───────────────────────────────────────────


def test_lidl_nimmt_den_letzten_block():
    """Vorne steht der Normalpreis, hinten der Aktionspreis.

    "Je 150/110 g · Normalpreis: 1.11 · 1 kg = 7.40/10.09 · 1 kg = 6.60/9.00"
    bei 0,99 € ⇒ 0,99/6,60 = 0,150 kg.
    """
    text = ("Je 150/110 g (Max. 24 Stück) · Normalpreis: 1.11 · "
            "1 kg = 7.40/10.09 · 1 kg = 6.60/9.00")

    groesse, basis = units.size_from_price_per_unit(0.99, text)

    assert groesse == pytest.approx(0.150, abs=0.002)
    assert basis == "kg"


def test_lidl_deluxe_honig():
    text = "Je 250 g (Max. 24 Stück) · Normalpreis: 16.99 · 1 kg = 67.96 · 1 kg = 59.96"

    groesse, _ = units.size_from_price_per_unit(14.99, text)

    assert groesse == pytest.approx(0.250, abs=0.002)


def test_lidl_ohne_grundpreis():
    assert units.size_from_price_per_unit(1.59, "Je Topf") == (None, "")
    assert units.size_from_price_per_unit(1.59, "") == (None, "")


# ── Mengenangabe als letzter Ausweg ──────────────────────────────────────


@pytest.mark.parametrize(
    "text, groesse, basis",
    [
        ("Je 250 g", 0.250, "kg"),
        ("je 400-g-Becher", 0.400, "kg"),
        ("Gekühlt. Je 250 g", 0.250, "kg"),
        ("1,5 l Flasche", 1.5, "l"),
        ("je 500 ml", 0.5, "l"),
        ("Je 3 Stück", 3.0, "Stk"),
        ("2x 350 g", 0.700, "kg"),
        ("Je 2x 350 g", 0.700, "kg"),
        ("je 130-g-Btl.", 0.130, "kg"),
    ],
)
def test_groesse_aus_mengenangabe(text, groesse, basis):
    g, b = units.size_from_quantity(text)

    assert g == pytest.approx(groesse, abs=0.002)
    assert b == basis


def test_grundpreisangabe_wird_nicht_als_menge_gelesen():
    """Sonst liest der Parser "1 kg = 5.70" als Packungsgröße von 1 kg."""
    text = "Je 300 g (Max. 24 Stück) · Normalpreis: 3.39 · 1 kg = 11.30"

    groesse, _ = units.size_from_quantity(text)

    assert groesse == pytest.approx(0.300, abs=0.002)


def test_keine_mengenangabe():
    assert units.size_from_quantity("Versch. Sorten") == (None, "")
    assert units.size_from_quantity("") == (None, "")


# ── Berechnung und Darstellung ───────────────────────────────────────────


def test_grundpreis_berechnen():
    assert units.unit_price(1.79, 0.25) == pytest.approx(7.16, abs=0.01)
    assert units.unit_price(1.49, 0.25) == pytest.approx(5.96, abs=0.01)


def test_historischer_preis_ergibt_korrekten_grundpreis():
    """Der Kern des Designs: Größe bleibt, Preis fällt."""
    groesse, _ = units.size_from_reference(1.79, 7.16, "kg")

    assert units.unit_price(0.99, groesse) == pytest.approx(3.96, abs=0.01)


@pytest.mark.parametrize("preis, groesse", [(None, 0.25), (1.79, None), (1.79, 0)])
def test_grundpreis_ohne_daten(preis, groesse):
    assert units.unit_price(preis, groesse) is None


def test_formatierung_deutsch():
    assert units.format_unit_price(1.79, 0.25, "kg") == "7,16 €/kg"
    assert units.format_unit_price(0.99, 3.0, "Stk") == "0,33 €/Stk"
    assert units.format_unit_price(1.79, None, "kg") == ""
    assert units.format_unit_price(1.79, 0.25, "") == ""


def test_sehr_kleine_grundpreise_bekommen_mehr_stellen():
    """0,02 €/Stk und 0,04 €/Stk dürfen nicht beide als 0,02 erscheinen."""
    assert units.format_unit_price(2.49, 100.0, "Stk") == "0,025 €/Stk"


def test_textmenge_korrigiert_das_rundungsrauschen():
    """1,99 € bei 4,97 €/kg ergibt 400,4 g – im Text steht exakt 400 g."""
    abgeleitet, _ = units.size_from_reference(1.99, 4.97, "kg")
    aus_text, _ = units.size_from_quantity("je 400-g-Becher")

    assert abgeleitet == pytest.approx(0.4004, abs=0.0005)
    assert units.refine_size(abgeleitet, aus_text) == pytest.approx(0.400)


def test_stark_abweichende_textmenge_wird_ignoriert():
    """Der Text nennt oft Varianten ("Je 250/200 g") – der Preis ist maßgeblich."""
    abgeleitet, _ = units.size_from_reference(1.79, 7.16, "kg")   # 250 g

    assert units.refine_size(abgeleitet, 1.0) == pytest.approx(0.25)


def test_refine_size_randfaelle():
    assert units.refine_size(None, 0.25) == pytest.approx(0.25)
    assert units.refine_size(0.25, None) == pytest.approx(0.25)
    assert units.refine_size(0.25, 0) == pytest.approx(0.25)
    assert units.refine_size(None, None) is None


def test_groessen_formatierung_rundet_rauschen_weg():
    assert units.format_size(0.400538, "kg") == "400.5 g"
    assert units.format_size(1.25352, "l") == "1.25 l"
    assert units.format_size(2.998, "Stk") == "3 Stk"


def test_groessen_formatierung_ist_lesbar():
    assert units.format_size(0.25, "kg") == "250 g"
    assert units.format_size(1.5, "kg") == "1.5 kg"
    assert units.format_size(0.5, "l") == "500 ml"
    assert units.format_size(3, "Stk") == "3 Stk"
    assert units.format_size(None, "kg") == ""

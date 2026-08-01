"""
PiClaw OS – Grundpreise (€/kg, €/l, €/Stück)

Erst der Grundpreis macht Angebote vergleichbar: 1,79 € für 250 g Butter ist
teurer als 2,49 € für 400 g, und ohne Umrechnung sieht es umgekehrt aus.

Gespeichert wird nicht der Grundpreis selbst, sondern die **Packungsgröße**
in einer Basiseinheit (kg, l, Stk). Der Grundpreis ergibt sich dann als
`preis / groesse`. Das hat zwei Vorteile: die Größe ändert sich nicht, wenn
der Preis fällt, und die Preisreihe liefert historisch korrekte Grundpreise
ohne sie mitschreiben zu müssen.

Datenlage (geprüft 08/2026):
* marktguru liefert bei **100 %** der Angebote `referencePrice` plus
  `unit.shortName` (kg 60 %, l 33 %, Stk 7 %) – daraus folgt die Größe direkt.
* Lidl liefert Text: `pricePerUnit` = "1 kg = 6.60/9.00". Bei mehreren
  Varianten steht der Aktionspreis im **letzten** "N Einheit = X"-Block.
* Fällt beides aus, wird die Menge aus der Beschreibung gelesen
  ("Je 250 g", "Je 3 Stück", "2x 350 g").
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("piclaw.shopping.units")

# Basiseinheiten, auf die alles umgerechnet wird.
KG, LITER, STUECK = "kg", "l", "Stk"

# Umrechnungsfaktoren in die jeweilige Basiseinheit.
_FAKTOR: dict[str, tuple[float, str]] = {
    "kg": (1.0, KG),
    "g": (0.001, KG),
    "mg": (0.000001, KG),
    "l": (1.0, LITER),
    "ltr": (1.0, LITER),
    "liter": (1.0, LITER),
    "ml": (0.001, LITER),
    "cl": (0.01, LITER),
    "stk": (1.0, STUECK),
    "st": (1.0, STUECK),
    "stück": (1.0, STUECK),
    "stueck": (1.0, STUECK),
    "beutel": (1.0, STUECK),
    "packung": (1.0, STUECK),
    "rolle": (1.0, STUECK),
}

_EINHEITEN = "|".join(sorted(_FAKTOR, key=len, reverse=True))

# "1 kg = 6.60/9.00" – bei Varianten zählt der erste Zahlenwert.
_PPU_RE = re.compile(
    rf"(\d+(?:[.,]\d+)?)\s*({_EINHEITEN})\s*=\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)

# "Je 250 g", "je 400-g-Becher", "2x 350 g", "1,5 l", "Je 3 Stück"
_MENGE_RE = re.compile(
    rf"(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*-?\s*({_EINHEITEN})\b",
    re.IGNORECASE,
)


def _zahl(text: str) -> float | None:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None


def normalise_unit(label: str) -> str:
    """Einheitenkürzel auf eine Basiseinheit abbilden. Leer wenn unbekannt."""
    key = (label or "").strip().lower().rstrip(".")
    eintrag = _FAKTOR.get(key)
    return eintrag[1] if eintrag else ""


def size_from_reference(
    price: float | None, reference_price: float | None, unit_label: str
) -> tuple[float | None, str]:
    """Packungsgröße aus Preis und Grundpreis ableiten (marktguru-Weg).

    1,79 € bei 7,16 €/kg ⇒ 0,250 kg.
    """
    basis = normalise_unit(unit_label)
    if not basis or not price or not reference_price or reference_price <= 0:
        return None, ""
    groesse = price / reference_price
    # Unplausibles verwerfen: 50 kg Butter oder 0,1 g sind Datenfehler.
    if not (0.001 <= groesse <= 1000):
        log.debug("Unplausible Packungsgröße %.4f %s verworfen", groesse, basis)
        return None, ""
    return groesse, basis


def size_from_price_per_unit(
    price: float | None, text: str
) -> tuple[float | None, str]:
    """Packungsgröße aus einem "1 kg = 6.60"-Text ableiten (Lidl-Weg).

    Bei mehreren Blöcken zählt der letzte – dort steht der Aktions-, davor
    der Normalpreis. Bei Varianten ("6.60/9.00") die erste Zahl.
    """
    if not price or not text:
        return None, ""
    treffer = _PPU_RE.findall(text)
    if not treffer:
        return None, ""
    menge_roh, einheit, grundpreis_roh = treffer[-1]
    basis = normalise_unit(einheit)
    menge = _zahl(menge_roh)
    grundpreis = _zahl(grundpreis_roh)
    if not basis or not menge or not grundpreis or grundpreis <= 0:
        return None, ""
    faktor = _FAKTOR[einheit.lower()][0]
    # "1 kg = 6.60" heißt: Grundpreis bezieht sich auf menge*faktor Basiseinheiten.
    groesse = price / grundpreis * menge * faktor
    if not (0.001 <= groesse <= 1000):
        return None, ""
    return groesse, basis


def size_from_quantity(text: str) -> tuple[float | None, str]:
    """Packungsgröße aus einer Mengenangabe lesen.

    Letzter Ausweg, wenn keine Quelle einen Grundpreis mitliefert.
    Mehrfachpackungen werden multipliziert ("2x 350 g" ⇒ 0,7 kg).
    """
    if not text:
        return None, ""
    # Grundpreis-Angaben ausblenden, sonst liest der Regex "1 kg" als Menge.
    ohne_ppu = _PPU_RE.sub(" ", text)
    for anzahl_roh, menge_roh, einheit in _MENGE_RE.findall(ohne_ppu):
        basis = normalise_unit(einheit)
        menge = _zahl(menge_roh)
        if not basis or not menge:
            continue
        faktor = _FAKTOR[einheit.lower()][0]
        anzahl = _zahl(anzahl_roh) or 1
        groesse = menge * faktor * anzahl
        if 0.001 <= groesse <= 1000:
            return groesse, basis
    return None, ""


def refine_size(
    derived: float | None, from_text: float | None, toleranz: float = 0.05
) -> float | None:
    """Gleicht die abgeleitete Größe gegen die Mengenangabe im Text ab.

    `size_from_reference` rechnet aus zwei gerundeten Zahlen: 1,99 € bei
    4,97 €/kg ergibt 400,4 g statt 400 g. Steht im Text eine exakte Menge und
    liegt sie nah genug an der abgeleiteten, gewinnt der Text – das ergibt
    runde Packungsgrößen und einen exakteren Grundpreis.

    Weicht sie stark ab, bleibt die abgeleitete Größe: sie passt garantiert
    zum Preis, während der Text auch eine Variante meinen kann
    ("Je 250/200 g").
    """
    if derived is None:
        return from_text
    if from_text is None or from_text <= 0:
        return derived
    if abs(from_text - derived) / derived <= toleranz:
        return from_text
    return derived


def unit_price(price: float | None, size: float | None) -> float | None:
    """Grundpreis aus Preis und Packungsgröße."""
    if price is None or not size or size <= 0:
        return None
    return price / size


def format_unit_price(price: float | None, size: float | None, label: str) -> str:
    """'5,96 €/kg' – leer, wenn kein Grundpreis bestimmbar ist."""
    wert = unit_price(price, size)
    if wert is None or not label:
        return ""
    # Bei sehr kleinen Beträgen zwei Nachkommastellen reichen nicht.
    stellen = 2 if wert >= 0.1 else 3
    return f"{wert:.{stellen}f}".replace(".", ",") + f" €/{label}"


def format_size(size: float | None, label: str) -> str:
    """'250 g' statt '0.25 kg' – für die Anzeige lesbarer."""
    if not size or not label:
        return ""
    # Abgeleitete Größen tragen Rundungsrauschen (400,4 g statt 400 g).
    # Drei signifikante Stellen reichen für jede reale Packung.
    if label == STUECK:
        return f"{round(size):g} Stk"
    if size < 1:
        klein = "g" if label == KG else "ml"
        return f"{round(size * 1000, 1):g} {klein}"
    return f"{round(size, 2):g} {label}"


__all__ = [
    "KG", "LITER", "STUECK",
    "normalise_unit",
    "size_from_reference",
    "size_from_price_per_unit",
    "size_from_quantity",
    "unit_price",
    "format_unit_price",
    "format_size",
]

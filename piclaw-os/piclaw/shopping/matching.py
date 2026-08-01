"""
PiClaw OS – Titel-Normalisierung und Händler-Zuordnung

Zwei Aufgaben:

1. **Produkt-Identität.** Ein Angebot aus einer Provider-Antwort muss über
   Wochen derselben Zeitreihe zugeordnet werden. Dafür wird der Titel
   normalisiert (Umlaute, Mengenangaben, Füllwörter, Groß/Klein) und dient
   zusammen mit dem Händler als Schlüssel.

2. **Händler-Zuordnung.** OpenStreetMap schreibt "ALDI Nord", "REWE City",
   "Netto Marken-Discount"; marktguru schreibt "ALDI Nord", "REWE Center",
   "PENNY". Beide Seiten werden auf einen kanonischen Schlüssel gebracht,
   damit sich Angebote auf die tatsächlich erreichbaren Ketten filtern lassen.
"""

from __future__ import annotations

import logging
import re
import unicodedata

log = logging.getLogger("piclaw.shopping.matching")

# Kanonische Händler-Schlüssel → Muster, die darauf zeigen. Bewusst als
# Substring-Muster auf dem normalisierten Namen, weil beide Quellen Zusätze
# anhängen ("REWE Center", "Lidl Filiale", "E center", "Aldi Süd").
# Reihenfolge zählt: spezifischere Marken zuerst, damit "netto marken-discount"
# nicht an einem allgemeineren Muster hängenbleibt.
_BRAND_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("aldi-nord", ("aldi nord",)),
    ("aldi-sued", ("aldi sued", "aldi sud", "aldi suued")),
    ("aldi", ("aldi",)),
    ("lidl", ("lidl",)),
    ("netto-discount", ("netto marken", "netto markendiscount", "netto md")),
    ("netto", ("netto",)),
    ("rewe", ("rewe",)),
    ("edeka", ("edeka", "e center", "ecenter", "e aktiv markt", "nahkauf")),
    ("penny", ("penny",)),
    ("kaufland", ("kaufland",)),
    ("real", ("real",)),
    ("norma", ("norma",)),
    ("famila", ("famila",)),
    ("combi", ("combi",)),
    ("marktkauf", ("marktkauf",)),
    ("globus", ("globus",)),
    ("hit", ("hit markt",)),
    ("tegut", ("tegut",)),
    ("dm", ("dm drogerie", "dm-drogerie", "dm markt")),
    ("rossmann", ("rossmann",)),
    ("mueller", ("mueller", "muller")),
    ("budni", ("budni", "budnikowsky")),
    ("denns", ("denns", "denn s")),
    ("alnatura", ("alnatura",)),
    ("bio-company", ("bio company",)),
    ("trinkgut", ("trinkgut",)),
    ("getraenke-hoffmann", ("getraenke hoffmann", "getranke hoffmann")),
    ("fristo", ("fristo",)),
    ("action", ("action",)),
    ("woolworth", ("woolworth",)),
)

# Anzeigename je kanonischem Schlüssel.
_BRAND_LABELS = {
    "aldi-nord": "ALDI Nord",
    "aldi-sued": "ALDI SÜD",
    "aldi": "ALDI",
    "lidl": "Lidl",
    "netto-discount": "Netto Marken-Discount",
    "netto": "Netto",
    "rewe": "REWE",
    "edeka": "EDEKA",
    "penny": "PENNY",
    "kaufland": "Kaufland",
    "real": "real",
    "norma": "NORMA",
    "famila": "famila",
    "combi": "combi",
    "marktkauf": "Marktkauf",
    "globus": "GLOBUS",
    "hit": "HIT",
    "tegut": "tegut",
    "dm": "dm",
    "rossmann": "Rossmann",
    "mueller": "Müller",
    "budni": "Budni",
    "denns": "denn's Biomarkt",
    "alnatura": "Alnatura",
    "bio-company": "BIO COMPANY",
    "trinkgut": "trinkgut",
    "getraenke-hoffmann": "Getränke Hoffmann",
    "fristo": "Fristo",
    "action": "Action",
    "woolworth": "Woolworth",
}

# "dm" ist zu kurz für Substring-Suche (steckt in "Edeka dm..." nicht, aber in
# vielen Wörtern); deshalb exakte Treffer separat.
_EXACT_BRANDS = {
    "dm": "dm",
    "hit": "hit",
    "combi": "combi",
    "real": "real",
}

_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "á": "a", "à": "a", "â": "a", "é": "e", "è": "e", "ê": "e",
    "í": "i", "ì": "i", "ó": "o", "ò": "o", "ô": "o", "ú": "u", "ù": "u",
})

# Mengen- und Verpackungsangaben. Die gehören nicht in die Produkt-Identität:
# "Butter 250 g" und "Butter 250g" sind dasselbe Produkt, und wenn der Händler
# von "250 g" auf "2 x 125 g" umstellt, soll die Reihe nicht abreißen.
_QUANTITY_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:x\s*\d+(?:[.,]\d+)?\s*)?"
    r"(?:kg|g|mg|l|ml|cl|stk|stueck|st|pkg|packung|beutel|dose|glas|flasche|becher)\b",
    re.IGNORECASE,
)

# Füllwörter aus marktguru-Beschreibungen. Enthält auch Gebindewörter samt
# der üblichen Abkürzungen ("130-g-Btl.", "500-g Pckg.", "400-g-Becher"):
# "Cola Flasche" und "Cola" sind dasselbe Produkt, und ein Wechsel des
# Gebindes darf die Preisreihe nicht abreißen lassen.
_NOISE_WORDS = frozenset({
    "je", "ca", "versch", "verschiedene", "sorten", "gekuehlt", "gekuhlt",
    "tiefgekuehlt", "angebot", "aktion", "neu", "und", "oder", "auch",
    "pro", "ab", "nur", "im", "in", "der", "die", "das", "mit", "ohne",
    "stueck", "stk", "xxl", "max",
    # Gebinde
    "packung", "packg", "pckg", "pkg", "beutel", "btl", "dose", "glas",
    "flasche", "fl", "becher", "topf", "schale", "tafel", "tuete", "tute",
    "karton", "kiste", "kasten", "netz", "bund",
})


def strip_accents(text: str) -> str:
    """Umlaute ausschreiben, restliche Diakritika entfernen."""
    text = text.translate(_UMLAUT_MAP)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_title(*parts: str) -> str:
    """Baut aus Marke/Produktname/Beschreibung einen stabilen Vergleichstitel.

    Mengenangaben und Füllwörter fliegen raus, Reihenfolge bleibt erhalten,
    Dubletten werden entfernt. Rückgabe ist kleingeschrieben und ASCII.
    """
    raw = " ".join(p for p in parts if p)
    text = strip_accents(raw).lower()
    text = _QUANTITY_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens: list[str] = []
    for token in text.split():
        if token in _NOISE_WORDS or len(token) < 2 or token.isdigit():
            continue
        if token not in tokens:
            tokens.append(token)
    return " ".join(tokens)


def normalize_retailer(name: str) -> str:
    """Händlername → kanonischer Schlüssel. Leerstring wenn unbekannt."""
    if not name:
        return ""
    flat = re.sub(r"[^a-z0-9 ]+", " ", strip_accents(name).lower())
    flat = " ".join(flat.split())
    if not flat:
        return ""

    if flat in _EXACT_BRANDS:
        return _EXACT_BRANDS[flat]

    for key, patterns in _BRAND_PATTERNS:
        if key in _EXACT_BRANDS:
            continue  # nur über exakten Treffer oben erreichbar
        for pattern in patterns:
            if pattern in flat:
                return key
    return ""


def retailer_label(key: str, fallback: str = "") -> str:
    """Kanonischer Schlüssel → Anzeigename."""
    return _BRAND_LABELS.get(key, fallback or key)


def product_key(retailer: str, title_norm: str) -> str:
    """Identität eines Produkts über Händler und normalisierten Titel."""
    return f"{normalize_retailer(retailer) or retailer.lower()}|{title_norm}"


def _word_matches(word: str, token: str) -> bool:
    """Passt ein einzelnes Titelwort zum Suchtoken?

    Regel: identisch oder **Kompositum mit dem Token als Kopf**. Im Deutschen
    steht der Kopf hinten – "Weidebutter" und "Markenbutter" sind Butter,
    "Buttermilch" ist Milch. Ein reiner Substring-Vergleich zieht genau diese
    Fehltreffer herein: die Provider-Suche nach "Butter" liefert
    "Hamfelder Hof Buttermilch Drink", was die Preisreihe verfälscht und in
    der Liste als günstigster Butterpreis auftaucht.

    Preis der Regel: Marken-Komposita mit dem Token vorn ("Chipsfrisch" zu
    "Chips") fallen raus. Dafür gibt es das Feld `query` am Artikel.
    """
    if word == token:
        return True
    return len(word) > len(token) and word.endswith(token)


def matches_item(title_norm: str, search_term: str) -> bool:
    """Prüft, ob ein Treffer wirklich zum Suchbegriff gehört.

    Die Volltextsuche machen die Provider serverseitig und großzügig; das
    hier entfernt die thematischen Ausreißer, bevor sie zu einer eigenen
    Preisreihe werden. Mehrwortsuchen ("griechischer joghurt") gelten als
    Treffer, wenn irgendein Token passt.
    """
    needle = normalize_title(search_term)
    if not needle:
        return True
    words = (title_norm or "").split()
    if not words:
        return False
    return any(
        _word_matches(word, token)
        for token in needle.split()
        for word in words
    )


__all__ = [
    "normalize_title",
    "normalize_retailer",
    "retailer_label",
    "product_key",
    "matches_item",
    "strip_accents",
]

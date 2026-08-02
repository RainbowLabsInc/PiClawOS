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
#
# Aufgenommen wird nur, was auch eine Angebotsquelle liefert: die Liste ist
# gegen die 469 Händler von `GET api.marktguru.de/api/v1/advertisers`
# abgeglichen. Möbel und Elektronik (XXXLutz, IKEA, Media Markt) fehlen
# bewusst – ihre OSM-Kategorien schleppen in Innenstädten dutzende
# Einzelhändler ohne Prospekt mit und verdrängen echte Märkte aus MAX_SHOPS.
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
    # Muss VOR "globus" stehen, sonst schluckt der Supermarkt den Baumarkt.
    ("globus-baumarkt", ("globus baumarkt",)),
    ("globus", ("globus",)),
    ("hit", ("hit markt",)),
    ("tegut", ("tegut",)),
    # marktguru schreibt "dm-drogerie markt"; die Bindestrich-Variante fehlte
    # und dm fiel dadurch komplett aus der Zuordnung.
    ("dm", ("dm drogerie", "dm markt")),
    ("rossmann", ("rossmann",)),
    ("mueller", ("mueller", "muller")),
    ("budni", ("budni", "budnikowsky")),
    ("denns", ("denns", "denn s")),
    ("alnatura", ("alnatura",)),
    ("bio-company", ("bio company",)),
    ("trinkgut", ("trinkgut",)),
    ("getraenke-hoffmann", ("getraenke hoffmann", "getranke hoffmann")),
    ("fristo", ("fristo",)),
    # ── Non-Food-Discounter ────────────────────────────────────────────
    ("action", ("action",)),
    ("woolworth", ("woolworth",)),
    ("tedi", ("tedi",)),
    ("thomas-philipps", ("thomas philipps",)),
    ("mac-geiz", ("mac geiz", "maec geiz")),
    ("pepco", ("pepco",)),
    # ── Baumarkt ───────────────────────────────────────────────────────
    ("obi", ("obi",)),
    ("toom", ("toom",)),
    ("hornbach", ("hornbach",)),
    ("bauhaus", ("bauhaus",)),
    ("hagebau", ("hagebau",)),
    ("hellweg", ("hellweg",)),
    ("baywa", ("baywa",)),
    ("b1-baumarkt", ("b1 discount",)),
    ("sonderpreis-baumarkt", ("sonderpreis baumarkt",)),
    ("v-baumarkt", ("v baumarkt",)),
    # ── Tierbedarf und Garten ──────────────────────────────────────────
    ("fressnapf", ("fressnapf",)),
    ("futterhaus", ("futterhaus",)),
    ("dehner", ("dehner",)),
    ("pflanzen-koelle", ("pflanzen koelle", "pflanzen kolle")),
    ("megazoo", ("megazoo",)),
    ("koelle-zoo", ("koelle zoo", "kolle zoo")),
    ("zoo-zajac", ("zoo zajac",)),
    ("zoo-co", ("zoo co",)),
    ("raiffeisen", ("raiffeisen markt", "raiffeisen os", "zg raiffeisen")),
    ("bellandris", ("bellandris",)),
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
    "tedi": "TEDi",
    "thomas-philipps": "Thomas Philipps",
    "mac-geiz": "Mäc Geiz",
    "pepco": "Pepco",
    "obi": "OBI",
    "toom": "toom",
    "hornbach": "HORNBACH",
    "bauhaus": "BAUHAUS",
    "hagebau": "Hagebaumarkt",
    "hellweg": "HELLWEG",
    "baywa": "BayWa Bau- & Gartenmarkt",
    "b1-baumarkt": "B1 Discount Baumarkt",
    "sonderpreis-baumarkt": "Sonderpreis-Baumarkt",
    "v-baumarkt": "V-Baumarkt",
    "globus-baumarkt": "Globus Baumarkt",
    "fressnapf": "Fressnapf",
    "futterhaus": "DAS FUTTERHAUS",
    "dehner": "Dehner Garten-Center",
    "pflanzen-koelle": "Pflanzen-Kölle",
    "megazoo": "MEGAZOO",
    "koelle-zoo": "KÖLLE-ZOO",
    "zoo-zajac": "Zoo Zajac",
    "zoo-co": "ZOO & CO",
    "raiffeisen": "Raiffeisen-Markt",
    "bellandris": "BELLANDRIS Gartencenter",
}

# Namen, die für eine Substring-Suche zu kurz sind ("dm" steckt in vielen
# Wörtern, "real" in "Areal"). Sie werden nur bei exakter Übereinstimmung
# zugeordnet.
#
# Achtung: das gilt für das *Muster*, nicht für den ganzen Schlüssel. Ein
# spezifischeres Muster desselben Schlüssels greift weiterhin – sonst fiele
# "dm-drogerie markt" komplett aus der Zuordnung, weil es weder exakt "dm"
# ist noch ein anderes Muster geprüft würde.
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
        for pattern in patterns:
            if pattern in _EXACT_BRANDS:
                continue  # zu kurz – nur über den exakten Treffer oben
            if pattern in flat:
                return key
    return ""


def retailer_label(key: str, fallback: str = "") -> str:
    """Kanonischer Schlüssel → Anzeigename."""
    return _BRAND_LABELS.get(key, fallback or key)


def product_key(retailer: str, title_norm: str) -> str:
    """Identität eines Produkts über Händler und normalisierten Titel."""
    return f"{normalize_retailer(retailer) or retailer.lower()}|{title_norm}"


def _word_matches(word: str, token: str, strict: bool = True) -> bool:
    """Passt ein einzelnes Titelwort zum Suchtoken?

    `strict=True` (Kopf-Regel): identisch oder Kompositum mit dem Token als
    **Kopf**. Im Deutschen steht der Kopf hinten – "Weidebutter" ist Butter,
    "Buttermilch" ist Milch.

    `strict=False`: zusätzlich Komposita mit dem Token **vorn**
    ("Toastbrot" zu "toast", "Kaffeepads" zu "kaffee"). Deutlich mehr echte
    Treffer, holt aber auch "Buttermilch" herein.

    Welche Variante gilt, entscheidet die Datenlage: liefert eine Quelle
    Warenkategorien (marktguru), übernimmt die Kategorie die Trennung und der
    Wortvergleich wird gar nicht gebraucht. Nur für Quellen ohne Kategorien
    (Lidl) bleibt er – dort lieber großzügig, weil eine Filialliste von ~56
    Angeboten wenig Raum für Fehltreffer lässt.
    """
    if word == token:
        return True
    if len(word) <= len(token):
        return False
    if word.endswith(token):
        return True
    return not strict and word.startswith(token)


def matches_item(title_norm: str, search_term: str, strict: bool = True) -> bool:
    """Prüft, ob ein Treffer wirklich zum Suchbegriff gehört.

    Nur noch Rückfallebene für Quellen ohne Warenkategorien – die eigentliche
    Trennung macht `dominant_category`. Mehrwortsuchen ("griechischer
    joghurt") gelten als Treffer, wenn irgendein Token passt.
    """
    needle = normalize_title(search_term)
    if not needle:
        return True
    words = (title_norm or "").split()
    if not words:
        return False
    return any(
        _word_matches(word, token, strict)
        for token in needle.split()
        for word in words
    )


# Wie viele der bestplatzierten Treffer die Kategorien bestimmen.
#
# Entscheidend ist der RANG, nicht die Häufigkeit: die Provider-Suche
# sortiert bereits nach Relevanz. Bei "toast" liegen auf 0-2 Brot/Brötchen
# und erst ab Position 3 die Toaster (Kategorie Küchengeräte) – nach
# Häufigkeit wären beide gleichauf (3:3) und die Toaster blieben drin.
# Bei "nutella" steht auf 0 Schokoaufstrich und direkt dahinter Kekse
# (Nutella & Go), beides richtig. Drei Plätze trennen beide Fälle korrekt.
_RANG_FENSTER = 3


def dominant_category(offers) -> tuple[int | None, str]:
    """Die Ankerkategorie einer Trefferliste – die des besten Treffers.

    Warum Kategorien besser sind als ein Titel-Wortvergleich, an echten
    Zahlen (marktguru, 08/2026): zu "kaffee" kamen 33 Treffer, alle in der
    Kategorie Kaffee – der Wortvergleich verwarf 21 davon (Kaffeepads,
    Kaffeekapseln, Kaffeegetränk). Zu "butter" liegt "Kerrygold Extra" in
    der Kategorie Butter, obwohl das Wort im Titel fehlt, während
    "Nut Butter Cups" unter Veganes und "Buttermilch Dessert" unter Joghurt
    liegen.
    """
    for offer in _nach_rang(offers):
        if getattr(offer, "category_id", None):
            return offer.category_id, offer.category
    return None, ""


def _nach_rang(offers) -> list:
    """Stellt die Relevanz-Reihenfolge der Quelle wieder her.

    search_all sortiert am Ende nach Preis; für die Kategorie-Auswahl zählt
    aber, was die Suchmaschine oben hatte.
    """
    return sorted(offers, key=lambda o: getattr(o, "rank", 999))


def relevant_categories(offers) -> set[int]:
    """Kategorien, die als zum Suchbegriff gehörig gelten.

    Alle, die unter den bestplatzierten `_RANG_FENSTER` Treffern vorkommen.
    """
    gesehen: list[int] = []
    for offer in _nach_rang(offers):
        kid = getattr(offer, "category_id", None)
        if not kid:
            continue
        gesehen.append(kid)
        if len(gesehen) >= _RANG_FENSTER:
            break
    return set(gesehen)


def filter_relevant(offers, search_term: str, strict: bool = True) -> list:
    """Entfernt thematische Ausreißer aus einer Trefferliste.

    Kategorie schlägt Wortvergleich: gibt es Kategorien, entscheiden sie.
    Angebote ohne Kategorie (Lidl) werden am Titel geprüft, dort bewusst
    großzügig – siehe `_word_matches`.
    """
    if not offers:
        return []
    erlaubt = relevant_categories(offers)
    out = []
    for offer in offers:
        kid = getattr(offer, "category_id", None)
        if erlaubt and kid:
            if kid in erlaubt:
                out.append(offer)
            continue
        titel = normalize_title(offer.brand, offer.title)
        # Ohne Kategorie-Anker der gelockerte Wortvergleich.
        if matches_item(titel, search_term, strict=False if erlaubt else strict):
            out.append(offer)
    return out


__all__ = [
    "normalize_title",
    "normalize_retailer",
    "retailer_label",
    "product_key",
    "matches_item",
    "dominant_category",
    "relevant_categories",
    "filter_relevant",
    "strip_accents",
]

import re

def _clean_query(query: str) -> str:
    # Chat-Präfixe entfernen
    q = re.sub(r"\[.*?\]", " ", query)

    # PLZ (5 Ziffern)
    q = re.sub(r"\b\d{5}\b", " ", q)

    # Radius (z.B. "20km", "20 km")
    q = re.sub(r"\b\d+\s*km\b", " ", q, flags=re.IGNORECASE)

    # Plattformnamen und Domains
    for term in ["kleinanzeigen.de", "ebay.de", "kleinanzeigen", "ebay", ".de"]:
        q = re.sub(re.escape(term), " ", q, flags=re.IGNORECASE)

    # Deutsche Stoppwörter/Rauschen für Marktplatz-Suche
    noise = ["suche", "finde", "such", "find", "schau", "schaue", "durchsuche",
             "zeig", "liste", "was kostet", "preis für", "gibt es", "schnäppchen",
             "angebot", "umkreis", "radius", "einen", "eine", "ein", "mir",
             "dem", "der", "die", "das", "bitte", "im", "in", "um", "von", "bis",
             "nähe", "für", "unter", "euro", "rosengarten", "hamburg", "berlin",
             "nach", "mit", "den", "auf", "mal", "einem", "einer", "münchen",
             "frankfurt", "düsseldorf", "köln", "hannover", "leipzig", "bremen",
             "kaufen", "verkaufen", "preis", "günstig", "billig", "suche", "verkaufe"]

    for word in noise:
        # q = re.sub(r"(?i)\b" + re.escape(word) + r"\b", " ", q)
        # Probieren wir es ohne \b für nähe falls es Probleme macht, oder mit besseren Grenzen
        pattern = r"(?i)(?<![\w])" + re.escape(word) + r"(?![\w])"
        q = re.sub(pattern, " ", q)

    # "Nähe" auch am Wortende entfernen falls Punkt/Fragezeichen folgt
    q = re.sub(r"(?i)nähe", " ", q)

    # Alle Sonderzeichen entfernen
    q = re.sub(r"[?!.,;:\-_/]", " ", q)

    # Mehrfache Leerzeichen bereinigen
    q = " ".join(q.split()).strip()
    return q

test_str = "nach einem Raspberry Pi 5 nähe 21224"
print(f"Original: '{test_str}'")
print(f"Cleaned:  '{_clean_query(test_str)}'")

import re

def _clean_query(query: str) -> str:
    # 1. PLZ (5 Ziffern) - using \D or boundaries
    q = re.sub(r"(?<!\d)\d{5}(?!\d)", " ", query)

    # 2. Radius
    q = re.sub(r"\b\d+\s*km\b", " ", q, flags=re.IGNORECASE)

    # 3. Plattformen
    for term in ["kleinanzeigen.de", "ebay.de", "kleinanzeigen", "ebay", ".de"]:
        q = re.sub(re.escape(term), " ", q, flags=re.IGNORECASE)

    # 4. Noise words
    noise = ["suche", "finde", "such", "find", "schau", "schaue", "durchsuche",
             "zeig", "liste", "was kostet", "preis für", "gibt es", "schnäppchen",
             "angebot", "umkreis", "radius", "einen", "eine", "ein", "mir",
             "dem", "der", "die", "das", "bitte", "im", "in", "um", "von", "bis",
             "nähe", "für", "unter", "euro", "rosengarten", "hamburg", "berlin",
             "nach", "mit", "den", "auf", "mal", "einem", "einer", "münchen",
             "frankfurt", "düsseldorf", "köln", "hannover", "leipzig", "bremen",
             "kaufen", "verkaufen", "preis", "günstig", "billig", "suche", "verkaufe"]

    for word in noise:
        # Using simpler boundaries for testing
        pattern = r"(?i)\b" + re.escape(word) + r"\b"
        q = re.sub(pattern, " ", q)

    q = re.sub(r"[?!.,;:\-_/]", " ", q)
    return " ".join(q.split()).strip()

test_cases = [
    "nach Raspberry Pi 5 21224",
    "suche nach einem Raspberry Pi 5 in der nähe von 21224 Rosengarten",
    "Raspberry Pi 5 auf Kleinanzeigen"
]

for t in test_cases:
    print(f"In:  '{t}'")
    print(f"Out: '{_clean_query(t)}'")
    print("-" * 20)

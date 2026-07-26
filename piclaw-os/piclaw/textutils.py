"""
PiClaw OS – Text-Normalisierung für Namen und Namensauflösung.

Hintergrund (Vorfall 24./25.07.2026): Sub-Agent-Namen wurden mit
`re.sub(r"[^a-zA-Z0-9]", "", …)` erzeugt, was Umlaute ersatzlos verschluckt.
Aus der Suchanfrage "Schweißgeräten Rosengarten" wurde der Agent
`Monitor_SchweigertenRosengar` – ein Name, den weder der Nutzer noch das LLM
je erraten konnte. Der Löschversuch per Chat scheiterte an drei Anläufen.

Zwei Funktionen, absichtlich getrennt:
  ascii_name()  – erzeugt Namen (verlustfrei transliteriert, ä→ae, ß→ss)
  normalize()   – vergleicht Namen (aggressiv: casefold, ohne Trennzeichen)
"""

import re
import unicodedata

# Deutsche und nordische Sonderzeichen, die eine feste Ersetzung brauchen.
# unicodedata.normalize("NFKD") allein löst ß, ø und đ nicht auf.
_TRANSLIT_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ẞ": "Ss",
    "å": "aa", "æ": "ae", "ø": "oe", "þ": "th", "ð": "dh", "đ": "d",
    "Å": "Aa", "Æ": "Ae", "Ø": "Oe", "Þ": "Th", "Ð": "Dh", "Đ": "D",
}

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")
_NORM_STRIP = re.compile(r"[^a-z0-9]")


def transliterate(text: str) -> str:
    """Ersetzt Sonderzeichen durch ASCII-Äquivalente, ohne Zeichen zu verlieren.

    "Schweißgeräte" → "Schweissgeraete" (nicht "Schweigerte")
    """
    if not text:
        return ""
    out = []
    for ch in text:
        if ch in _TRANSLIT_MAP:
            out.append(_TRANSLIT_MAP[ch])
            continue
        # Akzente abtrennen: é → e, ç → c
        decomposed = unicodedata.normalize("NFKD", ch)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(stripped)
    return "".join(out)


def ascii_name(text: str, max_len: int = 20) -> str:
    """Baut einen ASCII-Namen aus beliebigem Text.

    Transliteriert zuerst und entfernt danach, was noch übrig ist – die
    Reihenfolge ist der ganze Punkt: umgekehrt gehen Umlaute verloren.
    """
    return _NON_ALNUM.sub("", transliterate(text))[:max_len]


def normalize(text: str) -> str:
    """Aggressive Normalform für Namensvergleiche.

    Macht "Monitor_Schweissgeraete", "monitor schweißgeräte" und
    "MonitorSchweissgeraete" vergleichbar. Nur zum Vergleichen gedacht,
    nie zum Anzeigen oder Speichern.
    """
    return _NORM_STRIP.sub("", transliterate(text or "").casefold())

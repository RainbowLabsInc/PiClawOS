"""
PiClaw OS – Soul System
Loads the agent's personality, purpose and behavioral guidelines from SOUL.md.

The soul file is plain Markdown/text at /etc/piclaw/SOUL.md (or ~/.piclaw/SOUL.md).
Its content is injected verbatim at the top of every system prompt, before any
capability descriptions. This means it takes precedence over the default behavior.

The user can write anything here:
  - Personality and communication style
  - Primary mission and purpose
  - Behavioral rules and restrictions
  - Language preferences
  - Specific domain knowledge
  - Relationships and context ("You live in Munich and help with my home lab")

A default soul is written on first boot if none exists.
The agent can read and update the soul file via tools.
"""

import logging
from datetime import datetime
from pathlib import Path
from piclaw.fileutils import atomic_write_text

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.soul")

SOUL_FILE = CONFIG_DIR / "SOUL.md"

DEFAULT_SOUL = """\
# PiClaw – Soul

## Wer bin ich?
Ich bin PiClaw, ein KI-Agent der dauerhaft auf diesem Raspberry Pi 5 lebt.
Ich bin kein Cloud-Dienst und kein temporärer Assistent – ich bin fest in dieses
Gerät eingebaut und kenne seine Geschichte, seine Konfiguration und seinen Besitzer.

## Meine Aufgabe
Ich helfe dabei, diesen Pi zu verwalten, zu automatisieren und als intelligentes
Gerät zu betreiben. Ich kann eigenständig handeln, Aufgaben planen und andere
Agenten beauftragen – aber ich agiere immer im Interesse des Nutzers.

## Charakter
- Ich bin direkt, technisch präzise und effizient.
- Ich erkläre was ich tue, aber ohne unnötige Ausschweifungen.
- Ich warne vor potenziell disruptiven Aktionen, führe sie aber durch wenn bestätigt.
- Ich erinnere mich an vergangene Gespräche, Entscheidungen und Präferenzen.
- Ich lerne was dem Nutzer wichtig ist und handle entsprechend.

## Sprache
Ich antworte auf Deutsch wenn ich auf Deutsch angesprochen werde,
auf Englisch wenn auf Englisch – ich folge der Sprache des Nutzers.

## Grenzen
- Ich führe keine destruktiven Aktionen ohne explizite Bestätigung aus.
- Ich berichte ehrlich wenn ich mir unsicher bin.
- Ich speichere keine sensiblen Daten (Passwörter, private Schlüssel) im Memory.

---
*Diese Datei kann jederzeit bearbeitet werden: /etc/piclaw/SOUL.md*
*Änderungen werden beim nächsten Gespräch wirksam.*
"""


def load() -> str:
    """Load soul file. Creates default if missing."""
    if not SOUL_FILE.exists():
        _write_default()
    try:
        content = SOUL_FILE.read_text(encoding="utf-8").strip()
        if not content:
            _write_default()
            content = DEFAULT_SOUL.strip()
        log.debug("Soul loaded (%s chars)", len(content))
        return content
    except Exception as e:
        log.error("Soul load failed: %s", e)
        return DEFAULT_SOUL.strip()


def save(content: str) -> str:
    """Overwrite soul file. Returns status message."""
    try:
        SOUL_FILE.parent.mkdir(parents=True, exist_ok=True)
        SOUL_FILE.write_text(content.strip() + "\n", encoding="utf-8")
        log.info("Soul file updated.")
        return (
            f"Soul saved ({len(content)} chars). Changes take effect next conversation."
        )
    except Exception as e:
        log.error("Soul save failed: %s", e)
        return f"Error saving soul: {e}"


def append(section: str) -> str:
    """Append a new section to the soul file."""
    current = load()
    timestamp = datetime.now().strftime("%Y-%m-%d")
    new_content = current + f"\n\n---\n*Added {timestamp}:*\n{section.strip()}\n"
    return save(new_content)


def get_path() -> Path:
    return SOUL_FILE


def _write_default():
    SOUL_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(SOUL_FILE, DEFAULT_SOUL)
    log.info("Default soul written to %s", SOUL_FILE)


def build_system_prompt(
    name: str, date: str, hostname: str, base_capabilities: str
) -> str:
    """
    Build the complete system prompt:
      1. Soul (personality, purpose – user-defined, takes precedence)
      2. Base capabilities (tool list, memory instructions)
    """
    soul = load()
    return (
        f"{soul}\n\n"
        "---\n\n"
        f"{base_capabilities.format(name=name, date=date, hostname=hostname)}"
    )

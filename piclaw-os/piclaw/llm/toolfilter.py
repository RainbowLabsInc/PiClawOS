"""
PiClaw OS – Intent-basiertes Tool-Filtering

Der Agent registriert ~96 Tool-Definitionen. Zusammen mit dem System-Prompt
sind das ~11k Prompt-Tokens pro Request. Zwei Folgen, beide auf dem Pi
gemessen (26.07.2026):

  1. Groq on_demand erlaubt 8000 TPM – `groq-actions` (das schnellste
     Backend, ~113ms) lief für den vollen Agent-Pfad grundsätzlich in
     413 rate_limit_exceeded und wurde über `max_input_tokens` übersprungen.
  2. Die Tool-Auswahl wurde unzuverlässig: auf "Lösche den Agenten X" wählte
     meta/llama-3.3-70b-instruct `thermal_status`, `pi_info` und `web_suche`
     statt `agent_remove`.

Beides adressiert derselbe Hebel: bei einem klar erkannten Intent nur die
Tools mitschicken, die dafür überhaupt in Frage kommen.

Bewusst konservativ. Gefiltert wird NUR, wenn die Klassifizierung
ausschließlich aus schmalen Intent-Tags (action / home_automation / query)
plus optionalen Sprach-Tags besteht. Alles andere – general, coding,
analysis, research, … – bekommt weiterhin den vollen Satz. Lieber ein
langsamer korrekter Call als ein schneller, dem das nötige Tool fehlt.
"""

import logging
import re

log = logging.getLogger("piclaw.llm.toolfilter")

# Sprach-Tags sind keine Capability – sie dürfen weder das Filtern auslösen
# noch verhindern. Deckungsgleich mit registry._LANGUAGE_TAGS.
LANGUAGE_TAGS = frozenset({"german", "english", "french", "spanish"})

# Nur diese Tags lösen überhaupt eine Filterung aus.
NARROW_TAGS = frozenset({"action", "home_automation", "query"})

# Immer dabei, egal welcher Intent: ohne agent_list/routine_list kann das
# Modell einen falsch geschriebenen Namen nicht nachschlagen, und
# memory_search ist der Einstieg in jeden Rückfrage-Kontext.
ALWAYS_TOOLS = frozenset({
    "agent_list",
    "routine_list",
    "memory_search",
})

# Steuer-Befehle: alles, was ein deutscher Imperativ ("Lösche…", "Stoppe…",
# "Starte…", "Installiere…") plausibel meinen kann.
ACTION_TOOLS = frozenset({
    # Sub-Agenten
    "agent_create", "agent_start", "agent_stop", "agent_remove",
    "agent_update", "agent_run_now",
    # Routinen
    "routine_enable", "routine_disable", "routine_create",
    "routine_run_now", "briefing_now",
    # Erinnerungen
    "reminder_create", "reminder_cancel", "reminder_list",
    # Home Assistant
    "ha_turn_on", "ha_turn_off", "ha_get_state", "ha_list_entities",
    # GPIO / Sensorik
    "gpio_write", "gpio_pwm", "gpio_read", "gpio_status",
    "sensor_add", "sensor_remove", "sensor_list", "sensor_read",
    # Dienste
    "service_control", "service_status", "service_list",
    # Pakete
    "parcel_add", "parcel_remove", "parcel_status",
    # Netzwerk-Steuerung
    "wifi_connect", "wifi_disconnect", "wake_device",
    # LLM-Verwaltung
    "llm_add", "llm_remove", "llm_update", "llm_list", "llm_test",
    # ClawHub
    "clawhub_install", "clawhub_uninstall", "clawhub_list_installed",
    # Gedächtnis / Soul
    "memory_write", "memory_log", "soul_write", "soul_append",
    # System
    "system_update", "watchdog_status",
})

# Reine Schalt-/Ablesebefehle für Haustechnik.
HOME_AUTOMATION_TOOLS = frozenset({
    "ha_turn_on", "ha_turn_off", "ha_get_state", "ha_list_entities",
    "gpio_write", "gpio_pwm", "gpio_read", "gpio_status",
    "sensor_read", "sensor_read_all", "sensor_list",
    "wake_device",
})

# Status-Fragen ("Wie warm ist es?", "Welche Agenten laufen?").
QUERY_TOOLS = frozenset({
    "agent_run_now",
    "reminder_list",
    "ha_get_state", "ha_list_entities",
    "gpio_read", "gpio_status",
    "sensor_read", "sensor_read_all", "sensor_list",
    "service_status", "service_list",
    "parcel_status",
    "llm_list",
    "memory_stats",
    "system_info", "system_report", "pi_info", "thermal_status",
    "network_status", "watchdog_status", "watchdog_alerts",
    "clawhub_list_installed", "soul_read",
})

_TAG_GROUPS: dict[str, frozenset[str]] = {
    "action": ACTION_TOOLS,
    "home_automation": HOME_AUTOMATION_TOOLS,
    "query": QUERY_TOOLS,
}

# Zweite Stufe: benennt der Befehl ein konkretes Objekt, reicht dessen
# Tool-Gruppe. "Lösche den Agenten X" braucht keine Paket-, WLAN- oder
# ClawHub-Tools. Das bringt den Prompt deutlich unter die Groq-Grenze und
# ist zugleich der wirksamste Hebel gegen falsche Tool-Wahl – bei ~10
# Kandidaten statt ~50 vergreift sich das Modell schlicht seltener.
#
# Reihenfolge = Priorität, der erste Treffer gewinnt. Deshalb steht die
# Agenten-Gruppe vorn: "Monitor_Netzwerk" enthält auch "Netzwerk".
_OBJECT_GROUPS: list[tuple[str, frozenset[str]]] = [
    (
        r"(sub-?agent|agenten|agent|monitor)",
        frozenset({
            "agent_list", "agent_create", "agent_start", "agent_stop",
            "agent_remove", "agent_update", "agent_run_now",
        }),
    ),
    (
        r"(routine|briefing)",
        frozenset({
            "routine_list", "routine_enable", "routine_disable",
            "routine_create", "routine_run_now", "briefing_now",
        }),
    ),
    (
        r"(erinner|reminder)",
        frozenset({"reminder_create", "reminder_cancel", "reminder_list"}),
    ),
    (
        r"(licht|lampe|leuchte|steckdose|schalter|rolladen|rollo|jalousie|"
        r"fernseher|heizung|thermostat)",
        frozenset({
            "ha_turn_on", "ha_turn_off", "ha_get_state", "ha_list_entities",
            "gpio_write", "gpio_read", "gpio_status", "gpio_pwm",
        }),
    ),
    (
        r"(sensor|gpio|\bpin\b|temperatur|luftfeucht)",
        frozenset({
            "sensor_add", "sensor_remove", "sensor_list", "sensor_read",
            "sensor_read_all", "gpio_read", "gpio_write", "gpio_status",
            "gpio_pwm",
        }),
    ),
    (
        r"(paket|sendung|lieferung|tracking)",
        frozenset({
            "parcel_add", "parcel_remove", "parcel_status", "parcel_extract",
            "parcel_inbox_import",
        }),
    ),
    (
        r"(backend|modell|\bmodel\b|\bllm\b)",
        frozenset({
            "llm_list", "llm_add", "llm_remove", "llm_update", "llm_test",
            "llm_discover",
        }),
    ),
    (
        r"(skill|clawhub|plugin)",
        frozenset({
            "clawhub_install", "clawhub_uninstall", "clawhub_list_installed",
            "clawhub_search", "clawhub_info",
        }),
    ),
    (
        r"(dienst|service|systemd)",
        frozenset({"service_control", "service_status", "service_list"}),
    ),
    (
        r"(wlan|wifi|netzwerk)",
        frozenset({
            "wifi_connect", "wifi_disconnect", "wifi_scan", "network_status",
            "wake_device",
        }),
    ),
]

_COMPILED_OBJECTS: list[tuple, ] = []


def _object_group(text: str) -> frozenset[str] | None:
    """Tool-Gruppe des zuerst genannten konkreten Objekts, sonst None."""
    global _COMPILED_OBJECTS
    if not _COMPILED_OBJECTS:
        _COMPILED_OBJECTS = [
            (re.compile(pat, re.IGNORECASE), group)
            for pat, group in _OBJECT_GROUPS
        ]
    for pattern, group in _COMPILED_OBJECTS:
        if pattern.search(text):
            return group
    return None


def select_tool_names(tags, text: str | None = None) -> set[str] | None:
    """Namen der für `tags` erlaubten Tools, oder None für 'nicht filtern'.

    None heißt ausdrücklich "voller Satz" und ist der Default für alles,
    was nicht eindeutig ein schmaler Intent ist.

    `text` ist die letzte Nutzernachricht. Nennt sie ein konkretes Objekt,
    wird zusätzlich auf dessen Gruppe eingeengt – aber immer im Schnitt mit
    dem Intent, damit eine Status-Frage nicht plötzlich Löschwerkzeug
    bekommt.
    """
    if not tags:
        return None

    intent = {str(t).lower() for t in tags} - LANGUAGE_TAGS
    # Leer (nur Sprach-Tags) oder mindestens ein breites Tag dabei → nicht filtern.
    if not intent or not intent <= NARROW_TAGS:
        return None

    keep: set[str] = set(ALWAYS_TOOLS)
    for tag in intent:
        keep |= _TAG_GROUPS.get(tag, frozenset())

    if text:
        group = _object_group(text)
        if group:
            narrowed = (group & keep) | set(ALWAYS_TOOLS)
            # Schnitt leer (z.B. "Zeig mir das Paket" – parcel_status ist in
            # QUERY, parcel_remove nicht): nur übernehmen wenn etwas über die
            # Immer-dabei-Tools hinaus bleibt.
            if narrowed > set(ALWAYS_TOOLS):
                keep = narrowed

    return keep


def filter_tools(tools, tags, text: str | None = None):
    """Reduziert `tools` auf die für `tags` plausiblen Definitionen.

    Gibt `tools` unverändert zurück, wenn nicht gefiltert werden soll oder
    wenn die Filterung nichts übrig ließe (Schutz gegen umbenannte Tools).
    """
    if not tools:
        return tools

    keep = select_tool_names(tags, text)
    if keep is None:
        return tools

    filtered = [t for t in tools if getattr(t, "name", None) in keep]
    if not filtered:
        # Kein einziger Treffer – vermutlich wurden Tools umbenannt und die
        # Listen oben sind veraltet. Dann lieber alles schicken als nichts.
        log.warning(
            "Tool-Filter für tags=%s ließ nichts übrig (%d Tools) – "
            "schicke ungefiltert. Namenslisten in toolfilter.py pruefen.",
            sorted(tags), len(tools),
        )
        return tools

    if len(filtered) < len(tools):
        log.info(
            "Tool-Filter: %d → %d Tools (tags=%s)",
            len(tools), len(filtered), sorted(tags),
        )
    return filtered

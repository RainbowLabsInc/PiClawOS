"""
PiClaw OS -- Interaktiver Konfigurations-Wizard (SSH/Terminal)
============================================================

Führt schrittweise durch die komplette Ersteinrichtung.
Laeuft vollständig im Terminal -- kein Browser, kein GUI nötig.

Features:
  - Visueller Fortschrittsbalken + Schritt-Nummern
  - Validierung mit sofortigem Feedback (LLM-Test, Telegram-Test)
  - Retry bei ungueltigen Eingaben
  - Maskierte Anzeige vorhandener Secrets
  - Alle Schritte überspringbar mit Enter
  - Farbiges Diff der Änderungen am Ende
  - Neustart-Hinweis wenn nötig

Aufruf: piclaw setup
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import subprocess

log = logging.getLogger(__name__)
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── SSH / TTY-Erkennung ────────────────────────────────────────────
# Laeuft der Wizard über SSH oder eine einfache serielle Konsole,
# ist stdin kein echter TTY -> getpass fällt auf normale Eingabe zurück,
# ANSI-Farben werden unterdrückt falls TERM ungesetzt ist.

_IS_TTY = sys.stdin.isatty() and sys.stdout.isatty()
_NO_COLOR = (
    not _IS_TTY or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb"
)

# UTF-8 sicher? (ältere Pis / serielle Konsolen können ASCII-only sein)
try:
    "✓✗".encode(sys.stdout.encoding or "ascii")
    _UTF8 = True
except (UnicodeEncodeError, LookupError):
    _UTF8 = False

TERMINAL_WIDTH = shutil.get_terminal_size((80, 24)).columns


# ── ANSI Farben -- deaktiviert wenn kein echtes Terminal ───────────
def _c(code: str) -> str:
    return "" if _NO_COLOR else code


R = _c("\033[0m")
B = _c("\033[1m")
DIM = _c("\033[2m")
UL = _c("\033[4m")

FG_BLUE = _c("\033[94m")
FG_CYAN = _c("\033[96m")
FG_GREEN = _c("\033[92m")
FG_YELLOW = _c("\033[93m")
FG_RED = _c("\033[91m")
FG_WHITE = _c("\033[97m")
FG_GRAY = _c("\033[90m")


# ── Symbole -- ASCII-Fallback wenn kein UTF-8 ──────────────────────
def _sym(utf8: str, ascii_: str) -> str:
    return utf8 if _UTF8 else ascii_


OK_SYM = _sym("✓", "OK")
SKIP_SYM = _sym("→", "->")
WARN_SYM = _sym("⚠", "!")
ERR_SYM = _sym("✗", "X")
INFO_SYM = _sym("·", "*")
SPIN_SYM = _sym("⟳", "~")
ARROW = _sym("❯", ">")


# ── Hilfsfunktionen ────────────────────────────────────────────────


def _w(n: int = 1) -> None:
    """Leerzeilen."""
    print("\n" * (n - 1))


def _rule(char: str = "─", color: str = FG_GRAY) -> None:
    print(f"{color}{char * min(TERMINAL_WIDTH, 72)}{R}")


def _header(step: int, total: int, title: str, icon: str = "◆") -> None:
    _w()
    _rule()
    filled = round((step / total) * 20)
    bar_done = (
        f"{FG_BLUE}{'#' * filled}{R}"
        if not _UTF8
        else FG_BLUE + ("\u2588" * filled) + R
    )
    bar_empty = (
        f"{FG_GRAY}{'.' * (20 - filled)}{R}"
        if not _UTF8
        else FG_GRAY + ("\u2591" * (20 - filled)) + R
    )
    pct = round((step / total) * 100)
    print(
        f"  {bar_done}{bar_empty}  {FG_GRAY}{pct}%{R}  {FG_GRAY}Schritt {step}/{total}{R}"
    )
    _w()
    print(f"  {FG_CYAN}{B}{icon}  {title}{R}")
    _w()


def _ok(msg: str) -> None:
    print(f"  {FG_GREEN}{OK_SYM}{R}  {msg}")


def _skip(msg: str) -> None:
    print(f"  {FG_GRAY}{SKIP_SYM}{R}  {DIM}{msg}{R}")


def _warn(msg: str) -> None:
    print(f"  {FG_YELLOW}{WARN_SYM}{R}  {msg}")


def _err(msg: str) -> None:
    print(f"  {FG_RED}{ERR_SYM}{R}  {msg}")


def _info(msg: str) -> None:
    print(f"  {FG_GRAY}{INFO_SYM}{R}  {DIM}{msg}{R}")


def _mask(val: str, show: int = 6) -> str:
    if not val:
        return f"{FG_GRAY}(nicht gesetzt){R}"
    mask_char = "*" if not _UTF8 else "●"
    if len(val) <= show:
        return f"{FG_YELLOW}{mask_char * len(val)}{R}"
    return f"{FG_YELLOW}{mask_char * (len(val) - show)}{val[-show:]}{R}"


def _flush_stdin() -> None:
    """Leert gepufferte Eingaben aus stdin (verhindert ungewolltes Überspringen)."""
    try:
        import termios

        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """
    Eingabezeile -- SSH-sicher:
    - stdin wird vor jeder Eingabe geleert (verhindert Überspringen durch gepufferte Newlines)
    - secret=True  ->  Eingabe trotzdem sichtbar (Token wird in config gespeichert, kein Passwort)
    """
    suffix = (
        f"  {FG_GRAY}[Enter = ueberspringen]{R}"
        if not default
        else f"  {FG_GRAY}[Enter = {default[:30]}]{R}"
    )
    print(f"\n  {FG_BLUE}{ARROW}{R} {B}{label}{R}{suffix}")
    sys.stdout.flush()

    # Stdin leeren bevor wir lesen (nicht bei secret/Token-Eingaben – verschluckt Paste-Zeichen)
    if not secret:
        _flush_stdin()

    try:
        val = input("    ").strip()
    except (EOFError, KeyboardInterrupt):
        val = ""

    return val or default


def _choice(
    label: str, options: list[tuple[str, str, str]], default: str | None = None
) -> str:
    """Auswahlmenü. options = [(key, label, description), ...]"""
    print(f"\n  {B}{label}{R}\n")
    for key, lbl, desc in options:
        marker = f"{FG_GREEN}[{key}]{R}" if key == default else f"{FG_BLUE}[{key}]{R}"
        desc_txt = f"  {FG_GRAY}{desc}{R}" if desc else ""
        print(f"    {marker}  {lbl}{desc_txt}")

    default_hint = f"  {FG_GRAY}[Enter = {default}]{R}" if default else ""
    print(f"\n  {FG_BLUE}{ARROW}{R} Wahl{default_hint}: ", end="", flush=True)
    _flush_stdin()
    try:
        val = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        val = ""
    return val or (default or "")


def _spinner(msg: str) -> None:
    print(f"  {FG_BLUE}{SPIN_SYM}{R}  {DIM}{msg}...{R}", end="\r", flush=True)


def _clear_line() -> None:
    print(" " * 60, end="\r", flush=True)


def _header(step: int, total: int, title: str, icon: str = "#") -> None:
    _w()
    _rule()
    # ASCII-freundlicher Fortschrittsbalken
    filled = round((step / total) * 20)
    if _UTF8:
        bar = (
            f"{FG_BLUE}{'#' * filled}{FG_GRAY}{'.' * (20 - filled)}{R}"
            if not _UTF8
            else f"{FG_BLUE}{chr(0x2588) * filled}{FG_GRAY}{chr(0x2591) * (20 - filled)}{R}"
        )
    else:
        bar = f"[{'#' * filled}{'.' * (20 - filled)}]"
    pct = round((step / total) * 100)
    print(f"  {bar}  {FG_GRAY}{pct}%  Schritt {step}/{total}{R}")
    _w()
    display_icon = icon if _UTF8 else ""
    print(f"  {FG_CYAN}{B}{display_icon}  {title}{R}")
    _w()


def _test_async(coro) -> tuple[bool, str]:
    """Führt eine async Funktion synchron aus und gibt (ok, message) zurück."""
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    except Exception as e:
        return False, str(e)
    finally:
        loop.close()


# ── Validatoren ────────────────────────────────────────────────────


async def _validate_llm(
    backend: str, api_key: str, model: str, base_url: str
) -> tuple[bool, str]:
    try:
        from piclaw.llm.base import Message
        from piclaw.llm.api import OpenAIBackend, AnthropicBackend

        # Direkt das passende Backend instanziieren – kein MultiLLMRouter,
        # der wuerde boot() benoetigen und haengt im Wizard-Kontext
        if backend == "anthropic":
            b = AnthropicBackend(
                api_key=api_key,
                model=model,
                temperature=0.7,
                max_tokens=64,
                timeout=45,
            )
        else:
            b = OpenAIBackend(
                api_key=api_key,
                model=model,
                base_url=base_url or "https://api.openai.com/v1",
                temperature=0.7,
                max_tokens=64,
                timeout=45,
            )

        resp = await asyncio.wait_for(
            b.chat([Message(role="user", content="Reply with exactly: OK")]),
            timeout=45,
        )
        return True, (resp.content or "OK")[:80]
    except TimeoutError:
        return False, "Timeout -- API erreichbar?"
    except Exception as e:
        msg = str(e)
        # 429 = Quota überschritten, aber Key ist gültig
        if "429" in msg:
            return True, "Key gültig (Quota-Limit erreicht)"
        return False, msg[:120]


async def _validate_telegram(token: str, chat_id: str) -> tuple[bool, str]:
    try:
        import aiohttp

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": "PiClaw Setup-Test -- Verbindung erfolgreich!",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json()
                if data.get("ok"):
                    return True, "Testnachricht gesendet ✓"
                return False, data.get("description", "Unbekannter Fehler")
    except Exception as e:
        return False, str(e)[:120]


async def _validate_discord_token(token: str) -> tuple[bool, str]:
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return True, f"Bot: {data.get('username', '?')}"
                return False, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)[:120]


async def _validate_ollama(base_url: str, model: str) -> tuple[bool, str]:
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{base_url.rstrip('/')}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    models = [m["name"] for m in data.get("models", [])]
                    if model in models:
                        return True, f"Modell gefunden: {model}"
                    return (
                        True,
                        f"Ollama erreichbar, Modell '{model}' nicht lokal vorhanden -- wird beim ersten Chat geladen",
                    )
                return False, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)[:120]


# ── Schritt-Funktionen ────────────────────────────────────────────


@dataclass
class WizardState:
    cfg: object  # PiClawConfig
    changed: list[str] = field(default_factory=list)
    restart_needed: bool = False

    def mark(self, label: str) -> None:
        self.changed.append(label)


def step_welcome(state: WizardState) -> None:
    """Willkommensbildschirm."""
    border = _sym("━", "=") * min(54, TERMINAL_WIDTH - 4)

    # Dynamischer Titel: frische Installation vs. Re-run
    cfg = state.cfg
    _already_configured = bool(
        getattr(getattr(cfg, "llm", None), "api_key", None)
        or getattr(getattr(cfg, "llm", None), "backend", "") in ("local", "ollama")
    )
    _title = "PiClaw OS -- Einstellungen" if _already_configured else "PiClaw OS -- Ersteinrichtung"

    print()
    print(f"  {FG_CYAN}{B}{border}{R}")
    print(f"  {FG_CYAN}{B}  {_title}{R}")
    print(f"  {FG_CYAN}{B}{border}{R}")
    print()
    print("  Dieser Wizard fuehrt durch die vollstaendige Konfiguration.")
    print(f"  {FG_GRAY}Jeden Schritt kannst du mit Enter ueberspringen.{R}")
    print(
        f"  {FG_GRAY}Bestehende Einstellungen werden nie ungefragt ueberschrieben.{R}"
    )

    # SSH ohne PTY warnen
    if not _IS_TTY:
        print()
        print(f"  {FG_YELLOW}{WARN_SYM} Kein PTY erkannt.{R}")
        print(f"  {FG_GRAY}Empfehlung: ssh -t pi@piclaw.local piclaw setup{R}")
        print(f"  {FG_GRAY}Das -t erzwingt ein PTY (verdeckt Passworteingaben).{R}")

    print()
    # System-Info anzeigen
    try:
        import platform
        import psutil

        mem_gb = round(psutil.virtual_memory().total / 1024**3, 1)
        print(
            f"  {FG_GRAY}System:  {platform.node()} | {platform.machine()} | {mem_gb} GB RAM{R}"
        )
    except Exception as _e:
        log.debug("Wizard config pre-load: %s", _e)

    # Bereits konfigurierte Punkte zeigen
    cfg = state.cfg
    llm_ok = bool(
        getattr(getattr(cfg, "llm", None), "api_key", None)
        or getattr(getattr(cfg, "llm", None), "backend", "") in ("local", "ollama")
    )
    tg_ok = bool(getattr(getattr(cfg, "telegram", None), "token", None))
    tok_ok = bool(getattr(getattr(cfg, "api", None), "secret_key", None))

    print()
    print("  Aktueller Status:")
    _ok("LLM konfiguriert") if llm_ok else _warn("LLM nicht konfiguriert")
    _ok("Telegram konfiguriert") if tg_ok else _info("Telegram nicht konfiguriert")
    _ok("API-Token vorhanden") if tok_ok else _warn("API-Token fehlt")
    print()
    input(f"  {FG_BLUE}{ARROW}{R} {B}Enter{R} zum Starten... ")


def step_agent(state: WizardState, step: int, total: int) -> None:
    """Schritt: Agent-Name und Grundeinstellungen."""
    _header(step, total, "Agent -- Name & Grundeinstellungen", "[Agent]")
    cfg = state.cfg

    print("  Der Agent-Name erscheint in Nachrichten und im Web-Dashboard.\n")
    _info(f"Aktuell: {B}{cfg.agent_name}{R}")

    name = _prompt("Agent-Name", default=cfg.agent_name)
    if name and name != cfg.agent_name:
        cfg.agent_name = name
        state.mark(f"agent_name -> '{name}'")
        _ok(f"Agent-Name: {B}{name}{R}")
    else:
        _skip(f"Behalten: {cfg.agent_name}")

    # Log-Level
    level = _choice(
        "Log-Level:",
        [
            ("INFO", "INFO", "Standard -- wichtige Ereignisse"),
            ("DEBUG", "DEBUG", "Ausführlich -- für Entwicklung"),
            ("WARNING", "WARNING", "Nur Warnungen und Fehler"),
        ],
        default=cfg.log_level,
    )
    if level.upper() in ("INFO", "DEBUG", "WARNING") and level.upper() != cfg.log_level:
        cfg.log_level = level.upper()
        state.mark(f"log_level -> {level.upper()}")
        _ok(f"Log-Level: {level.upper()}")
    else:
        _skip(f"Behalten: {cfg.log_level}")


def step_llm(state: WizardState, step: int, total: int) -> None:
    """Schritt: LLM-Backend konfigurieren und testen."""
    _header(step, total, "LLM-Backend -- KI-Anbieter konfigurieren", "[LLM]")
    cfg = state.cfg

    has_key = bool(cfg.llm.api_key)
    is_local = cfg.llm.backend in ("local", "ollama")
    status_str = (
        f"{FG_GREEN}[OK] {cfg.llm.backend.capitalize()} / {cfg.llm.model}{R}"
        if (has_key or is_local)
        else f"{FG_YELLOW}[!] Kein API-Key{R}"
    )
    print(f"  Aktuell: {status_str}\n")

    provider = _choice(
        "Welchen Anbieter möchtest du verwenden?",
        [
            (
                "1",
                "API-Key (Auto-Detect)",
                "Anthropic / OpenAI / Gemini / Mistral / Fireworks / NVIDIA NIM",
            ),
            ("2", "Ollama (lokal)", "eigener Server · kein API-Key"),
            ("3", "Gemma 2B (Pi)", "offline · ~1.5 GB RAM · schnell"),  # Standard
            ("e", "Behalten", f"aktuell: {cfg.llm.backend}"),
        ],
        default="e",
    )

    if provider == "1":
        _w()
        print(f"  {FG_GRAY}Unterstützte Provider (Auto-Detect anhand Key-Präfix):{R}")
        print(f"  {FG_GRAY}  Anthropic:   sk-ant-...{R}")
        print(f"  {FG_GRAY}  OpenAI:      sk-proj-... oder sk-...{R}")
        print(f"  {FG_GRAY}  Google:      AIza...  → Gemini 2.0 Flash{R}")
        print(f"  {FG_GRAY}  Groq:        gsk_...  → Llama 3.3 70B{R}")
        print(f"  {FG_GRAY}  Mistral:     Key von console.mistral.ai{R}")
        print(f"  {FG_GRAY}  Fireworks:   fw-...{R}")
        print(f"  {FG_GRAY}  NVIDIA NIM:  nvapi-... → bestes verfügbares Modell{R}")
        print(f"  {FG_GRAY}  Cerebras:    csk-...{R}")
        print()

        def _try_auto(initial_key: str | None = None) -> bool:
            """Versucht Auto-Detect. Gibt True zurück wenn gespeichert."""
            key = initial_key or _prompt("API-Key", secret=True)
            if not key:
                _skip("Übersprungen")
                return True  # abgebrochen, nicht wiederholen

            from piclaw.llm.api import detect_provider_and_model

            _flush_stdin()
            _spinner("API-Key wird geprüft (Auto-Detect)...")
            try:
                loop = asyncio.new_event_loop()
                detected_backend, base_url, model = loop.run_until_complete(
                    detect_provider_and_model(key)
                )
            except Exception as e:
                _clear_line()
                _err(f"Auto-Detect fehlgeschlagen: {e}")
                return False
            finally:
                loop.close()
            _clear_line()
            _ok(f"Erkannt: {detected_backend} / {model}")

            _spinner("Verbindung testen...")
            ok, msg = _test_async(_validate_llm(detected_backend, key, model, base_url))
            _clear_line()

            if ok:
                _ok(f"Verbindung erfolgreich: {FG_GRAY}{msg[:60]}{R}")
                cfg.llm.backend = detected_backend
                cfg.llm.api_key = key
                cfg.llm.model = model
                cfg.llm.base_url = base_url
                state.mark(f"llm -> {detected_backend}/{model}")
                state.restart_needed = True
                return True

            _err(f"Verbindung fehlgeschlagen: {msg}")
            _flush_stdin()
            ans = input("    Trotzdem speichern? [j/N]: ").strip().lower()
            if ans == "j":
                cfg.llm.backend = detected_backend
                cfg.llm.api_key = key
                cfg.llm.model = model
                cfg.llm.base_url = base_url
                state.mark(f"llm -> {detected_backend}/{model} (ungetestet)")
                state.restart_needed = True
                return True

            _flush_stdin()
            retry = input("    Nochmal versuchen? [j/N]: ").strip().lower()
            if retry == "j":
                return False  # Signal: nochmal

            _flush_stdin()
            manual = input("    Manuell eingeben? [j/N]: ").strip().lower()
            if manual == "j":
                _do_manual()
                return True

            _skip("Nicht gespeichert")
            return True

        def _do_manual():
            """Manuelle LLM-Konfiguration."""
            _w()
            print(f"  {FG_GRAY}Manuelle Konfiguration – alle Parameter selbst eingeben{R}")
            print()
            providers = [
                ("openai",     "OpenAI-kompatibel (NIM, Together, Groq, Cerebras, ...)"),
                ("anthropic",  "Anthropic (Claude)"),
            ]
            for i, (p, desc) in enumerate(providers, 1):
                print(f"  [{i}] {p:12} {FG_GRAY}{desc}{R}")
            _flush_stdin()
            choice = input(f"  {FG_BLUE}{ARROW}{R} Provider [1]: ").strip() or "1"
            backend = providers[int(choice) - 1][0] if choice.isdigit() and 1 <= int(choice) <= len(providers) else "openai"

            _flush_stdin()
            base_url = _prompt("Base-URL", default="https://integrate.api.nvidia.com/v1")
            _flush_stdin()
            model = _prompt("Modell", default="")
            if not model:
                _err("Modell darf nicht leer sein")
                return
            _flush_stdin()
            key = _prompt("API-Key", secret=True) or ""

            _spinner("Verbindung testen...")
            ok, msg = _test_async(_validate_llm(backend, key, model, base_url))
            _clear_line()
            if ok:
                _ok(f"Verbindung erfolgreich: {FG_GRAY}{msg[:60]}{R}")
            else:
                _warn(f"Verbindung fehlgeschlagen: {msg}")
                _flush_stdin()
                if input("    Trotzdem speichern? [j/N]: ").strip().lower() != "j":
                    _skip("Nicht gespeichert")
                    return

            cfg.llm.backend = backend
            cfg.llm.api_key = key
            cfg.llm.model = model
            cfg.llm.base_url = base_url
            state.mark(f"llm -> {backend}/{model}")
            state.restart_needed = True
            _ok(f"Gespeichert: {backend} / {model}")

        # Hauptloop: Auto-Detect mit Wiederholungsmöglichkeit
        while not _try_auto():
            pass

    elif provider == "2":
        default_url = getattr(cfg.llm, "base_url", "") or "http://localhost:11434"
        url = _prompt("Ollama-URL", default=default_url) or default_url
        # qwen2.5:3b: bestes Tool Calling in dieser Größe, ~2GB, Pi 5-tauglich
        _cur = getattr(cfg.llm, "model", "") or ""
        _cur_backend = getattr(cfg.llm, "backend", "")
        _default_model = _cur if (_cur and _cur_backend == "ollama") else "qwen2.5:3b"
        model = _prompt("Modell", default=_default_model) or _default_model

        _spinner("Ollama erreichbar?")
        ok, msg = _test_async(_validate_ollama(url, model))
        _clear_line()
        if ok:
            _ok(f"Ollama OK: {FG_GRAY}{msg}{R}")
        else:
            _warn(f"Ollama nicht erreichbar: {msg}")
            print()
            _info("Ollama installieren und Modell laden:")
            print(f"  {FG_GRAY}  curl -fsSL https://ollama.com/install.sh | sh{R}")
            print(f"  {FG_GRAY}  ollama pull {model}{R}")
            print(f"  {FG_GRAY}  (ollama läuft danach automatisch als Service){R}")
            print()
            _info("Config wird trotzdem gespeichert – Ollama kann später gestartet werden.")

        cfg.llm.backend = "ollama"
        cfg.llm.base_url = url
        cfg.llm.model = model
        cfg.llm.api_key = ""
        state.mark(f"llm -> ollama/{model}")
        state.restart_needed = True
        _ok(f"Ollama konfiguriert: {url} / {model}")

    elif provider == "3":
        cfg.llm.backend = "local"
        cfg.llm.api_key = ""
        cfg.llm.model = "/etc/piclaw/models/gemma-2b-q4.gguf"
        state.mark("llm -> local/gemma2b")
        state.restart_needed = True
        _ok("Gemma 2B gewählt (Standard – schnellstes empfohlenes Modell)")
        print()
        ans = (
            input(
                f"  {FG_BLUE}{ARROW}{R} Modell jetzt herunterladen? (~2.4 GB, 5-20 Min) [J/n]: "
            )
            .strip()
            .lower()
        )
        if ans in ("", "j", "y"):
            print()
            _info("Lade Gemma 2B herunter – bitte warten...")
            import subprocess
            import sys

            venv_python = sys.executable
            result = subprocess.run(
                [venv_python, "-m", "piclaw.cli", "model", "download"], timeout=1800
            )
            if result.returncode == 0:
                _ok("Gemma 2B erfolgreich heruntergeladen")
            else:
                _warn("Download fehlgeschlagen – später manuell: piclaw model download")
        else:
            _info("Modell später herunterladen: piclaw model download  (~1.6 GB)")

    else:
        _skip(f"Behalten: {cfg.llm.backend}")


# Mapping: Zweck-Label → Tags die der Router verwendet
_PURPOSE_TAGS = {
    "1": (["coding", "debugging", "analysis"], "Coding & Debugging"),
    "2": (["general", "chat", "reasoning"], "Chat & Allgemein"),
    "3": (["creative", "writing"], "Kreatives Schreiben"),
    "4": (
        ["summarization", "translation", "research"],
        "Zusammenfassung & Übersetzung",
    ),
    "5": (["math", "science", "analysis"], "Mathematik & Wissenschaft"),
    "6": (["fast", "general"], "Schnelle Antworten"),
    "7": (["offline", "general", "fast"], "Offline / Lokal"),
    "8": (
        ["general", "reasoning", "coding", "creative", "summarization"],
        "Alles (General Purpose)",
    ),
}


def _ask_purpose() -> list[str]:
    """Fragt nach dem Verwendungszweck und gibt Tags zurück."""
    print()
    print("  Wofür soll dieses Backend bevorzugt eingesetzt werden?")
    print("  (Mehrfachauswahl mit Komma, z.B. 1,3)")
    print()
    for k, (_, label) in _PURPOSE_TAGS.items():
        print(f"    [{k}] {label}")
    print()
    raw = input(f"  {FG_BLUE}{ARROW}{R} Zweck [Enter = 8 (Alles)]: ").strip() or "8"
    tags: list[str] = []
    for choice in raw.split(","):
        choice = choice.strip()
        if choice in _PURPOSE_TAGS:
            tags.extend(_PURPOSE_TAGS[choice][0])
    # Deduplizieren, Reihenfolge behalten
    seen: set[str] = set()
    result = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result or _PURPOSE_TAGS["8"][0]


def step_llm_extra(state: WizardState, step: int, total: int) -> None:
    """Schritt: Weitere LLM-Backends zur Registry hinzufügen."""
    _header(step, total, "Weitere LLM-Backends -- optional", "[LLM+]")
    from piclaw.llm.registry import LLMRegistry, BackendConfig

    registry = LLMRegistry()

    print("  Hier kannst du weitere LLM-Backends registrieren.")
    print("  Für jeden Backend legst du fest wofür er zuständig ist.")
    print("  Der Router wählt dann automatisch das passende Modell.")
    print()

    while True:
        ans = (
            input(f"  {FG_BLUE}{ARROW}{R} Backend hinzufügen? [j/N]: ").strip().lower()
        )
        if ans not in ("j", "y"):
            break

        print()
        print("  Anbieter:")
        print(f"    [1]  NVIDIA NIM     {FG_GRAY}nvapi-... → Llama 3.3 70B (empfohlen){R}")
        print(f"    [2]  Groq           {FG_GRAY}gsk_... → Llama 3.3 70B (sehr schnell, free){R}")
        print(f"    [3]  Cerebras       {FG_GRAY}csk-... → Llama 3.3 70B (schnellste API){R}")
        print(f"    [4]  Google Gemini  {FG_GRAY}AIza... → Gemini 2.0 Flash{R}")
        print(f"    [5]  Anthropic      {FG_GRAY}sk-ant-... → Claude Sonnet{R}")
        print(f"    [6]  OpenAI-kompatibel {FG_GRAY}beliebiger Anbieter{R}")
        print(f"    [7]  Lokales Modell {FG_GRAY}GGUF-Datei{R}")
        print()
        prov_choice = input(f"  {FG_BLUE}{ARROW}{R} Wahl: ").strip()

        # Helper: OpenAI-kompatibler Backend speichern
        def _save_openai_backend(base_url: str, default_model: str, default_name: str,
                                   default_prio: int, temperature: float = 0.7) -> bool:
            _flush_stdin()
            key = _prompt("API-Key", secret=True)
            if not key:
                return False
            _flush_stdin()
            model = _prompt("Modell", default=default_model) or default_model
            _flush_stdin()
            name = _prompt("Name (eindeutig)", default=default_name) or default_name
            priority = int(_prompt("Priorität (1-10)", default=str(default_prio)) or str(default_prio))
            tags = _ask_purpose()
            _spinner("Verbindung testen")
            ok, msg = _test_async(_validate_llm("openai", key, model, base_url))
            _clear_line()
            if ok:
                _ok(f"Verbindung OK: {FG_GRAY}{msg[:50]}{R}")
            else:
                _warn(f"Test fehlgeschlagen: {msg}")
                _flush_stdin()
                if input("    Trotzdem speichern? [j/N]: ").strip().lower() != "j":
                    return False
            bc = BackendConfig(
                name=name, provider="openai", model=model, api_key=key,
                base_url=base_url, priority=priority, tags=tags,
                temperature=temperature,
                notes=f"Zweck: {', '.join(tags)} – via Setup-Wizard",
            )
            registry.add(bc)
            _ok(f"Backend '{name}' gespeichert  {FG_GRAY}Tags: {', '.join(tags)}{R}")
            return True

        if prov_choice == "1":
            # NVIDIA NIM – mit Live-Modell-Detection
            _flush_stdin()
            key = _prompt("NVIDIA NIM API-Key (nvapi-...)", secret=True)
            if not key:
                continue
            _spinner("Verfügbare Modelle abrufen...")
            from piclaw.llm.api import _detect_nim_model
            loop2 = asyncio.new_event_loop()
            nim_model = loop2.run_until_complete(
                _detect_nim_model(key, "https://integrate.api.nvidia.com/v1")
            )
            loop2.close()
            _clear_line()
            _ok(f"Empfohlenes Modell: {nim_model}")
            _save_openai_backend(
                "https://integrate.api.nvidia.com/v1", nim_model,
                "nim-fallback", 7, temperature=0.6
            )

        elif prov_choice == "2":
            # Groq
            _info("Kostenlos registrieren: console.groq.com")
            _save_openai_backend(
                "https://api.groq.com/openai/v1",
                "llama-3.3-70b-versatile", "groq-fallback", 7
            )

        elif prov_choice == "7":
            # Cerebras
            _info("Kostenlos registrieren: cloud.cerebras.ai")
            _save_openai_backend(
                "https://api.cerebras.ai/v1",
                "llama-3.3-70b", "cerebras-fallback", 6
            )

        elif prov_choice == "4":
            # Google Gemini
            _info("Kostenlos: aistudio.google.com/apikey  (AIza... Key)")
            _save_openai_backend(
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "gemini-2.0-flash", "gemini-fallback", 6
            )

        elif prov_choice == "5":
            # Anthropic
            _flush_stdin()
            key = _prompt("Anthropic API-Key (sk-ant-…)", secret=True)
            if not key:
                continue
            _flush_stdin()
            model = _prompt("Modell", default="claude-sonnet-4-20250514") or "claude-sonnet-4-20250514"
            _flush_stdin()
            name = _prompt("Name", default="claude-fallback") or "claude-fallback"
            priority = int(_prompt("Priorität", default="7") or "7")
            tags = _ask_purpose()
            _spinner("Verbindung testen")
            ok, msg = _test_async(_validate_llm("anthropic", key, model, "https://api.anthropic.com"))
            _clear_line()
            if ok:
                _ok("Verbindung OK")
            else:
                _warn(f"Test fehlgeschlagen: {msg}")
                _flush_stdin()
                if input("    Trotzdem speichern? [j/N]: ").strip().lower() != "j":
                    continue
            bc = BackendConfig(
                name=name, provider="anthropic", model=model, api_key=key,
                base_url="https://api.anthropic.com", priority=priority, tags=tags,
                notes=f"Zweck: {', '.join(tags)} – via Setup-Wizard",
            )
            registry.add(bc)
            _ok(f"Backend '{name}' gespeichert  {FG_GRAY}Tags: {', '.join(tags)}{R}")

        elif prov_choice == "6":
            # OpenAI-kompatibel (manuell)
            _flush_stdin()
            base_url = _prompt("Base URL", default="https://api.openai.com/v1") or "https://api.openai.com/v1"
            _save_openai_backend(base_url, "gpt-4o", "openai-extra", 6)

        elif prov_choice == "3":
            from piclaw.config import CONFIG_DIR

            default_path = str(CONFIG_DIR / "models" / "gemma-2b-q4.gguf")
            model_path = (
                _prompt("Pfad zur GGUF-Datei", default=default_path) or default_path
            )
            name = _prompt("Name", default="local-gemma") or "local-gemma"
            priority = int(_prompt("Priorität", default="3") or "3")
            tags = _ask_purpose()

            from pathlib import Path

            if not Path(model_path).exists():
                _warn(f"Datei nicht gefunden: {model_path}")
                _info("Später herunterladen: piclaw model download")
            else:
                _ok(f"Modell gefunden: {model_path}")

            bc = BackendConfig(
                name=name,
                provider="local",
                model=model_path,
                api_key="",
                base_url="",
                priority=priority,
                tags=tags,
                notes=f"Lokales GGUF – Zweck: {', '.join(tags)}",
            )
            registry.add(bc)
            _ok(
                f"Lokales Backend '{name}' registriert  {FG_GRAY}Tags: {', '.join(tags)}{R}"
            )

        else:
            break

        print()

    current = registry.list_all()
    if current:
        print(f"  Registrierte Backends ({len(current)}):")
        for b in current:
            status = "✅" if b.enabled else "⏸"
            print(f"    {status} [{b.priority}] {b.name} – {b.provider}/{b.model[:40]}")
    print()


def step_telegram(state: WizardState, step: int, total: int) -> None:
    """Schritt: Telegram konfigurieren."""
    _header(step, total, "Telegram -- Benachrichtigungen & Chat", "[TG]")
    cfg = state.cfg

    has_token = bool(cfg.telegram.token)
    if has_token:
        print(f"  Token vorhanden: {_mask(cfg.telegram.token)}")
        print(f"  Chat-ID: {FG_GRAY}{cfg.telegram.chat_id or '(leer)'}{R}")
        if (
            input(f"\n  {FG_BLUE}{ARROW}{R} Neu konfigurieren? [j/N]: ").strip().lower()
            != "j"
        ):
            _skip("Behalten")
            return
    else:
        print("  Telegram erlaubt dem Agenten, dir Nachrichten zu senden")
        print("  und Befehle per Telegram entgegenzunehmen.\n")
        print(
            f"  {FG_GRAY}Bot erstellen: Schreibe {B}@BotFather{R}{FG_GRAY} auf Telegram -> /newbot{R}"
        )
        print(
            f"  {FG_GRAY}Chat-ID finden: Schreibe {B}@userinfobot{R}{FG_GRAY} auf Telegram{R}"
        )

    token = _prompt("Bot-Token (von @BotFather)", secret=True)
    if not token:
        _skip("Telegram nicht konfiguriert")
        return

    chat_id = _prompt("Deine Chat-ID (von @userinfobot)")
    if not chat_id:
        _warn("Chat-ID fehlt -- ohne diese kann der Agent dir keine Nachrichten senden")
        if input("    Trotzdem nur Token speichern? [j/N]: ").strip().lower() != "j":
            _skip("Nicht gespeichert")
            return

    _spinner("Verbindung testen")
    ok, msg = (
        _test_async(_validate_telegram(token, chat_id))
        if chat_id
        else (False, "Keine Chat-ID")
    )
    _clear_line()

    if ok:
        _ok(f"Telegram OK: {msg}")
    else:
        _warn(f"Test fehlgeschlagen: {msg}")
        _info("Hast du deinem Bot schon eine Nachricht geschickt?")
        if input("    Trotzdem speichern? [j/N]: ").strip().lower() != "j":
            _skip("Nicht gespeichert")
            return

    cfg.telegram.token = token
    cfg.telegram.chat_id = chat_id
    state.mark("telegram konfiguriert")
    state.restart_needed = True
    _ok("Telegram gespeichert")


def step_discord(state: WizardState, step: int, total: int) -> None:
    """Schritt: Discord konfigurieren (optional)."""
    _header(step, total, "Discord -- Bot (optional)", "[Discord]")
    cfg = state.cfg

    has_token = bool(cfg.discord.token)
    if has_token:
        print(f"  Bot-Token vorhanden: {_mask(cfg.discord.token)}")
        print(f"  Channel-ID: {FG_GRAY}{cfg.discord.channel_id or '(leer)'}{R}")
        if (
            input(f"\n  {FG_BLUE}{ARROW}{R} Neu konfigurieren? [j/N]: ").strip().lower()
            != "j"
        ):
            _skip("Behalten")
            return
    else:
        print("  Discord ist optional. Ueberspringen mit Enter.\n")
        print(f"  {FG_GRAY}Bot erstellen: {UL}discord.com/developers/applications{R}")
        print(f"  {FG_GRAY}Channel-ID: Rechtsklick auf Channel -> ID kopieren{R}")

    token = _prompt("Bot-Token", secret=True)
    if not token:
        _skip("Discord nicht konfiguriert")
        return

    _spinner("Token prüfen")
    ok, msg = _test_async(_validate_discord_token(token))
    _clear_line()
    if ok:
        _ok(f"Token gueltig: {FG_GRAY}{msg}{R}")
    else:
        _warn(f"Token-Pruefung: {msg}")

    channel_raw = _prompt("Channel-ID (Zahlen)")
    if channel_raw:
        try:
            cfg.discord.channel_id = int(channel_raw)
        except ValueError:
            _warn("Keine gueltige Channel-ID")

    cfg.discord.token = token
    state.mark("discord konfiguriert")
    state.restart_needed = True
    _ok("Discord gespeichert")


def step_agentmail(state: WizardState, step: int, total: int) -> None:
    """Schritt: AgentMail konfigurieren (optional)."""
    _header(step, total, "AgentMail -- E-Mail fuer Dameon (optional)", "[Mail]")
    cfg = state.cfg

    has_key = bool(cfg.agentmail.api_key)
    if has_key:
        addr = cfg.agentmail.email_address or "(Inbox noch nicht erstellt)"
        print(f"  API-Key vorhanden: {_mask(cfg.agentmail.api_key)}")
        print(f"  Adresse: {FG_GRAY}{addr}{R}")
        if (
            input(f"\n  {FG_BLUE}{ARROW}{R} Neu konfigurieren? [j/N]: ").strip().lower()
            != "j"
        ):
            _skip("Behalten")
            return
    else:
        print("  AgentMail gibt Dameon eine eigene E-Mail-Adresse.")
        print("  Damit kann er Versandbestaetigungen empfangen und")
        print("  Pakete automatisch tracken.\n")
        print(f"  {FG_GRAY}1. Gehe zu {UL}https://agentmail.to{R}")
        print(f"  {FG_GRAY}2. Erstelle einen Account und generiere einen API-Key{R}")
        print(f"  {FG_GRAY}3. Kopiere den API-Key{R}\n")

    api_key = _prompt("AgentMail API-Key", secret=True)
    if not api_key:
        _skip("AgentMail nicht konfiguriert")
        return

    cfg.agentmail.api_key = api_key

    # Inbox erstellen
    agent_name = cfg.agent_name or "Dameon"
    default_user = agent_name.lower().replace(" ", "")
    username = _prompt(f"Inbox-Benutzername [{default_user}]") or default_user

    _spinner(f"Erstelle {username}@agentmail.to")
    try:
        ok, result = _test_async(_create_agentmail_inbox(api_key, agent_name, username))
        _clear_line()
        if ok:
            import re as _re
            id_match = _re.search(r"ID:\s*(\S+)", result)
            email_match = _re.search(r"Email:\s*(\S+)", result)
            if id_match:
                cfg.agentmail.inbox_id = id_match.group(1)
            if email_match:
                cfg.agentmail.email_address = email_match.group(1)
            _ok(f"Inbox erstellt: {cfg.agentmail.email_address}")
        else:
            _warn(f"Inbox-Erstellung: {result}")
            _ok("API-Key gespeichert - Inbox kann spaeter erstellt werden")
    except Exception as e:
        _clear_line()
        _warn(f"Fehler: {e}")
        _ok("API-Key gespeichert")

    state.mark("agentmail konfiguriert")
    state.restart_needed = True


async def _create_agentmail_inbox(api_key: str, display_name: str, username: str):
    """Erstellt eine AgentMail-Inbox. Gibt (True, info_str) zurueck."""
    try:
        from agentmail import AsyncAgentMail
    except ImportError:
        return False, "agentmail nicht installiert. Bitte: pip install agentmail --break-system-packages"
    client = AsyncAgentMail(api_key=api_key)
    inbox = await client.inboxes.create(display_name=display_name, username=username)
    return True, f"Email: {inbox.email_address}\nID: {inbox.inbox_id}"


def step_parcel_tracking(state: WizardState, step: int, total: int) -> None:
    """Schritt: Paket-Tracking konfigurieren (optional)."""
    _header(step, total, "Paket-Tracking -- Sendungsverfolgung (optional)", "[Paket]")
    cfg = state.cfg

    # DHL API Key aus config.toml lesen (nicht im Dataclass)
    import tomllib as _toml
    from piclaw.config import CONFIG_DIR as _CD
    _cfg_path = _CD / "config.toml"
    _dhl_key = ""
    if _cfg_path.exists():
        try:
            _raw = _toml.loads(_cfg_path.read_text(encoding="utf-8"))
            _dhl_key = _raw.get("parcel_tracking", {}).get("dhl_api_key", "")
        except Exception:
            pass

    print("  Dameon kann Pakete von DHL, Hermes, DPD, GLS und UPS verfolgen.")
    print("  Trackingnummern per Telegram, Chat oder E-Mail-Weiterleitung.\n")

    if cfg.agentmail.email_address:
        print(f"  {FG_GREEN}{CHECK}{R} AgentMail aktiv: {cfg.agentmail.email_address}")
        print(f"  {FG_GRAY}Versandbestaetigungen an diese Adresse weiterleiten{R}")
        print(f"  {FG_GRAY}→ Dameon erkennt Trackingnummern automatisch{R}\n")
    else:
        print(f"  {FG_GRAY}Tipp: AgentMail einrichten fuer automatische Paketerkennung{R}\n")

    if _dhl_key:
        print(f"  DHL API-Key vorhanden: {_mask(_dhl_key)}")
        if (
            input(f"\n  {FG_BLUE}{ARROW}{R} Neu konfigurieren? [j/N]: ").strip().lower()
            != "j"
        ):
            _skip("Behalten")
            return
    else:
        print("  Optional: DHL API-Key fuer detaillierte Tracking-Events.")
        print(f"  {FG_GRAY}Kostenlos auf {UL}https://developer.dhl.com{R}")
        print(f"  {FG_GRAY}→ 'Shipment Tracking - Unified' API freischalten{R}")
        print(f"  {FG_GRAY}Ohne Key funktioniert Tracking trotzdem (via Parcello){R}\n")

    dhl_key = _prompt("DHL API-Key (Enter = ueberspringen)", secret=True)
    if not dhl_key:
        _ok("Paket-Tracking aktiv (ohne DHL API-Key)")
        state.mark("paket-tracking konfiguriert")
        return

    # DHL Key in config.toml schreiben
    try:
        if _cfg_path.exists():
            content = _cfg_path.read_text(encoding="utf-8")
        else:
            content = ""

        if "[parcel_tracking]" in content:
            import re as _re
            content = _re.sub(
                r'(dhl_api_key\s*=\s*)"[^"]*"',
                f'\\1"{dhl_key}"',
                content,
            )
        else:
            content += f'\n[parcel_tracking]\ndhl_api_key = "{dhl_key}"\n'

        _cfg_path.write_text(content, encoding="utf-8")
        _ok("DHL API-Key gespeichert")
    except Exception as e:
        _warn(f"Fehler beim Speichern: {e}")

    state.mark("paket-tracking + DHL konfiguriert")
    state.restart_needed = True


def step_mqtt(state: WizardState, step: int, total: int) -> None:
    """Schritt: MQTT / Home Assistant (optional)."""
    _header(step, total, "MQTT -- Home Assistant Integration (optional)", "[MQTT]")

    print("  MQTT verbindet PiClaw mit Home Assistant, Mosquitto etc.\n")
    print(f"  {FG_GRAY}Wird in /etc/piclaw/config.toml unter [mqtt] gespeichert.{R}")

    skip = _prompt("MQTT-Broker-Adresse (z.B. homeassistant.local)", default="")
    if not skip:
        _skip("MQTT nicht konfiguriert")
        return

    broker = skip
    port = _prompt("Port", default="1883") or "1883"
    user = _prompt("Benutzername (optional)")
    passwd = _prompt("Passwort (optional)", secret=True) if user else ""
    ha_disc = (
        input(
            f"\n  {FG_BLUE}{ARROW}{R} Home Assistant Auto-Discovery aktivieren? [J/n]: "
        )
        .strip()
        .lower()
    )

    # Schreibe in config.toml direkt (MQTT ist noch kein Dataclass-Feld)
    try:
        from piclaw.config import CONFIG_FILE
        import tomllib
        import tomli_w

        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "rb") as f:
                raw = tomllib.load(f)
        else:
            raw = {}
        raw["mqtt"] = {
            "broker": broker,
            "port": int(port),
            "username": user,
            "password": passwd,
            "ha_discovery": ha_disc != "n",
            "topic_in": "piclaw/in",
            "topic_out": "piclaw/out",
        }
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(raw, f)
        state.mark(f"mqtt -> {broker}:{port}")
        _ok(f"MQTT gespeichert: {broker}:{port}")
        if ha_disc != "n":
            _info("Home Assistant erkennt PiClaw automatisch nach dem nächsten Start")
    except Exception as e:
        _err(f"Speichern fehlgeschlagen: {e}")


def step_homeassistant(state: WizardState, step: int, total: int) -> None:
    """Schritt: Home Assistant Connector konfigurieren."""
    _header(step, total, "Home Assistant -- Smart Home Connector", "[HA]")

    print("  Verbindet PiClaw mit deiner Home Assistant Instanz.")
    print("  Du kannst dann per Telegram/Discord schreiben:")
    print(f"  {FG_GRAY}  'Mach das Wohnzimmerlicht aus'")
    print(f"  {FG_GRAY}  'Wie warm ist es im Schlafzimmer?'")
    print(f"  {FG_GRAY}  'Starte die Abendroutine'{R}")
    print()

    # Pruefen ob bereits konfiguriert
    try:
        from piclaw.config import CONFIG_FILE
        import tomllib

        existing_url = ""
        existing_token = ""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "rb") as f:
                raw = tomllib.load(f)
            ha_raw = raw.get("homeassistant", {})
            existing_url = ha_raw.get("url", "")
            existing_token = ha_raw.get("token", "")
    except Exception:
        existing_url = ""
        existing_token = ""

    if existing_token:
        _ok(f"Bereits konfiguriert: {existing_url}")
        if (
            input(f"\n  {FG_BLUE}{ARROW}{R} Neu konfigurieren? [j/N]: ").strip().lower()
            != "j"
        ):
            _skip("Behalten")
            return

    print(f"\n  {FG_GRAY}Long-Lived Access Token in HA erstellen:{R}")
    print(f"  {FG_GRAY}HA -> Profil (unten links) -> Sicherheit -> Token erstellen{R}")
    print()

    url = (
        _prompt(
            "Home Assistant URL",
            default=existing_url or "http://homeassistant.local:8123",
        )
        or "http://homeassistant.local:8123"
    )

    token = _prompt("Long-Lived Access Token", secret=True)
    if not token:
        _skip("Home Assistant nicht konfiguriert")
        return

    # Verbindung testen
    _spinner("Verbindung zu Home Assistant testen")
    ok, info = _test_async(_ping_ha(url, token))
    _clear_line()

    if ok:
        _ok(f"Home Assistant erreichbar: v{info}")
    else:
        _warn(f"Nicht erreichbar: {info}")
        _info("URL korrekt? Ist HA im selben Netzwerk? Token gueltig?")
        if (
            input(f"  {FG_BLUE}{ARROW}{R} Trotzdem speichern? [J/n]: ").strip().lower()
            == "n"
        ):
            _skip("Nicht gespeichert")
            return

    # Push-Events konfigurieren
    print()
    print(f"  {B}Push-Benachrichtigungen{R} -- welche Ereignisse sollen")
    print("  per Telegram/Discord gemeldet werden?")
    print()
    event_choices = {
        "m": ("motion_detected", "Bewegung erkannt"),
        "d": ("door_opened", "Tuer/Fenster geoeffnet"),
        "a": ("alarm_triggered", "Alarm ausgeloest"),
        "s": ("smoke_detected", "Rauch erkannt"),
        "": ("flood_detected", "Wasser/Flut erkannt"),
    }
    for key, (_, label) in event_choices.items():
        print(f"    [{key}] {label}")
    print("    [Enter] Alle aktivieren (empfohlen)")
    print()
    sel = (
        input(f"  {FG_BLUE}{ARROW}{R} Auswahl (z.B. 'mda' fuer mehrere): ")
        .strip()
        .lower()
    )

    if not sel:
        chosen_events = [v[0] for v in event_choices.values()]
    else:
        chosen_events = [event_choices[k][0] for k in sel if k in event_choices]

    if not chosen_events:
        chosen_events = [v[0] for v in event_choices.values()]

    # In config.toml schreiben
    try:
        import tomllib
        import tomli_w

        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "rb") as f:
                raw = tomllib.load(f)
        else:
            raw = {}

        raw["homeassistant"] = {
            "url": url.rstrip("/"),
            "token": token,
            "verify_ssl": False,
            "notify_on_events": chosen_events,
        }
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(raw, f)

        state.mark(f"homeassistant -> {url}")
        state.restart_needed = True
        _ok("Home Assistant gespeichert ✅")
        _ok(f"Push-Events: {', '.join(chosen_events) if chosen_events else 'keine'}")
        _info("Nach dem Neustart: 'piclaw' -> 'Mach das Licht an'")
        _info("Falls HA nicht erreichbar war: 'piclaw setup' erneut aufrufen sobald HA laeuft")
    except Exception as e:
        _err(f"Speichern fehlgeschlagen: {e}")


async def _ping_ha(url: str, token: str) -> tuple[bool, str]:
    """Testet HA-Verbindung direkt ohne den vollen Client."""
    import aiohttp as _aiohttp

    try:
        async with _aiohttp.ClientSession() as s:
            async with s.get(
                f"{url.rstrip('/')}/api/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=_aiohttp.ClientTimeout(total=8),
                ssl=False,
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return True, data.get("version", "OK")
                return False, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)[:80]


def step_wifi(state: WizardState, step: int, total: int) -> None:
    """Schritt: WLAN konfigurieren (optional, via nmcli)."""
    _header(step, total, "WLAN -- Netzwerkverbindung", "[WLAN]")

    # Aktuellen Status zeigen
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-", "DEVICE,STATE,CONNECTION", "device"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        connected = [
            l
            for l in result.stdout.strip().split("\n")
            if "connected" in l and "lo" not in l
        ]
        if connected:
            for c in connected:
                parts = c.split(":")
                _ok(
                    f"Verbunden: {parts[0] if parts else c}  {FG_GRAY}({parts[2] if len(parts) > 2 else ''}){R}"
                )
            if (
                input(
                    f"\n  {FG_BLUE}{ARROW}{R} Anderes Netzwerk konfigurieren? [j/N]: "
                )
                .strip()
                .lower()
                != "j"
            ):
                _skip("WLAN-Verbindung behalten")
                return
        else:
            _warn("Keine aktive WLAN-Verbindung gefunden")
            print()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _info("nmcli nicht verfügbar -- WLAN manuell konfigurieren")
        _skip("Übersprungen")
        return

    # Verfügbare Netzwerke scannen
    try:
        _spinner("Netzwerke suchen")
        scan = subprocess.run(
            ["nmcli", "-t", "-", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _clear_line()
        nets = []
        for line in scan.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 2 and parts[0]:
                nets.append((parts[0], parts[1] if len(parts) > 1 else "?"))

        if nets:
            print(f"\n  {FG_GRAY}Gefundene Netzwerke:{R}")
            for ssid, signal in nets[:8]:
                bars = "▂▄▆█"[min(3, int(signal or 0) // 25)]
                print(f"    {FG_GRAY}{bars}{R}  {ssid}")
    except Exception as _e:
        log.debug("wifi scan display: %s", _e)

    ssid = _prompt("WLAN-Name (SSID)")
    if not ssid:
        _skip("WLAN nicht konfiguriert")
        return

    password = _prompt("Passwort", secret=True)
    _spinner(f"Verbinde mit '{ssid}'")
    try:
        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        _clear_line()
        if result.returncode == 0:
            _ok(f"Verbunden mit '{ssid}'")
            state.mark(f"wlan -> {ssid}")
        else:
            _err(f"Verbindung fehlgeschlagen: {result.stderr.strip()[:80]}")
    except subprocess.TimeoutExpired:
        _clear_line()
        _err("Timeout -- SSID oder Passwort falsch?")


def step_proactive(state: WizardState, step: int, total: int) -> None:
    """Schritt: Proaktiver Agent – Briefings & Routinen."""
    _header(step, total, "Proaktiver Agent -- Briefings & Routinen", "[Auto]")

    print("  PiClaw kann dich automatisch informieren -- ohne dass du fragst.\n")
    print("  Beispiele:")
    print(f"  {FG_GRAY}  Morgens um 7: Wetter + Hausueberblick per Telegram{R}")
    print(f"  {FG_GRAY}  Abends um 22: Offene Lichter und Tueren checken{R}")
    print(f"  {FG_GRAY}  Pi zu heiss (>80 Grad): sofortige Warnung{R}")
    print(f"  {FG_GRAY}  Wochentags: Systembericht{R}")
    print()

    # Vordefinierte Routinen anzeigen und aktivieren lassen
    defaults = [
        ("morning_briefing", "Morgen-Briefing", "taeglich 07:00", "0 7 * * *"),
        ("evening_check", "Abend-Check", "taeglich 22:00", "0 22 * * *"),
        ("weekly_report", "Wochenbericht", "Montag 08:00", "0 8 * * 1"),
        ("temp_check", "Temperatur-Watcher", "alle 30 Minuten", "*/30 * * * *"),
    ]

    choices: list[str] = []
    custom_cron: dict[str, str] = {}  # key → angepasste Cron-Expression

    print(f"  {B}Welche Routinen aktivieren?{R}")
    print(f"  {FG_GRAY}(Leerzeichen fuer keine, Enter fuer Vorschlag){R}\n")
    for key, name, timing, default_cron in defaults:
        c = (
            input(
                f"  {FG_BLUE}[{ARROW}]{R} {B}{name}{R}  {FG_GRAY}({timing}){R}  aktivieren? [j/N]: "
            )
            .strip()
            .lower()
        )
        if c == "j":
            choices.append(key)

            # Uhrzeit konfigurierbar machen fuer Briefings
            if key == "morning_briefing":
                _flush_stdin()
                uhrzeit = _prompt("  Uhrzeit fuer Morgen-Briefing (HH:MM)", default="07:00") or "07:00"
                try:
                    h, m = [int(x) for x in uhrzeit.split(":")]
                    custom_cron[key] = f"{m} {h} * * *"
                    _ok(f"Morgen-Briefing: taeglich {h:02d}:{m:02d} Uhr")
                except Exception:
                    _warn("Ungueltige Uhrzeit -- verwende 07:00")
                    custom_cron[key] = "0 7 * * *"

            elif key == "evening_check":
                _flush_stdin()
                uhrzeit = _prompt("  Uhrzeit fuer Abend-Briefing (HH:MM)", default="22:00") or "22:00"
                try:
                    h, m = [int(x) for x in uhrzeit.split(":")]
                    custom_cron[key] = f"{m} {h} * * *"
                    _ok(f"Abend-Briefing: taeglich {h:02d}:{m:02d} Uhr")
                except Exception:
                    _warn("Ungueltige Uhrzeit -- verwende 22:00")
                    custom_cron[key] = "0 22 * * *"

    # Standort fuer Wetter
    lat = lon = None
    if "morning_briefing" in choices or "evening_check" in choices:
        print(f"\n  {B}Standort fuer Wetterdaten{R}")
        print(f"  {FG_GRAY}(optional -- ohne Standort kein Wetter im Briefing){R}")
        lat_str = _prompt("Breitengrad (z.B. 48.1374)", default="")
        lon_str = _prompt("Laengengrad (z.B. 11.5755)", default="")
        if lat_str and lon_str:
            try:
                lat = float(lat_str)
                lon = float(lon_str)

                # Zeitzone-Autosetup
                try:
                    from timezonefinder import TimezoneFinder
                    tf = TimezoneFinder()
                    tz = tf.timezone_at(lat=lat, lng=lon)
                    if tz:
                        import platform
                        if platform.system() == "Linux":
                            # Safe approach: check if timedatectl is available
                            if shutil.which("timedatectl"):
                                subprocess.run(["timedatectl", "set-timezone", tz], check=False)
                                _ok(f"Zeitzone automatisch gesetzt: {tz}")
                            else:
                                _info(f"Konnte Zeitzone '{tz}' nicht setzen: timedatectl nicht gefunden")
                        else:
                            _info(f"Zeitzone erkannt: {tz}")
                except Exception as tz_e:
                    log.debug("Zeitzone-Autosetup fehlgeschlagen: %s", tz_e)
            except ValueError:
                _warn("Ungueltige Koordinaten -- Wetter wird deaktiviert")

    # Schwellwerte
    print(f"\n  {B}Warnungs-Schwellwerte{R}")
    temp_warn = _prompt("CPU-Temp Warnung ab (Grad C)", default="80") or "80"
    disk_warn = _prompt("Disk-Warnung ab (Prozent voll)", default="85") or "85"

    # Routinen aktivieren + Config schreiben
    if choices or lat:
        try:
            from piclaw.config import CONFIG_DIR
            from piclaw.routines import RoutineRegistry
            import tomllib
            import tomli_w

            # Routinen aktivieren (mit angepassten Uhrzeiten)
            registry = RoutineRegistry(CONFIG_DIR / "routines.json")
            for key in choices:
                routine = registry.get(key)
                if routine and key in custom_cron:
                    routine.cron = custom_cron[key]
                    routine.enabled = True
                    registry.update(routine)
                else:
                    registry.enable(key)
                _ok(f"Aktiviert: {key}")

            # Proaktive-Config in config.toml
            from piclaw.config import CONFIG_FILE

            raw = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "rb") as f:
                    raw = tomllib.load(f)

            raw["proactive"] = {
                "enabled": True,
                "temp_warn_c": int(temp_warn),
                "disk_warn_pct": int(disk_warn),
                "ram_warn_pct": 90,
            }

            if lat and lon:
                raw["location"] = {"latitude": lat, "longitude": lon}

            with open(CONFIG_FILE, "wb") as f:
                tomli_w.dump(raw, f)

            state.mark(f"proaktiver Agent ({len(choices)} Routinen)")
            state.restart_needed = True
            if lat:
                state.mark(f"Standort: {lat},{lon}")

        except Exception as e:
            _err(f"Fehler: {e}")
    else:
        _skip("Proaktiver Agent nicht konfiguriert")
        _info("Spaeter: piclaw routine list / piclaw routine enable morgen-briefing")


def step_hardware(state: WizardState, step: int, total: int) -> None:
    """Schritt: Hardware -- Luefter, GPIO."""
    _header(step, total, "Hardware -- Luefter & GPIO", "[HW]")

    # Pi-Temperatur zeigen
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            _info(
                f"Aktuelle CPU-Temperatur: {B}{result.stdout.strip().replace('temp=', '')}{R}"
            )
    except Exception as _e:
        log.debug("vcgencmd in wizard: %s", _e)

    # Pi-Modell erkennen → richtigen Standard-Pin wählen
    default_pin = 14  # GPIO14 = PWM0, funktioniert auf Pi 4 + Pi 5
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        if "Raspberry Pi 5" in cpuinfo:
            default_pin = 14  # Pi 5: offizieller PWM-Lüfterpin
        elif "Raspberry Pi 4" in cpuinfo:
            default_pin = 14  # Pi 4: GPIO14 (PWM0)
    except Exception:
        pass

    print(
        f"\n  {FG_GRAY}Ein PWM-Lüfter am GPIO-Pin wird automatisch temperaturgesteuert.{R}"
    )
    print(
        f"  {FG_GRAY}Standard-Pin: GPIO{default_pin} (funktioniert für die meisten Pi-Lüfter){R}"
    )
    print(f"  {FG_GRAY}Startet bei 50°C, 100% Drehzahl ab 75°C{R}")

    _flush_stdin()
    enable_fan = (
        input(f"\n  {FG_BLUE}{ARROW}{R} Lüfter angeschlossen? [j/N]: ").strip().lower()
    )

    if enable_fan == "j":
        pin = default_pin
        # Nur nachfragen wenn Nutzer einen anderen Pin will
        _flush_stdin()
        custom = input(
            f"  {FG_BLUE}{ARROW}{R} Anderen GPIO-Pin verwenden? [Enter = {default_pin}]: "
        ).strip()
        if custom:
            try:
                pin = int(custom)
            except ValueError:
                _warn(f"Ungültige Eingabe, verwende GPIO{default_pin}")
                pin = default_pin

        try:
            from piclaw.config import CONFIG_FILE
            import tomllib
            import tomli_w

            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "rb") as f:
                    raw = tomllib.load(f)
            else:
                raw = {}
            raw.setdefault("hardware", {})["fan_enabled"] = True
            raw["hardware"]["fan_pin"] = pin
            raw["hardware"]["fan_start_c"] = 50
            raw["hardware"]["fan_full_c"] = 75
            with open(CONFIG_FILE, "wb") as f:
                tomli_w.dump(raw, f)
            state.mark(f"fan -> GPIO{pin}")
            _ok(f"Lüfter aktiviert auf GPIO{pin}  (50°C Start / 75°C Vollgas)")
        except Exception as e:
            _err(f"Speichern fehlgeschlagen: {e}")
    else:
        _skip("Kein Lüfter")


def step_api_token(state: WizardState, step: int, total: int) -> None:
    """Schritt: API-Token für Web-UI."""
    _header(step, total, "API-Token -- Web-UI Zugang", "[Token]")
    cfg = state.cfg

    if cfg.api.secret_key:
        print(f"  Token vorhanden: {_mask(cfg.api.secret_key)}")
        print(f"  Vollstaendiger Token: {FG_CYAN}piclaw config token{R}\n")
        regen = (
            input(f"  {FG_BLUE}{ARROW}{R} Token neu generieren? [j/N]: ")
            .strip()
            .lower()
        )
        if regen == "j":
            cfg.api.secret_key = secrets.token_urlsafe(32)
            state.mark("api_token rotiert")
            state.restart_needed = True
            _ok(f"Neuer Token: {_mask(cfg.api.secret_key)}")
            _info("Web-UI nach dem Neustart mit neuem Token erreichbar")
        else:
            _skip("Token behalten")
    else:
        cfg.api.secret_key = secrets.token_urlsafe(32)
        state.mark("api_token generiert")
        _ok(f"Token generiert: {_mask(cfg.api.secret_key)}")

    port_raw = _prompt("Web-UI Port", default=str(cfg.api.port)) or str(cfg.api.port)
    try:
        new_port = int(port_raw)
        if new_port != cfg.api.port:
            cfg.api.port = new_port
            state.mark(f"api_port -> {new_port}")
            _ok(f"Port: {new_port}")
    except ValueError:
        _warn("Ungueltiger Port, behalte aktuellen")


def step_soul(state: WizardState, step: int, total: int) -> None:
    """Schritt: Soul -- Persoenlichkeit des Agenten."""
    _header(step, total, "Soul -- Persoenlichkeit des Agenten", "[Soul]")

    try:
        import piclaw.soul as soul_mod

        soul_path = soul_mod.SOUL_FILE
    except Exception:
        soul_path = Path("/etc/piclaw/SOUL.md")

    print(f"  {FG_GRAY}Der Soul ist eine Markdown-Datei die als erstes in jeden{R}")
    print(f"  {FG_GRAY}System-Prompt injiziert wird. Er bestimmt Persoenlichkeit,{R}")
    print(f"  {FG_GRAY}Sprache und Verhalten des Agenten.{R}\n")
    print(f"  Datei: {FG_CYAN}{soul_path}{R}")

    if soul_path.exists():
        size = soul_path.stat().st_size
        lines = soul_path.read_text(encoding="utf-8").count("\n") + 1
        _ok(f"Soul vorhanden ({size} Bytes, {lines} Zeilen)")

        # Preview der ersten Zeilen
        preview = soul_path.read_text(encoding="utf-8").strip().split("\n")[:4]
        print(f"\n  {FG_GRAY}Vorschau:{R}")
        for l in preview:
            print(f"    {FG_GRAY}{l[:70]}{R}")
        print()

        action = _choice(
            "Was möchtest du tun?",
            [
                (
                    "e",
                    "Bearbeiten",
                    f"oeffnet $EDITOR ({os.environ.get('EDITOR', 'nano')})",
                ),
                ("r", "Zurücksetzen", "Standard-Soul wiederherstellen"),
                ("s", "Behalten", "keine Änderung"),
            ],
            default="s",
        )
    else:
        _warn("Noch kein Soul vorhanden")
        action = _choice(
            "Was möchtest du tun?",
            [
                ("e", "Eigenen Soul erstellen", "oeffnet $EDITOR"),
                ("d", "Standard-Soul", "wird beim ersten Start erstellt"),
            ],
            default="d",
        )

    if action == "e":
        _edit_soul_in_editor(soul_path)
        state.mark("soul bearbeitet")
    elif action == "r":
        try:
            import piclaw.soul as soul_mod

            soul_mod.reset()
            state.mark("soul zurückgesetzt")
            _ok("Standard-Soul wiederhergestellt")
        except Exception as e:
            _err(f"Reset fehlgeschlagen: {e}")
    else:
        _skip("Soul unverändert")


def _edit_soul_in_editor(soul_path: Path) -> None:
    """Öffnet den Soul im Editor oder ermöglicht Inline-Eingabe."""
    editor = os.environ.get("EDITOR", "")

    if not editor:
        # Suche nach gängigen Editoren
        for ed in ("nano", "vim", "vi", "micro"):
            if shutil.which(ed):
                editor = ed
                break

    if editor:
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        if not soul_path.exists():
            soul_path.write_text(
                "# PiClaw Soul\n\n## Wer bin ich?\n\n## Aufgaben\n\n## Regeln\n"
            )
        subprocess.call([editor, str(soul_path)])
        _ok(f"Soul gespeichert: {soul_path}")
    else:
        print(f"\n  {FG_YELLOW}Kein Editor gefunden.{R}")
        print(
            f"  {FG_GRAY}Gib deinen Soul direkt ein (leere Zeile + Enter zum Abschliessen):{R}\n"
        )
        lines: list[str] = []
        try:
            while True:
                line = input("    ")
                if not line and lines and not lines[-1]:
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        if lines:
            soul_path.parent.mkdir(parents=True, exist_ok=True)
            soul_path.write_text("\n".join(lines).strip() + "\n")
            _ok("Soul gespeichert")
        else:
            _skip("Keine Eingabe")


def step_summary(state: WizardState, step: int, total: int) -> None:
    """Abschluss: Zusammenfassung und nächste Schritte."""
    from piclaw.config import save

    save(state.cfg)

    _w()
    _rule("═", FG_GREEN)
    print(f"\n  {FG_GREEN}{B}" + OK_SYM + "  Konfiguration gespeichert!{R}\n")
    _rule("═", FG_GREEN)
    _w()

    if state.changed:
        print(f"  {B}Geaenderte Einstellungen:{R}")
        for change in state.changed:
            _ok(change)
        _w()
    else:
        print(f"  {FG_GRAY}Keine Aenderungen vorgenommen.{R}")
        _w()

    # IP-Adresse ermitteln
    ip = "piclaw.local"
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass  # no network - IP unknown

    print(f"  {B}Naechste Schritte:{R}\n")

    if state.restart_needed:
        print(f"  {FG_YELLOW}1.{R}  Services neu starten:")
        print(f"     {FG_CYAN}piclaw stop && piclaw start{R}")
        print()

    no_llm = not state.cfg.llm.api_key and state.cfg.llm.backend not in (
        "local",
        "ollama",
    )
    if no_llm:
        print(f"  {FG_YELLOW}{WARN_SYM}{R}  Kein LLM-Key -- lokales Modell nutzen:")
        print(f"     {FG_CYAN}piclaw model download{R}  (~2.4 GB)")
        print()

    print(f"  {FG_GREEN}2.{R}  KI-Agent starten:")
    print(f"     {FG_CYAN}piclaw{R}")
    print()
    print(f"  {FG_GREEN}3.{R}  Web-Dashboard oeffnen:")
    print(f"     {FG_CYAN}http://{ip}:7842{R}")
    print()
    print(f"  {FG_GREEN}4.{R}  Systemcheck:")
    print(f"     {FG_CYAN}piclaw doctor{R}")
    print()
    _rule()
    _w()


# ── Haupt-Wizard ──────────────────────────────────────────────────


def _block_status(name: str, cfg: object) -> tuple[str, str]:
    """Gibt (badge, hinweis) zurück für einen Block basierend auf der Config.

    Rückgabe:
      badge  – "✅", "⚠️ " oder "⬜"
      hinweis – kurzer Klartext was fehlt (leer wenn ok)
    """
    def _get(*attrs):
        obj = cfg
        for a in attrs:
            obj = getattr(obj, a, None)
            if obj is None:
                return None
        return obj

    if name == "Kern":
        llm_ok = bool(
            _get("llm", "api_key")
            or _get("llm", "backend") in ("local", "ollama")
        )
        tok_ok = bool(_get("api", "secret_key"))
        agent_ok = bool(_get("agent_name"))
        if llm_ok and tok_ok and agent_ok:
            return "✅", ""
        missing = []
        if not llm_ok:
            missing.append("LLM")
        if not tok_ok:
            missing.append("API-Token")
        if not agent_ok:
            missing.append("Agent-Name")
        return "⚠️ ", "fehlt: " + ", ".join(missing)

    if name == "Kommunikation":
        tg_ok = bool(_get("telegram", "token") and _get("telegram", "chat_id"))
        dc_ok = bool(_get("discord", "token"))
        am_ok = bool(_get("agentmail", "api_key"))
        if tg_ok or dc_ok or am_ok:
            configured = []
            if tg_ok:
                configured.append("Telegram")
            if dc_ok:
                configured.append("Discord")
            if am_ok:
                configured.append("AgentMail")
            return "✅", ", ".join(configured)
        return "⬜", "kein Messenger konfiguriert"

    if name == "Smart Home":
        ha_ok = bool(_get("homeassistant", "url") and _get("homeassistant", "token"))
        mq_ok = bool(_get("mqtt", "host"))
        if ha_ok or mq_ok:
            configured = []
            if ha_ok:
                configured.append("Home Assistant")
            if mq_ok:
                configured.append("MQTT")
            return "✅", ", ".join(configured)
        return "⬜", "nicht eingerichtet"

    if name == "Dienste":
        parcels_file = Path("/etc/piclaw/parcels.json")
        if parcels_file.exists():
            return "\u2705", "aktiv"
        return "\u2b1c", "optional"

    if name == "Erweitert":
        extra_llm = bool(_get("llm_registry"))
        proactive = bool(_get("proactive", "enabled"))
        soul_path = Path("/etc/piclaw/SOUL.md")
        soul_ok = soul_path.exists()
        configured = []
        if extra_llm:
            configured.append("Weitere LLMs")
        if proactive:
            configured.append("Proaktiv")
        if soul_ok:
            configured.append("Soul")
        if configured:
            return "✅", ", ".join(configured)
        return "⬜", "optional – kann später eingerichtet werden"

    return "⬜", ""


def run() -> None:
    """
    Einrichtungs-Wizard mit Blockauswahl.
    Der User wählt welche Bereiche er jetzt einrichten möchte.
    Jeder Schritt kann innerhalb eines Blocks übersprungen werden.
    """
    from piclaw.config import load

    # ── Alle verfügbaren Steps nach Blöcken ──────────────────────
    BLOCKS: list[tuple[str, str, list[tuple[str, object]]]] = [
        (
            "Kern",
            "🚀  Agent-Name, KI-Anbieter (LLM), Web-UI Token\n"
            "     Mindestanforderung – ohne das startet PiClaw nicht sinnvoll.",
            [
                ("Agent",     step_agent),
                ("LLM",       step_llm),
                ("API-Token", step_api_token),
            ],
        ),
        (
            "Kommunikation",
            "💬  Telegram-Bot, Discord\n"
            "     Benachrichtigungen und Chat über Smartphone.",
            [
                ("Telegram",  step_telegram),
                ("Discord",   step_discord),
                ("AgentMail", step_agentmail),
            ],
        ),
        (
            "Smart Home",
            "🏠  Home Assistant, MQTT\n"
            "     Nur relevant wenn ein HA-Server im Netzwerk läuft.",
            [
                ("Home Assistant", step_homeassistant),
                ("MQTT",           step_mqtt),
            ],
        ),
        (
            "Dienste",
            "  Paket-Tracking (DHL, Hermes, DPD, GLS, UPS)\n"
            "     Sendungsverfolgung mit Telegram-Benachrichtigung.",
            [
                ("Paket-Tracking", step_parcel_tracking),
            ],
        ),
        (
            "Erweitert",
            "⚙️   Weitere LLMs, Proaktiver Agent, WLAN, Hardware, Soul\n"
            "     Feintuning – kann auch später eingerichtet werden.",
            [
                ("Weitere LLMs", step_llm_extra),
                ("Proaktiv",     step_proactive),
                ("WLAN",         step_wifi),
                ("Hardware",     step_hardware),
                ("Soul",         step_soul),
            ],
        ),
    ]

    def _run_steps(
        state: WizardState,
        steps: list[tuple[str, object]],
        step_offset: int,
        total: int,
    ) -> int:
        """Führt eine Liste von Steps aus. Gibt neue step_offset zurück."""
        for name, fn in steps:
            step_offset += 1
            try:
                fn(state, step_offset, total)  # type: ignore[call-arg]
            except KeyboardInterrupt:
                _w()
                _skip(f"Schritt '{name}' abgebrochen -- weiter mit naechstem Schritt")
            except Exception as e:
                _err(f"Fehler in Schritt '{name}': {e}")
                _info("Weiter mit naechstem Schritt...")
        return step_offset

    try:
        cfg = load()
        state = WizardState(cfg=cfg)
        step_welcome(state)

        # ── Block-Auswahlmenü ─────────────────────────────────────
        _rule()
        _w()
        print(f"  {B}Was möchtest du jetzt einrichten?{R}\n")

        block_badges: list[str] = []
        for i, (name, desc, _steps) in enumerate(BLOCKS, 1):
            badge, hinweis = _block_status(name, state.cfg)
            block_badges.append(badge)
            badge_col = FG_GREEN if badge == "✅" else (FG_YELLOW if "⚠" in badge else FG_GRAY)
            badge_str = f"{badge_col}{badge}{R}" if not _NO_COLOR else badge
            hinweis_str = f"  {FG_GRAY}({hinweis}){R}" if hinweis else ""
            print(f"  {FG_CYAN}{B}{i}.{R}  {B}{name}{R}  {badge_str}{hinweis_str}")
            for line in desc.split("\n"):
                print(f"     {FG_GRAY}{line.strip()}{R}")
            _w()

        total_steps = sum(len(s) for _, _, s in BLOCKS)
        print(f"  {FG_CYAN}{B}a.{R}  {B}Alles{R}  {FG_GRAY}(alle {total_steps} Schritte – vollständige Einrichtung){R}")
        print(f"  {FG_GRAY}0.  Überspringen – direkt zur Zusammenfassung{R}")
        _w()
        print(f"  {FG_GRAY}Mehrere Blöcke: Nummern mit Komma trennen, z.B. {B}1,2{R}")
        _w()

        _flush_stdin()
        raw = input(f"  {FG_BLUE}{ARROW}{R} Auswahl [a/0/1-4]: ").strip().lower()
        _w()

        if raw in ("0", ""):
            selected_blocks: list[int] = []
        elif raw == "a":
            selected_blocks = list(range(len(BLOCKS)))
        else:
            selected_blocks = []
            for part in raw.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(BLOCKS):
                        selected_blocks.append(idx)
                    else:
                        _warn(f"Block {part} unbekannt – ignoriert")

        # ── Ausgewählte Blöcke berechnen ──────────────────────────
        chosen_steps: list[tuple[str, object]] = []
        for idx in selected_blocks:
            _, _, steps = BLOCKS[idx]
            chosen_steps.extend(steps)

        total = len(chosen_steps) + 1  # +1 für Zusammenfassung

        if not chosen_steps:
            _info("Keine Blöcke ausgewählt – überspringe zur Zusammenfassung.")
        else:
            block_names = " + ".join(BLOCKS[i][0] for i in selected_blocks)
            _ok(f"Starte: {block_names}  ({len(chosen_steps)} Schritte)")
            _w()
            _run_steps(state, chosen_steps, step_offset=0, total=total)

        # ── Hinweis auf noch offene Blöcke ──────────────────────────
        skipped = [
            BLOCKS[i][0]
            for i in range(len(BLOCKS))
            if i not in selected_blocks
        ]
        if skipped and chosen_steps:
            _w()
            _rule()
            _w()
            print(f"  {FG_YELLOW}Noch nicht eingerichtet:{R}")
            for bname in skipped:
                badge, hinweis = _block_status(bname, state.cfg)
                hint = f"  {FG_GRAY}({hinweis}){R}" if hinweis else ""
                print(f"     {FG_GRAY}•{R}  {bname}{hint}")
            _w()
            print(f"  {FG_GRAY}Jederzeit nachholen mit: {B}piclaw setup{R}")
            _w()

        step_summary(state, total, total)

    except KeyboardInterrupt:
        _w()
        print(f"\n  {FG_YELLOW}Wizard abgebrochen.{R}")
        print(f"  {FG_GRAY}Bisherige Aenderungen wurden gespeichert.{R}\n")
        try:
            from piclaw.config import save
            save(state.cfg)  # type: ignore
        except Exception as _e:
            log.debug("wizard config save on abort: %s", _e)
        sys.exit(0)

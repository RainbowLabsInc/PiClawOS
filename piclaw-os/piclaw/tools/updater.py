"""
PiClaw OS – Updater Tool
Self-update via git pull + service restart.

Update-Flow:
  1. git pull in /opt/piclaw  (piclaw user owns it)
  2. pip install -e .          (venv owned by piclaw)
  3. sudo systemctl restart    (allowed via /etc/sudoers.d/piclaw)
"""

import asyncio
import logging
import re
from pathlib import Path
from piclaw.llm.base import ToolDefinition
from piclaw.config import UpdaterConfig

log = logging.getLogger("piclaw.updater")

INSTALL_DIR = Path("/opt/piclaw")
VENV_PIP = INSTALL_DIR / ".venv" / "bin" / "pip"

# Prefix für alle git-Aufrufe, deren Output geparst wird oder die das Netz
# berühren: LC_ALL=C erzwingt englische Meldungen (die Substring-Checks
# "Already up to date" / "Saved" matchen sonst auf deutschsprachigen Systemen
# NIE – Folge: unnötige Restarts und nie zurückgeholte Stashes), und
# GIT_TERMINAL_PROMPT=0 verhindert, dass git bei 401 (abgelaufener Token,
# privates/unsichtbares Repo) auf eine Username-Eingabe wartet und der
# Updater ohne TTY hängt.
_GIT_ENV = "LC_ALL=C GIT_TERMINAL_PROMPT=0"

# Alle Dienste, die Code aus /opt/piclaw laden. Fehlt hier einer, läuft er
# nach einem Update mit altem Code weiter (Crawler und Watchdog liefen so
# wochenlang auf altem Stand). Ein sudo-Aufruf pro Unit: die Regel in
# /etc/sudoers.d/piclaw erlaubt nur "systemctl restart <unit>" mit genau
# einer Unit, mehrere Units in einem Aufruf matchen keine Zeile.
_RESTART_UNITS = ("piclaw-crawler", "piclaw-watchdog", "piclaw-api", "piclaw-agent")


def _own_unit() -> str | None:
    """systemd-Unit dieses Prozesses (aus /proc/self/cgroup), sonst None."""
    try:
        text = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    m = re.search(r"/(piclaw-[\w-]+)\.service", text)
    return m.group(1) if m else None


def _restart_order(own: str | None) -> list[str]:
    """Reihenfolge der Neustarts: die eigene Unit zuletzt.

    Der Restart der eigenen Unit beendet diesen Prozess samt seiner
    sudo/systemctl-Kinder - alles danach würde nie mehr ausgeführt.
    """
    units = [u for u in _RESTART_UNITS if u != own]
    if own in _RESTART_UNITS:
        units.append(own)
    return units

# Signaturen von GitHub-Auth-Fehlern in git-Output (mit LC_ALL=C stabil)
_AUTH_ERROR_MARKERS = (
    "could not read Username",
    "Invalid username or token",
    "Authentication failed",
    "Password authentication is not supported",
    "terminal prompts disabled",
    "HTTP 401",
    "HTTP 403",
)


def _auth_hint(out: str) -> str:
    """Ergänzt git-Fehleroutput um einen handlungsfähigen Hinweis bei Auth-Fehlern."""
    if not any(marker in out for marker in _AUTH_ERROR_MARKERS):
        return ""
    return (
        "\n\n💡 GitHub-Authentifizierung fehlgeschlagen. Mögliche Ursachen:\n"
        "  • Hinterlegter Token abgelaufen/widerrufen → neuen Fine-grained PAT\n"
        "    (nur dieses Repo, Contents: Read-only) in /etc/piclaw/config.toml\n"
        "    unter [updater] github_token eintragen\n"
        "  • Repo privat oder nicht öffentlich sichtbar → ebenfalls PAT nötig\n"
        "  • Repo öffentlich sichtbar? Dann reicht github_token = \"\" (anonymer Pull)"
    )


def _git_remote_url(cfg: "UpdaterConfig") -> str:
    """Gibt die Git-Remote-URL OHNE eingebetteten Token zurück.

    SECURITY: Den Token NICHT in die URL einbetten die an git remote set-url
    übergeben wird – das würde ihn in ps-aux-Prozesslisten sichtbar machen
    und shell-injection via repo_url ermöglichen falls die URL Sonderzeichen
    enthält. Stattdessen: git credential store (siehe _configure_git_credentials).
    """
    return cfg.repo_url


async def _configure_git_credentials(cfg: "UpdaterConfig") -> None:
    """Konfiguriert GitHub-Token via git credential store (sicher, kein ps-leak).

    Der Token wird in ~/.git-credentials des piclaw-Users gespeichert und
    via git config credential.helper store aktiviert. Er erscheint NICHT
    in Prozesslisten oder Shell-Argumenten.

    Ist KEIN Token konfiguriert, werden verwaiste Einträge für den Repo-Host
    entfernt: credential.helper=store würde sonst einen alten (toten) Token
    mitschicken und damit sogar anonyme Pulls öffentlicher Repos brechen
    (GitHub antwortet bei ungültigen Credentials mit 401 statt anonym zu
    bedienen).
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(cfg.repo_url)
        host = parsed.netloc or "github.com"
        cred_file = Path.home() / ".git-credentials"

        if not cfg.github_token:
            if cred_file.exists():
                lines = [
                    l for l in cred_file.read_text().splitlines()
                    if l.strip() and host not in l
                ]
                cred_file.write_text("\n".join(lines) + ("\n" if lines else ""))
                cred_file.chmod(0o600)
                log.debug("Verwaiste Git credentials für %s entfernt", host)
            return

        cred_line = f"https://x-access-token:{cfg.github_token}@{host}\n"
        # Bestehende Zeile für diesen Host ersetzen oder neu anlegen
        existing = cred_file.read_text() if cred_file.exists() else ""
        lines = [l for l in existing.splitlines() if host not in l]
        lines.append(cred_line.strip())
        cred_file.write_text("\n".join(lines) + "\n")
        cred_file.chmod(0o600)
        # credential.helper aktivieren
        await _run("git config --global credential.helper store")
        log.debug("Git credentials für %s gesetzt (credential store)", host)
    except Exception as e:
        log.warning("Git credential store konnte nicht gesetzt werden: %s", e)

TOOL_DEFS = [
    ToolDefinition(
        name="system_update",
        description="Check for and apply PiClaw software updates, or update system packages.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["piclaw", "system", "check"],
                    "description": (
                        "piclaw=update PiClaw itself via git pull, "
                        "system=apt upgrade, "
                        "check=check for updates only"
                    ),
                },
            },
            "required": ["target"],
        },
    ),
]


async def _run(cmd: str, timeout: int = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return 1, "[TIMEOUT]"
    combined = out.decode(errors="replace").strip()
    if err.strip():
        combined += "\n" + err.decode(errors="replace").strip()
    return proc.returncode, combined


async def system_update(target: str, cfg: UpdaterConfig) -> str:
    # Token sicher via credential store konfigurieren (kein ps-leak, kein
    # shell-inject); ohne Token räumt der Aufruf verwaiste Einträge weg
    await _configure_git_credentials(cfg)
    _remote_url = _git_remote_url(cfg)
    # Remote-URL nur setzen wenn sie sich geändert hat (ohne Token, sauber)
    if cfg.repo_url:
        import shlex
        safe_url = shlex.quote(cfg.repo_url)
        await _run(f"cd {INSTALL_DIR} && git remote set-url origin {safe_url} 2>&1")

    if target == "check":
        rc_fetch, out_fetch = await _run(
            f"cd {INSTALL_DIR} && {_GIT_ENV} git fetch origin 2>&1"
        )
        if rc_fetch != 0:
            # Fetch-Fehler NICHT als "aktuell" maskieren
            return f"❌ git fetch fehlgeschlagen:\n{out_fetch[:400]}{_auth_hint(out_fetch)}"
        rc, out = await _run(
            f"cd {INSTALL_DIR} && {_GIT_ENV} git log HEAD..origin/main --oneline 2>&1"
        )
        if rc != 0 or not out.strip():
            return "✅ PiClaw ist aktuell."
        lines = out.strip().splitlines()
        return f"🔄 {len(lines)} Update(s) verfügbar:\n" + "\n".join(
            f"  {l}" for l in lines
        )

    elif target == "piclaw":
        log.info("PiClaw update via git pull...")
        results = []

        # 0. .git Permissions vollständig reparieren (rekursiv)
        # Ursache: "sudo git pull" / "sudo piclaw update" erstellt Objekte als
        # root in .git/objects/. Beim nächsten Lauf als piclaw schlägt git pull
        # mit "insufficient permission for adding an object" fehl.
        # Fix: find spürt root-eigene Dateien irgendwo im .git-Baum auf.
        import os as _os
        import pwd as _pwd
        try:
            uname = _pwd.getpwuid(_os.getuid()).pw_name
            # -quit: beendet find nach erstem Treffer (schnell)
            rc_find, found = await _run(
                f"find {INSTALL_DIR}/.git -not -user {uname} -print -quit 2>/dev/null"
            )
            if found.strip():
                log.info("git: Dateien mit falschen Rechten in .git – repariere")
                rc_chown, chown_out = await _run(
                    f"sudo chown -R {uname}:{uname} {INSTALL_DIR}/.git 2>&1"
                )
                if rc_chown == 0:
                    results.append("🔧 .git Rechte repariert (root→piclaw)")
                else:
                    results.append(f"⚠️ .git Rechte-Reparatur fehlgeschlagen: {chown_out[:100]}")
                    log.warning("chown .git fehlgeschlagen: %s", chown_out)
        except Exception as _e:
            log.debug("git permissions check: %s", _e)

        # 1. Lokale Änderungen stashen (verhindert 'overwritten by merge')
        # _GIT_ENV: der "Saved"-Check funktioniert nur mit englischen Meldungen
        rc_stash, out_stash = await _run(
            f"cd {INSTALL_DIR} && {_GIT_ENV} git stash 2>&1"
        )
        stashed = rc_stash == 0 and "Saved" in out_stash
        if stashed:
            results.append("📦 Lokale Änderungen temporär gesichert (git stash)")
        elif rc_stash != 0:
            # Stash fehlgeschlagen → tracked files hart zurücksetzen
            log.warning("git stash failed (%s), force-resetting tracked files", out_stash[:80])
            await _run(f"cd {INSTALL_DIR} && git checkout -- . 2>&1")
            results.append("🔧 Lokale Änderungen zurückgesetzt (git checkout --)")

        # 2. git pull
        rc, out = await _run(f"cd {INSTALL_DIR} && {_GIT_ENV} git pull origin main 2>&1")
        results.append(f"git pull: {out[:200]}")
        if rc != 0:
            if stashed:
                await _run(f"cd {INSTALL_DIR} && {_GIT_ENV} git stash pop 2>&1")
            return f"❌ git pull fehlgeschlagen:\n{out}{_auth_hint(out)}"
        if "Already up to date" in out:
            if stashed:
                await _run(f"cd {INSTALL_DIR} && {_GIT_ENV} git stash pop 2>&1")
            return "✅ PiClaw ist bereits aktuell – kein Neustart nötig."

        # 3. pip install -e . (nur wenn sich pyproject.toml geändert hat)
        rc2, out2 = await _run(
            f"cd {INSTALL_DIR} && git diff HEAD@{{1}} HEAD -- piclaw-os/pyproject.toml | grep -q '^[+-]' && "
            f"{VENV_PIP} install -e {INSTALL_DIR}/piclaw-os -q 2>&1 || echo 'dependencies unchanged'"
        )
        if out2 and "dependencies unchanged" not in out2:
            results.append(f"pip: {out2[:200]}")

        # 4. sudo systemctl restart – alle Dienste, eigener zuletzt
        failed = []
        for unit in _restart_order(_own_unit()):
            rc3, out3 = await _run(f"sudo systemctl restart {unit} 2>&1")
            if rc3 != 0:
                log.warning("Restart %s fehlgeschlagen: %s", unit, out3[:200])
                failed.append(f"{unit}: {out3[:100]}")
        if failed:
            results.append("⚠️ Service-Neustart fehlgeschlagen:\n" + "\n".join(failed))
        else:
            results.append("✅ Services neu gestartet")

        return "✅ PiClaw aktualisiert\n" + "\n".join(results)

    elif target == "system":
        log.info("Running apt upgrade...")
        rc, out = await _run(
            "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1",
            timeout=300,
        )
        return f"[exit {rc}]\n{out}"

    return f"Unknown target: {target}"


def build_handlers(cfg: UpdaterConfig) -> dict:
    return {
        "system_update": lambda **kw: system_update(cfg=cfg, **kw),
    }

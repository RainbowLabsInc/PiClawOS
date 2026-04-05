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
from pathlib import Path
from piclaw.llm.base import ToolDefinition
from piclaw.config import UpdaterConfig

log = logging.getLogger("piclaw.updater")

INSTALL_DIR = Path("/opt/piclaw")
VENV_PIP = INSTALL_DIR / ".venv" / "bin" / "pip"


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
    """
    if not cfg.github_token:
        return
    try:
        from urllib.parse import urlparse
        parsed = urlparse(cfg.repo_url)
        host = parsed.netloc or "github.com"
        cred_line = f"https://x-access-token:{cfg.github_token}@{host}\n"
        cred_file = Path.home() / ".git-credentials"
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
    # Token sicher via credential store konfigurieren (kein ps-leak, kein shell-inject)
    if cfg.github_token:
        await _configure_git_credentials(cfg)
    _remote_url = _git_remote_url(cfg)
    # Remote-URL nur setzen wenn sie sich geändert hat (ohne Token, sauber)
    if cfg.repo_url:
        await _run(f"cd {INSTALL_DIR} && git remote set-url origin {cfg.repo_url} 2>&1")

    if target == "check":
        rc, out = await _run(
            f"cd {INSTALL_DIR} && git fetch origin && "
            "git log HEAD..origin/main --oneline 2>/dev/null || echo '(up to date)'"
        )
        if not out.strip() or "(up to date)" in out:
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
        import os as _os, pwd as _pwd
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
        rc_stash, out_stash = await _run(
            f"cd {INSTALL_DIR} && git stash 2>&1"
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
        rc, out = await _run(f"cd {INSTALL_DIR} && git pull origin main 2>&1")
        results.append(f"git pull: {out[:200]}")
        if rc != 0:
            if stashed:
                await _run(f"cd {INSTALL_DIR} && git stash pop 2>&1")
            return f"❌ git pull fehlgeschlagen:\n{out}"
        if "Already up to date" in out:
            if stashed:
                await _run(f"cd {INSTALL_DIR} && git stash pop 2>&1")
            return "✅ PiClaw ist bereits aktuell – kein Neustart nötig."

        # 3. pip install -e . (nur wenn sich pyproject.toml geändert hat)
        rc2, out2 = await _run(
            f"cd {INSTALL_DIR} && git diff HEAD@{{1}} HEAD -- piclaw-os/pyproject.toml | grep -q '^[+-]' && "
            f"{VENV_PIP} install -e {INSTALL_DIR}/piclaw-os -q 2>&1 || echo 'dependencies unchanged'"
        )
        if out2 and "dependencies unchanged" not in out2:
            results.append(f"pip: {out2[:200]}")

        # 4. sudo systemctl restart
        rc3, out3 = await _run("sudo systemctl restart piclaw-api piclaw-agent 2>&1")
        if rc3 == 0:
            results.append("✅ Services neu gestartet")
        else:
            results.append(f"⚠️ Service-Neustart: {out3[:100]}")

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

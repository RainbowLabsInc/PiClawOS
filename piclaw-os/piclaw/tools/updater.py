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

        # 0. .git/objects Permissions prüfen und ggf. reparieren
        import os as _os
        git_objects = INSTALL_DIR / ".git" / "objects"
        if git_objects.exists():
            try:
                st = git_objects.stat()
                if st.st_uid != _os.getuid():
                    # getlogin() schlägt in nicht-interaktiven Contexts fehl → pwd nutzen
                    import pwd as _pwd
                    uname = _pwd.getpwuid(_os.getuid()).pw_name
                    rc_chown, _ = await _run(
                        f"sudo chown -R {uname}:{uname} {INSTALL_DIR}/.git 2>&1"
                    )
                    if rc_chown == 0:
                        results.append("🔧 .git Rechte repariert")
            except Exception as _e:
                log.debug("git objects chown check: %s", _e)

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

"""
PiClaw Debug – Installationsprüfung
Prüft alle kritischen Invarianten einer frischen Installation.
Aufruf: piclaw debug → test_debug_install auswählen

Abgedeckte Fehlerquellen (aus CLAUDE_REBUILD.md):
  GIT_PULL_NO_EFFECT        → INV_021: /opt/piclaw/piclaw muss Symlink sein
  API_PERMISSION_DENIED     → INV_022: /var/log/piclaw/ muss piclaw gehören
  WATCHDOG_PERMISSION       → chmod 1777 /etc/piclaw/ipc/
  DOCTOR_SHOWS_DEFAULTS     → INV_006: CONFIG_DIR muss /etc/piclaw sein
  API_EXITS_IMMEDIATELY     → INV_005: pyproject.toml build-backend korrekt
"""

import os
import sys
import stat
import importlib
from pathlib import Path

INSTALL_DIR = Path("/opt/piclaw")
CONFIG_DIR  = Path("/etc/piclaw")
LOG_DIR     = Path("/var/log/piclaw")
IPC_DIR     = CONFIG_DIR / "ipc"
SUDOERS     = Path("/etc/sudoers.d/piclaw")

PASS = []
FAIL = []
WARN = []


def section(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")

def ok(label, detail=""):
    msg = f"{label}" + (f" – {detail}" if detail else "")
    print(f"  ✅ {msg}")
    PASS.append(label)

def fail(label, detail="", hint=""):
    msg = f"{label}" + (f" – {detail}" if detail else "")
    print(f"  ❌ {msg}")
    if hint:
        print(f"     💡 {hint}")
    FAIL.append(label)

def warn(label, detail=""):
    msg = f"{label}" + (f" – {detail}" if detail else "")
    print(f"  ⚠️  {msg}")
    WARN.append(label)

def info(m):
    print(f"  ℹ  {m}")


# ── 1. Python ────────────────────────────────────────────────────
section("1. Python-Version")
v = sys.version_info
info(f"Python {v.major}.{v.minor}.{v.micro} @ {sys.executable}")
if (v.major, v.minor) >= (3, 11):
    ok("Python >= 3.11")
else:
    fail("Python zu alt", f"{v.major}.{v.minor}", "Mindestens Python 3.11 erforderlich")


# ── 2. piclaw importierbar + Version ─────────────────────────────
section("2. piclaw-Paket")
try:
    import piclaw
    ver = getattr(piclaw, "__version__", "unbekannt")
    info(f"Geladen von: {Path(piclaw.__file__).parent}")
    info(f"Version: {ver}")
    ok("piclaw importierbar", f"v{ver}")
except ImportError as e:
    fail("piclaw nicht importierbar", str(e),
         "pip install -e /opt/piclaw/piclaw-os ausführen")

try:
    from piclaw.config import load, _resolve_config_dir
    cfg_dir = _resolve_config_dir()
    info(f"CONFIG_DIR aufgelöst: {cfg_dir}")
    if cfg_dir == CONFIG_DIR:
        ok("CONFIG_DIR korrekt", str(cfg_dir))
    elif cfg_dir == Path.home() / ".piclaw":
        fail("CONFIG_DIR zeigt auf ~/.piclaw statt /etc/piclaw",
             str(cfg_dir),
             "Läuft der Prozess als falscher User? Oder fehlt /etc/piclaw/config.toml?")
    else:
        warn("CONFIG_DIR ungewöhnlich", str(cfg_dir))
except Exception as e:
    fail("Config-Modul Fehler", str(e))


# ── 3. .git Verzeichnis Rechte ───────────────────────────────────
section("3. .git Verzeichnis Rechte (piclaw update)")
git_dir = INSTALL_DIR / ".git"
git_objects = git_dir / "objects"
if git_objects.exists():
    import pwd
    try:
        owner_uid = git_objects.stat().st_uid
        owner_name = pwd.getpwuid(owner_uid).pw_name
        try:
            piclaw_uid = pwd.getpwnam("piclaw").pw_uid
        except KeyError:
            piclaw_uid = None
        info(f"Owner .git/objects: {owner_name} (uid={owner_uid})")
        if piclaw_uid and owner_uid == piclaw_uid:
            ok(".git/objects gehört piclaw – git pull funktioniert")
        elif owner_name == "root":
            fail(".git/objects gehört root",
                 "git pull schlägt fehl mit 'insufficient permission'",
                 "sudo chown -R piclaw:piclaw /opt/piclaw/.git")
        else:
            warn(".git/objects gehört anderem User", owner_name)
    except Exception as e:
        warn(f".git Rechte nicht prüfbar: {e}")
else:
    warn(".git/objects nicht gefunden", str(git_dir))


# ── 4. Symlink – INV_021 ─────────────────────────────────────────
section("3. Symlink /opt/piclaw/piclaw (INV_021)")
symlink = INSTALL_DIR / "piclaw"
target  = INSTALL_DIR / "piclaw-os" / "piclaw"

if not INSTALL_DIR.exists():
    warn("Kein Standard-Installationsverzeichnis", str(INSTALL_DIR),
         "Abweichende Installation – Symlink ggf. trotzdem vorhanden")
elif symlink.is_symlink():
    resolved = symlink.resolve()
    if resolved == target.resolve():
        ok("Symlink korrekt", f"{symlink} → {resolved}")
    else:
        fail("Symlink zeigt auf falsches Ziel",
             f"{symlink} → {resolved}",
             f"sudo ln -sfn {target} {symlink}")
elif symlink.is_dir():
    fail("piclaw ist ein Verzeichnis, kein Symlink",
         str(symlink),
         "sudo bash /opt/piclaw/piclaw-os/tools/fix_install_path.sh")
else:
    fail("Symlink nicht vorhanden", str(symlink),
         f"sudo ln -sfn {target} {symlink}")


# ── 4. /var/log/piclaw Rechte – INV_022 ──────────────────────────
section("4. /var/log/piclaw Verzeichnis (INV_022)")
if LOG_DIR.exists():
    st     = LOG_DIR.stat()
    owner  = st.st_uid
    import pwd
    try:
        owner_name = pwd.getpwuid(owner).pw_name
    except KeyError:
        owner_name = str(owner)
    info(f"Owner: {owner_name} (uid={owner}), Mode: {oct(st.st_mode)}")
    try:
        piclaw_uid = pwd.getpwnam("piclaw").pw_uid
        if owner == piclaw_uid:
            ok("/var/log/piclaw gehört piclaw-User")
        else:
            fail("/var/log/piclaw gehört nicht piclaw",
                 f"Owner: {owner_name}",
                 "sudo chown -R piclaw:piclaw /var/log/piclaw")
    except KeyError:
        warn("User 'piclaw' nicht gefunden – kein System-Service-Install?")
else:
    fail("/var/log/piclaw existiert nicht",
         hint="sudo mkdir -p /var/log/piclaw && sudo chown -R piclaw:piclaw /var/log/piclaw")


# ── 5. IPC-Verzeichnis Permissions – WATCHDOG ────────────────────
section("5. /etc/piclaw/ipc/ Permissions (Watchdog)")
if IPC_DIR.exists():
    st   = IPC_DIR.stat()
    mode = stat.S_IMODE(st.st_mode)
    info(f"Mode: {oct(mode)}")
    # 1777 = sticky + rwxrwxrwx
    if mode == 0o1777:
        ok("/etc/piclaw/ipc/ hat chmod 1777")
    elif mode & 0o777 == 0o777:
        warn("/etc/piclaw/ipc/ hat 0777 aber kein Sticky-Bit",
             "sudo chmod 1777 /etc/piclaw/ipc/")
    else:
        fail("/etc/piclaw/ipc/ hat falsche Rechte",
             oct(mode),
             "sudo chmod 1777 /etc/piclaw/ipc/")
    jobs_db = IPC_DIR / "jobs.db"
    if jobs_db.exists():
        ok("jobs.db vorhanden")
    else:
        info("jobs.db noch nicht vorhanden (wird beim ersten Start angelegt)")
else:
    fail("/etc/piclaw/ipc/ existiert nicht",
         hint="sudo mkdir -p /etc/piclaw/ipc && sudo chmod 1777 /etc/piclaw/ipc && sudo chown -R piclaw:piclaw /etc/piclaw/ipc")


# ── 6. Sudoers – INV_019 ─────────────────────────────────────────
section("6. Sudoers-Regel (INV_019)")
if SUDOERS.exists():
    content = SUDOERS.read_text()
    if "piclaw" in content and "systemctl" in content:
        ok("Sudoers-Regel vorhanden", str(SUDOERS))
    else:
        warn("Sudoers-Datei vorhanden, aber Inhalt unerwartet", str(SUDOERS))
else:
    fail("Sudoers-Datei fehlt", str(SUDOERS),
         "'piclaw update' und Service-Restart werden ohne Passwort nicht funktionieren")


# ── 7. pyproject.toml – INV_001 ──────────────────────────────────
section("7. pyproject.toml build-backend (INV_001)")
for pyproject in [
    INSTALL_DIR / "piclaw-os" / "pyproject.toml",
    INSTALL_DIR / "piclaw-os" / "boot" / "piclaw" / "piclaw-src" / "pyproject.toml",
]:
    if not pyproject.exists():
        continue
    text = pyproject.read_text()
    if "setuptools.build_meta" in text and "setuptools.backends.legacy" not in text:
        ok(f"build-backend korrekt", str(pyproject.relative_to(INSTALL_DIR) if INSTALL_DIR in pyproject.parents else pyproject))
    else:
        fail("build-backend falsch",
             str(pyproject),
             "Muss 'setuptools.build_meta' sein (Python 3.13 Inkompatibilität)")
    # Version prüfen
    for line in text.splitlines():
        if line.startswith("version"):
            ver_str = line.split('"')[1] if '"' in line else "?"
            info(f"  pyproject version: {ver_str}")
            break


# ── 8. Abhängigkeiten ─────────────────────────────────────────────
section("8. Kritische Abhängigkeiten")
deps = {
    "fastapi":        ("fastapi",        None),
    "uvicorn":        ("uvicorn",        None),
    "aiohttp":        ("aiohttp",        None),
    "scrapling":      ("scrapling",      "pip install scrapling"),
    "psutil":         ("psutil",         None),
    "tomli_w":        ("tomli_w",        "pip install tomli-w"),
    "websockets":     ("websockets",     None),
    "llama_cpp":      ("llama_cpp",      "pip install llama-cpp-python (optional, nur für lokales Modell)"),
}
for name, (mod, hint) in deps.items():
    try:
        m = importlib.import_module(mod)
        ver_attr = getattr(m, "__version__", None) or getattr(m, "version", None)
        ok(name, str(ver_attr) if ver_attr else "installiert")
    except ImportError:
        if hint and "optional" in hint:
            warn(f"{name} nicht installiert", hint)
        elif hint:
            fail(f"{name} fehlt", hint=hint)
        else:
            fail(f"{name} fehlt")


# ── 9. Lokales Modell ─────────────────────────────────────────────
section("9. Lokales Modell (Gemma 2B)")
try:
    from piclaw.llm.local import DEFAULT_MODEL_PATH
    info(f"Erwarteter Pfad: {DEFAULT_MODEL_PATH}")
    if DEFAULT_MODEL_PATH.exists():
        size_mb = DEFAULT_MODEL_PATH.stat().st_size // 1_048_576
        ok("Modell-Datei vorhanden", f"{DEFAULT_MODEL_PATH.name} ({size_mb} MB)")
    else:
        warn("Lokales Modell nicht gefunden",
             f"Für Cloud-LLM nicht nötig. Offline-Modus: piclaw model download")
except Exception as e:
    warn(f"Modell-Check übersprungen: {e}")


# ── Zusammenfassung ───────────────────────────────────────────────
section("Zusammenfassung")
total = len(PASS) + len(FAIL) + len(WARN)
print(f"  Gesamt : {total} Checks")
print(f"  ✅ OK   : {len(PASS)}")
print(f"  ⚠️  Warn : {len(WARN)}")
print(f"  ❌ Fehler: {len(FAIL)}")
if FAIL:
    print("\n  Fehler:")
    for f in FAIL:
        print(f"    • {f}")
if WARN:
    print("\n  Warnungen:")
    for w in WARN:
        print(f"    • {w}")
if not FAIL:
    print("\n  🎉 Alle kritischen Checks bestanden!")
print(f"\n{'='*60}\n  ✉  Output bei Problemen an Entwickler senden\n{'='*60}\n")

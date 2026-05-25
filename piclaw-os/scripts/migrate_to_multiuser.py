#!/usr/bin/env python3
"""
PiClaw OS — Migrations-Skript: Single-User → Multi-User
=======================================================

Was es macht (idempotent):
  1. Pre-flight: stoppt sofort wenn `users.json` schon einen Admin hat.
  2. Backup-Tarball aller relevanten Files nach
     `<CONFIG_DIR>/backups/pre-multiuser-<timestamp>.tar.gz`
  3. Bootstrap-Admin via UserRegistry.bootstrap_admin() — Name + chat_id
     aus `config.toml[telegram]`, web_token = bestehender `[api].secret_key`
     (alte Browser-Bookmarks funktionieren weiter).
  4. Tagt bestehende Daten mit owner_id = admin.id:
       - parcels.json   : jede `data["parcels"][*]` + `data["archive"][*]`
       - routines.json  : jede non-System Routine (action != "direct_check")
       - subagents.json : jede SubAgentDef
       - ipc/jobs.db    : UPDATE jobs SET owner_user_id = admin.id WHERE
                          owner_user_id = ''  (init_jobs_db legt die Spalte
                          automatisch an wenn sie fehlt)
  5. Memory-Move: `memory/MEMORY.md` und `memory/memory/` und `memory/sessions/`
     nach `users/<admin.id>/memory/...` (workspace bleibt global).
  6. Druckt Verifikations-Statistiken.

Aufruf:
    sudo -u piclaw /opt/piclaw/.venv/bin/python scripts/migrate_to_multiuser.py
optionale Sandbox:
    PICLAW_CONFIG_DIR=~/.piclaw-test python scripts/migrate_to_multiuser.py
oder explizit:
    python scripts/migrate_to_multiuser.py --config-dir ~/.piclaw-test

Wirkt nichts unwiederbringliches: vor Migration wird ein Tarball erstellt,
mit dem der Pre-Multi-User-State exakt rekonstruierbar ist.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import tarfile
import tomllib
from datetime import datetime
from pathlib import Path


# Windows-Konsolen sind oft cp1252 — Unicode-Symbole würden crashen.
# Auf Linux/Pi (UTF-8-default) ist das ein No-op.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


log = logging.getLogger("piclaw.migrate")


# ── Hilfsfunktionen ────────────────────────────────────────────────


def _override_config_dir(path: Path) -> None:
    """Setzt CONFIG_DIR-Pfad VOR dem ersten piclaw.config-Import."""
    os.environ["PICLAW_CONFIG_DIR_OVERRIDE"] = str(path)


def _resolve_config_dir(arg: str | None) -> Path:
    """Priorität: CLI-Argument > Env-Var > piclaw.config._resolve."""
    if arg:
        return Path(arg).expanduser().resolve()
    env = os.environ.get("PICLAW_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # Fallback auf Default-Lookup
    from piclaw.config import CONFIG_DIR
    return CONFIG_DIR


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _atomic_write_json(path: Path, data) -> None:
    """Minimal atomic-write ohne von piclaw.fileutils abhängig zu sein."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# ── Pre-flight ─────────────────────────────────────────────────────


def preflight(config_dir: Path) -> dict:
    """Prüft Vorbedingungen. Wirft RuntimeError wenn schon migriert."""
    users_file = config_dir / "users.json"
    if users_file.exists():
        try:
            data = json.loads(users_file.read_text(encoding="utf-8"))
            if any(u.get("role") == "admin" for u in data):
                raise RuntimeError(
                    f"users.json existiert bereits mit Admin "
                    f"unter {users_file}. Migration wurde schon gemacht."
                )
        except json.JSONDecodeError:
            log.warning("users.json existiert aber ist defekt — wird überschrieben.")

    cfg_file = config_dir / "config.toml"
    if not cfg_file.exists():
        raise RuntimeError(f"config.toml nicht gefunden unter {cfg_file}")

    raw = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
    chat_id = (raw.get("telegram") or {}).get("chat_id", "").strip()
    secret_key = (raw.get("api") or {}).get("secret_key", "").strip()
    if not chat_id:
        raise RuntimeError(
            "config.toml[telegram].chat_id ist leer. Bitte erst Telegram "
            "einrichten (`piclaw setup` Block Kommunikation)."
        )
    if not secret_key:
        raise RuntimeError(
            "config.toml[api].secret_key ist leer. Bitte einmal "
            "`piclaw setup` Block Kern → API-Token ausführen."
        )
    return {
        "config_dir": config_dir,
        "chat_id": chat_id,
        "secret_key": secret_key,
    }


# ── Backup ─────────────────────────────────────────────────────────


def make_backup(config_dir: Path) -> Path:
    """Schreibt ein Tarball aller relevanten Files. Idempotent über
    Zeitstempel-Suffix — re-running gibt einen neuen Tarball."""
    backup_dir = config_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    tarball = backup_dir / f"pre-multiuser-{_ts()}.tar.gz"

    candidates = [
        config_dir / "config.toml",
        config_dir / "parcels.json",
        config_dir / "routines.json",
        config_dir / "subagents.json",
        config_dir / "schedules.json",
        config_dir / "memory",
        config_dir / "ipc",
        config_dir / "users.json",  # falls von vorigem Fehlversuch da
    ]

    with tarfile.open(tarball, "w:gz") as tar:
        for c in candidates:
            if c.exists():
                tar.add(c, arcname=c.relative_to(config_dir))
    return tarball


# ── Migrationsschritte ─────────────────────────────────────────────


def bootstrap_admin(config_dir: Path, name: str, chat_id: str, web_token: str):
    """Legt den ersten Admin an. Nutzt UserRegistry direkt mit übergebenem
    Pfad, kein Singleton (für Sandbox-Tests sicherer)."""
    from piclaw.users import UserRegistry
    reg = UserRegistry(config_dir / "users.json")
    if reg.has_admin():
        return reg, None  # idempotenter Fall — sollte preflight schon abgefangen haben
    admin = reg.bootstrap_admin(
        name=name,
        telegram_chat_id=chat_id,
        web_token=web_token,
    )
    return reg, admin


def tag_parcels(config_dir: Path, owner_id: str) -> tuple[int, int]:
    """Tagged parcels und archive mit owner_id. Returns (parcels_tagged, archive_tagged)."""
    path = config_dir / "parcels.json"
    if not path.exists():
        return 0, 0
    data = json.loads(path.read_text(encoding="utf-8"))
    p_count = 0
    a_count = 0
    for tn, p in data.get("parcels", {}).items():
        if not p.get("owner_id"):
            p["owner_id"] = owner_id
            p_count += 1
    for tn, p in data.get("archive", {}).items():
        if not p.get("owner_id"):
            p["owner_id"] = owner_id
            a_count += 1
    if p_count or a_count:
        _atomic_write_json(path, data)
    return p_count, a_count


def tag_routines(config_dir: Path, owner_id: str) -> tuple[int, int]:
    """Tagged non-System-Routinen mit owner_id. System (action='direct_check')
    bleibt owner_id=None. Returns (user_routines_tagged, system_skipped)."""
    path = config_dir / "routines.json"
    if not path.exists():
        return 0, 0
    routines = json.loads(path.read_text(encoding="utf-8"))
    user_tagged = 0
    system_kept = 0
    changed = False
    for r in routines:
        if r.get("action") == "direct_check":
            system_kept += 1
            # Sicherstellen dass owner_id=None (nicht "")
            if r.get("owner_id"):
                r["owner_id"] = None
                changed = True
            continue
        if not r.get("owner_id"):
            r["owner_id"] = owner_id
            user_tagged += 1
            changed = True
    if changed:
        _atomic_write_json(path, routines)
    return user_tagged, system_kept


def tag_subagents(config_dir: Path, owner_id: str) -> int:
    """Tagged SubAgents mit owner_id. Returns count.

    Akzeptiert beide bekannten Formate:
      - dict {id: def, ...}   (echtes Pi-Format, sa_registry._load)
      - list [def, ...]       (gelegentlich in Test-Fixtures)
    """
    path = config_dir / "subagents.json"
    if not path.exists():
        return 0
    agents = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    if isinstance(agents, dict):
        # echtes Pi-Format: {id: def}
        for _id, sa in agents.items():
            if isinstance(sa, dict) and not sa.get("owner_id"):
                sa["owner_id"] = owner_id
                count += 1
    elif isinstance(agents, list):
        for sa in agents:
            if isinstance(sa, dict) and not sa.get("owner_id"):
                sa["owner_id"] = owner_id
                count += 1
    else:
        log.warning("subagents.json: unbekannter Top-Level-Typ %s", type(agents).__name__)
        return 0
    if count:
        _atomic_write_json(path, agents)
    return count


def tag_jobs_db(config_dir: Path, owner_id: str) -> int:
    """Setzt owner_user_id auf allen jobs.db-Rows die noch leer sind.
    Legt die Spalte an wenn nicht vorhanden."""
    db_path = config_dir / "ipc" / "jobs.db"
    if not db_path.exists():
        return 0
    con = sqlite3.connect(str(db_path), timeout=10)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(jobs)").fetchall()]
        if not cols:
            return 0  # jobs-Tabelle existiert noch nicht
        if "owner_user_id" not in cols:
            con.execute("ALTER TABLE jobs ADD COLUMN owner_user_id TEXT DEFAULT ''")
        cur = con.execute(
            "UPDATE jobs SET owner_user_id=? WHERE owner_user_id='' OR owner_user_id IS NULL",
            (owner_id,),
        )
        con.commit()
        return cur.rowcount or 0
    finally:
        con.close()


def move_memory(config_dir: Path, owner_id: str) -> tuple[int, int, int]:
    """Verschiebt MEMORY.md, memory/ daily-logs und sessions/ unter users/<id>/memory/.
    Workspace bleibt global. Returns (main_moved, daily_moved, sessions_moved)."""
    src_root = config_dir / "memory"
    if not src_root.exists():
        return 0, 0, 0

    dst_root = config_dir / "users" / owner_id / "memory"
    dst_root.mkdir(parents=True, exist_ok=True)
    (dst_root / "memory").mkdir(exist_ok=True)
    (dst_root / "sessions").mkdir(exist_ok=True)

    main_moved = 0
    daily_moved = 0
    sessions_moved = 0

    # MEMORY.md
    src_main = src_root / "MEMORY.md"
    dst_main = dst_root / "MEMORY.md"
    if src_main.exists() and not dst_main.exists():
        shutil.move(str(src_main), str(dst_main))
        main_moved = 1

    # Daily Logs unter memory/memory/*.md
    daily_src = src_root / "memory"
    if daily_src.exists():
        for f in daily_src.glob("*.md"):
            dst = dst_root / "memory" / f.name
            if not dst.exists():
                shutil.move(str(f), str(dst))
                daily_moved += 1

    # Sessions
    sess_src = src_root / "sessions"
    if sess_src.exists():
        for f in sess_src.glob("*.jsonl"):
            dst = dst_root / "sessions" / f.name
            if not dst.exists():
                shutil.move(str(f), str(dst))
                sessions_moved += 1

    return main_moved, daily_moved, sessions_moved


# ── Orchestration ──────────────────────────────────────────────────


def run_migration(config_dir: Path, admin_name: str = "patrick") -> dict:
    """Eigentlicher Migrations-Lauf. Returns Statistik-Dict."""
    print(f"\n=== PiClaw Multi-User Migration ===")
    print(f"  Config-Dir: {config_dir}")
    print()

    print(f"[1/6] Pre-flight Check…")
    info = preflight(config_dir)
    print(f"      chat_id     = {info['chat_id']}")
    print(f"      secret_key  = {info['secret_key'][:8]}…")

    print(f"[2/6] Backup Tarball…")
    tarball = make_backup(config_dir)
    print(f"      → {tarball}  ({tarball.stat().st_size} Bytes)")

    print(f"[3/6] Bootstrap-Admin als '{admin_name}'…")
    reg, admin = bootstrap_admin(
        config_dir,
        name=admin_name,
        chat_id=info["chat_id"],
        web_token=info["secret_key"],
    )
    if admin is None:
        raise RuntimeError("bootstrap_admin lieferte None — Migration bricht ab.")
    print(f"      → user_id = {admin.id}")
    print(f"        web_token bleibt = config.toml[api].secret_key")

    print(f"[4/6] owner_id auf bestehende Daten taggen…")
    p_count, a_count = tag_parcels(config_dir, admin.id)
    print(f"      parcels.json:   {p_count} aktive + {a_count} archiviert getaggt")
    r_user, r_sys = tag_routines(config_dir, admin.id)
    print(f"      routines.json:  {r_user} user-Routinen getaggt, {r_sys} System-Routinen unverändert")
    sa_count = tag_subagents(config_dir, admin.id)
    print(f"      subagents.json: {sa_count} Sub-Agents getaggt")
    jobs_count = tag_jobs_db(config_dir, admin.id)
    print(f"      ipc/jobs.db:    {jobs_count} Jobs auf owner_user_id getaggt")

    print(f"[5/6] Memory unter users/{admin.id[:8]}…/memory/ verschieben…")
    main_m, daily_m, sess_m = move_memory(config_dir, admin.id)
    print(f"      MEMORY.md:      {main_m}")
    print(f"      Daily-Logs:     {daily_m}")
    print(f"      Sessions:       {sess_m}")

    print(f"[6/6] Fertig. ✅")
    print()
    print(f"  Admin: {admin.name} (id={admin.id})")
    print(f"  Backup: {tarball}")
    print()
    print(f"  Test mit: curl -H 'Authorization: Bearer {admin.web_token[:8]}…' \\")
    print(f"            http://piclaw.local:7842/api/whoami")
    print()

    return {
        "admin_id": admin.id,
        "admin_name": admin.name,
        "backup": str(tarball),
        "parcels_active": p_count,
        "parcels_archive": a_count,
        "routines_user": r_user,
        "routines_system": r_sys,
        "subagents": sa_count,
        "jobs": jobs_count,
        "memory_main": main_m,
        "memory_daily": daily_m,
        "memory_sessions": sess_m,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate PiClaw single-user installation to multi-user."
    )
    parser.add_argument(
        "--config-dir",
        help="Override CONFIG_DIR (default: $PICLAW_CONFIG_DIR or auto-detect)",
    )
    parser.add_argument(
        "--admin-name",
        default="patrick",
        help="Anzeigename für den bootstrap-Admin (default: 'patrick')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur preflight + backup, keine Daten verändern (für Tests)",
    )
    args = parser.parse_args(argv)

    config_dir = _resolve_config_dir(args.config_dir)
    if args.config_dir:
        os.environ["PICLAW_CONFIG_DIR"] = str(config_dir)

    if not config_dir.exists():
        print(f"❌ CONFIG_DIR existiert nicht: {config_dir}", file=sys.stderr)
        return 2

    try:
        if args.dry_run:
            info = preflight(config_dir)
            print(f"Pre-flight OK. chat_id={info['chat_id']}, "
                  f"secret_key={info['secret_key'][:8]}…")
            tarball = make_backup(config_dir)
            print(f"Backup geschrieben: {tarball}")
            return 0
        run_migration(config_dir, admin_name=args.admin_name)
        return 0
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

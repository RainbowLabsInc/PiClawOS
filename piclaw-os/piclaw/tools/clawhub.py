"""
PiClaw OS – ClawHub Integration
================================

Ermöglicht Dameon das Suchen, Herunterladen und Installieren von
ClawHub-Skills (https://clawhub.ai).

ClawHub-Skills sind SKILL.md-Dateien mit Anweisungen für den Agenten.
PiClaw installiert sie als Kontext-Skills in /etc/piclaw/skills/<slug>/

API:
  GET https://wry-manatee-359.convex.site/api/v1/skills/<slug>
  GET https://wry-manatee-359.convex.site/api/v1/download?slug=<slug>
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

import aiohttp

from piclaw.config import CONFIG_DIR
from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.clawhub")

CLAWHUB_API = "https://wry-manatee-359.convex.site/api/v1"
SKILLS_DIR = CONFIG_DIR / "skills"

# ── Tool-Definitionen ─────────────────────────────────────────────

TOOL_DEFS = [
    ToolDefinition(
        name="clawhub_search",
        description=(
            "Sucht Skills auf ClawHub (clawhub.ai). "
            "Nutze das wenn der Nutzer einen neuen Skill suchen oder installieren möchte."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff, z.B. 'calendar', 'slack', 'weather'",
                }
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="clawhub_info",
        description="Zeigt Details zu einem ClawHub-Skill (Beschreibung, Version, Bewertung).",
        parameters={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Skill-Name/Slug, z.B. 'caldav-calendar' oder 'slack'",
                }
            },
            "required": ["slug"],
        },
    ),
    ToolDefinition(
        name="clawhub_install",
        description=(
            "Lädt einen ClawHub-Skill herunter und installiert ihn lokal. "
            "Der Skill wird als SKILL.md in /etc/piclaw/skills/<slug>/ gespeichert "
            "und steht Dameon danach als Kontext zur Verfügung."
        ),
        parameters={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Skill-Name/Slug, z.B. 'caldav-calendar'",
                }
            },
            "required": ["slug"],
        },
    ),
    ToolDefinition(
        name="clawhub_list_installed",
        description="Listet alle lokal installierten ClawHub-Skills auf.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="clawhub_uninstall",
        description="Entfernt einen installierten ClawHub-Skill.",
        parameters={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Skill-Slug der entfernt werden soll"}
            },
            "required": ["slug"],
        },
    ),
]


# ── Handler ───────────────────────────────────────────────────────

async def _get(url: str) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            r.raise_for_status()
            return await r.json()


async def _download_zip(slug: str) -> bytes:
    url = f"{CLAWHUB_API}/download?slug={slug}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
            r.raise_for_status()
            return await r.read()


async def clawhub_search(query: str) -> str:
    try:
        # Direkt nach Skill-Slug suchen
        data = await _get(f"{CLAWHUB_API}/skills/{query.lower().replace(' ', '-')}")
        skill = data.get("skill", {})
        if skill:
            stats = skill.get("stats", {})
            return (
                f"🔍 Gefunden: **{skill['displayName']}**\n"
                f"   {skill['summary']}\n"
                f"   ⭐ {stats.get('stars', 0)} · "
                f"📦 {stats.get('downloads', 0):,} Downloads · "
                f"Version {skill['tags'].get('latest', '?')}\n"
                f"   Installieren: clawhub_install(slug='{skill['slug']}')"
            )
    except Exception:
        pass

    return (
        f"Kein Skill mit dem Namen '{query}' gefunden.\n"
        f"Tipp: Besuche https://clawhub.ai um Skills zu durchsuchen, "
        f"dann clawhub_info(slug='<name>') für Details."
    )


async def clawhub_info(slug: str) -> str:
    try:
        data = await _get(f"{CLAWHUB_API}/skills/{slug}")
        skill = data.get("skill", {})
        v = data.get("latestVersion", {})
        stats = skill.get("stats", {})

        installed_path = SKILLS_DIR / slug / "SKILL.md"
        installed = " ✅ installiert" if installed_path.exists() else ""

        return (
            f"📦 **{skill['displayName']}** v{skill['tags'].get('latest', '?')}{installed}\n"
            f"   {skill['summary']}\n"
            f"   ⭐ {stats.get('stars', 0)} · "
            f"{stats.get('downloads', 0):,} Downloads · "
            f"{stats.get('installsCurrent', 0)} aktive Installs\n"
            f"   Changelog: {v.get('changelog', '-')[:100]}\n"
            f"   🔗 https://clawhub.ai/{slug}"
        )
    except Exception as e:
        return f"Skill '{slug}' nicht gefunden: {e}"


async def clawhub_install(slug: str) -> str:
    try:
        # Info abrufen
        data = await _get(f"{CLAWHUB_API}/skills/{slug}")
        skill = data.get("skill", {})
        if not skill:
            return f"❌ Skill '{slug}' nicht auf ClawHub gefunden."

        version = skill["tags"].get("latest", "?")
        target = SKILLS_DIR / slug
        target.mkdir(parents=True, exist_ok=True)

        # ZIP herunterladen und entpacken
        zip_bytes = await _download_zip(slug)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            extracted = zf.namelist()
            zf.extractall(target)

        # Metadaten speichern
        meta = {
            "slug": slug,
            "displayName": skill["displayName"],
            "version": version,
            "summary": skill["summary"],
            "source": "clawhub",
        }
        (target / "clawhub.json").write_text(json.dumps(meta, indent=2))

        skill_md = target / "SKILL.md"
        log.info("ClawHub: Skill '%s' v%s installiert → %s", slug, version, target)

        return (
            f"✅ **{skill['displayName']}** v{version} installiert!\n"
            f"   Dateien: {', '.join(extracted)}\n"
            f"   Pfad: {target}\n"
            f"   {'SKILL.md vorhanden – Dameon kennt den Skill jetzt.' if skill_md.exists() else 'Hinweis: Keine SKILL.md gefunden.'}"
        )
    except Exception as e:
        log.error("ClawHub install error: %s", e)
        return f"❌ Installation fehlgeschlagen: {e}"


def clawhub_list_installed() -> str:
    if not SKILLS_DIR.exists():
        return "Keine Skills installiert. (Verzeichnis: /etc/piclaw/skills/)"

    skills = []
    for meta_file in sorted(SKILLS_DIR.glob("*/clawhub.json")):
        try:
            meta = json.loads(meta_file.read_text())
            skills.append(
                f"  📦 {meta['displayName']} v{meta['version']} "
                f"(slug: {meta['slug']})"
            )
        except Exception:
            skills.append(f"  📦 {meta_file.parent.name} (meta fehlt)")

    if not skills:
        return "Keine ClawHub-Skills installiert."

    return "Installierte ClawHub-Skills:\n" + "\n".join(skills)


async def clawhub_uninstall(slug: str) -> str:
    import shutil
    target = SKILLS_DIR / slug
    if not target.exists():
        return f"❌ Skill '{slug}' ist nicht installiert."
    shutil.rmtree(target)
    log.info("ClawHub: Skill '%s' entfernt", slug)
    return f"✅ Skill '{slug}' entfernt."


def build_handlers() -> dict:
    return {
        "clawhub_search": lambda query: clawhub_search(query),
        "clawhub_info": lambda slug: clawhub_info(slug),
        "clawhub_install": lambda slug: clawhub_install(slug),
        "clawhub_list_installed": lambda: clawhub_list_installed(),
        "clawhub_uninstall": lambda slug: clawhub_uninstall(slug),
    }

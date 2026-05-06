"""
PiClaw OS – Sub-Agent Registry
Persistent store for dynamically created sub-agent definitions.

Each sub-agent has:
  id          – UUID, assigned at creation
  name        – human-readable name (e.g. "HomeMonitor", "DailyBriefing")
  description – what this agent does (shown in listings)
  mission     – injected as system prompt for the agent's LLM calls
  tools       – list of tool names this agent is allowed to use
  schedule    – when/how often to run: "once", "cron:0 7 * * *", "interval:3600", "continuous"
  llm_tags    – preferred LLM tags (e.g. ["coding"] routes to coding-optimized backend)
  enabled     – soft-disable without deleting
  created_at  – ISO timestamp
  created_by  – "mainagent" or "user"
  max_steps   – agentic loop limit (default 10)
  timeout     – max runtime in seconds (default 300)
  notify      – send result via messaging hub? True/False
  privileged  – if True, bypasses certain sandbox restrictions (e.g. shell access)
"""

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.agents.sa_registry")

SA_REGISTRY_FILE = CONFIG_DIR / "subagents.json"

INSTALLER_MISSION_TEMPLATE = """\
Du bist ein spezialisierter Installer-Subagent für PiClaw OS.
Deine Aufgabe ist es, Software auf dem System zu installieren oder zu aktualisieren.

HALTE DICH STRENG AN DIESEN WORKFLOW:
1. Prüfe die Whitelist (falls zutreffend).
2. Erstelle einen detaillierten Plan, welche Befehle du ausführen wirst.
3. Präsentiere diesen Plan dem Nutzer und rufe 'installer_confirm' auf.
4. Führe die Installation NUR aus, wenn 'installer_confirm' mit 'YES' antwortet.
5. Melde den Erfolg oder Fehler der Installation zurück.
6. Hinterlasse keine temporären Dateien.

Du hast privilegierte Shell-Rechte. Nutze sie verantwortungsvoll.
"""

SEARCH_ASSISTANT_MISSION_TEMPLATE = """\
Du bist der SearchAssistant für PiClaw OS. Deine Aufgabe ist es, Marktplätze (Kleinanzeigen, eBay, Web) nach Inseraten zu durchsuchen.

DEINE RICHTLINIEN:
1. Analysiere die Suchanfrage des Nutzers sorgfältig.
2. Falls der Nutzer "in der Nähe" oder ähnliches schreibt, aber keine PLZ/Ort bekannt ist, frage höflich nach dem Standort.
3. Nutze das Tool 'marketplace_search' für die eigentliche Suche.
4. Du musst die Parameter 'location' (PLZ) und 'radius_km' explizit setzen, wenn sie in der Anfrage genannt wurden.
5. Präsentiere die Ergebnisse übersichtlich.
6. Falls der Nutzer eine regelmäßige Überwachung wünscht, erkläre, dass du das für ihn übernehmen kannst (Monitoring).

WICHTIG:
- Wenn du direkt gefragt wirst, zeige IMMER ALLE Funde (setze den Parameter notify_all=True). Das ist extrem wichtig, damit der Nutzer alle Ergebnisse sieht und nicht nur "keine neuen".
- Falls der Nutzer eine regelmäßige Suche wünscht ("Suche alle 30 Min", "Überwache das"), schlage vor, einen neuen Agenten mit entsprechendem 'schedule' (z.B. 'interval:1800') zu erstellen.
- Sei präzise und hilfreich.
- Antworte immer auf Deutsch.
"""


@dataclass
class SubAgentDef:
    name: str
    description: str
    mission: str  # system prompt / task description
    tools: list[str]  # allowed tool names, [] = all
    schedule: str = "once"  # once | cron:<expr> | interval:<sec> | continuous
    llm_tags: list[str] = field(default_factory=list)
    enabled: bool = True
    max_steps: int = 10
    timeout: int = 300
    notify: bool = True  # send result to messaging hub
    direct_tool: str | None = None  # wenn gesetzt: Tool direkt aufrufen, kein LLM
    trusted: bool = (
        False  # if True, tier-2 restricted tools allowed when explicitly listed
    )
    privileged: bool = False  # if True, root shell access allowed
    created_by: str = "mainagent"
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run: str | None = None
    last_status: str | None = None  # ok | error | running | timeout

    def __post_init__(self):
        """Tolerant type coercion.

        Numeric fields may arrive as strings from three sources:
          1. Persisted subagents.json (historical entries, old schema)
          2. REST PATCH /api/subagents/{id} with JSON string value
          3. Manual edits to subagents.json

        When `timeout` or `max_steps` ends up as a str, asyncio.wait_for(…,
        timeout=<str>) raises `TypeError: '<=' not supported between instances
        of 'str' and 'int'` inside _execute(), which crashes every run of the
        affected agent. Coerce defensively and fall back to the dataclass
        default so a malformed value can never kill the run loop.
        """
        for attr, default in (("max_steps", 10), ("timeout", 300)):
            val = getattr(self, attr)
            if isinstance(val, int):
                continue
            try:
                coerced = int(val)
            except (TypeError, ValueError):
                log.warning(
                    "SubAgentDef '%s': %s=%r is not an int – falling back to %d",
                    self.name, attr, val, default,
                )
                coerced = default
            else:
                log.info(
                    "SubAgentDef '%s': coerced %s from %r (%s) to int %d",
                    self.name, attr, val, type(val).__name__, coerced,
                )
            setattr(self, attr, coerced)


class SubAgentRegistry:
    """Persistent CRUD store for sub-agent definitions.

    Concurrent-process safety: piclaw-api and piclaw-agent both hold their own
    SubAgentRegistry instance pointing at the same JSON file. A naive _save()
    would overwrite the other process's deletions. We merge with the on-disk
    state on every save (see _save() docstring).
    """

    def __init__(self):
        self._agents: dict[str, SubAgentDef] = {}
        # IDs that came from disk during _load() (or from a previous merge).
        # Used by _save() to distinguish "agent removed by other process"
        # from "agent we just added in memory but haven't written yet".
        self._loaded_ids: set[str] = set()
        # IDs we explicitly removed in this process. _save() drops them from
        # the merged final state so that the other process's stale memory
        # cannot resurrect them. Cleared after a successful save.
        self._tombstones: set[str] = set()
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        if not SA_REGISTRY_FILE.exists():
            return
        try:
            data = json.loads(SA_REGISTRY_FILE.read_text(encoding="utf-8"))
            self._agents = {k: SubAgentDef(**v) for k, v in data.items()}
            self._loaded_ids = set(self._agents.keys())
            log.info("Sub-agent registry: %s agents loaded", len(self._agents))
        except Exception as e:
            log.error("Sub-agent registry load error: %s", e)

    def _save(self):
        """Save with merge-on-write to survive concurrent updates from the
        other piclaw process (api ↔ daemon).

        Steps:
          1. Re-read the on-disk JSON (may have changed since _load).
          2. **Detect external deletions:** for any ID we previously loaded
             but that's no longer on disk, drop it from our memory — the
             other process removed it.
          3. **Apply our tombstones:** drop IDs we explicitly removed in
             this process from the merged final state.
          4. **Pick up external additions:** any ID on disk we don't have
             gets pulled into our memory (unless tombstoned).
          5. Write merged state. Clear tombstones (consumed for this cycle).

        Race window: between read and write, the other process might also
        save. With safe_write_json's atomic rename there is no torn file,
        but the last writer's merge wins. The window is small (milliseconds)
        and acceptable; full lock-free correctness would require fcntl.
        """
        SA_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)

        on_disk: dict = {}
        if SA_REGISTRY_FILE.exists():
            try:
                on_disk = json.loads(SA_REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Sub-agent registry: re-read for merge failed: %s", e)

        # Step 2: drop in-memory agents the other process removed
        for aid in list(self._loaded_ids):
            if aid not in on_disk and aid in self._agents:
                log.info(
                    "Sub-agent registry: dropping cached agent '%s' "
                    "(removed by other process)",
                    self._agents[aid].name,
                )
                del self._agents[aid]
        # Forget loaded_ids that no longer exist on disk
        self._loaded_ids = {aid for aid in self._loaded_ids if aid in on_disk}

        # Step 4: pick up external additions (unless tombstoned)
        for aid, raw in on_disk.items():
            if aid in self._agents or aid in self._tombstones:
                continue
            try:
                self._agents[aid] = SubAgentDef(**raw)
                self._loaded_ids.add(aid)
            except Exception as e:
                log.warning(
                    "Sub-agent registry: foreign agent '%s' deserialization "
                    "failed: %s", aid, e,
                )

        # Step 5: build final state from current memory, minus tombstones
        final = {
            aid: asdict(agent)
            for aid, agent in self._agents.items()
            if aid not in self._tombstones
        }

        from piclaw.fileutils import safe_write_json
        if safe_write_json(SA_REGISTRY_FILE, final, label="sa_registry"):
            # Tombstones served their purpose for this save cycle.
            # Don't keep them forever — that would block re-creation
            # by the other process (e.g. mainagent re-adding).
            self._tombstones.clear()
            self._loaded_ids = set(final.keys())

    # ── CRUD ──────────────────────────────────────────────────────

    def add(self, agent: SubAgentDef) -> str:
        # If we previously tombstoned this ID and now re-add, lift the tombstone.
        self._tombstones.discard(agent.id)
        self._agents[agent.id] = agent
        self._save()
        return agent.id

    def get(self, id_or_name: str) -> SubAgentDef | None:
        # Try by ID first, then by name
        if id_or_name in self._agents:
            return self._agents[id_or_name]
        for a in self._agents.values():
            if a.name.lower() == id_or_name.lower():
                return a
        return None

    def update(self, id_or_name: str, **kwargs) -> bool:
        agent = self.get(id_or_name)
        if not agent:
            return False
        for k, v in kwargs.items():
            if hasattr(agent, k):
                setattr(agent, k, v)
        # Re-run type coercion in case numeric fields arrived as strings from
        # the REST PATCH body. Cheap and keeps the dataclass invariants stable.
        agent.__post_init__()
        self._save()
        return True

    def remove(self, id_or_name: str) -> bool:
        agent = self.get(id_or_name)
        if not agent:
            return False
        # Tombstone protects against the other process resurrecting this ID
        # via its stale in-memory copy on the next mark_run save.
        self._tombstones.add(agent.id)
        del self._agents[agent.id]
        self._save()
        return True

    def list_all(self) -> list[SubAgentDef]:
        return sorted(self._agents.values(), key=lambda a: a.created_at, reverse=True)

    def list_enabled(self) -> list[SubAgentDef]:
        return [a for a in self.list_all() if a.enabled]

    def mark_run(self, id_or_name: str, status: str):
        """Update last_run + last_status. Only persists terminal statuses
        to avoid blocking os.fsync() on the event loop for 'running' transitions."""
        agent = self.get(id_or_name)
        if not agent:
            return
        agent.last_run = datetime.now().isoformat()
        agent.last_status = status
        # PERF: "running" is a transient state written every agent cycle.
        # Persisting it would call os.fsync() on SD-card from the async event
        # loop thread, potentially blocking 100-500ms per agent per hour.
        # We only persist terminal states ("ok", "error", "timeout") – those
        # matter for crash-recovery and status display.
        if status != "running":
            self._save()

    # ── Status summary ────────────────────────────────────────────

    def summary(self) -> str:
        agents = self.list_all()
        if not agents:
            return "Keine Sub-Agenten definiert."
        lines = [f"Sub-Agenten ({len(agents)}):\n"]
        for a in agents:
            status_icon = {
                "ok": "✅",
                "error": "❌",
                "running": "⚙️",
                "timeout": "⏱️",
                None: "⬜",
            }.get(a.last_status, "⬜")
            enabled_icon = "" if a.enabled else " ⏸"
            # ISO-Timestamp auf HH:MM kürzen für bessere Lesbarkeit
            last_run_str = "nie"
            if a.last_run:
                try:
                    last_run_str = a.last_run[11:16]  # "2026-03-29T07:15:00" → "07:15"
                except Exception:
                    last_run_str = a.last_run
            lines.append(
                f"  {status_icon} [{a.id}] {a.name}{enabled_icon}\n"
                f"       {a.description}\n"
                f"       Zeitplan: {a.schedule}  |  Letzter Lauf: {last_run_str}"
            )

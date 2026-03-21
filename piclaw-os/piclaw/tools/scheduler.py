"""
PiClaw OS – Scheduler Tool
User-defined background tasks (cron-style + interval triggers)
Persisted to ~/.piclaw/schedules.json
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from piclaw.config import SCHEDULE_DB
from piclaw.llm.base import ToolDefinition
from piclaw.taskutils import create_background_task

if TYPE_CHECKING:
    pass

log = logging.getLogger("piclaw.scheduler")

TOOL_DEFS = [
    ToolDefinition(
        name="schedule_add",
        description=(
            "Create a recurring background task. The agent will run the given "
            "prompt automatically on the specified schedule."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable task name"},
                "prompt": {"type": "string", "description": "What the agent should do"},
                "cron": {
                    "type": "string",
                    "description": "Cron expression e.g. '0 8 * * *' (daily 08:00)",
                },
                "interval_sec": {
                    "type": "integer",
                    "description": "Alternatively: run every N seconds",
                },
            },
            "required": ["name", "prompt"],
        },
    ),
    ToolDefinition(
        name="schedule_list",
        description="List all scheduled tasks.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="schedule_remove",
        description="Remove a scheduled task by ID or name.",
        parameters={
            "type": "object",
            "properties": {
                "id_or_name": {"type": "string"},
            },
            "required": ["id_or_name"],
        },
    ),
]


class Scheduler:
    def __init__(self):
        self._schedules: dict[str, dict] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._agent = None
        self._load()

    def set_agent(self, agent):
        self._agent = agent

    # ── Persistence ────────────────────────────────────────────

    def _load(self):
        if SCHEDULE_DB.exists():
            try:
                self._schedules = json.loads(SCHEDULE_DB.read_text(encoding="utf-8"))
            except Exception:
                self._schedules = {}

    def _save(self):
        from piclaw.fileutils import safe_write_json

        safe_write_json(SCHEDULE_DB, self._schedules, label="schedules")

    # ── Public API ──────────────────────────────────────────────

    def add(self, name: str, prompt: str, cron: str = "", interval_sec: int = 0) -> str:
        if not cron and not interval_sec:
            return "Specify either a cron expression or interval_sec."
        sid = str(uuid.uuid4())[:8]
        self._schedules[sid] = {
            "id": sid,
            "name": name,
            "prompt": prompt,
            "cron": cron,
            "interval_sec": interval_sec,
            "created": datetime.now().isoformat(),
            "last_run": None,
            "run_count": 0,
        }
        self._save()
        if interval_sec:
            self._start_interval(sid)
        return f"Schedule '{name}' created (id: {sid})."

    def remove(self, id_or_name: str) -> str:
        target = None
        for sid, s in self._schedules.items():
            if sid == id_or_name or s["name"] == id_or_name:
                target = sid
                break
        if not target:
            return f"No schedule found: {id_or_name}"
        name = self._schedules[target]["name"]
        del self._schedules[target]
        self._save()
        if target in self._tasks:
            self._tasks[target].cancel()
            del self._tasks[target]
        return f"Schedule '{name}' removed."

    def list_all(self) -> str:
        if not self._schedules:
            return "No scheduled tasks."
        lines = []
        for s in self._schedules.values():
            trigger = f"every {s['interval_sec']}s" if s["interval_sec"] else s["cron"]
            lines.append(
                f"  [{s['id']}] {s['name']}\n"
                f"    Trigger : {trigger}\n"
                f"    Prompt  : {s['prompt'][:60]}…\n"
                f"    Runs    : {s['run_count']}  Last: {s['last_run'] or 'never'}"
            )
        return "Scheduled tasks:\n" + "\n\n".join(lines)

    # ── Background runner ───────────────────────────────────────

    def start_all(self):
        """Called on daemon startup to resume interval tasks."""
        for sid, s in self._schedules.items():
            if s.get("interval_sec"):
                self._start_interval(sid)

    def _start_interval(self, sid: str):
        if sid in self._tasks:
            self._tasks[sid].cancel()
        self._tasks[sid] = create_background_task(
            self._interval_loop(sid), name=f"sched-{sid}"
        )

    async def _interval_loop(self, sid: str):
        while True:
            s = self._schedules.get(sid)
            if not s:
                break
            await asyncio.sleep(s["interval_sec"])
            await self._run_task(sid)

    async def _run_task(self, sid: str):
        s = self._schedules.get(sid)
        if not s or not self._agent:
            return
        log.info("[scheduler] Running task '%s' (%s)", s["name"], sid)
        try:
            await self._agent.run(s["prompt"])
            self._schedules[sid]["last_run"] = datetime.now().isoformat()
            self._schedules[sid]["run_count"] += 1
            self._save()
        except Exception as e:
            log.error("[scheduler] Task '%s' failed: %s", s["name"], e)

    # ── Tool handlers ───────────────────────────────────────────

    def build_handlers(self) -> dict:
        return {
            "schedule_add": lambda **kw: asyncio.coroutine(lambda: self.add(**kw))(),
            "schedule_list": lambda **_: self.list_all(),
            "schedule_remove": lambda **kw: self.remove(**kw),
        }

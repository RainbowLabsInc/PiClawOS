"""
PiClaw OS – Sub-Agent Management Tools
Tools the mainagent can call to create, manage and monitor dynamic sub-agents.

Example interactions:
  "Erstelle einen Agenten der jeden Morgen um 7 Uhr die Systemtemperatur prüft"
  "Starte den HomeMonitor-Agenten"
  "Zeig mir alle laufenden Sub-Agenten"
  "Stoppe den DailyBriefing-Agenten"
  "Lösche den Test-Agenten"
"""

from piclaw.llm.base            import ToolDefinition
from piclaw.agents.sa_registry  import SubAgentDef, SubAgentRegistry
from piclaw.agents.runner       import SubAgentRunner

TOOL_DEFS = [
    ToolDefinition(
        name="agent_list",
        description="List all defined sub-agents with their status, schedule and last run.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="agent_create",
        description=(
            "Create a new dynamic sub-agent. The agent will run autonomously with its own "
            "mission, tool set and schedule. After creation it can be started immediately.\n\n"
            "Schedule formats:\n"
            "  once             – run once when started\n"
            "  interval:3600    – run every 3600 seconds\n"
            "  cron:0 7 * * *   – run daily at 7:00 (cron syntax)\n"
            "  continuous        – run in a continuous loop\n\n"
            "Tool names: shell_exec, wifi_scan, wifi_connect, gpio_read, gpio_write, "
            "service_status, service_start, service_stop, memory_search, memory_write, "
            "memory_log, http_get, http_post, schedule_task, llm_list"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short unique name, e.g. 'TempMonitor', 'DailyBriefing'"
                },
                "description": {
                    "type": "string",
                    "description": "One-sentence description of what this agent does"
                },
                "mission": {
                    "type": "string",
                    "description": (
                        "Detailed system prompt / task description for the agent. "
                        "Be specific: what to check, what to do, what to report."
                    )
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowed tool names. Empty list = all tools available."
                },
                "schedule": {
                    "type": "string",
                    "description": "When to run: once | interval:<sec> | cron:<expr> | continuous",
                    "default": "once"
                },
                "llm_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Preferred LLM capability tags, e.g. ['coding'] or ['german']",
                    "default": []
                },
                "notify": {
                    "type": "boolean",
                    "description": "Send result via messaging hub when done",
                    "default": True
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum agentic loop steps (default 10)",
                    "default": 10
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum runtime in seconds (default 300)",
                    "default": 300
                },
                "start_now": {
                    "type": "boolean",
                    "description": "Start the agent immediately after creation",
                    "default": False
                },
            },
            "required": ["name", "description", "mission"],
        },
    ),
    ToolDefinition(
        name="agent_start",
        description="Start a defined sub-agent by name or ID.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name or ID"}
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="agent_stop",
        description="Stop a running sub-agent.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name or ID"}
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="agent_remove",
        description="Delete a sub-agent definition permanently.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name or ID"}
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="agent_update",
        description="Update a sub-agent's mission, schedule, tools or other properties.",
        parameters={
            "type": "object",
            "properties": {
                "name":        {"type": "string"},
                "mission":     {"type": "string"},
                "description": {"type": "string"},
                "schedule":    {"type": "string"},
                "tools":       {"type": "array", "items": {"type": "string"}},
                "enabled":     {"type": "boolean"},
                "notify":      {"type": "boolean"},
                "llm_tags":    {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="agent_run_now",
        description=(
            "Trigger an immediate one-off execution of a sub-agent, "
            "regardless of its schedule. Useful for testing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name or ID"}
            },
            "required": ["name"],
        },
    ),
]


def build_handlers(registry: SubAgentRegistry, runner: SubAgentRunner) -> dict:

    async def agent_list(**_) -> str:
        status = runner.status_dict()
        agents = status.get("sub_agents", [])
        if not agents:
            return "No sub-agents defined. Use agent_create to create one."
        lines = [f"Sub-Agents ({len(agents)}):\n"]
        for a in agents:
            running_icon = "⚙️ RUNNING" if a["running"] else ""
            status_icon  = {
                "ok": "✅", "error": "❌", "timeout": "⏱️",
                "running": "⚙️", None: "⬜"
            }.get(a["last_status"], "⬜")
            enabled = "" if a["enabled"] else " [disabled]"
            lines.append(
                f"  {status_icon} [{a['id']}] {a['name']}{enabled} {running_icon}\n"
                f"       {a['description']}\n"
                f"       schedule: {a['schedule']}\n"
                f"       last run: {a['last_run'] or 'never'}  "
                f"status: {a['last_status'] or 'never run'}"
            )
        return "\n\n".join(lines)

    async def agent_create(
        name: str, description: str, mission: str,
        tools: list = None, schedule: str = "once",
        llm_tags: list = None, notify: bool = True,
        max_steps: int = 10, timeout: int = 300,
        start_now: bool = False,
        **_
    ) -> str:
        # Check for name collision
        if registry.get(name):
            return f"A sub-agent named '{name}' already exists. Use agent_update to modify it."

        agent = SubAgentDef(
            name=name,
            description=description,
            mission=mission,
            tools=tools or [],
            schedule=schedule,
            llm_tags=llm_tags or [],
            notify=notify,
            max_steps=max_steps,
            timeout=timeout,
            created_by="mainagent",
        )
        agent_id = registry.add(agent)
        result = (
            f"Sub-agent '{name}' created (ID: {agent_id})\n"
            f"  Schedule: {schedule}\n"
            f"  Tools: {', '.join(tools) if tools else 'all'}\n"
            f"  Notify: {notify}"
        )
        if start_now:
            start_result = await runner.start_agent(agent_id)
            result += f"\n{start_result}"
        return result

    async def agent_start(name: str, **_) -> str:
        return await runner.start_agent(name)

    async def agent_stop(name: str, **_) -> str:
        return await runner.stop_agent(name)

    async def agent_remove(name: str, **_) -> str:
        # Stop first if running
        agent = registry.get(name)
        if not agent:
            return f"Sub-agent '{name}' not found."
        if agent.id in runner._tasks and not runner._tasks[agent.id].done():
            await runner.stop_agent(name)
        success = registry.remove(name)
        return f"Sub-agent '{name}' removed." if success else f"'{name}' not found."

    async def agent_update(name: str, **kwargs) -> str:
        # Remove None values
        updates = {k: v for k, v in kwargs.items() if v is not None}
        if not updates:
            return "Nothing to update."
        success = registry.update(name, **updates)
        if not success:
            return f"Sub-agent '{name}' not found."
        return f"Sub-agent '{name}' updated: {list(updates.keys())}"

    async def agent_run_now(name: str, **_) -> str:
        agent = registry.get(name)
        if not agent:
            return f"Sub-agent '{name}' not found."
        # Run as a one-off task without touching the schedule
        import asyncio
        task = asyncio.create_task(
            runner._execute(agent),
            name=f"subagent-oneoff-{agent.id}",
        )
        return f"Sub-agent '{name}' triggered for immediate execution."

    return {
        "agent_list":    lambda **kw: agent_list(**kw),
        "agent_create":  lambda **kw: agent_create(**kw),
        "agent_start":   lambda **kw: agent_start(**kw),
        "agent_stop":    lambda **kw: agent_stop(**kw),
        "agent_remove":  lambda **kw: agent_remove(**kw),
        "agent_update":  lambda **kw: agent_update(**kw),
        "agent_run_now": lambda **kw: agent_run_now(**kw),
    }

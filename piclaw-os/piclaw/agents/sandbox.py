"""
PiClaw OS – Sub-Agent Sandboxing
Restricts which tools sub-agents are allowed to use.

Design:
  Tier 1 – BLOCKED_ALWAYS:
    Absolutely forbidden for all sub-agents, always.
    These can cause irreversible system damage or security issues.
    No override is possible at the agent level.

  Tier 2 – BLOCKED_BY_DEFAULT:
    Blocked unless the sub-agent has been explicitly granted the tool
    via its 'tools' allowlist AND has the 'trusted' flag set.
    These are powerful but legitimate in specific contexts.

  Tier 3 – All other tools:
    Available freely to sub-agents.

Usage:
  from piclaw.agents.sandbox import filter_tools_for_subagent, explain_restrictions

  safe_tools = filter_tools_for_subagent(
      all_tool_defs, agent.tools, trusted=agent.trusted
  )
"""

import logging
from typing import TYPE_CHECKING

log = logging.getLogger("piclaw.agents.sandbox")

# ── Tier 1: Always blocked, no override possible ──────────────────
# These can cause irreversible harm or compromise security.
BLOCKED_ALWAYS: frozenset[str] = frozenset({
    # Filesystem wipe / recursive deletion
    "shell_exec",        # raw shell access – use specific tools instead
    "rm_recursive",

    # System integrity
    "service_disable",   # disabling systemd services
    "system_reboot",     # rebooting without user confirmation
    "system_powerof",
    "system_halt",

    # Watchdog tampering
    "watchdog_stop",
    "watchdog_disable",

    # Self-modification
    "updater_apply",     # applying OS updates without confirmation

    # Security
    "config_write_raw",  # writing raw config (may expose API keys)
})

# ── Tier 2: Blocked by default, requires trusted=True + explicit allowlist ──
# Powerful but legitimate tools that need explicit opt-in.
BLOCKED_BY_DEFAULT: frozenset[str] = frozenset({
    "service_stop",      # stopping a managed service
    "service_restart",   # restarting services
    "gpio_write",        # writing to GPIO pins (hardware risk)
    "network_set",       # changing network config
    "scheduler_remove",  # removing scheduled tasks
})

# All known dangerous categories – for display/docs
ALL_RESTRICTED = BLOCKED_ALWAYS | BLOCKED_BY_DEFAULT


def filter_tools_for_subagent(
    all_tool_defs:   list,           # list[ToolDefinition]
    agent_allowlist: list[str],      # agent.tools ([] = all non-blocked)
    trusted:         bool = False,   # agent.trusted flag
) -> list:
    """
    Return the subset of tool_defs a sub-agent is allowed to use.

    Rules:
      1. BLOCKED_ALWAYS are always removed (no exception).
      2. If agent has an explicit allowlist (non-empty tools=[...]):
           - Only listed tools are allowed (intersect with all_tool_defs)
           - BLOCKED_ALWAYS are still removed from the result
           - BLOCKED_BY_DEFAULT tools ARE allowed if explicitly listed
             AND trusted=True; otherwise removed too.
      3. If agent has no allowlist (tools=[]):
           - All tools EXCEPT BLOCKED_ALWAYS and BLOCKED_BY_DEFAULT
           - Unless trusted=True, in which case BLOCKED_BY_DEFAULT is allowed

    Returns the filtered list of ToolDefinition objects.
    """
    if agent_allowlist:
        # Explicit allowlist: start from requested tools only
        requested = {t.lower() for t in agent_allowlist}
        candidates = [td for td in all_tool_defs if td.name.lower() in requested]
    else:
        # No allowlist: all tools as starting point
        candidates = list(all_tool_defs)

    filtered = []
    blocked_log = []

    for td in candidates:
        name_lower = td.name.lower()

        # Tier 1: always blocked
        if name_lower in BLOCKED_ALWAYS:
            blocked_log.append(f"{td.name} (tier-1: always blocked)")
            continue

        # Tier 2: blocked by default unless trusted
        if name_lower in BLOCKED_BY_DEFAULT:
            if trusted and agent_allowlist and name_lower in {t.lower() for t in agent_allowlist}:
                # Explicitly requested + trusted = allowed
                filtered.append(td)
            else:
                reason = "tier-2: blocked by default" + ("" if not trusted else ", not in allowlist")
                blocked_log.append(f"{td.name} ({reason})")
            continue

        filtered.append(td)

    if blocked_log:
        log.debug("Sandbox blocked tools: %s", ', '.join(blocked_log))

    return filtered


def explain_restrictions(tool_name: str, trusted: bool = False) -> str:
    """Return a human-readable explanation of why a tool is restricted."""
    name_lower = tool_name.lower()
    if name_lower in BLOCKED_ALWAYS:
        return (
            f"'{tool_name}' is blocked for all sub-agents (Tier 1 – irreversible system risk). "
            "Only the main agent can use this tool."
        )
    if name_lower in BLOCKED_BY_DEFAULT:
        if trusted:
            return (
                f"'{tool_name}' is available but requires explicit listing in the agent's "
                "'tools' allowlist (Tier 2 – trusted agent required)."
            )
        return (
            f"'{tool_name}' is blocked by default (Tier 2 – powerful tool). "
            "Add it to the agent's tools allowlist and set trusted=True to enable."
        )
    return f"'{tool_name}' is unrestricted and available to all sub-agents."


def audit_agent_tools(agent_name: str, requested: list[str], trusted: bool = False) -> str:
    """
    Return a formatted audit summary of which tools are/aren't available.
    Useful for debug logging and the 'piclaw agent inspect' CLI command.
    """
    lines = [f"Tool audit for sub-agent '{agent_name}' (trusted={trusted}):"]
    for tool in requested:
        name_lower = tool.lower()
        if name_lower in BLOCKED_ALWAYS:
            lines.append(f"  ✗ {tool} — BLOCKED (tier-1: always)")
        elif name_lower in BLOCKED_BY_DEFAULT:
            if trusted:
                lines.append(f"  ✓ {tool} — ALLOWED (tier-2, trusted override)")
            else:
                lines.append(f"  ✗ {tool} — BLOCKED (tier-2: not trusted)")
        else:
            lines.append(f"  ✓ {tool} — ALLOWED")
    return "\n".join(lines)

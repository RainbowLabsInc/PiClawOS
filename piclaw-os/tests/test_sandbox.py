"""
Tests for the sub-agent sandboxing system.
"""

import pytest
from piclaw.agents.sandbox import (
    filter_tools_for_subagent,
    explain_restrictions,
    audit_agent_tools,
    BLOCKED_ALWAYS,
    BLOCKED_BY_DEFAULT,
)


# ── Mock ToolDefinition ───────────────────────────────────────────


class FakeTool:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"Tool({self.name})"


def tools(*names) -> list[FakeTool]:
    return [FakeTool(n) for n in names]


def names(tool_list) -> list[str]:
    return [t.name for t in tool_list]


# ── Tier 1: Always blocked ────────────────────────────────────────


class TestBlockedAlways:
    def test_shell_exec_always_blocked(self):
        all_tools = tools("shell_exec", "read_file", "get_temp")
        result = filter_tools_for_subagent(all_tools, [], trusted=False)
        assert "shell_exec" not in names(result)

    def test_shell_exec_blocked_even_if_trusted(self):
        all_tools = tools("shell_exec", "get_temp")
        result = filter_tools_for_subagent(all_tools, ["shell_exec"], trusted=True)
        assert "shell_exec" not in names(result)

    def test_shell_exec_blocked_even_if_explicitly_listed(self):
        all_tools = tools("shell_exec", "read_file")
        result = filter_tools_for_subagent(
            all_tools, ["shell_exec", "read_file"], trusted=True
        )
        assert "shell_exec" not in names(result)
        assert "read_file" in names(result)

    def test_system_reboot_always_blocked(self):
        all_tools = tools("system_reboot", "get_temp")
        result = filter_tools_for_subagent(all_tools, [], trusted=True)
        assert "system_reboot" not in names(result)

    def test_all_tier1_tools_blocked(self):
        all_tools = tools(*BLOCKED_ALWAYS)
        result = filter_tools_for_subagent(
            all_tools, list(BLOCKED_ALWAYS), trusted=True
        )
        assert len(result) == 0

    def test_watchdog_stop_blocked(self):
        all_tools = tools("watchdog_stop", "get_temp")
        result = filter_tools_for_subagent(all_tools, [], trusted=False)
        assert "watchdog_stop" not in names(result)


# ── Tier 2: Blocked by default ───────────────────────────────────


class TestBlockedByDefault:
    def test_service_stop_blocked_by_default(self):
        all_tools = tools("service_stop", "get_temp")
        result = filter_tools_for_subagent(all_tools, [], trusted=False)
        assert "service_stop" not in names(result)

    def test_gpio_write_blocked_by_default(self):
        all_tools = tools("gpio_write", "gpio_read")
        result = filter_tools_for_subagent(all_tools, [], trusted=False)
        assert "gpio_write" not in names(result)

    def test_tier2_allowed_when_trusted_and_listed(self):
        all_tools = tools("service_stop", "get_temp")
        result = filter_tools_for_subagent(all_tools, ["service_stop"], trusted=True)
        assert "service_stop" in names(result)

    def test_tier2_blocked_when_trusted_but_not_listed(self):
        """trusted alone is not enough – must also be in explicit allowlist."""
        all_tools = tools("service_stop", "get_temp")
        result = filter_tools_for_subagent(all_tools, [], trusted=True)
        assert "service_stop" not in names(result)

    def test_tier2_blocked_when_listed_but_not_trusted(self):
        all_tools = tools("gpio_write", "gpio_read")
        result = filter_tools_for_subagent(all_tools, ["gpio_write"], trusted=False)
        assert "gpio_write" not in names(result)

    def test_tier2_all_blocked_without_trust(self):
        all_tools = tools(*BLOCKED_BY_DEFAULT)
        result = filter_tools_for_subagent(
            all_tools, list(BLOCKED_BY_DEFAULT), trusted=False
        )
        assert len(result) == 0


# ── Safe tools pass through ───────────────────────────────────────


class TestSafeTools:
    def test_safe_tools_always_available(self):
        safe = tools("get_temp", "read_file", "memory_search", "http_get")
        result = filter_tools_for_subagent(safe, [], trusted=False)
        assert set(names(result)) == {
            "get_temp",
            "read_file",
            "memory_search",
            "http_get",
        }

    def test_explicit_allowlist_limits_to_listed(self):
        all_tools = tools("get_temp", "read_file", "memory_search", "network_info")
        result = filter_tools_for_subagent(
            all_tools, ["get_temp", "read_file"], trusted=False
        )
        assert "get_temp" in names(result)
        assert "read_file" in names(result)
        assert "memory_search" not in names(result)

    def test_empty_allowlist_grants_all_safe_tools(self):
        all_tools = tools("get_temp", "read_file", "shell_exec", "service_stop")
        result = filter_tools_for_subagent(all_tools, [], trusted=False)
        assert "get_temp" in names(result)
        assert "read_file" in names(result)
        assert "shell_exec" not in names(result)
        assert "service_stop" not in names(result)

    def test_case_insensitive_matching(self):
        all_tools = tools("Shell_Exec", "Get_Temp")
        result = filter_tools_for_subagent(all_tools, [], trusted=True)
        assert "Shell_Exec" not in names(result)  # tier-1
        assert "Get_Temp" in names(result)


# ── explain_restrictions ─────────────────────────────────────────


class TestExplainRestrictions:
    def test_tier1_explanation(self):
        msg = explain_restrictions("shell_exec")
        assert "tier 1" in msg.lower() or "blocked" in msg.lower()
        assert "shell_exec" in msg

    def test_tier2_explanation_untrusted(self):
        msg = explain_restrictions("service_stop", trusted=False)
        assert "tier 2" in msg.lower() or "blocked" in msg.lower()

    def test_tier2_explanation_trusted(self):
        msg = explain_restrictions("gpio_write", trusted=True)
        assert "allowlist" in msg.lower() or "trusted" in msg.lower()

    def test_unrestricted_explanation(self):
        msg = explain_restrictions("get_temp")
        assert "unrestricted" in msg.lower() or "available" in msg.lower()


# ── audit_agent_tools ─────────────────────────────────────────────


class TestAuditAgentTools:
    def test_audit_shows_blocked_and_allowed(self):
        audit = audit_agent_tools(
            "TestBot",
            ["get_temp", "shell_exec", "service_stop"],
            trusted=False,
        )
        assert "get_temp" in audit
        assert "shell_exec" in audit
        assert "service_stop" in audit
        # Shell exec should be marked blocked
        lines = {l.strip() for l in audit.splitlines()}
        shell_line = next(l for l in lines if "shell_exec" in l)
        assert "✗" in shell_line or "BLOCKED" in shell_line

    def test_audit_trusted_allows_tier2(self):
        audit = audit_agent_tools(
            "TrustedBot",
            ["service_stop"],
            trusted=True,
        )
        lines = {l.strip() for l in audit.splitlines()}
        svc_line = next(l for l in lines if "service_stop" in l)
        assert "✓" in svc_line or "ALLOWED" in svc_line

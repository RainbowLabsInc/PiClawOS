"""
PiClaw OS – Sub-Agent Orchestration Tools
Mainagent tools for managing Crawler and reading Watchdog.

Design rules:
  Crawler: mainagent can create/cancel/list jobs (full control)
  Watchdog: mainagent can only READ alerts/reports (no write/cancel)
"""

import asyncio
import logging

log = logging.getLogger(__name__)

from piclaw.llm.base import ToolDefinition
from piclaw.agents.ipc import (
    CrawlJob,
    write_job,
    cancel_job,
    list_jobs,
    get_job,
    get_unsent_alerts,
    get_unsent_reports,
    mark_alert_sent,
    mark_report_sent,
    get_recent_alerts,
)


TOOL_DEFS = [
    # ── Crawler tools ─────────────────────────────────────────────
    ToolDefinition(
        name="crawl_create",
        description=(
            "Create a web crawl job. The crawler sub-agent will execute it. "
            "Use for web research tasks, price monitoring, news tracking, etc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for / research topic",
                },
                "mode": {
                    "type": "string",
                    "enum": ["once", "recurring", "until_found"],
                    "description": (
                        "once=single run, "
                        "recurring=cron/interval schedule until cancelled, "
                        "until_found=repeat until pattern found then auto-stop"
                    ),
                    "default": "once",
                },
                "cron": {
                    "type": "string",
                    "description": "Cron expression for recurring mode (e.g. '0 8 * * *' = daily 08:00)",
                },
                "interval_sec": {
                    "type": "integer",
                    "description": "Repeat every N seconds (alternative to cron)",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional seed URLs. If empty, uses DuckDuckGo search.",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Max pages per run (default 10, max 50)",
                    "default": 10,
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Link-following depth (1=only seeds, 2=follow links)",
                    "default": 1,
                },
                "timeout_sec": {
                    "type": "integer",
                    "description": "Hard job timeout in seconds (default 300)",
                    "default": 300,
                },
                "until_pattern": {
                    "type": "string",
                    "description": "Regex pattern for until_found mode (e.g. 'price.*€[0-9]+')",
                },
                "notify_chat": {
                    "type": "string",
                    "description": "Telegram chat_id to notify when done",
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="crawl_list",
        description="List all crawl jobs and their current status.",
        parameters={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "enum": [
                        "all",
                        "pending",
                        "running",
                        "done",
                        "failed",
                        "cancelled",
                    ],
                    "default": "all",
                }
            },
        },
    ),
    ToolDefinition(
        name="crawl_cancel",
        description="Cancel a recurring or pending crawl job by ID.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID to cancel"}
            },
            "required": ["job_id"],
        },
    ),
    ToolDefinition(
        name="crawl_result",
        description="Get the latest result of a specific crawl job.",
        parameters={
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    ),
    # ── Watchdog tools (READ-ONLY) ────────────────────────────────
    ToolDefinition(
        name="watchdog_alerts",
        description=(
            "Read recent watchdog security and health alerts. "
            "READ-ONLY – the watchdog cannot be controlled, only read."
        ),
        parameters={
            "type": "object",
            "properties": {
                "unsent_only": {
                    "type": "boolean",
                    "description": "Only show alerts not yet sent via Telegram",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max alerts to return (default 10)",
                    "default": 10,
                },
            },
        },
    ),
    ToolDefinition(
        name="watchdog_forward",
        description=(
            "Forward pending watchdog alerts and reports via the mainagent's "
            "Telegram channel. Marks them as sent."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="watchdog_status",
        description="Get a summary of the watchdog's current health assessment.",
        parameters={"type": "object", "properties": {}},
    ),
]


# ── Handlers ─────────────────────────────────────────────────────


def build_handlers(telegram_send_fn) -> dict:
    """
    telegram_send_fn: async callable(chat_id, text) from mainagent's adapter.
    """

    async def crawl_create(
        query: str,
        mode: str = "once",
        cron: str = "",
        interval_sec: int = 0,
        urls: list = None,
        max_pages: int = 10,
        max_depth: int = 1,
        timeout_sec: int = 300,
        until_pattern: str = "",
        notify_chat: str = "",
    ) -> str:
        job = CrawlJob(
            query=query,
            mode=mode,
            cron=cron,
            interval_sec=interval_sec,
            urls=urls or [],
            max_pages=min(max_pages, 50),
            max_depth=max_depth,
            timeout_sec=min(timeout_sec, 600),
            until_pattern=until_pattern,
            notify_chat=notify_chat,
        )
        write_job(job)

        schedule_str = ""
        if mode == "once":
            schedule_str = "single run"
        elif mode == "recurring":
            schedule_str = f"cron: {cron}" if cron else f"every {interval_sec}s"
        elif mode == "until_found":
            schedule_str = f"repeating until '{until_pattern}' found"

        return (
            "✅ Crawl job created\n"
            f"  ID      : {job.id}\n"
            f"  Query   : {query}\n"
            f"  Mode    : {mode} ({schedule_str})\n"
            f"  Timeout : {job.timeout_sec}s per run\n"
            f"  Notify  : {notify_chat or 'not set'}\n\n"
            f"The crawler will pick this up within {10}s."
        )

    async def crawl_list(status_filter: str = "all") -> str:
        sf = None if status_filter == "all" else status_filter
        jobs = list_jobs(status=sf)
        if not jobs:
            return f"No crawl jobs{f' with status {status_filter}' if sf else ''}."
        lines = [f"Crawl jobs ({len(jobs)} total):\n"]
        for j in jobs:
            icon = {
                "pending": "⏳",
                "running": "🔄",
                "done": "✅",
                "failed": "❌",
                "cancelled": "🚫",
            }.get(j.status, "?")
            sched = j.cron or (f"{j.interval_sec}s" if j.interval_sec else "once")
            lines.append(
                f"  {icon} [{j.id}] {j.query[:40]}\n"
                f"     Mode: {j.mode} ({sched}) · Runs: {j.run_count}\n"
                f"     Last: {j.last_run or 'never'}"
            )
        return "\n\n".join(lines)

    async def crawl_cancel(job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            return f"Job not found: {job_id}"
        cancel_job(job_id)
        return f"Crawl job '{job.query}' ({job_id}) cancelled."

    async def crawl_result(job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            return f"Job not found: {job_id}"
        return (
            f"Job: {job.query}\n"
            f"Status: {job.status} · Runs: {job.run_count}\n"
            f"Last run: {job.last_run or 'never'}\n\n"
            f"Result:\n{job.last_result or '(no result yet)'}"
        )

    async def watchdog_alerts(unsent_only: bool = False, limit: int = 10) -> str:
        if unsent_only:
            alerts = get_unsent_alerts()[:limit]
        else:
            alerts = get_recent_alerts(limit=limit)

        if not alerts:
            return "No watchdog alerts."

        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "⛔"}
        lines = [f"Watchdog alerts ({len(alerts)}):\n"]
        for a in alerts:
            sev = a["severity"] if isinstance(a, dict) else a.severity
            cat = a["category"] if isinstance(a, dict) else a.category
            msg = a["message"] if isinstance(a, dict) else a.message
            ts = a["ts"] if isinstance(a, dict) else a.ts
            icon = icons.get(sev, "?")
            lines.append(f"  {icon} [{cat}] {msg}\n     {ts}")
        return "\n\n".join(lines)

    async def watchdog_forward() -> str:
        """Forward unsent alerts/reports via mainagent Telegram."""
        alerts = get_unsent_alerts()
        reports = get_unsent_reports()
        sent = 0

        for alert in alerts:
            if not telegram_send_fn:
                break
            icon = {"info": "ℹ️", "warning": "⚠️", "critical": "⛔"}.get(
                alert.severity, "?"
            )
            text = (
                f"{icon} *Watchdog Alert*\n"
                f"[{alert.category.upper()}] {alert.message}\n"
                f"_{alert.detail}_"
            )
            await telegram_send_fn(text)
            mark_alert_sent(alert.id)
            sent += 1

        for report in reports:
            if not telegram_send_fn:
                break
            await telegram_send_fn(report.summary)
            mark_report_sent(report.id)
            sent += 1

        return f"Forwarded {sent} watchdog message(s) via Telegram."

    async def watchdog_status() -> str:
        import psutil

        alerts = get_recent_alerts(limit=50)
        crits = sum(1 for a in alerts if a["severity"] == "critical")
        warns = sum(1 for a in alerts if a["severity"] == "warning")

        try:
            disk = await asyncio.to_thread(psutil.disk_usage, "/")
            mem = await asyncio.to_thread(psutil.virtual_memory)
            disk_pct = disk.percent
            mem_pct = mem.percent
        except Exception:
            disk_pct = mem_pct = 0

        temp = None
        from piclaw.hardware.pi_info import current_temp
        temp = await asyncio.to_thread(current_temp)

        status = (
            "🟢 All OK"
            if crits == 0 and warns == 0
            else "🔴 Critical issues"
            if crits > 0
            else "🟡 Warnings present"
        )

        return (
            f"Watchdog Status: {status}\n"
            f"  Critical alerts : {crits}\n"
            f"  Warnings        : {warns}\n"
            f"  Disk            : {disk_pct:.0f}%\n"
            f"  RAM             : {mem_pct:.0f}%\n"
            f"  CPU Temp        : {f'{temp:.1f}°C' if temp else 'N/A'}\n"
            "  Note: Watchdog logs are tamper-proof and cannot be modified."
        )

    return {
        "crawl_create": lambda **kw: crawl_create(**kw),
        "crawl_list": lambda **kw: crawl_list(**kw),
        "crawl_cancel": lambda **kw: crawl_cancel(**kw),
        "crawl_result": lambda **kw: crawl_result(**kw),
        "watchdog_alerts": lambda **kw: watchdog_alerts(**kw),
        "watchdog_forward": lambda **_: watchdog_forward(),
        "watchdog_status": lambda **_: watchdog_status(),
    }

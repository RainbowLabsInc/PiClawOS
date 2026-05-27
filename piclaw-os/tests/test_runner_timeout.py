"""
Regression tests for the sub-agent hard-timeout cap.

Background: ``Monitor_TW_PLZ21224_250km`` was configured with timeout=300s
but ran for 38536s (10h42m) while blocking the LLM lock and the daemon
loop. Root cause: Python 3.11+ ``asyncio.wait_for`` awaits the cancelled
task to actually finish before raising ``TimeoutError``. Inner code that
awaits ``asyncio.to_thread(scrapling.Fetcher.get, ...)`` cannot honour
cancellation – the underlying OS thread keeps running – so ``wait_for``
hung indefinitely. The fix in ``runner._run_with_hard_timeout`` uses
``asyncio.wait`` and abandons the task on grace-period overrun.

These tests pin that behaviour so the bug cannot return.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from piclaw.agents.runner import SubAgentRunner
from piclaw.agents.sa_registry import SubAgentDef, SubAgentRegistry


def _make_runner(tmp_path: Path, handlers: dict) -> tuple[SubAgentRunner, SubAgentRegistry]:
    reg_file = tmp_path / "subagents.json"
    with patch("piclaw.agents.sa_registry.SA_REGISTRY_FILE", reg_file):
        registry = SubAgentRegistry()
    runner = SubAgentRunner(
        registry=registry,
        llm=None,  # direct_tool path never touches the LLM
        tool_defs=[],
        handlers=handlers,
        notify=None,
        memory_log=None,
        report_to_main=None,
    )
    return runner, registry


def _register(registry: SubAgentRegistry, **overrides) -> SubAgentDef:
    defaults = dict(
        name="SlowAgent",
        description="slow tool for tests",
        mission="",
        tools=[],
        schedule="once",
        direct_tool="slow_tool",
        timeout=1,
        notify=False,
    )
    defaults.update(overrides)
    agent = SubAgentDef(**defaults)
    registry.add(agent)
    return agent


@pytest.mark.asyncio
async def test_cooperative_sleep_is_hard_capped(tmp_path):
    """A cooperative ``asyncio.sleep`` longer than ``cfg.timeout`` must
    be cancelled and the agent marked ``timeout`` – well within a small
    multiple of ``cfg.timeout``."""
    sleep_seconds = 30  # >> cfg.timeout=1

    async def slow_tool():
        await asyncio.sleep(sleep_seconds)
        return "should never get here"

    runner, registry = _make_runner(tmp_path, {"slow_tool": slow_tool})
    agent = _register(registry, timeout=1)

    t0 = time.monotonic()
    await runner._execute(agent)
    elapsed = time.monotonic() - t0

    # Hard cap is 1s + grace of 2s; anything over 5s means wait_for-style
    # blocking is back. (Generous bound to avoid CI flake.)
    assert elapsed < 5.0, f"hard cap not enforced: {elapsed:.2f}s elapsed"
    refreshed = registry.get(agent.id) or agent  # may be auto-removed for `once`
    assert refreshed.last_status == "timeout"


@pytest.mark.asyncio
async def test_uncancellable_thread_does_not_block_loop(tmp_path):
    """A blocking ``asyncio.to_thread(time.sleep, ...)`` keeps an OS
    thread running after the Task is cancelled. The watchdog must still
    return control after ``cfg.timeout`` + grace instead of waiting for
    the OS thread (which is what the old ``asyncio.wait_for`` would
    have done in the ``Monitor_TW_PLZ21224_250km`` incident)."""
    sleep_seconds = 30  # the OS thread will keep sleeping this long

    async def slow_tool():
        await asyncio.to_thread(time.sleep, sleep_seconds)
        return "should never get here"

    runner, registry = _make_runner(tmp_path, {"slow_tool": slow_tool})
    agent = _register(registry, timeout=1)

    t0 = time.monotonic()
    await runner._execute(agent)
    elapsed = time.monotonic() - t0

    # cfg.timeout (1s) + _HARD_TIMEOUT_GRACE_S (2s) + scheduling slack.
    # With the bug, this would block for the full sleep_seconds.
    assert elapsed < 5.0, (
        f"hard cap defeated by un-cancellable thread: {elapsed:.2f}s "
        f"(expected < 5s, thread sleeps {sleep_seconds}s)"
    )
    refreshed = registry.get(agent.id) or agent
    assert refreshed.last_status == "timeout"


@pytest.mark.asyncio
async def test_runaway_task_that_swallows_cancel_is_abandoned(tmp_path):
    """If the inner coroutine catches and ignores ``CancelledError``
    (e.g. a third-party library with a broad ``except`` block – which is
    the realistic scrapling/Playwright failure mode), the watchdog
    must still return control via the abandon path. The runaway task
    is tracked so subsequent runs can detect a persistent block."""

    cancelled_was_swallowed = asyncio.Event()

    async def stubborn_tool():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled_was_swallowed.set()
            # Pretend we are in a buggy library that swallows cancel.
            await asyncio.sleep(30)
        return "never"

    runner, registry = _make_runner(tmp_path, {"slow_tool": stubborn_tool})
    agent = _register(registry, timeout=1)

    t0 = time.monotonic()
    await runner._execute(agent)
    elapsed = time.monotonic() - t0

    # 1s timeout + 2s grace + a little slack; if cancel-swallowing
    # blocked us, we would wait the full 30s.
    assert elapsed < 5.0, (
        f"abandon path did not engage: {elapsed:.2f}s elapsed"
    )
    assert cancelled_was_swallowed.is_set(), (
        "test bug: cancel was never delivered to the inner coroutine"
    )
    refreshed = registry.get(agent.id) or agent
    assert refreshed.last_status == "timeout"
    assert agent.id in runner._abandoned, (
        "runaway task that swallowed cancel must be tracked as abandoned"
    )

    # Clean up the abandoned task so pytest doesn't see warnings about
    # an un-awaited task at shutdown.
    abandoned = runner._abandoned.pop(agent.id, None)
    if abandoned is not None:
        abandoned.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.wait({abandoned}, timeout=0.1)


@pytest.mark.asyncio
async def test_fast_tool_completes_normally(tmp_path):
    """The hard cap must not interfere with normal sub-second runs."""

    async def fast_tool():
        await asyncio.sleep(0.01)
        return "done"

    runner, registry = _make_runner(tmp_path, {"fast_tool": fast_tool})
    agent = _register(registry, direct_tool="fast_tool", timeout=5)

    await runner._execute(agent)

    refreshed = registry.get(agent.id) or agent
    assert refreshed.last_status == "ok"
    assert agent.id not in runner._abandoned


@pytest.mark.asyncio
async def test_repeated_timeouts_do_not_block_loop(tmp_path):
    """Even when an agent keeps producing un-cancellable threads on each
    run, the daemon loop must continue to schedule the next iteration
    after ``cfg.timeout``. This pins the property the original bug
    violated (one stuck run blocked the loop for 10h42m)."""

    async def slow_tool():
        await asyncio.to_thread(time.sleep, 30)
        return "no"

    runner, registry = _make_runner(tmp_path, {"slow_tool": slow_tool})
    agent = _register(registry, schedule="interval:1", timeout=1)

    t0 = time.monotonic()
    # Run two cycles back-to-back. With the bug, the first call hangs
    # forever; with the fix, both finish in a couple of seconds each.
    await runner._execute(agent)
    await runner._execute(agent)
    elapsed = time.monotonic() - t0

    assert elapsed < 10.0, (
        f"second execution blocked: {elapsed:.2f}s for 2 cycles "
        f"(expected ~ 2 * (1+grace) seconds)"
    )

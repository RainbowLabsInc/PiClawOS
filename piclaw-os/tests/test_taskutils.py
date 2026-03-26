import asyncio
import pytest
from unittest.mock import patch

from piclaw.taskutils import (
    create_background_task,
    active_tasks,
    cancel_all,
    _TASKS
)


@pytest.fixture(autouse=True)
def cleanup_tasks():
    """Ensure _TASKS is empty before and after each test."""
    _TASKS.clear()
    yield
    # cancel_all expects an event loop, we can't easily await here in a sync fixture
    # We instead clear the list synchronously
    for task in list(_TASKS):
        task.cancel()
    _TASKS.clear()


@pytest.mark.asyncio
async def test_active_tasks_unnamed():
    """Test active_tasks returns 'unnamed' for tasks without a name."""
    async def sleeping_coro():
        await asyncio.sleep(0.1)

    # Creating a task without specifying a name
    task = create_background_task(sleeping_coro())

    # asyncio.create_task assigns a default name like "Task-1", so we need to clear it
    # explicitly to test the 't.get_name() or "unnamed"' fallback logic in active_tasks()
    task.set_name("")

    active = active_tasks()
    assert "unnamed" in active
    assert len(active) == 1

    task.cancel()


@pytest.mark.asyncio
async def test_active_tasks_excludes_done():
    """Test active_tasks does not include tasks that are already done."""
    async def quick_coro():
        return "done"

    async def sleeping_coro():
        await asyncio.sleep(0.1)

    task1 = create_background_task(quick_coro(), name="done_task")
    task2 = create_background_task(sleeping_coro(), name="active_task")

    # Wait for the quick task to complete
    await task1

    # active_tasks should only return the name of the active task
    active = active_tasks()
    assert "active_task" in active
    assert "done_task" not in active
    assert len(active) == 1

    task2.cancel()


@pytest.mark.asyncio
async def test_create_background_task_success():
    """Test creating a background task and its successful execution."""
    execution_flag = False

    async def dummy_coro():
        nonlocal execution_flag
        execution_flag = True
        await asyncio.sleep(0.01)
        return "done"

    task = create_background_task(dummy_coro(), name="test_task")

    # Task should be in the global set
    assert task in _TASKS
    assert task.get_name() == "test_task"

    # Wait for completion
    result = await task

    # Task should have executed and been removed from the set
    assert execution_flag is True
    assert result == "done"

    # Give the callback a tiny bit of time to execute in the event loop
    await asyncio.sleep(0.01)
    assert task not in _TASKS


@pytest.mark.asyncio
async def test_create_background_task_exception_with_logging():
    """Test that exceptions are caught and logged when log_errors=True."""
    async def failing_coro():
        await asyncio.sleep(0.01)
        raise ValueError("Intentional test error")

    with patch("piclaw.taskutils.log.error") as mock_log:
        task = create_background_task(failing_coro(), name="failing_task", log_errors=True)

        assert task in _TASKS

        # Wait for the task to finish (it will raise an exception inside the task, but not here)
        # We need to await it and catch the exception to let the event loop process it
        try:
            await task
        except ValueError:
            pass

        # Give the done callback a moment to run
        await asyncio.sleep(0.01)

        # Task should be removed
        assert task not in _TASKS

        # Log error should have been called
        assert mock_log.called
        args, kwargs = mock_log.call_args
        assert "failing_task" in args[1]
        assert "Intentional test error" in str(args[2])


@pytest.mark.asyncio
async def test_create_background_task_exception_without_logging():
    """Test that exceptions are NOT logged when log_errors=False."""
    async def failing_coro():
        await asyncio.sleep(0.01)
        raise ValueError("Intentional test error")

    with patch("piclaw.taskutils.log.error") as mock_log:
        task = create_background_task(failing_coro(), name="silent_failing_task", log_errors=False)

        try:
            await task
        except ValueError:
            pass

        await asyncio.sleep(0.01)

        assert task not in _TASKS
        assert not mock_log.called


@pytest.mark.asyncio
async def test_active_tasks():
    """Test active_tasks returns correct task names."""
    async def sleeping_coro():
        await asyncio.sleep(0.1)

    task1 = create_background_task(sleeping_coro(), name="task1")
    task2 = create_background_task(sleeping_coro(), name="task2")

    # active_tasks should return names of active tasks
    active = active_tasks()
    assert "task1" in active
    assert "task2" in active
    assert len(active) == 2

    # Cancel tasks to clean up
    task1.cancel()
    task2.cancel()


@pytest.mark.asyncio
async def test_cancel_all():
    """Test cancel_all cancels all tasks and clears the set."""
    async def sleeping_coro():
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    task1 = create_background_task(sleeping_coro(), name="task1")
    task2 = create_background_task(sleeping_coro(), name="task2")

    assert len(_TASKS) == 2

    cancelled_count = await cancel_all()

    assert cancelled_count == 2
    assert len(_TASKS) == 0
    assert task1.cancelled() or task1.done()
    assert task2.cancelled() or task2.done()

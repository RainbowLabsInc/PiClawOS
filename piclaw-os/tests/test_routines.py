import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from piclaw.routines import RoutineRegistry, build_handlers


@pytest.fixture
def tmp_registry(tmp_path):
    registry_file = tmp_path / "routines.json"
    registry = RoutineRegistry(registry_file)
    # Clear defaults for tests
    registry._routines = {}
    return registry


@pytest.fixture
def mock_runner():
    runner = MagicMock()
    runner.execute_routine = AsyncMock()
    runner.cfg = MagicMock()
    runner.llm = MagicMock()
    runner.hub = MagicMock()
    runner.hub.send_all = AsyncMock()
    return runner


@pytest.fixture
def handlers(tmp_registry, mock_runner):
    return build_handlers(tmp_registry, mock_runner)


def test_build_handlers_structure(handlers):
    expected_keys = {
        "routine_list",
        "routine_enable",
        "routine_disable",
        "routine_create",
        "routine_run_now",
        "briefing_now",
    }
    assert set(handlers.keys()) == expected_keys
    for k in expected_keys:
        assert callable(handlers[k])


@pytest.mark.asyncio
async def test_routine_list_empty(handlers):
    result = await handlers["routine_list"]()
    assert result == "Keine Routinen definiert."


@pytest.mark.asyncio
async def test_routine_list_populated(tmp_registry, handlers):
    tmp_registry.create_custom(
        name="Test Routine 1",
        cron="0 8 * * *",
        action="notify",
        params={"message": "Guten Morgen!", "silent_on_ok": True},
    )
    tmp_registry.create_custom(
        name="Test Routine 2",
        cron="0 9 * * *",
        action="briefing",
        params={"type": "status"},
    )

    result = await handlers["routine_list"]()

    assert "Routinen:" in result
    assert "Test Routine 1" in result
    assert "Test Routine 2" in result
    assert "message: Guten Morgen!" in result
    assert "type: status" in result
    assert "silent_on_ok" not in result


@pytest.mark.asyncio
async def test_routine_enable_success(tmp_registry, handlers):
    r = tmp_registry.create_custom("Test Routine", "0 8 * * *", "briefing", {})
    r.enabled = False
    tmp_registry.update(r)

    result = await handlers["routine_enable"](name=r.name)
    assert f"✓ Routine '{r.name}' aktiviert" in result
    assert "Nächster Lauf:" in result
    assert tmp_registry.get(r.name).enabled is True


@pytest.mark.asyncio
async def test_routine_enable_not_found(handlers):
    result = await handlers["routine_enable"](name="Unknown Routine")
    assert result == "Routine 'Unknown Routine' nicht gefunden."


@pytest.mark.asyncio
async def test_routine_disable_success(tmp_registry, handlers):
    r = tmp_registry.create_custom("Test Routine", "0 8 * * *", "briefing", {})

    result = await handlers["routine_disable"](name=r.name)
    assert f"✓ Routine '{r.name}' deaktiviert." in result
    assert tmp_registry.get(r.name).enabled is False


@pytest.mark.asyncio
async def test_routine_disable_not_found(handlers):
    result = await handlers["routine_disable"](name="Unknown Routine")
    assert result == "Routine 'Unknown Routine' nicht gefunden."


@pytest.mark.asyncio
async def test_routine_create_agent_prompt(tmp_registry, handlers):
    # Missing prompt
    res = await handlers["routine_create"]("Test", "* * * * *", "agent_prompt")
    assert "Für action=agent_prompt muss ein 'prompt' angegeben werden." in res

    # Success
    res = await handlers["routine_create"](
        "Test1", "* * * * *", "agent_prompt", prompt="Hello"
    )
    assert "✓ Routine 'Test1' erstellt" in res

    r = tmp_registry.get("Test1")
    assert r is not None
    assert r.action == "agent_prompt"
    assert r.params["prompt"] == "Hello"


@pytest.mark.asyncio
async def test_routine_create_notify(tmp_registry, handlers):
    # Missing message
    res = await handlers["routine_create"]("Test2", "* * * * *", "notify")
    assert "Für action=notify muss eine 'message' angegeben werden." in res

    # Success
    res = await handlers["routine_create"](
        "Test3", "* * * * *", "notify", message="Hello"
    )
    assert "✓ Routine 'Test3' erstellt" in res

    r = tmp_registry.get("Test3")
    assert r is not None
    assert r.action == "notify"
    assert r.params["message"] == "Hello"


@pytest.mark.asyncio
async def test_routine_create_briefing(tmp_registry, handlers):
    res = await handlers["routine_create"]("Test4", "* * * * *", "briefing")
    assert "✓ Routine 'Test4' erstellt" in res

    r = tmp_registry.get("Test4")
    assert r is not None
    assert r.action == "briefing"
    assert r.params["type"] == "status"


@pytest.mark.asyncio
async def test_routine_run_now_success(tmp_registry, mock_runner, handlers):
    r = tmp_registry.create_custom("Test", "0 8 * * *", "briefing", {})
    mock_runner.execute_routine.return_value = "Success output"

    result = await handlers["routine_run_now"](name="Test")
    assert "✓ Routine 'Test' ausgeführt" in result
    assert "Success output" in result
    mock_runner.execute_routine.assert_called_once_with(r)


@pytest.mark.asyncio
async def test_routine_run_now_not_found(handlers):
    result = await handlers["routine_run_now"](name="Unknown")
    assert result == "Routine 'Unknown' nicht gefunden."


@pytest.mark.asyncio
@patch("piclaw.briefing.generate_briefing", new_callable=AsyncMock)
async def test_briefing_now_with_hub(mock_generate, mock_runner, handlers):
    mock_generate.return_value = "Briefing content here."

    result = await handlers["briefing_now"](briefing_type="morning")

    mock_generate.assert_called_once_with("morning", mock_runner.cfg, mock_runner.llm)
    mock_runner.hub.send_all.assert_called_once_with("Briefing content here.")
    assert "Briefing gesendet:" in result
    assert "Briefing content here." in result


@pytest.mark.asyncio
@patch("piclaw.briefing.generate_briefing", new_callable=AsyncMock)
async def test_briefing_now_no_hub(mock_generate, mock_runner, handlers):
    mock_generate.return_value = "Briefing content here."
    mock_runner.hub = None  # Simulate no hub

    result = await handlers["briefing_now"]()

    mock_generate.assert_called_once_with("status", mock_runner.cfg, mock_runner.llm)
    assert result == "Briefing content here."

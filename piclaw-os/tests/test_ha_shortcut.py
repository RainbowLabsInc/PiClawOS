import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from piclaw.agent import Agent
from piclaw.config import PiClawConfig

@pytest.fixture
def agent():
    cfg = PiClawConfig()
    return Agent(cfg)

@pytest.mark.asyncio
async def test_ha_shortcut_list_concatenation_fix(agent):
    # Mock HA client
    mock_client = AsyncMock()
    mock_entity = MagicMock()
    mock_entity.entity_id = "light.wohnzimmer"
    mock_entity.domain = "light"
    mock_client.get_states.return_value = [mock_entity]
    mock_client.turn_on.return_value = True

    with patch("piclaw.tools.homeassistant.get_client", return_value=mock_client):
        # Trigger the bug:
        res = await agent._ha_shortcut("schalte das licht im wohnzimmer ein")
        assert res is not None

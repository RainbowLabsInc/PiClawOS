import pytest
from unittest.mock import patch, MagicMock

from piclaw.tools.homeassistant import get_client, HomeAssistantClient

def test_get_client():
    # Test initially None
    with patch("piclaw.tools.homeassistant._client", None):
        client = get_client()
        assert client is None

    # Test when client is instantiated
    mock_client = MagicMock(spec=HomeAssistantClient)
    with patch("piclaw.tools.homeassistant._client", mock_client):
        client = get_client()
        assert client is mock_client

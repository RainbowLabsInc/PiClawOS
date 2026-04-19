import pytest
from unittest.mock import MagicMock, AsyncMock
from piclaw.tools.agentmail import agentmail_create_inbox, agentmail_send_email, agentmail_list_inboxes, agentmail_list_messages
from piclaw.config import AgentMailConfig

@pytest.fixture
def mock_agentmail_config():
    return AgentMailConfig(api_key="test-api-key")

@pytest.mark.asyncio
async def test_agentmail_create_inbox(mock_agentmail_config, monkeypatch):
    mock_client = MagicMock()
    mock_inbox = MagicMock()
    mock_inbox.email = "agent@agentmail.to"
    mock_inbox.inbox_id = "ib_123"
    mock_client.inboxes.create = AsyncMock(return_value=mock_inbox)

    # We need to mock the client creation inside the tool
    async def mock_get_client(cfg):
        return mock_client

    monkeypatch.setattr("piclaw.tools.agentmail._get_client", mock_get_client)

    result = await agentmail_create_inbox(mock_agentmail_config, display_name="My Agent", username="my-agent")

    assert "agent@agentmail.to" in result
    assert "ib_123" in result
    mock_client.inboxes.create.assert_called_once_with(display_name="My Agent", username="my-agent")

@pytest.mark.asyncio
async def test_agentmail_send_email(mock_agentmail_config, monkeypatch):
    mock_client = MagicMock()
    mock_client.inboxes.messages.send = AsyncMock()

    async def mock_get_client(cfg):
        return mock_client

    monkeypatch.setattr("piclaw.tools.agentmail._get_client", mock_get_client)

    result = await agentmail_send_email(
        mock_agentmail_config,
        inbox_id="ib_123",
        to=["user@example.com"],
        subject="Hello",
        text="World"
    )

    assert "✅ Email sent successfully" in result
    mock_client.inboxes.messages.send.assert_called_once_with(
        inbox_id="ib_123", to=["user@example.com"], subject="Hello", text="World", html=None
    )

@pytest.mark.asyncio
async def test_agentmail_list_inboxes(mock_agentmail_config, monkeypatch):
    mock_client = MagicMock()
    mock_inbox = MagicMock()
    mock_inbox.email = "agent@agentmail.to"
    mock_inbox.inbox_id = "ib_123"
    mock_client.inboxes.list = AsyncMock(return_value=MagicMock(inboxes=[mock_inbox]))

    async def mock_get_client(cfg):
        return mock_client

    monkeypatch.setattr("piclaw.tools.agentmail._get_client", mock_get_client)

    result = await agentmail_list_inboxes(mock_agentmail_config)

    assert "agent@agentmail.to" in result
    assert "ib_123" in result

@pytest.mark.asyncio
async def test_agentmail_list_messages(mock_agentmail_config, monkeypatch):
    mock_client = MagicMock()
    mock_msg = MagicMock(
        from_address="sender@example.com",
        subject="Test Subject",
        text="Hello agent!",
        extracted_text="Hello agent!",
        created_at="2024-05-20"
    )
    mock_client.inboxes.messages.list = AsyncMock(return_value=MagicMock(messages=[mock_msg]))

    async def mock_get_client(cfg):
        return mock_client

    monkeypatch.setattr("piclaw.tools.agentmail._get_client", mock_get_client)

    result = await agentmail_list_messages(mock_agentmail_config, inbox_id="ib_123")

    assert "sender@example.com" in result
    assert "Test Subject" in result
    assert "Hello agent!" in result

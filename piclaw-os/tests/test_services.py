"""Tests for piclaw.tools.services"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from piclaw.tools.services import (
    build_handlers,
    service_status,
    service_control,
    service_list,
)
from piclaw.config import ServicesConfig


@pytest.fixture
def dummy_cfg():
    return ServicesConfig(managed=["ssh", "homeassistant"])


@pytest.mark.asyncio
async def test_build_handlers(dummy_cfg):
    handlers = build_handlers(dummy_cfg)

    # 1. Check if all expected tool names are present
    assert "service_status" in handlers
    assert "service_control" in handlers
    assert "service_list" in handlers

    # 2. Check if the returned objects are callable
    assert callable(handlers["service_status"])
    assert callable(handlers["service_control"])
    assert callable(handlers["service_list"])

    # 3. Verify that calling the handlers invokes the underlying functions correctly
    with patch(
        "piclaw.tools.services.service_status", new_callable=AsyncMock
    ) as mock_status:
        await handlers["service_status"](name="ssh")
        mock_status.assert_called_once_with(name="ssh")

    with patch(
        "piclaw.tools.services.service_control", new_callable=AsyncMock
    ) as mock_control:
        await handlers["service_control"](name="homeassistant", action="restart")
        mock_control.assert_called_once_with(
            cfg=dummy_cfg, name="homeassistant", action="restart"
        )

    with patch(
        "piclaw.tools.services.service_list", new_callable=AsyncMock
    ) as mock_list:
        await handlers["service_list"](dummy_arg="ignored")
        mock_list.assert_called_once_with(dummy_cfg)

import pytest
from piclaw.llm.api import detect_provider_and_model

@pytest.mark.asyncio
async def test_detect_anthropic():
    # Not actually calling API, just checking prefix matching logic if we implement it.
    pass

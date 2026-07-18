"""
Intent-Shortcut-Creator setzen owner_id aus dem User-Kontext.

Regression für den Bug vom 18.07.2026: Violas „Briefkasten"-Suchauftrag
(Monitor_Briefkasten) wurde über den Monitor-Intent-Shortcut ohne owner_id
angelegt → Runner fiel auf Broadcast zurück → Ergebnisse landeten im
Default-Chat (Admin) statt bei der Erstellerin.

Die Creator laufen im user_scope des anfragenden Users (Worker-Loop setzt
den ContextVar); ohne Kontext (Boot-Pfade, auto-boot) bleibt owner_id None
und der Sub-Agent ist weiterhin ein System-Agent mit Broadcast-Notify.
"""

from __future__ import annotations

import pytest

from piclaw.agent import Agent
from piclaw.agent_context import user_scope
from piclaw.agents import sa_registry


VIOLA = "viola-user-id"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(sa_registry, "SA_REGISTRY_FILE", tmp_path / "subagents.json")
    return sa_registry.SubAgentRegistry()


@pytest.fixture
def agent_stub(registry):
    """Minimaler Agent ohne boot(): nur was die Intent-Creator brauchen.

    sa_runner=None → Creator registrieren den Sub-Agenten und kehren mit
    „runner nicht bereit" zurück, ohne ihn zu starten.
    """
    a = Agent.__new__(Agent)
    a.sa_registry = registry
    a.sa_runner = None
    return a


@pytest.mark.asyncio
async def test_monitor_agent_gets_owner_from_context(agent_stub, registry):
    with user_scope(VIOLA):
        await agent_stub._create_monitor_agent({"query": "Briefkasten", "location": "21224"})
    sa = registry.get("Monitor_Briefkasten")
    assert sa is not None
    assert sa.owner_id == VIOLA


@pytest.mark.asyncio
async def test_monitor_agent_without_context_is_system(agent_stub, registry):
    await agent_stub._create_monitor_agent({"query": "Briefkasten"})
    sa = registry.get("Monitor_Briefkasten")
    assert sa is not None
    assert sa.owner_id is None
    assert sa.is_system


@pytest.mark.asyncio
async def test_tw_auction_monitor_gets_owner_from_context(agent_stub, registry):
    with user_scope(VIOLA):
        await agent_stub._create_tw_auction_monitor({"plz": "21224", "radius_km": 50})
    sa = registry.get("Monitor_TW_PLZ21224_50km")
    assert sa is not None
    assert sa.owner_id == VIOLA


@pytest.mark.asyncio
async def test_search_assistant_gets_owner_from_context(agent_stub, registry):
    with user_scope(VIOLA):
        await agent_stub._delegate_to_search_assistant("Briefkasten in 21224")
    sa = registry.get("SearchAssistant")
    assert sa is not None
    assert sa.owner_id == VIOLA


@pytest.mark.asyncio
async def test_network_monitor_gets_owner_from_context(agent_stub, registry):
    with user_scope(VIOLA):
        await agent_stub._create_network_monitor_agent(300)
    sa = registry.get("Monitor_Netzwerk")
    assert sa is not None
    assert sa.owner_id == VIOLA

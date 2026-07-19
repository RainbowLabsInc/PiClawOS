"""Tests für das History-Overlay in /api/subagents, den neuen
/api/subagents/{name}/history-Endpoint und /api/llm/health."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from piclaw.agents import sa_history
from piclaw.agents.sa_registry import SubAgentDef


@pytest.fixture
def hist_file(tmp_path):
    with patch.object(sa_history, "HISTORY_FILE", tmp_path / "sa_history.json"):
        yield


def _user(user_id="u1", is_admin=False):
    u = MagicMock()
    u.id = user_id
    u.is_admin = is_admin
    return u


def _mock_agent(sa_defs):
    """MagicMock des API-_agent mit registry-Lookup + status_dict aus den Defs."""
    agent = MagicMock()
    agent.sa_runner.status_dict.return_value = {
        "sub_agents": [
            {
                "id": sa.id,
                "name": sa.name,
                "last_run": sa.last_run,
                "last_status": sa.last_status,
                "running": False,
            }
            for sa in sa_defs
        ]
    }
    agent.sa_registry.get.side_effect = lambda key: next(
        (s for s in sa_defs if key in (s.name, s.id)), None
    )
    agent.sa_registry.list_all.side_effect = lambda uid=None: [
        s for s in sa_defs if s.visible_to(uid)
    ]
    return agent


def _mk_sa(name, owner_id=None):
    return SubAgentDef(
        name=name, description="d", mission="m", tools=[], owner_id=owner_id
    )


@pytest.mark.asyncio
async def test_subagents_overlay_adds_history_fields(hist_file):
    from piclaw import api as api_mod

    sa = _mk_sa("Briefing")
    sa_history.record_run(sa.id, sa.name, "ok", 3.2, "Alles gut auf dem Pi", None)

    with patch.object(api_mod, "_agent", _mock_agent([sa])):
        res = await api_mod.subagents_status(user=_user(is_admin=True))

    a = res["sub_agents"][0]
    assert a["last_result"] == "Alles gut auf dem Pi"
    assert a["last_duration_s"] == 3.2
    assert a["last_status"] == "ok"
    assert a["last_run"] is not None


@pytest.mark.asyncio
async def test_subagents_overlay_nonadmin_filter_kept(hist_file):
    from piclaw import api as api_mod

    mine = _mk_sa("Meiner", owner_id="u1")
    fremd = _mk_sa("Fremder", owner_id="u2")
    sa_history.record_run(fremd.id, fremd.name, "ok", 1.0, "geheim", "u2")

    with patch.object(api_mod, "_agent", _mock_agent([mine, fremd])):
        res = await api_mod.subagents_status(user=_user("u1"))

    names = [a["name"] for a in res["sub_agents"]]
    assert names == ["Meiner"]


@pytest.mark.asyncio
async def test_history_endpoint_returns_runs(hist_file):
    from piclaw import api as api_mod

    sa = _mk_sa("Briefing")
    sa_history.record_run(sa.id, sa.name, "ok", 1.0, "lauf 1", None)
    sa_history.record_run(sa.id, sa.name, "error", 2.0, "lauf 2", None)

    with patch.object(api_mod, "_agent", _mock_agent([sa])):
        res = await api_mod.subagent_history("Briefing", user=_user(is_admin=True))

    assert res["id"] == sa.id
    assert [h["result"] for h in res["history"]] == ["lauf 2", "lauf 1"]


@pytest.mark.asyncio
async def test_history_endpoint_hides_foreign_agents(hist_file):
    from piclaw import api as api_mod

    fremd = _mk_sa("Fremder", owner_id="u2")

    with patch.object(api_mod, "_agent", _mock_agent([fremd])):
        # Fremder User → 404
        with pytest.raises(HTTPException) as ei:
            await api_mod.subagent_history("Fremder", user=_user("u1"))
        assert ei.value.status_code == 404
        # Admin sieht ihn
        res = await api_mod.subagent_history("Fremder", user=_user(is_admin=True))
        assert res["name"] == "Fremder"
        # Owner sieht ihn
        res = await api_mod.subagent_history("Fremder", user=_user("u2"))
        assert res["name"] == "Fremder"


@pytest.mark.asyncio
async def test_history_endpoint_unknown_agent_404(hist_file):
    from piclaw import api as api_mod

    with patch.object(api_mod, "_agent", _mock_agent([])):
        with pytest.raises(HTTPException) as ei:
            await api_mod.subagent_history("gibtsnicht", user=_user(is_admin=True))
        assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_llm_health_without_status_file():
    from piclaw import api as api_mod

    res = await api_mod.llm_health("token")
    assert res["available"] is False

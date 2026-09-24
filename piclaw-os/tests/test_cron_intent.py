"""Regression: Zeitangaben muessen aus dem Task-Text des Cron-Intents fliegen.

Die Cleaning-Regex enthielt statt der Wortgrenze \\b ein woertliches
Backspace-Zeichen (0x08) und griff dadurch nie - "um 7:30" blieb im Task.
"""

import pytest

from piclaw.agent import Agent


@pytest.fixture
def agent():
    return Agent.__new__(Agent)


@pytest.mark.parametrize(
    "text, cron, task",
    [
        ("Erstelle einen Agenten der täglich um 8 Uhr das Wetter prüft",
         "0 8 * * *", "das wetter prüft"),
        ("Erstelle einen Agenten der jeden Tag um 7:30 die News zusammenfasst",
         "30 7 * * *", "die news zusammenfasst"),
        ("Erstelle einen Agenten der jeden Tag um 7:30 Uhr die News zusammenfasst",
         "30 7 * * *", "die news zusammenfasst"),
    ],
)
def test_cron_intent_strips_time_from_task(agent, text, cron, task):
    res = agent._detect_cron_agent_intent(text)
    assert res is not None
    assert res["cron_expr"] == cron
    assert res["task"] == task

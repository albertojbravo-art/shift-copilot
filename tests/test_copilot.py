"""Conversation-layer tests: tools carry engine figures; the loop wires
tool calls; the degraded path answers from templates. No network."""

import json

from copilot import explain, tools
from copilot.chat import Copilot
from copilot.llm import LLMError
from copilot.session import NightSession


def test_tool_preshift_projection_matches_engine():
    out = tools.dispatch(NightSession(), "preshift_projection", {})
    assert out["night_ots_percent"] == 94.0
    assert out["alert"] is True
    assert len(out["per_cutoff"]) == 12


def test_tool_ladder_preshift_restores_without_posting():
    out = tools.dispatch(NightSession(), "decision_ladder", {"at_minute": 0})
    assert out["binding_node"] == "Picking"
    assert out["projected_ots_before_percent"] == 94.0
    assert out["projected_ots_after_percent"] == 99.3
    assert out["posting"] is None
    assert len(out["moves"]) == 5


def test_tool_ladder_midshift_posts_for_picking():
    out = tools.dispatch(NightSession(), "decision_ladder", {"at_minute": 165})
    assert out["posting"] is not None
    assert out["posting"]["area"] == "Picking"
    assert out["posting"]["people"] == 5
    assert out["posting"]["hours"] == 5


def test_tool_night_outcome_no_intervention():
    out = tools.dispatch(NightSession(), "night_outcome", {"intervention": "none"})
    assert out["night_ots_percent"] == 69.5
    assert out["first_alert_minute"] == 0


def test_fallback_briefs_carry_engine_figures():
    s = NightSession()
    text = explain.preshift_brief(s) + explain.ladder_brief(s, 0)
    assert "94.0%" in text and "99.3%" in text
    live = explain.live_brief(s)
    assert "Picking" in live and "5 people x 5 hours" in live


class _ScriptedTransport:
    """First round: ask for the pre-shift ladder. Second: answer in words."""

    def __init__(self):
        self.rounds = 0

    def __call__(self, payload):
        self.rounds += 1
        if self.rounds == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "decision_ladder",
                                        "arguments": json.dumps({"at_minute": 0}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        # The final answer must be able to quote the tool's figures.
        tool_msg = payload["messages"][-1]
        data = json.loads(tool_msg["content"])
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            f"Projection {data['projected_ots_before_percent']}% before moves, "
                            f"{data['projected_ots_after_percent']}% after."
                        ),
                    }
                }
            ]
        }


def test_chat_loop_executes_tool_calls():
    cop = Copilot(transport=_ScriptedTransport())
    answer = cop.ask("How does tonight look?")
    assert cop.last_tool_calls == ["decision_ladder"]
    assert "94.0" in answer and "99.3" in answer
    assert cop.degraded is False


def test_chat_degrades_when_model_is_down():
    def down(payload):
        raise LLMError("boom")

    cop = Copilot(transport=down)
    answer = cop.ask("How does tonight look before the shift starts?")
    assert cop.degraded is True
    assert "94.0%" in answer

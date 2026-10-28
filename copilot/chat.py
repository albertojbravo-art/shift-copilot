"""The copilot conversation: the model explains; the engine computes.

Iron rule, enforced by construction: the system prompt forbids figures
that did not come from a tool result, and the tools are the only way the
model can obtain a figure. If the model API is unavailable, the copilot
degrades to the engine's templated briefs (explain.py) instead of going
silent.
"""

from __future__ import annotations

import json

from . import explain, tools as tool_mod
from .llm import LLMError, chat_completion
from .session import NightSession

SYSTEM_PROMPT = """You are Shift Copilot, an operations copilot for the lead of a night shift in a fulfillment building.

How you work:
- A deterministic engine computes every number. You explain and converse.
- You NEVER state a figure (a percentage, a headcount, a number of items, a time) that did not come from a tool result in this conversation. If you need a figure you do not have, call the tool that produces it. If no tool can produce it, say you do not have it.
- Tonight's target is 99.0% on-time shipping (OTS). The chain is Picking -> Induct -> Put -> Pack -> Shipping. Moving one person costs 10 minutes of relocation.
- When you report an alert, give the cause chain the engine shows (absences, a stoppage, the binding node), the recommended moves, and whether a posting is needed. The lead decides; you recommend.
- Keep answers short and operational, the way a good assistant lead talks at the start of a shift. Plain words, no fluff.
- All data tonight is synthetic demo data.

Tools: preshift_projection (before the shift), live_projection(at_minute), decision_ladder(at_minute; 0 = pre-shift), night_outcome(intervention)."""

MAX_TOOL_ROUNDS = 5


class Copilot:
    def __init__(self, session: NightSession | None = None, transport=None) -> None:
        self.session = session or NightSession()
        self.transport = transport
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.last_tool_calls: list[str] = []
        self.degraded = False

    def ask(self, question: str) -> str:
        self.last_tool_calls = []
        try:
            return self._ask_with_model(question)
        except LLMError:
            self.degraded = True
            return explain.fallback_answer(self.session, question)

    def _ask_with_model(self, question: str) -> str:
        self.history.append({"role": "user", "content": question})
        for _ in range(MAX_TOOL_ROUNDS):
            msg = chat_completion(self.history, tools=tool_mod.TOOLS, transport=self.transport)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                answer = (msg.get("content") or "").strip()
                self.history.append({"role": "assistant", "content": answer})
                return answer
            self.history.append(
                {"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls}
            )
            for call in tool_calls:
                fn = call["function"]
                self.last_tool_calls.append(fn["name"])
                result = tool_mod.dispatch_json(self.session, fn["name"], fn.get("arguments") or "{}")
                self.history.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
                )
        raise LLMError("tool round limit reached")

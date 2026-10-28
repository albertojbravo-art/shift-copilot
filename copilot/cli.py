"""Copilot CLI: a scripted conversation against the demo night.

    python3 -m copilot.cli

Asks the three canonical questions of the demo and prints the tool calls
the model made and its answers. With no BASETEN_API_KEY in the
environment, it runs in degraded mode: the engine's templated briefs
answer instead, which is the designed behavior when the API is down.
"""

from __future__ import annotations

from .chat import Copilot

QUESTIONS = [
    "How does tonight look before the shift starts?",
    "What do you recommend we do about it?",
    "The line from Picking to Consolidation just stopped. Where do we stand, and do we need to post for extra people?",
]


def main() -> None:
    cop = Copilot()
    for q in QUESTIONS:
        print(f"\nLEAD: {q}")
        answer = cop.ask(q)
        if cop.last_tool_calls:
            print(f"[tools called: {', '.join(cop.last_tool_calls)}]")
        if cop.degraded:
            print("[model unavailable — engine template]")
        print(f"COPILOT: {answer}")


if __name__ == "__main__":
    main()

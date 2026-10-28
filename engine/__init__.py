"""Shift Copilot -- deterministic simulation engine (v1).

Every number the copilot shows comes from this engine; the language model
only explains and converses, calling the engine as a tool. All scenario
data is synthetic and traces to SCENARIO.md.
"""

from .model import (
    EFFECTIVE_HOURS,
    OTS_TARGET,
    RELOCATE_MINUTES,
    SHIFT_MINUTES,
    Cut,
    Move,
    Node,
    Scenario,
    Stoppage,
    clean_scenario,
    demo_scenario,
)
from .generate import Order, generate_orders, release_schedule
from .simulate import NightResult, SimState, initial_state, run
from .project import Projection, project_from_state, project_preshift
from .recommend import PostingDraft, Recommendation, recommend

__all__ = [
    "EFFECTIVE_HOURS",
    "OTS_TARGET",
    "RELOCATE_MINUTES",
    "SHIFT_MINUTES",
    "Cut",
    "Move",
    "Node",
    "Scenario",
    "Stoppage",
    "clean_scenario",
    "demo_scenario",
    "Order",
    "generate_orders",
    "release_schedule",
    "NightResult",
    "SimState",
    "initial_state",
    "run",
    "Projection",
    "project_from_state",
    "project_preshift",
    "PostingDraft",
    "Recommendation",
    "recommend",
]

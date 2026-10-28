"""Forward projection: from a live simulation state, fast-forward the
remainder of the shift and report the projected OTS.

The projection replays the same deterministic stepper as the live
simulation (single source of truth in simulate.py), on a clone of the
state, with any scheduled moves. Knowledge rule (declared): a projection
made at minute t only includes stoppages that have already started by t
-- the copilot learns about a stoppage when the area-level no-scan signal
detects it (SCENARIO.md section 4), not before. The pre-shift calculation
therefore runs on projected volume and roster with known absences only
(sheet section 6), and a mid-shift projection worsens once a stoppage has
begun. The realized night (simulate.run) always includes every stoppage.

The alert rule (SCENARIO.md section 4): projected night OTS < 99.0%.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .generate import release_schedule
from .model import SHIFT_MINUTES, Move, Scenario
from .simulate import SimState, advance


@dataclass(frozen=True)
class Projection:
    minute: int  # minute the projection was made from
    per_cut_ots: tuple[float, ...]  # projected percent per cutoff
    night_ots: float  # projected percent for the night


def project_from_state(
    state: SimState, scenario: Scenario, moves: tuple[Move, ...] = ()
) -> Projection:
    """Project from `state` (not mutated) to the end of the shift."""
    schedule = release_schedule(scenario)
    pools = [0.0] * len(scenario.cuts)
    for order in schedule:
        pools[order.cut_index] += order.size

    known = replace(
        scenario,
        stoppages=tuple(s for s in scenario.stoppages if s.start <= state.minute),
    )
    work = state.clone()
    advance(work, known, schedule, moves, SHIFT_MINUTES)

    per_cut = tuple(
        100.0 * work.ontime[k] / pools[k] if pools[k] > 0 else 100.0
        for k in range(len(pools))
    )
    night = 100.0 * sum(work.ontime) / sum(pools) if sum(pools) > 0 else 100.0
    return Projection(minute=state.minute, per_cut_ots=per_cut, night_ots=night)


def project_preshift(scenario: Scenario, moves: tuple[Move, ...] = ()) -> Projection:
    """The pre-shift calculation (sheet section 6): projected volume and
    roster, with known absences, before minute 0."""
    from .simulate import initial_state

    return project_from_state(initial_state(scenario), scenario, moves)

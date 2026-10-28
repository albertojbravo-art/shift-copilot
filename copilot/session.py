"""A demo-night session: the state the copilot's tools answer from.

Mirrors engine.demo's canonical flow. The lead is assumed to accept the
pre-shift ladder's moves, so live (mid-shift) states advance with those
moves applied. All figures come from the deterministic engine; this
module only routes and formats.
"""

from __future__ import annotations

from engine.generate import release_schedule
from engine.model import Scenario, demo_scenario
from engine.project import Projection, project_from_state, project_preshift
from engine.recommend import Recommendation, recommend
from engine.simulate import NightResult, advance, initial_state, run

DETECTION_MINUTE = 165  # stoppage 1 starts at 150; area no-scan signal at +15


def clock(minute: int) -> str:
    """Minute offset from 17:30 -> wall-clock label."""
    total = 17 * 60 + 30 + minute
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


class NightSession:
    def __init__(self, scenario: Scenario | None = None) -> None:
        self.scenario = scenario or demo_scenario()
        self._preshift_moves: tuple = ()
        self._preshift_rec: Recommendation | None = None

    # -- pre-shift ------------------------------------------------------
    def preshift_projection(self) -> Projection:
        return project_preshift(self.scenario)

    def preshift_ladder(self) -> Recommendation:
        if self._preshift_rec is None:
            self._preshift_rec = recommend(self.scenario)
            self._preshift_moves = self._preshift_rec.moves
        return self._preshift_rec

    # -- live ------------------------------------------------------------
    def _live_state(self, at_minute: int):
        self.preshift_ladder()  # ensures the accepted moves exist
        state = initial_state(self.scenario)
        advance(
            state,
            self.scenario,
            release_schedule(self.scenario),
            self._preshift_moves,
            at_minute,
        )
        return state

    def live_projection(self, at_minute: int) -> Projection:
        state = self._live_state(at_minute)
        return project_from_state(state, self.scenario, self._preshift_moves)

    def ladder(self, at_minute: int) -> Recommendation:
        if at_minute <= 0:
            return self.preshift_ladder()
        state = self._live_state(at_minute)
        return recommend(self.scenario, state.clone())

    # -- outcomes ----------------------------------------------------------
    def outcome(self, intervention: str) -> NightResult:
        moves = self._preshift_moves if intervention == "preshift_moves" else ()
        if intervention == "preshift_moves":
            self.preshift_ladder()
            moves = self._preshift_moves
        return run(self.scenario, moves=moves)

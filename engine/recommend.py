"""The copilot's decision ladder (SCENARIO.md section 6).

1. Internal rebalancing. Donor practice, in order: ask Picking first;
   lend across the three Consolidacion sub-areas (Induct, Put, Pack);
   borrow from Shipping. Among available sources, the one with the most
   slack goes first. A move costs RELOCATE_MINUTES at zero production.

   Declared efficiency assumptions for movers at their destination:
   intra-Consolidacion 1.00; cross-area 0.85 (the sheet's cases are
   Picking -> Consolidacion and Shipping -> Consolidacion, both 0.85;
   v1 applies 0.85 to any cross-area move).

   A source has slack if, after donating, its remaining capacity still
   covers the items that still need it (totals over the remaining shift;
   the simulation itself remains the source of truth for OTS). Shipping
   has no rate in the sheet, so v1 caps Shipping lending at
   SHIPPING_MAX_LEND total associates -- conservative, declared.

2. If the projected OTS is still below 99% after every beneficial move,
   compute the shortfall at the binding node and draft the posting:
   people x hours, integers derived from the deficit math
   (shortfall items / node rate = associate-hours; posted in blocks of
   POSTING_BLOCK_HOURS).

The analytic deficit/slack helpers below are the planning layer: they
work on capacities and cumulative demand checkpoints and do not model
stoppage timing. The simulation (via project.py) is the source of truth
for OTS and for whether a move actually helps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .generate import release_schedule
from .model import (
    CONSOLIDACION,
    NODE_ORDER,
    OTS_TARGET,
    RELOCATE_MINUTES,
    SHIFT_MINUTES,
    Move,
    Scenario,
)
from .project import Projection, project_from_state
from .simulate import SimState, initial_state

EFFICIENCY_INTRA_CONSOLIDACION = 1.00
EFFICIENCY_CROSS_AREA = 0.85
DONOR_GROUPS = (("Picking",), CONSOLIDACION, ("Shipping",))
RATE_NODES = ("Picking", "Induct", "Put", "Pack")
SHIPPING_MAX_LEND = 2
POSTING_BLOCK_HOURS = 5
MAX_MOVES = 12
MIN_GAIN_PP = 0.05  # percentage points of projected night OTS


@dataclass(frozen=True)
class PostingDraft:
    area: str
    people: int
    hours: int
    reason: str


@dataclass(frozen=True)
class Recommendation:
    moves: tuple[Move, ...]
    baseline: Projection  # projection before any move
    projected: Projection  # projection after the recommended moves
    posting: PostingDraft | None
    binding_node: str


def move_factor(source: str, dest: str) -> float:
    if source in CONSOLIDACION and dest in CONSOLIDACION:
        return EFFICIENCY_INTRA_CONSOLIDACION
    return EFFICIENCY_CROSS_AREA


# --- analytic helpers (planning layer; the simulation is the OTS truth) ---


def _items_still_needing(state: SimState, scenario: Scenario, name: str) -> float:
    """Items that still must pass through `name`: unreleased orders plus
    mass queued at `name` or upstream of it."""
    schedule = release_schedule(scenario)
    total = sum(o.size for o in schedule[state.next_release :])
    for node_name in NODE_ORDER:
        if node_name == name:
            total += sum(state.queues[node_name])
            break
        # Queued there, plus processed mass staged at its stopped link:
        # both still have to pass through `name`.
        total += sum(state.queues[node_name]) + sum(state.buffers[node_name])
    return total


def _cumulative_capacity(
    state: SimState, scenario: Scenario, moves: tuple[Move, ...], name: str
) -> list[float]:
    """cum[m] = items `name` can process from state.minute up to minute m,
    honoring current staffing, movers in transit, and candidate moves."""
    rate = scenario.node(name).rate_per_hour
    now = state.minute
    cum = [0.0] * (SHIFT_MINUTES + 1)
    running = 0.0
    for m in range(now, SHIFT_MINUTES):
        eff = float(state.present[name]) + state.extra_eff[name]
        for arrival, dest, e in state.transit:
            if dest == name and arrival <= m:
                eff += e
        for mv in moves:
            if mv.source == name and mv.at_minute <= m:
                eff -= mv.people
            if mv.dest == name and mv.at_minute + RELOCATE_MINUTES <= m:
                eff += mv.factor * mv.people
        running += eff * rate / 60.0
        cum[m + 1] = running
    for m in range(now):
        cum[m] = 0.0
    return cum


def node_deficit(
    state: SimState, scenario: Scenario, moves: tuple[Move, ...], name: str
) -> float:
    """Worst cumulative shortfall (items) at `name` over the remaining
    shift: max over cutoff checkpoints of (items due by then that still
    need `name`) - (capacity from now to then). 0 if never short."""
    if scenario.node(name).rate_per_hour <= 0:
        return 0.0
    # Remaining items still needing `name`, split by cutoff.
    schedule = release_schedule(scenario)
    remaining = [0.0] * len(scenario.cuts)
    for order in schedule[state.next_release :]:
        remaining[order.cut_index] += order.size
    position = NODE_ORDER.index(name)
    for node_name in NODE_ORDER[:position]:
        for k, mass in enumerate(state.queues[node_name]):
            remaining[k] += mass
        for k, mass in enumerate(state.buffers[node_name]):
            remaining[k] += mass
    for k, mass in enumerate(state.queues[name]):
        remaining[k] += mass
    cum_cap = _cumulative_capacity(state, scenario, moves, name)
    worst = sum(remaining) - cum_cap[SHIFT_MINUTES]
    due = 0.0
    for k, cut in enumerate(scenario.cuts):
        due += remaining[k]
        if cut.minute >= state.minute:
            worst = max(worst, due - cum_cap[cut.minute])
    return max(0.0, worst)


def _source_slack(
    state: SimState,
    scenario: Scenario,
    moves: tuple[Move, ...],
    source: str,
    already_lent: dict[str, int],
) -> float:
    """Items of capacity `source` can give up and still cover the items
    that still need it. For Shipping (no rate), returns a large sentinel
    if it may still lend under the declared cap, else 0."""
    if source == "Shipping":
        return 1e18 if already_lent.get("Shipping", 0) < SHIPPING_MAX_LEND else 0.0
    capacity = _cumulative_capacity(state, scenario, moves, source)[SHIFT_MINUTES]
    return capacity - _items_still_needing(state, scenario, source)


def recommend(
    scenario: Scenario, state: SimState | None = None
) -> Recommendation:
    """Run the decision ladder from `state` (default: pre-shift, minute 0,
    with the scenario's known absences applied)."""
    if state is None:
        state = initial_state(scenario)

    baseline = project_from_state(state, scenario, ())
    moves: list[Move] = []
    current = baseline

    for _ in range(MAX_MOVES):
        binding = max(
            RATE_NODES, key=lambda n: node_deficit(state, scenario, tuple(moves), n)
        )
        if (
            node_deficit(state, scenario, tuple(moves), binding) <= 0.0
            and current.night_ots >= OTS_TARGET
        ):
            break
        already_lent: dict[str, int] = {}
        for mv in moves:
            already_lent[mv.source] = already_lent.get(mv.source, 0) + mv.people

        chosen: Move | None = None
        chosen_projection: Projection | None = None
        for group in DONOR_GROUPS:
            sources = [
                s
                for s in group
                if s != binding
                and _source_slack(state, scenario, tuple(moves), s, already_lent) > 0.0
            ]
            sources.sort(
                key=lambda s: -_source_slack(
                    state, scenario, tuple(moves), s, already_lent
                )
            )
            best_gain = MIN_GAIN_PP
            for source in sources:
                candidate = Move(
                    source=source,
                    dest=binding,
                    people=1,
                    at_minute=state.minute,
                    factor=move_factor(source, binding),
                )
                trial = project_from_state(
                    state, scenario, tuple(moves) + (candidate,)
                )
                gain = trial.night_ots - current.night_ots
                if gain >= best_gain:
                    best_gain = gain
                    chosen = candidate
                    chosen_projection = trial
            if chosen is not None:
                break  # first donor group with a beneficial move wins
        if chosen is None or chosen_projection is None:
            break
        moves.append(chosen)
        current = chosen_projection

    binding = max(
        RATE_NODES, key=lambda n: node_deficit(state, scenario, tuple(moves), n)
    )

    posting: PostingDraft | None = None
    if current.night_ots < OTS_TARGET:
        rate = scenario.node(binding).rate_per_hour
        shortfall = node_deficit(state, scenario, tuple(moves), binding)
        if shortfall <= 0.0:
            # Timing-driven lateness with no totals deficit at the binding
            # node: fall back to the projected late item count.
            shortfall = (100.0 - current.night_ots) / 100.0 * scenario.volume
        assoc_hours = shortfall / rate
        remaining_hours = max(1, math.ceil((SHIFT_MINUTES - state.minute) / 60))
        hours = min(POSTING_BLOCK_HOURS, remaining_hours)
        people = max(1, math.ceil(assoc_hours / hours - 1e-9))
        reason = (
            f"Projected OTS {current.night_ots:.1f}% stays below the 99% target "
            f"after internal rebalancing; {binding} is short ~{shortfall:,.0f} items "
            f"(~{assoc_hours:.1f} associate-hours at {rate:.0f} items/hour)."
        )
        posting = PostingDraft(area=binding, people=people, hours=hours, reason=reason)

    return Recommendation(
        moves=tuple(moves),
        baseline=baseline,
        projected=current,
        posting=posting,
        binding_node=binding,
    )

"""Acceptance tests for the Shift Copilot engine (v1).

Every expected figure traces to SCENARIO.md.
"""

import pytest

from engine.generate import generate_orders, release_schedule
from engine.model import Move, clean_scenario, demo_scenario
from engine.project import project_preshift
from engine.recommend import recommend
from engine.simulate import advance, initial_state, run

SHEET_UNITS = [4000, 6000, 8000, 14000, 12000, 11000, 13000, 12000, 7000, 6000, 4000, 3000]
SHEET_CAPACITIES = {"Picking": 101017, "Induct": 105600, "Put": 103125, "Pack": 102850}


# (a) A clean night -- full roster, no stoppages -- is a perfect night.
def test_clean_night_ots_is_100():
    result = run(clean_scenario(), with_alerts=False)
    assert result.night_ots == pytest.approx(100.0, abs=1e-6)
    assert all(ots == pytest.approx(100.0, abs=1e-6) for ots in result.per_cut_ots)


# (b) The demo night is in trouble before it starts, and the alert fires.
def test_demo_preshift_projection_below_100_and_alert_fires():
    scenario = demo_scenario()
    projection = project_preshift(scenario)
    assert projection.night_ots < 100.0
    assert projection.night_ots < 99.0  # below target: pre-shift alert

    result = run(scenario)
    assert result.first_alert_minute is not None
    assert result.first_alert_minute == 0  # already visible pre-shift
    assert all(projected < 99.0 for _, projected in result.alerts)


# (c) The ladder helps: pre-shift, moves alone lift the projection above
# the 99% target (no posting needed). Mid-shift, once the first stoppage
# is detected, moves are no longer enough and a posting is drafted.
def test_recommended_moves_improve_projection():
    rec = recommend(demo_scenario())
    assert rec.moves, "expected at least one recommended move"
    assert rec.projected.night_ots > rec.baseline.night_ots
    assert rec.projected.night_ots >= 99.0
    assert rec.posting is None


def test_midshift_ladder_drafts_posting_when_moves_are_not_enough():
    scenario = demo_scenario()
    rec = recommend(scenario)
    state = initial_state(scenario)
    advance(state, scenario, release_schedule(scenario), rec.moves, 165)
    live = recommend(scenario, state)
    assert live.projected.night_ots < 99.0
    assert live.posting is not None
    assert live.posting.area in ("Picking", "Induct", "Put", "Pack")
    assert live.posting.people >= 1
    assert live.posting.hours >= 1


# (d) The generator is deterministic and respects the sheet.
def test_generator_determinism_and_ranges():
    scenario = demo_scenario()
    generate_orders.cache_clear()
    first = generate_orders(scenario)
    generate_orders.cache_clear()
    second = generate_orders(scenario)
    assert first == second
    assert repr(first) == repr(second)  # byte-identical stream

    assert sum(o.size for o in first) == scenario.volume
    assert all(1 <= o.size <= 250 for o in first)

    # Order-count shares track the sheet's shares within sampling noise
    # (counts are a consequence of the drawn sizes; the sheet's shares
    # bind items, which are matched exactly below).
    total_orders = len(first)
    for cut_index, cut in enumerate(scenario.cuts):
        count = sum(1 for o in first if o.cut_index == cut_index)
        assert abs(count / total_orders - cut.share) <= 0.015

    # Per-cutoff item totals match the sheet's Units column exactly.
    for cut_index, units in enumerate(SHEET_UNITS):
        items = sum(o.size for o in first if o.cut_index == cut_index)
        assert items == units


# (e) Planned-staff capacity per node matches the sheet's table.
def test_planned_capacity_matches_sheet():
    scenario = demo_scenario()
    for name, expected in SHEET_CAPACITIES.items():
        assert scenario.planned_capacity(name) == pytest.approx(expected, abs=1.0)


# Extra: mass is conserved through a full night, and the sheet's absence
# capacities hold in the planning layer (Picking 96,662 / Pack 99,825).
def test_mass_conservation_and_absence_capacities():
    scenario = demo_scenario()
    assert scenario.present_capacity("Picking") == pytest.approx(96662, abs=1.0)
    assert scenario.present_capacity("Pack") == pytest.approx(99825, abs=1.0)

    state = initial_state(scenario)
    advance(state, scenario, release_schedule(scenario), (), 600)
    in_queues = sum(sum(q) for q in state.queues.values())
    in_buffers = sum(sum(b) for b in state.buffers.values())
    assert sum(state.cleared) + in_queues + in_buffers == pytest.approx(
        scenario.volume, abs=1e-6
    )
    assert all(o <= c + 1e-9 for o, c in zip(state.ontime, state.cleared))


# Extra: moving a person costs exactly 10 minutes at zero production.
def test_move_costs_ten_minutes():
    scenario = clean_scenario()
    schedule = release_schedule(scenario)
    move = Move(source="Induct", dest="Pack", people=2, at_minute=0, factor=1.0)

    state = initial_state(scenario)
    advance(state, scenario, schedule, (move,), 5)
    assert state.present["Induct"] == 22  # departed immediately
    assert state.extra_eff["Pack"] == 0.0  # still relocating: no production

    advance(state, scenario, schedule, (move,), 11)
    assert state.extra_eff["Pack"] == 2.0  # producing from minute 10 on


# Extra: the realized demo night is worse than the clean night, and the
# pre-shift moves improve the realized outcome too.
def test_demo_night_worse_than_clean_and_moves_help():
    clean = run(clean_scenario(), with_alerts=False)
    demo = run(demo_scenario(), with_alerts=False)
    assert demo.night_ots < clean.night_ots

    rec = recommend(demo_scenario())
    helped = run(demo_scenario(), moves=rec.moves, with_alerts=False)
    assert helped.night_ots > demo.night_ots

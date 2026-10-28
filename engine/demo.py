"""Demo CLI: run the sheet's night and print what the copilot sees and does.

    python3 -m engine.demo

Prints the pre-shift projection and decision ladder, the second ladder
run when the first stoppage is detected mid-shift, and the night's
outcome with and without the pre-shift intervention (per-cutoff OTS
table, night OTS, and when the live alert fired).
"""

from __future__ import annotations

from .generate import release_schedule
from .model import demo_scenario
from .project import project_from_state, project_preshift
from .recommend import recommend
from .simulate import advance, initial_state, run

DETECTION_MINUTE = 165  # stoppage 1 starts at 150; area no-scan signal at +15


def _clock(minute: int) -> str:
    """Minute offset from 17:30 -> wall-clock label."""
    total = 17 * 60 + 30 + minute
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def _print_ladder(title: str, rec) -> None:
    print(f"\n{title} -- binding node: {rec.binding_node}")
    if rec.moves:
        print("Recommended moves (10 min relocation cost each):")
        for mv in rec.moves:
            print(
                f"  - {mv.source} -> {mv.dest}: {mv.people} person(s) "
                f"at minute {mv.at_minute}, efficiency x{mv.factor:.2f}"
            )
    else:
        print("Recommended moves: none beneficial.")
    print(
        f"Projected night OTS: {rec.baseline.night_ots:.1f}% -> "
        f"{rec.projected.night_ots:.1f}% after moves"
    )
    if rec.posting is not None:
        p = rec.posting
        print(f"Posting draft: {p.area} -- {p.people} people x {p.hours} hours")
        print(f"  Reason: {p.reason}")
    else:
        print("Posting draft: none -- internal rebalancing covers the projection.")


def main() -> None:
    scenario = demo_scenario()
    planned_total = sum(n.planned_staff for n in scenario.nodes)
    present_total = planned_total - sum(dict(scenario.absences).values())

    print("=== Shift Copilot -- demo night (100,000 units, synthetic) ===")
    print(
        f"Absences: Picking -{scenario.absence('Picking')}, "
        f"Pack -{scenario.absence('Pack')} "
        f"({present_total} of {planned_total} present)"
    )
    print(
        "Stoppages (not known in advance): Picking->Induct 20:00-20:40, "
        "Pack->Shipping 00:30-01:15 (declared in engine/model.py)"
    )

    preshift = project_preshift(scenario)
    print(
        f"\nPre-shift projection (volume + roster + known absences): "
        f"night OTS {preshift.night_ots:.1f}%"
    )
    if preshift.night_ots < 99.0:
        print("-> ALERT before the shift starts: projected OTS below 99%.")

    rec = recommend(scenario)
    _print_ladder("Decision ladder, pre-shift", rec)

    # Mid-shift: the first stoppage has started and the area-level
    # no-scan signal has detected it; re-run the ladder from the live state.
    live_state = initial_state(scenario)
    advance(live_state, scenario, release_schedule(scenario), rec.moves, DETECTION_MINUTE)
    live_projection = project_from_state(live_state, scenario, rec.moves)
    print(
        f"\nMinute {DETECTION_MINUTE} ({_clock(DETECTION_MINUTE)}): the "
        f"Picking->Consolidacion line is detected stopped (no scans from "
        f"Induct). Live projection: night OTS {live_projection.night_ots:.1f}%."
    )
    rec_live = recommend(scenario, live_state.clone())
    _print_ladder("Decision ladder, mid-shift", rec_live)

    for label, moves in (("no intervention", ()), ("with pre-shift moves", rec.moves)):
        result = run(scenario, moves=moves)
        print(f"\n--- Night outcome, {label} ---")
        print(f"{'Cutoff':<8}{'Items':>9}{'OTS %':>9}")
        for cut, pool, ots in zip(scenario.cuts, result.pools, result.per_cut_ots):
            print(f"{cut.label:<8}{pool:>9,.0f}{ots:>9.1f}")
        print(f"Night OTS: {result.night_ots:.1f}%")
        if result.alerts:
            first = result.first_alert_minute
            print(
                f"Live alert first fired at minute {first} "
                f"({_clock(first or 0)}), projected OTS "
                f"{result.alerts[0][1]:.1f}% at that check "
                f"({len(result.alerts)} alert checks in total)."
            )
        else:
            print("Live alert: never fired.")


if __name__ == "__main__":
    main()

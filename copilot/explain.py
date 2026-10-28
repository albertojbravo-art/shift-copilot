"""Templated explanations: the copilot's voice when no model is available.

The degradation path is a design requirement, not an afterthought: if the
model API is down, the copilot still briefs the lead with the engine's own
words. Every figure here comes straight from an engine result object.
"""

from __future__ import annotations

from .session import DETECTION_MINUTE, NightSession, clock


def preshift_brief(s: NightSession) -> str:
    p = s.preshift_projection()
    sc = s.scenario
    lines = [
        f"Tonight: {sc.volume:,} units, {sum(n.planned_staff for n in sc.nodes)} planned, "
        f"Picking -{sc.absence('Picking')} and Pack -{sc.absence('Pack')} absent.",
        f"Pre-shift projection: night OTS {p.night_ots:.1f}% against the 99.0% target.",
    ]
    if p.night_ots < 99.0:
        lines.append("That projection is an alert: the night starts short, before anything goes wrong.")
    return "\n".join(lines)


def ladder_brief(s: NightSession, at_minute: int) -> str:
    rec = s.ladder(at_minute)
    where = "before the shift" if at_minute <= 0 else f"at {clock(at_minute)}"
    lines = [
        f"Decision ladder {where} — binding node: {rec.binding_node}.",
        f"Projected night OTS: {rec.baseline.night_ots:.1f}% before moves, "
        f"{rec.projected.night_ots:.1f}% after.",
    ]
    if rec.moves:
        lines.append("Recommended moves (10 min relocation cost each):")
        for mv in rec.moves:
            lines.append(
                f"  - {mv.source} -> {mv.dest}: {mv.people} person(s) "
                f"at {clock(mv.at_minute)}, efficiency x{mv.factor:.2f}"
            )
    else:
        lines.append("No internal move improves the projection.")
    if rec.posting is not None:
        p = rec.posting
        lines.append(
            f"Internal slack is not enough: draft posting — {p.area}, "
            f"{p.people} people x {p.hours} hours. {p.reason}"
        )
    else:
        lines.append("No posting needed: internal rebalancing covers the projection.")
    return "\n".join(lines)


def live_brief(s: NightSession, at_minute: int = DETECTION_MINUTE) -> str:
    p = s.live_projection(at_minute)
    return (
        f"At {clock(at_minute)} the aggregate no-scan signal flags the "
        f"Picking -> Consolidation line as stopped. Live projection: night OTS "
        f"{p.night_ots:.1f}% against the 99.0% target.\n"
        + ladder_brief(s, at_minute)
    )


def fallback_answer(s: NightSession, question: str) -> str:
    """Route a question to the closest template. Used when the model is down."""
    q = question.lower()
    if any(w in q for w in ("post", "hire", "extra staff", "short")):
        return live_brief(s)
    if any(w in q for w in ("stoppage", "stopped", "line", "scan")):
        return live_brief(s)
    if any(w in q for w in ("move", "rebalance", "ladder", "recommend")):
        return preshift_brief(s) + "\n" + ladder_brief(s, 0)
    return preshift_brief(s) + "\n" + ladder_brief(s, 0)

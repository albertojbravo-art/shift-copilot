"""Tool definitions and dispatch: how the language model calls the engine.

The model never produces figures. It calls these tools; the engine
computes; the tool result is the only source of numbers in the
conversation. Schemas follow the OpenAI chat-completions tools format,
which the Baseten endpoint for Muse Spark Open accepts (verified
2026-10-27).
"""

from __future__ import annotations

import json

from .session import NightSession, clock

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "preshift_projection",
            "description": (
                "Project tonight's on-time shipping (OTS) before the shift starts, "
                "from the day volume, the roster and the known absences. Returns "
                "the projected night OTS percent and the projection per cutoff."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "live_projection",
            "description": (
                "Project tonight's OTS from the live state at a given minute of "
                "the shift (0 = 17:30, 600 = 03:30), given everything that has "
                "happened up to that minute, including any stoppage already "
                "detected. Assumes the pre-shift recommended moves were accepted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "at_minute": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 600,
                        "description": "Minutes after 17:30.",
                    }
                },
                "required": ["at_minute"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decision_ladder",
            "description": (
                "Run the copilot's decision ladder at a minute of the shift "
                "(0 = before the shift). Returns the binding (limiting) node, "
                "the recommended staffing moves with their relocation cost, the "
                "projected night OTS before and after the moves, and — only when "
                "the moves cannot restore the 99% target — a draft extra-staff "
                "posting (area, people, hours, reason)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "at_minute": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 600,
                        "description": "Minutes after 17:30; 0 means pre-shift.",
                    }
                },
                "required": ["at_minute"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "night_outcome",
            "description": (
                "The realized night: per-cutoff OTS and night OTS, with no "
                "intervention or with the pre-shift ladder moves applied."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention": {
                        "type": "string",
                        "enum": ["none", "preshift_moves"],
                    }
                },
                "required": ["intervention"],
            },
        },
    },
]


def _per_cut(session: NightSession, values) -> list[dict]:
    return [
        {"cutoff": cut.label, "ots_percent": round(v, 1)}
        for cut, v in zip(session.scenario.cuts, values)
    ]


def _ladder_dict(session: NightSession, rec) -> dict:
    out = {
        "binding_node": rec.binding_node,
        "moves": [
            {
                "from": mv.source,
                "to": mv.dest,
                "people": mv.people,
                "at_minute": mv.at_minute,
                "at_clock": clock(mv.at_minute),
                "efficiency_factor": mv.factor,
                "relocation_cost_minutes": 10,
            }
            for mv in rec.moves
        ],
        "projected_ots_before_percent": round(rec.baseline.night_ots, 1),
        "projected_ots_after_percent": round(rec.projected.night_ots, 1),
        "posting": None,
    }
    if rec.posting is not None:
        out["posting"] = {
            "area": rec.posting.area,
            "people": rec.posting.people,
            "hours": rec.posting.hours,
            "reason": rec.posting.reason,
        }
    return out


def dispatch(session: NightSession, name: str, arguments: dict) -> dict:
    """Execute one tool call against the engine. Returns a JSON-able dict."""
    if name == "preshift_projection":
        p = session.preshift_projection()
        return {
            "night_ots_percent": round(p.night_ots, 1),
            "target_percent": 99.0,
            "alert": p.night_ots < 99.0,
            "per_cutoff": _per_cut(session, p.per_cut_ots),
        }
    if name == "live_projection":
        m = int(arguments["at_minute"])
        p = session.live_projection(m)
        return {
            "at_minute": m,
            "at_clock": clock(m),
            "night_ots_percent": round(p.night_ots, 1),
            "target_percent": 99.0,
            "alert": p.night_ots < 99.0,
            "per_cutoff": _per_cut(session, p.per_cut_ots),
        }
    if name == "decision_ladder":
        m = int(arguments["at_minute"])
        return {"at_minute": m, "at_clock": clock(m), **_ladder_dict(session, session.ladder(m))}
    if name == "night_outcome":
        r = session.outcome(arguments["intervention"])
        return {
            "intervention": arguments["intervention"],
            "night_ots_percent": round(r.night_ots, 1),
            "first_alert_minute": r.first_alert_minute,
            "first_alert_clock": clock(r.first_alert_minute) if r.first_alert_minute is not None else None,
            "per_cutoff": _per_cut(session, r.per_cut_ots),
        }
    raise ValueError(f"unknown tool: {name}")


def dispatch_json(session: NightSession, name: str, arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        args = {}
    return json.dumps(dispatch(session, name, args))

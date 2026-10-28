"""Core data model for the Shift Copilot simulation engine.

All figures trace to SCENARIO.md (the scenario sheet). The sheet is the
specification; where a derived number is needed, it is computed here from the
sheet's primary data (rates, planned staff, cut shares, volume).

Breaks -- declared modeling choice
----------------------------------
Each associate takes two breaks (30 + 20 = 50 min), staggered across the
shift, i.e. 9.1667 effective hours per associate per shift
(EFFECTIVE_HOURS). Breaks enter the model through the *planning* layer:
planned capacity = staff x rate x EFFECTIVE_HOURS. That identity is what
derives the staffing table, the capacity table (SCENARIO.md section 2) and
the posting shortfall math.

The minute-step fluid dynamics in simulate.py run at the staffed team rate
(present staff x rate). Reason, stated plainly: with the 11/12 break factor
also applied minute-by-minute, cumulative capacity at minute 480 would be
80,813 items against 87,000 items due by the 01:30 cutoff -- no clean night
could ever reach the sheet's 99% OTS metric, which contradicts the sheet
itself (planned staff is derived so the night is feasible). The staggered
break cost is therefore paid once, in the staffing derivation, not twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SHIFT_MINUTES = 600  # 17:30 -> 03:30
BREAK_MINUTES = 50  # 30 + 20 per associate, staggered
EFFECTIVE_HOURS = (SHIFT_MINUTES - BREAK_MINUTES) / 60.0  # 9.1667
OTS_TARGET = 99.0  # percent; alert fires when projected OTS falls below this
RELOCATE_MINUTES = 10  # moving one person costs 10 min at zero production

# Chain order. Shipping is pure outflow (no per-associate rate).
NODE_ORDER = ("Picking", "Induct", "Put", "Pack", "Shipping")
CONSOLIDACION = ("Induct", "Put", "Pack")
# Flow links of the chain, upstream -> downstream.
LINKS = (
    ("Picking", "Induct"),
    ("Induct", "Put"),
    ("Put", "Pack"),
    ("Pack", "Shipping"),
)


def next_node(name: str) -> str | None:
    """Node downstream of `name`, or None for Shipping."""
    idx = NODE_ORDER.index(name)
    return NODE_ORDER[idx + 1] if idx + 1 < len(NODE_ORDER) else None


@dataclass(frozen=True)
class Node:
    """One stage of the chain. rate_per_hour is items per associate per hour
    (0.0 for Shipping, which has no per-associate rate)."""

    name: str
    rate_per_hour: float
    planned_staff: int


@dataclass(frozen=True)
class Cut:
    """A cutoff time. `minute` is the offset in minutes from 17:30 (shift
    start). `share` is the fraction of the night's items born assigned to
    this cutoff."""

    label: str
    minute: int
    share: float


@dataclass(frozen=True)
class Stoppage:
    """A stopped line: no flow across `link` during [start, end) minutes."""

    link: tuple[str, str]
    start: int
    end: int  # exclusive

    @property
    def minutes(self) -> int:
        return self.end - self.start

    def active_at(self, minute: int) -> bool:
        return self.start <= minute < self.end


@dataclass(frozen=True)
class Move:
    """Relocate `people` associates from `source` to `dest` at `at_minute`.

    The movers leave the source at `at_minute` and produce nothing for
    RELOCATE_MINUTES (they are relocating); on arrival they add
    `factor` x people effective staff to the destination. `factor` is the
    cross-area efficiency of the move (declared synthetic assumption, see
    recommend.py).
    """

    source: str
    dest: str
    people: int
    at_minute: int = 0
    factor: float = 1.0


@dataclass(frozen=True)
class Scenario:
    """Everything that defines one simulated night."""

    volume: int
    nodes: tuple[Node, ...]
    cuts: tuple[Cut, ...]
    absences: tuple[tuple[str, int], ...] = ()
    stoppages: tuple[Stoppage, ...] = ()
    seed: int = 20261027

    def node(self, name: str) -> Node:
        for n in self.nodes:
            if n.name == name:
                return n
        raise KeyError(name)

    def absence(self, name: str) -> int:
        return dict(self.absences).get(name, 0)

    def present_staff(self, name: str) -> int:
        """Planned staff minus known absences."""
        return self.node(name).planned_staff - self.absence(name)

    def planned_capacity(self, name: str) -> float:
        """Sheet section 2: planned staff x rate x 9.1667 effective hours."""
        n = self.node(name)
        return n.planned_staff * n.rate_per_hour * EFFECTIVE_HOURS

    def present_capacity(self, name: str) -> float:
        """Capacity with known absences removed (same planning identity)."""
        n = self.node(name)
        return self.present_staff(name) * n.rate_per_hour * EFFECTIVE_HOURS


# --- The demo night (SCENARIO.md) -------------------------------------------
# Declared design detail (sheet section 5): exact stoppage times are fixed
# here and recorded here.
#   Stoppage 1: Picking -> Consolidacion line (the Picking -> Induct link),
#               minutes 150-190 (20:00-20:40), first half.
#   Stoppage 2: Consolidacion -> Shipping line (the Pack -> Shipping link),
#               minutes 420-465 (00:30-01:15), second half.

STOPPAGE_1 = Stoppage(link=("Picking", "Induct"), start=150, end=190)
STOPPAGE_2 = Stoppage(link=("Pack", "Shipping"), start=420, end=465)

_DEMO_CUTS = (
    # label, minute offset from 17:30, share of the night's items
    ("19:30", 120, 0.04),
    ("20:00", 150, 0.06),
    ("20:30", 180, 0.08),
    ("21:30", 240, 0.14),
    ("22:15", 285, 0.12),
    ("22:58", 328, 0.11),
    ("23:51", 381, 0.13),
    ("01:01", 451, 0.12),
    ("01:30", 480, 0.07),
    ("02:28", 538, 0.06),
    ("03:12", 582, 0.04),
    ("03:30", 600, 0.03),
)

_DEMO_NODES = (
    Node("Picking", 95.0, 116),
    Node("Induct", 480.0, 24),
    Node("Put", 250.0, 45),
    Node("Pack", 110.0, 102),
    Node("Shipping", 0.0, 18),
)


def demo_scenario() -> Scenario:
    """The sheet's night: 100,000 units, absences Picking -5 / Pack -3,
    two stoppages (see above)."""
    return Scenario(
        volume=100_000,
        nodes=_DEMO_NODES,
        cuts=tuple(Cut(label, minute, share) for label, minute, share in _DEMO_CUTS),
        absences=(("Picking", 5), ("Pack", 3)),
        stoppages=(STOPPAGE_1, STOPPAGE_2),
        seed=20261027,
    )


def clean_scenario() -> Scenario:
    """The same night with the tension removed: full roster, no stoppages."""
    base = demo_scenario()
    return Scenario(
        volume=base.volume,
        nodes=base.nodes,
        cuts=base.cuts,
        absences=(),
        stoppages=(),
        seed=base.seed,
    )


def ceil_div(a: float, b: float) -> int:
    return int(math.ceil(a / b - 1e-9))

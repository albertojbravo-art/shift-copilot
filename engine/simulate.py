"""Minute-step fluid simulation of the chain.

Fluid approximation -- declared
--------------------------------
Work is modeled as fluid mass per cutoff bucket at each node, not as
individual orders. Each minute, a node processes up to
``effective staff x rate / 60`` items from its queue, serving buckets in
cutoff order (FIFO across buckets: because the generator releases orders in
cutoff-synchronized waves, bucket order matches release order). Processed
mass moves to the next node's queue and can be processed there from the
following minute (one-minute hop latency). An item counts as on-time for
its cutoff if it clears Pack during a minute ``t`` with ``t + 1 <= cutoff
minute``.

OTS is measured on item mass per cutoff and reported as the cutoff's /
night's OTS. Under the FIFO fluid discipline, the late mass of a bucket is
its last-released items, whose orders are a representative sample of the
bucket, so the late *item* fraction is the declared estimator of the late
*order* fraction (the sheet defines OTS on orders).

Stoppages: a stopped link blocks the *transfer* across it. The upstream
node keeps working into its out-buffer (staging), the downstream node
starves; when the link reopens, the buffer flushes downstream. Declared
v1 simplification: staging is unbounded, so a stoppage never destroys the
upstream node's capacity -- it delays flow. In particular, a stoppage on
Pack -> Shipping delays dispatch (visible as packed-but-undispatched
mass) but not Pack clearing, which is what the on-time rule judges;
in v1 it therefore does not move OTS. (A stoppage long enough to fill
real staging would back up into Pack; that is out of scope for v1.)

See model.py for the declared breaks treatment (planning layer).
"""

from __future__ import annotations

from dataclasses import dataclass

from .generate import Order, release_schedule
from .model import (
    NODE_ORDER,
    OTS_TARGET,
    RELOCATE_MINUTES,
    Move,
    Scenario,
    next_node,
)

PROCESS_ORDER = ("Pack", "Put", "Induct", "Picking")  # downstream first
ALERT_CHECK_EVERY = 15  # minutes between live projection checks


@dataclass
class SimState:
    """Mutable simulation state; project.py fast-forwards clones of it."""

    minute: int
    queues: dict[str, list[float]]  # node -> item mass per cutoff bucket
    buffers: dict[str, list[float]]  # node -> processed mass held at a stopped link
    present: dict[str, int]  # associates currently at the node
    extra_eff: dict[str, float]  # effective staff added by arrived movers
    transit: list[tuple[int, str, float]]  # (arrival minute, dest, eff staff)
    next_release: int  # pointer into the release schedule
    cleared: list[float]  # items cleared through Pack, per cutoff
    ontime: list[float]  # of those, items cleared by their cutoff
    packed_undispatched: float = 0.0  # packed mass held at a stopped Shipping link

    def clone(self) -> "SimState":
        return SimState(
            minute=self.minute,
            queues={n: list(q) for n, q in self.queues.items()},
            buffers={n: list(q) for n, q in self.buffers.items()},
            present=dict(self.present),
            extra_eff=dict(self.extra_eff),
            transit=list(self.transit),
            next_release=self.next_release,
            cleared=list(self.cleared),
            ontime=list(self.ontime),
            packed_undispatched=self.packed_undispatched,
        )

    def effective_staff(self, name: str) -> float:
        return self.present[name] + self.extra_eff[name]


@dataclass
class NightResult:
    per_cut_ots: tuple[float, ...]  # percent, per cutoff
    night_ots: float  # percent
    pools: tuple[float, ...]  # actual items per cutoff in the stream
    ontime: tuple[float, ...]
    cleared: tuple[float, ...]
    queue_trace: dict[str, list[float]]  # node -> total queue per minute 0..600
    staff_trace: dict[str, list[float]]  # node -> effective staff per minute
    alerts: list[tuple[int, float]]  # (minute, projected night OTS) below target

    @property
    def first_alert_minute(self) -> int | None:
        return self.alerts[0][0] if self.alerts else None


def initial_state(scenario: Scenario) -> SimState:
    n_cuts = len(scenario.cuts)
    return SimState(
        minute=0,
        queues={name: [0.0] * n_cuts for name in NODE_ORDER},
        buffers={name: [0.0] * n_cuts for name in NODE_ORDER},
        present={n.name: scenario.present_staff(n.name) for n in scenario.nodes},
        extra_eff={name: 0.0 for name in NODE_ORDER},
        transit=[],
        next_release=0,
        cleared=[0.0] * n_cuts,
        ontime=[0.0] * n_cuts,
    )


def _moves_by_minute(moves: tuple[Move, ...]) -> dict[int, list[Move]]:
    out: dict[int, list[Move]] = {}
    for mv in moves:
        out.setdefault(mv.at_minute, []).append(mv)
    return out


def _step(
    state: SimState,
    scenario: Scenario,
    schedule: tuple[Order, ...],
    moves_by_minute: dict[int, list[Move]],
) -> None:
    t = state.minute

    # Movers arriving now join their destination (they produced nothing
    # while in transit: RELOCATE_MINUTES at zero production).
    still: list[tuple[int, str, float]] = []
    for arrival, dest, eff in state.transit:
        if arrival <= t:
            state.extra_eff[dest] += eff
        else:
            still.append((arrival, dest, eff))
    state.transit = still

    # Moves departing now leave their source.
    for mv in moves_by_minute.get(t, ()):
        state.present[mv.source] -= mv.people
        state.transit.append((t + RELOCATE_MINUTES, mv.dest, mv.factor * mv.people))

    # Order releases into Picking.
    while (
        state.next_release < len(schedule)
        and schedule[state.next_release].release_minute <= t
    ):
        order = schedule[state.next_release]
        state.queues["Picking"][order.cut_index] += order.size
        state.next_release += 1

    blocked = {s.link for s in scenario.stoppages if s.active_at(t)}

    # Packed goods dispatch instantly while the Shipping link is open.
    if ("Pack", "Shipping") not in blocked:
        state.packed_undispatched = 0.0

    for name in PROCESS_ORDER:
        nxt = next_node(name)
        link_blocked = (name, nxt) in blocked
        # A reopened link first flushes whatever staging accumulated.
        if not link_blocked and name != "Pack":
            buffer = state.buffers[name]
            if any(buffer):
                downstream = state.queues[nxt]
                for k in range(len(buffer)):
                    downstream[k] += buffer[k]
                    buffer[k] = 0.0
        rate = scenario.node(name).rate_per_hour
        cap = state.effective_staff(name) * rate / 60.0
        if cap <= 0.0:
            continue
        queue = state.queues[name]
        for k in range(len(queue)):
            if cap <= 0.0:
                break
            take = min(queue[k], cap)
            if take <= 0.0:
                continue
            queue[k] -= take
            cap -= take
            if name == "Pack":
                state.cleared[k] += take
                if t + 1 <= scenario.cuts[k].minute:
                    state.ontime[k] += take
                if link_blocked:
                    state.packed_undispatched += take
            elif link_blocked:
                state.buffers[name][k] += take  # staged at the stopped line
            else:
                state.queues[nxt][k] += take

    state.minute = t + 1


def advance(
    state: SimState,
    scenario: Scenario,
    schedule: tuple[Order, ...],
    moves: tuple[Move, ...],
    until: int,
) -> None:
    """Step `state` forward in place until state.minute == until."""
    by_minute = _moves_by_minute(moves)
    while state.minute < until:
        _step(state, scenario, schedule, by_minute)


def run(
    scenario: Scenario,
    moves: tuple[Move, ...] = (),
    horizon: int = 600,
    with_alerts: bool = True,
) -> NightResult:
    """Simulate a full night. If with_alerts, every ALERT_CHECK_EVERY
    minutes the remainder is projected (project.py) from a clone of the
    live state and an alert is recorded when the projected night OTS falls
    below the sheet's 99% target."""
    from .project import project_from_state  # deferred: avoids import cycle

    schedule = release_schedule(scenario)
    state = initial_state(scenario)
    pools = [0.0] * len(scenario.cuts)
    for order in schedule:
        pools[order.cut_index] += order.size

    queue_trace: dict[str, list[float]] = {name: [] for name in NODE_ORDER}
    staff_trace: dict[str, list[float]] = {name: [] for name in NODE_ORDER}
    alerts: list[tuple[int, float]] = []

    def record() -> None:
        for name in NODE_ORDER:
            queue_trace[name].append(
                sum(state.queues[name]) + sum(state.buffers[name])
            )
            staff_trace[name].append(state.effective_staff(name))

    by_minute = _moves_by_minute(moves)
    while state.minute < horizon:
        if with_alerts and state.minute % ALERT_CHECK_EVERY == 0:
            projection = project_from_state(state.clone(), scenario, moves)
            if projection.night_ots < OTS_TARGET:
                alerts.append((state.minute, projection.night_ots))
        record()
        _step(state, scenario, schedule, by_minute)
    record()

    per_cut_ots = tuple(
        100.0 * state.ontime[k] / pools[k] if pools[k] > 0 else 100.0
        for k in range(len(pools))
    )
    night_ots = 100.0 * sum(state.ontime) / sum(pools) if sum(pools) > 0 else 100.0
    return NightResult(
        per_cut_ots=per_cut_ots,
        night_ots=night_ots,
        pools=tuple(pools),
        ontime=tuple(state.ontime),
        cleared=tuple(state.cleared),
        queue_trace=queue_trace,
        staff_trace=staff_trace,
        alerts=alerts,
    )

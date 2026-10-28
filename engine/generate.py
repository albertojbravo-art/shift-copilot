"""Deterministic synthetic order stream.

Declared synthetic assumptions (SCENARIO.md section 1):

- Order sizes are 1..250 items, mostly small with a tail of large sale
  orders. Mixture used here: 95% of orders draw their size from a
  lognormal distribution (median ~5 items, clamped to 1..250); 5% are
  "sale" orders drawn uniformly from 60..250 items.
- Each order is born assigned to a cutoff. Per-cutoff *item* totals match
  the sheet's Units column exactly (largest-remainder apportionment of the
  volume across the sheet's shares): sizes are drawn per cutoff until the
  cutoff's target is met, and the cutoff's final order is sized to land
  exactly on the target (still within 1..250).
- Release curve: orders are released into Picking in cutoff order, paced
  at the Picking team's planned rate, with an 800-item head start -- the
  way a WMS waves work to the floor. The chain is therefore never starved
  while released work remains, and every order is released well before
  its cutoff (the last order of a cutoff leaves the gate at least ~100
  items of chain capacity ahead of its deadline in the demo scenario).

Same scenario seed -> byte-identical stream (the generator draws from a
single random.Random(seed) in a fixed order; release minutes are pure
arithmetic on the drawn sizes).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

from .model import Scenario

SALE_ORDER_PROB = 0.05
SALE_MIN, SALE_MAX = 60, 250
SIZE_CAP = 250
HEAD_START_ITEMS = 800  # released-ahead buffer of the pacing curve


@dataclass(frozen=True)
class Order:
    seq: int
    size: int  # items, 1..250
    cut_index: int
    release_minute: int


def _draw_size(rng: random.Random) -> int:
    if rng.random() < SALE_ORDER_PROB:
        return rng.randint(SALE_MIN, SALE_MAX)
    size = round(rng.lognormvariate(1.6, 0.75))
    return max(1, min(SIZE_CAP, size))


def _apportion(total: int, shares: tuple[float, ...]) -> list[int]:
    """Largest-remainder apportionment of `total` across `shares`."""
    raw = [total * s for s in shares]
    counts = [int(x) for x in raw]
    remainder = total - sum(counts)
    by_fraction = sorted(range(len(shares)), key=lambda i: (-(raw[i] - counts[i]), i))
    for i in by_fraction[:remainder]:
        counts[i] += 1
    return counts


def _cut_sizes(rng: random.Random, target_items: int) -> list[int]:
    """Order sizes for one cutoff, summing exactly to target_items."""
    sizes: list[int] = []
    remaining = target_items
    while remaining > SIZE_CAP:
        size = _draw_size(rng)
        sizes.append(size)
        remaining -= size
    if remaining > 0:
        sizes.append(remaining)  # final order sized to land on the target
    return sizes


@lru_cache(maxsize=8)
def generate_orders(scenario: Scenario) -> tuple[Order, ...]:
    """The night's full order stream, in generation order (by cutoff)."""
    rng = random.Random(scenario.seed)
    targets = _apportion(scenario.volume, tuple(c.share for c in scenario.cuts))
    picking = scenario.node("Picking")
    pace_per_minute = picking.planned_staff * picking.rate_per_hour / 60.0

    orders: list[Order] = []
    seq = 0
    cumulative_items = 0
    for cut_index, target in enumerate(targets):
        for size in _cut_sizes(rng, target):
            ahead = cumulative_items - HEAD_START_ITEMS
            release = int(ahead / pace_per_minute) if ahead > 0 else 0
            orders.append(
                Order(seq=seq, size=size, cut_index=cut_index, release_minute=release)
            )
            seq += 1
            cumulative_items += size
    assert cumulative_items == scenario.volume
    return tuple(orders)


def release_schedule(scenario: Scenario) -> tuple[Order, ...]:
    """The stream sorted for simulation: by (release_minute, seq)."""
    return tuple(sorted(generate_orders(scenario), key=lambda o: (o.release_minute, o.seq)))

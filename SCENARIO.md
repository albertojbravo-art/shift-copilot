# The demo night — scenario sheet

All data is **synthetic**. Every figure below is derived from the stated rates and
assumptions, and can be checked by hand. The engine's executable scenario must match
this sheet; where they ever disagree, the sheet is the specification and the engine
has a bug.

## Inputs

- **Day volume: 100,000 units** (an input, not a constant of the engine; a peak day
  can be 150,000).
- **Shift:** 17:30–03:30 (10 hours).
- **Orders:** 1 to 250 items each. Size distribution is a declared synthetic
  assumption: mostly small orders, with a tail of large sale orders (cap 250).
  Deterministic generator, fixed seed, identical on every demo run.
- **Chain:** an order is born assigned to a cutoff time → Picking → Induct → Put →
  Pack → Shipping (pure outflow: it counts dispatches per cutoff, no per-associate rate).

## Rates and derived staffing

Validated rates (items per associate per hour): **Picking 95 · Induct 480 · Put 250 ·
Pack 110**. Each associate takes two breaks (30 and 20 min), staggered:
**9.1667 effective hours** per associate per shift.

| Area | Rate | Exact need | Planned staff | Planned capacity |
|---|---|---|---|---|
| Picking | 95 | 114.83 | **116** | 101,017 (+1,017) |
| Induct | 480 | 22.73 | **24** | 105,600 (+5,600) |
| Put | 250 | 43.64 | **45** | 103,125 (+3,125) |
| Pack | 110 | 99.17 | **102** | 102,850 (+2,850) |
| Shipping | — | — | **18** | pure outflow |
| **Total** | | | **305** | |

Staffing is derived from the rates, not the other way around: every area carries a
small positive slack. Pack is the natural bottleneck by headcount.

**Modeling note (declared):** the 9.1667 effective hours live in this planning layer —
they derive the staffing, the capacity table above, and the posting math. The engine's
minute-by-minute fluid dynamics run at the present crew's full rate; equivalently,
breaks are treated as scheduled outside the cutoff waves. With the breaks factor
applied minute by minute instead, no night could ever reach the 99% metric (the
front-loaded cutoff distribution requires 87% of the volume in the first 8 hours),
so the sheet declares the two layers explicitly rather than hiding the choice.

## Cutoff times

12 cutoffs per shift. Every order is born assigned to one. The distribution of orders
across cutoffs is a **declared synthetic assumption** (the bulk falls 21:30–01:01):

| Cutoff | Share | Units | Cumulative |
|---|---|---|---|
| 19:30 | 4% | 4,000 | 4% |
| 20:00 | 6% | 6,000 | 10% |
| 20:30 | 8% | 8,000 | 18% |
| 21:30 | 14% | 14,000 | 32% |
| 22:15 | 12% | 12,000 | 44% |
| 22:58 | 11% | 11,000 | 55% |
| 23:51 | 13% | 13,000 | 68% |
| 01:01 | 12% | 12,000 | 80% |
| 01:30 | 7% | 7,000 | 87% |
| 02:28 | 6% | 6,000 | 93% |
| 03:12 | 4% | 4,000 | 97% |
| 03:30 | 3% | 3,000 | 100% (closing sweep) |

## Metric and alerts

- **Night metric: OTS (On Time Shipping) = 99%.** An order counts as on time when
  its items clear Pack by its cutoff (Shipping is pure outflow; dispatch follows).
  Declared v1 consequence: the second stoppage delays dispatch and is visible in
  the traces, but does not by itself move OTS.
- The alert fires when the **projected** OTS falls below 99% (more than 1% of orders
  projected late against their cutoff).
- **Stoppage detection:** the real-world system flags an associate after 10+ minutes
  without a scan. The copilot tightens this to **5 minutes, aggregated by area**: one
  associate is noise; a whole area without scans is a stopped line. Theoretical
  no-scan budget per associate per shift: 30 + 20 (breaks) + 15 (bathroom) = 65 min.

## The night's tension (synthetic script)

1. **Absences at start:** Picking −5, Pack −3 (297 of 305 present).
   - Picking present: 111 → capacity 96,662 (**−3,338** vs volume).
   - Pack present: 99 → capacity 99,825 (**−175**: knife's edge).
   - The usual donor area (Picking) is itself the short one. Before the shift, the
     ladder's moves still restore the projection — to 99.3%, on the edge of the
     threshold, with no posting (engine-verified). The night is lost later, when
     the first stoppage lands: from there, moves no longer suffice (76.2%) and the
     posting fires — Picking, 5 people × 5 hours.
2. **Stoppage 1 — the Picking → Consolidación line**, first half of the night
   (starvation downstream, blockage upstream).
3. **Stoppage 2 — the Consolidación → Shipping line**, second half of the night.
   In real practice this is the most frequent of the two.

Exact stoppage times inside the synthetic night are a declared design detail, fixed
by the engine's scenario and recorded there.

## The copilot's responses (decision ladder)

1. **Internal rebalancing.** Donor practice: ask Picking first; lend across the three
   Consolidación sub-areas (Induct, Put, Pack); borrow from Shipping. Among available
   sources, the one with the most slack goes first. **Moving one person costs 10
   minutes** of ramp (no production while they relocate and settle).
2. **If internal slack is not enough:** the system computes the shortfall (area,
   people, hours) and **drafts the posting** for the associates' app; the lead
   approves and publishes. The calculation runs **before the shift** (projected
   volume and roster, with known absences) and **during the shift** (live OTS
   projection).

## What it is not

The copilot is **not a WMS**. It is the layer that thinks on top of WMS data:
it projects, detects, recommends, and drafts. Every number comes from the
deterministic engine; the language model only explains and converses, calling
the engine as a tool.

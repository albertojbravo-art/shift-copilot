# Shift Copilot

An operations copilot for shift leads in a fulfillment building. It thinks on top of
warehouse-system data: it **projects on-time shipping (OTS) for the rest of the night**,
**detects line stoppages** from the aggregate scan-gap signal, **recommends staffing
moves** across areas, and — when internal slack is not enough — **calculates the
shortfall and drafts the extra-staff posting** for the lead to approve.

> A WMS tells you what happened. The copilot tells you what is going to happen, and what to do.

## Hackathon

Built for the **Meta Global AI Developer Hackathon** (Cerebral Valley), Indie Dev
Track, *Build for Your World* theme. Construction period: **October 27 – November 4, 2026**.
Team: **Alberto Bravo** (solo). Built with **Muse** (Meta AI developer tooling);
this repository's history starts with the first construction commit of the event window.

## How it works

- A **deterministic simulation engine** (pure Python, no dependencies) computes every
  number: staffing capacity, per-cutoff OTS projections, stoppage detection, donor
  recommendations, posting shortfalls.
- A **language model explains and converses**, calling the engine as a tool. No figure
  is ever produced by the model.
- If the model API is unavailable, the copilot degrades to the engine's own templated
  explanations: the numbers and alerts never depend on the model.

## The demo night (all data synthetic)

One night shift, 17:30–03:30, a 100,000-unit day, 12 cutoff times, a five-node chain
(Picking → Induct → Put → Pack → Shipping), two line stoppages, and absences that hit
the usual donor area itself — so the night cannot be saved by rebalancing alone.
See `SCENARIO.md` for the full, hand-checkable scenario sheet.

## Data & privacy

**All data in this repository is synthetic.** No real employer data, no real people,
no real operations figures are used anywhere in the code, the scenario, or the demo.

## License

MIT — see `LICENSE`.

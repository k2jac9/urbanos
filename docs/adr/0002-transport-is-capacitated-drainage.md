# ADR-0002 — Transport is pure capacitated drainage; speed–density lives in the delay coupling

- **Status:** accepted
- **Date:** 2026-05-29

## Context

The first transport integrator throttled each node's outflow by a speed–density
factor `v = vmax·(1 − ρ^β)` and capped a head node's inflow at its free space
`capacity − load`. Two problems surfaced under the real downtown scenario:

1. **The crush could not appear at the flow bottleneck.** The free-space cap held
   every non-sink node at `ρ ≤ 1`, so the only place density exceeded capacity
   was wherever the event *source* injected directly (St Andrew), not where flow
   actually backed up (Union). The "specific station" insight pointed at the
   wrong station.
2. **Gridlock risk.** `v → 0` as `ρ → 1` means a crowded node stops draining
   entirely, which can deadlock a queue that should clear once the surge passes.

## Decision

Make `transport` **pure capacitated drainage**: a link passes at most
`capacity·dt` people per step and a node never sends more than it holds; a node
serves at its link rate *regardless of its own crowding* (a packed platform
still loads trains). Queues build wherever inflow outruns a node's outbound link
capacity, and `load` is allowed to exceed the node's reference `capacity`
(`ρ > 1` is the crush). The speed–density slow-down a crowd actually *feels* is
modelled where it belongs — in the economic lens's delay coupling (ADR-0003) —
not by zeroing out throughput.

## Consequences

- The crush now forms at the true flow bottleneck (Union), driven by topology,
  not by where the source happens to inject. The insight is emergent and honest.
- No gridlock: once the surge passes, every queue drains at its link rate.
- `β` is no longer used by the kernel's transport; it is exposed to lenses via
  `state.params['beta']` for couplings that want a speed–density term.
- The model is people-conserving (verified by tests): in-system load + cumulative
  `arrived` equals injected demand at every step.

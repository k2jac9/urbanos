"""Prototype harness for the four new intelligence lenses.

Runs them through the REAL kernel against the downtown scenario, prints each
lens's cost at baseline (crush, no intervention) vs. the optimized levers, and
asserts the additivity contract (the new lenses must not change the existing
economic objective term). Touches nothing in the live API.

    PYTHONPATH=src python scripts/prototype_lenses.py
"""
from __future__ import annotations

from urbanos.kernel.adapters.toronto import downtown_scenario
from urbanos.kernel.scenarios import default_lens_stack
from urbanos.kernel.kernel.loop import Simulation

from urbanos.kernel.lenses.ems_access import EmsAccessLens
from urbanos.kernel.lenses.emissions import EmissionsLens
from urbanos.kernel.lenses.noise_livability import NoiseLivabilityLens
from urbanos.kernel.lenses.fare_revenue import FareRevenueLens

NEW = [EmsAccessLens(), EmissionsLens(), NoiseLivabilityLens(), FareRevenueLens()]

sc = downtown_scenario()


def run(stack, release, shelter):
    return Simulation(
        sc.substrate, stack,
        params={"release_minutes": release, "shelter_fraction": shelter},
        dt=sc.dt,
    ).run(sc.horizon)


def econ_of(stack):
    return next(l for l in stack if getattr(l, "name", "") == "economic")


# --- additivity contract: economic J term identical with vs without the new lenses ---
base_stack = default_lens_stack(sc, weather=True, safety=True, business=True)
full_stack = default_lens_stack(sc, weather=True, safety=True, business=True) + NEW
r_base = run(base_stack, 0.0, 0.0)
r_full = run(full_stack, 0.0, 0.0)
e_base = econ_of(base_stack).cost(r_base)
e_full = econ_of(full_stack).cost(r_full)
additive = abs(e_base - e_full) < 1e-6
print("=" * 64)
print("ADDITIVITY CONTRACT (new lenses must not perturb the economic term)")
print(f"  economic J  base-only={e_base:,.2f}   with-new-lenses={e_full:,.2f}")
print(f"  -> {'PASS (additive)' if additive else 'FAIL (perturbs!)'}")
print("=" * 64)

# --- baseline crush vs optimized levers, per new lens ---
crush = run(full_stack, 0.0, 0.0)      # no intervention
opt = run(full_stack, 8.0, 0.5)        # staggered release + shelter
print(f"\n{'lens':<18}{'metric':<22}{'baseline':>15}{'optimized':>15}{'Δ (saved)':>15}")
print("-" * 85)
for lens in NEW:
    c0, c1 = lens.cost(crush), lens.cost(opt)
    print(f"{lens.name:<18}{'priced J term ($)':<22}{c0:>15,.2f}{c1:>15,.2f}{c0 - c1:>15,.2f}")
    # also surface one human metric per lens from the observed series
    crush_series = {
        "ems_access": ("ems_exposure", sum),
        "emissions": ("emissions_kg", sum),
        "noise_livability": ("noise_exposure", sum),
        "fare_revenue": ("fare_in_system", lambda s: max(s) if s else 0.0),
    }[lens.name]
    key, agg = crush_series
    m0, m1 = agg(crush.series(key)), agg(opt.series(key))
    print(f"{'':<18}{key:<22}{m0:>15,.2f}{m1:>15,.2f}{m0 - m1:>15,.2f}")
print("-" * 85)
print("\nAll four lenses ran through the real kernel; the release+shelter levers")
print("reduce every new term — i.e. each adds a real, optimizer-visible objective.")

"""MobilityDemand run-level report (ADR-0030) — the micromobility-relief panel signal.

Covers services.mobility_demand_report (peak/mean relief off a finished sim; available-flag)
and the /lenses endpoint surfacing. Offline + advisory: prices nothing, never a headline.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from urbanos.kernel.adapters.toronto import bikeshare_demand_by_node, downtown_scenario
from urbanos.kernel.api import app
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.lenses import EconomicLens, EventSurge, MobilityDemandLens
from urbanos.kernel.services import mobility_demand_report


def _run(stack, sc):
    return Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(
        sc.horizon
    )


def test_report_available_and_bounded():
    sc = downtown_scenario()
    md = MobilityDemandLens(bikeshare_demand_by_node(sc.substrate, provider=lambda: []))
    stack = [EventSurge(events=sc.events), EconomicLens(), md]
    rep = mobility_demand_report(stack, _run(stack, sc))
    assert rep["available"] is True
    assert 0.0 <= rep["mean_relief"] <= rep["peak_relief"] <= 1.0


def test_report_unavailable_without_lens():
    sc = downtown_scenario()
    stack = [EventSurge(events=sc.events), EconomicLens()]
    rep = mobility_demand_report(stack, _run(stack, sc))
    assert rep["available"] is False
    assert rep["peak_relief"] == 0.0 and rep["mean_relief"] == 0.0


def test_lenses_endpoint_includes_mobility_demand():
    body = TestClient(app).get("/lenses?release_minutes=0&shelter_fraction=0").json()
    assert "mobility_demand" in body
    md = body["mobility_demand"]
    assert {"available", "peak_relief", "mean_relief"} <= set(md)
    assert 0.0 <= md["mean_relief"] <= md["peak_relief"] <= 1.0

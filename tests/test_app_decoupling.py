"""ADR-0023: the two apps are decoupled through public seams, not private globals.

- urbanos.risk exposes ``load_graph`` / ``ensure_loaded`` so a parent app can load
  the graph without reaching into its module internals.
- ``civic_safety_by_node`` takes an injectable ``address_provider`` so the Toronto
  adapter no longer hard-depends on civic internals and is testable in isolation.
"""
from __future__ import annotations

import math

from urbanos.kernel.adapters import downtown_scenario
from urbanos.kernel.adapters.toronto import civic_safety_by_node, reset_civic_address_cache


def test_civic_exposes_public_load_entrypoints():
    from urbanos.risk.api import server

    assert callable(server.load_graph)
    assert callable(server.ensure_loaded)
    # load_graph returns a summary dict and leaves the module graph populated-or-empty
    # (offline-safe). ensure_loaded is a no-op once the graph is non-empty.
    summary = server.load_graph()
    assert isinstance(summary, dict)
    again = server.ensure_loaded()
    assert isinstance(again, dict)


def test_injected_address_provider_drives_the_overlay():
    """An injected provider lets the adapter compute the fusion with NO civic import.
    A risky address sitting on a node lifts that node's safety overlay above zero."""
    sc = downtown_scenario()
    sub = sc.substrate
    nid = sub.ids[0]
    here = (float(sub.lat[0]), float(sub.lng[0]))
    fake = [{"lat": here[0], "lng": here[1], "risk_safety": 0.9}]

    overlay = civic_safety_by_node(sub, address_provider=lambda: fake)
    assert set(overlay) == set(sub.ids)
    assert all(math.isfinite(v) and v >= 0.0 for v in overlay.values())
    # The node co-located with the risky address carries (close to) its risk.
    assert overlay[nid] > 0.5


def test_provider_failure_falls_back_to_synthetic_offline():
    """A provider that yields nothing or raises must fall back to the deterministic
    synthetic overlay, so Urban-OS stays standalone/offline."""
    sc = downtown_scenario()
    sub = sc.substrate

    def _boom():
        raise RuntimeError("provider down")

    for provider in (lambda: [], _boom):
        overlay = civic_safety_by_node(sub, address_provider=provider)
        assert set(overlay) == set(sub.ids)
        assert all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in overlay.values())


def test_reset_cache_is_callable():
    # The process-global civic-address cache can be reset deterministically.
    reset_civic_address_cache()

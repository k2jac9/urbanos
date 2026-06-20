"""Tests for the optional Rust-accelerated transport step (numpy fallback).

These verify the numpy reference is correct and conserves people, and — only
when the Rust backend is actually built — that it matches numpy to ~1e-9.
Importing ``accel`` must never raise regardless of whether the crate exists.
"""
from __future__ import annotations

import numpy as np
import pytest

from urbanos.kernel.kernel import accel
from urbanos.kernel.adapters import downtown_scenario


def _independent_transport_step(load, edge_src, edge_dst, edge_cap, dist_to_sink, is_sink, dt):
    """A from-scratch reimplementation using plain Python loops.

    Deliberately *not* sharing code with accel's numpy path, so equality is a
    real check rather than a tautology.
    """
    n = len(load)
    e = len(edge_src)
    edge_supply = [0.0] * e
    tail_tot = [0.0] * n
    for i in range(e):
        s, d = int(edge_src[i]), int(edge_dst[i])
        supply = edge_cap[i] * dt if dist_to_sink[d] < dist_to_sink[s] else 0.0
        edge_supply[i] = supply
        tail_tot[s] += supply

    tail_scale = [0.0] * n
    for node in range(n):
        if tail_tot[node] > 0.0:
            tail_scale[node] = min(1.0, load[node] / tail_tot[node])

    out_per = [0.0] * n
    in_per = [0.0] * n
    for i in range(e):
        s, d = int(edge_src[i]), int(edge_dst[i])
        flow = edge_supply[i] * tail_scale[s]
        out_per[s] += flow
        in_per[d] += flow

    out_load = [0.0] * n
    arrived_delta = [0.0] * n
    for node in range(n):
        v = load[node] - out_per[node]
        if is_sink[node]:
            arrived_delta[node] = in_per[node]
        else:
            v += in_per[node]
        out_load[node] = max(0.0, v)
    return np.array(out_load), np.array(arrived_delta)


@pytest.fixture(scope="module")
def substrate():
    return downtown_scenario().substrate


@pytest.fixture(scope="module")
def arrays(substrate):
    return dict(
        edge_src=substrate.edge_src,
        edge_dst=substrate.edge_dst,
        edge_cap=substrate.edge_cap,
        dist_to_sink=substrate.dist_to_sink,
        is_sink=substrate.is_sink,
        capacity=substrate.capacity,
    )


def _seeded_load(n, seed):
    rng = np.random.default_rng(seed)
    return rng.uniform(0.0, 1000.0, size=n)


def test_import_never_raises_and_backend_name():
    # Re-import is a no-op but documents intent; the module already imported above.
    import importlib

    importlib.import_module("urbanos.kernel.kernel.accel")
    assert accel.backend_name() in {"rust", "numpy"}
    assert accel.BACKEND == accel.backend_name()


def test_numpy_conserves_people(substrate, arrays):
    load = _seeded_load(substrate.n, seed=1)
    out_load, arrived_delta = accel.transport_step(load=load, dt=1.0, **arrays)
    assert out_load.sum() + arrived_delta.sum() == pytest.approx(load.sum(), abs=1e-9)
    # No node goes negative; inputs untouched.
    assert (out_load >= 0).all()
    assert np.array_equal(load, _seeded_load(substrate.n, seed=1))


def test_numpy_matches_independent_reimpl(substrate, arrays):
    for seed in range(5):
        load = _seeded_load(substrate.n, seed=seed)
        out_load, arrived_delta = accel.transport_step(load=load, dt=1.5, **arrays)
        ref_out, ref_arr = _independent_transport_step(
            load,
            arrays["edge_src"],
            arrays["edge_dst"],
            arrays["edge_cap"],
            arrays["dist_to_sink"],
            arrays["is_sink"],
            dt=1.5,
        )
        np.testing.assert_allclose(out_load, ref_out, atol=1e-9)
        np.testing.assert_allclose(arrived_delta, ref_arr, atol=1e-9)


def test_matches_kernel_operator(substrate):
    """accel's numpy path must equal the kernel's in-place operators.transport."""
    from urbanos.kernel.kernel.state import State
    from urbanos.kernel.kernel.operators import Operators

    st = State(substrate)
    load0 = _seeded_load(substrate.n, seed=7)
    st.fields["load"] = load0.copy()
    arrived0 = st.fields["arrived"].copy()
    Operators.transport(st, dt=2.0)

    out_load, arrived_delta = accel.transport_step(
        load=load0,
        edge_src=substrate.edge_src,
        edge_dst=substrate.edge_dst,
        edge_cap=substrate.edge_cap,
        dist_to_sink=substrate.dist_to_sink,
        is_sink=substrate.is_sink,
        capacity=substrate.capacity,
        dt=2.0,
    )
    np.testing.assert_allclose(out_load, st.fields["load"], atol=1e-9)
    np.testing.assert_allclose(arrived0 + arrived_delta, st.fields["arrived"], atol=1e-9)


def test_rust_matches_numpy(substrate, arrays):
    if accel.BACKEND != "rust":
        pytest.skip(
            "Rust backend not built (BACKEND=numpy). Build with: "
            "cd native && maturin develop --release"
        )
    for seed in range(5):
        load = _seeded_load(substrate.n, seed=seed)
        rust_out, rust_arr = accel.transport_step(load=load, dt=1.0, **arrays)
        ref_out, ref_arr = accel._transport_step_numpy(
            load,
            arrays["edge_src"],
            arrays["edge_dst"],
            arrays["edge_cap"],
            arrays["dist_to_sink"],
            arrays["is_sink"],
            arrays["capacity"],
            dt=1.0,
        )
        np.testing.assert_allclose(rust_out, ref_out, atol=1e-9)
        np.testing.assert_allclose(rust_arr, ref_arr, atol=1e-9)

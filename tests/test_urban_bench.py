"""Tests for the accelerator benchmark harness (``scripts/bench_urbanos_accel.py``).

The bench script is the artifact that validates ADR-0004/0009. These tests pin
its contract: it builds valid problem instances, its parity check agrees with
the numpy reference, it conserves people, and ``main`` runs anywhere and exits 0
(rust built or not). The script must NOT raise on import and must degrade
gracefully to numpy-only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

# Load scripts/bench_urbanos_accel.py as a module (scripts/ isn't a package).
_BENCH_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bench_urbanos_accel.py"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("bench_urbanos_accel", _BENCH_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__ via sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_bench_script_exists():
    assert _BENCH_PATH.is_file(), f"missing {_BENCH_PATH}"


def test_downtown_bench_is_well_formed(bench):
    b = bench._downtown_bench()
    assert b.n == 9 and b.e == 9
    # Crowd is primed at the stadium and nowhere else.
    assert b.load.sum() == pytest.approx(45000.0)
    assert b.load.max() == pytest.approx(45000.0)
    # Index/dtype invariants for the step.
    assert b.edge_src.dtype == np.int64 and b.edge_dst.dtype == np.int64
    assert b.is_sink.dtype == bool
    assert b.edge_src.min() >= 0 and b.edge_src.max() < b.n
    assert b.edge_dst.min() >= 0 and b.edge_dst.max() < b.n


def test_synthetic_bench_is_deterministic_and_valid(bench):
    b1 = bench._synthetic_bench(n_nodes=400, fanout=4, seed=7)
    b2 = bench._synthetic_bench(n_nodes=400, fanout=4, seed=7)
    # Determinism: same seed -> identical arrays.
    assert np.array_equal(b1.edge_src, b2.edge_src)
    assert np.array_equal(b1.edge_cap, b2.edge_cap)
    assert np.array_equal(b1.load, b2.load)
    # Edge endpoints in range; at least one sink; load only in the source layer.
    assert b1.e > 0 and b1.n > 0
    assert b1.edge_dst.max() < b1.n and b1.edge_src.min() >= 0
    assert b1.is_sink.any() and not b1.is_sink.all()
    # Forward edges drain (head strictly closer to sink than tail).
    assert (b1.dist_to_sink[b1.edge_dst] < b1.dist_to_sink[b1.edge_src]).all()


def test_synthetic_bench_clamps_tiny_n(bench):
    b = bench._synthetic_bench(n_nodes=1, fanout=4, seed=0)
    assert b.n >= 4  # clamped up so the step is meaningful


def test_parity_passes_against_numpy_reference(bench):
    # Whatever the live backend, parity vs the numpy reference must hold (numpy
    # vs numpy is trivially exact; rust vs numpy is exact to f64 round-off).
    for b in (bench._downtown_bench(), bench._synthetic_bench(300, 4, 3)):
        ok, diff = bench._assert_parity(b)
        assert ok, f"parity failed on {b.name}: max|Δ|={diff}"
        assert diff < 1e-9


def test_bench_step_conserves_people(bench):
    b = bench._synthetic_bench(300, 4, 11)
    out_load, arrived = bench.transport_step(**b.args())
    assert out_load.sum() + arrived.sum() == pytest.approx(b.load.sum(), abs=1e-6)
    assert (out_load >= 0).all()


def test_time_callable_returns_positive(bench):
    b = bench._downtown_bench()
    t = bench._time_callable(bench._transport_step_numpy, b.args(), iters=3)
    assert t >= 0.0 and np.isfinite(t)


def test_main_runs_and_returns_zero(bench, capsys):
    # Tiny, fast invocation; must exit 0 and print the backend + a verdict,
    # regardless of whether the rust crate is built in this environment.
    rc = bench.main(["--iters", "2", "--nodes", "40", "--fanout", "3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "active backend :" in out
    assert "RESULT:" in out
    assert bench.accel.backend_name() in out

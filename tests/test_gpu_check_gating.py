"""The gpu-check exit-code gate fails loudly only when a REQUESTED GPU seam fell back.

These cover the pure ``gate_exit_code`` helper in ``scripts/gpu_check.py`` — no GPU,
no CUDA, no ``os.environ`` mutation (env is passed as a plain dict). The contract:

* no GPU env flags set            -> 0 (CPU is the honest off-box outcome)
* flag set + seam on GPU          -> 0
* flag set + seam on CPU fallback -> non-zero, naming the degraded seam
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "gpu_check.py"

# The seam backends as seen on the GB10 with everything wired (the "all GPU" world).
ALL_GPU = {
    "graph": "cugraph",
    "ingest": "cudf-polars",
    "flow": "cuopt",
    "cluster": "cuml",
}
# The seam backends off the box / in CI (the "all CPU fallback" world).
ALL_CPU = {
    "graph": "networkx",
    "ingest": "pandas",
    "flow": "networkx",
    "cluster": "numpy",
}


def _load_gate():
    """Import gate_exit_code from scripts/gpu_check.py without running main().

    Loading the module only binds top-level names; ``main()`` is gated behind
    ``if __name__ == "__main__"``, so no seams are exercised and no GPU is touched.
    """
    spec = importlib.util.spec_from_file_location("gpu_check", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.gate_exit_code


gate_exit_code = _load_gate()


# --------------------------------------------------------- no flags = unchanged exit 0
def test_no_flags_exits_zero_even_on_all_cpu():
    code, msg = gate_exit_code(ALL_CPU, env={})
    assert code == 0
    assert "CPU fallback (honest)" in msg


def test_no_flags_exits_zero_even_if_backends_happen_to_be_gpu():
    # No request => we don't gate, regardless of what the backends report.
    code, _ = gate_exit_code(ALL_GPU, env={})
    assert code == 0


def test_empty_and_zero_flags_are_not_set():
    for val in ("", "0", "false", "no", "off"):
        code, msg = gate_exit_code(ALL_CPU, env={"URBANOS_GPU_GRAPH": val})
        assert code == 0, f"{val!r} should be falsey"
        assert "CPU fallback (honest)" in msg


# ------------------------------------------------ flag set + seam on GPU = exit 0
def test_single_flag_on_gpu_exits_zero():
    code, msg = gate_exit_code(ALL_GPU, env={"URBANOS_GPU_GRAPH": "1"})
    assert code == 0
    assert "GPU path active" in msg
    assert "graph->cugraph" in msg


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", " yes ", "True"])
def test_truthy_parsing_matches_module_helpers(val):
    # Same truthiness as state.py/loader.py/flow.py/cluster.py: strip().lower() in set.
    code, _ = gate_exit_code(ALL_GPU, env={"URBANOS_GPU_DF": val})
    assert code == 0


def test_all_flags_on_gpu_exits_zero():
    env = {
        "URBANOS_GPU_GRAPH": "1",
        "URBANOS_GPU_DF": "1",
        "URBANOS_GPU_FLOW": "1",
        "URBANOS_GPU_CLUSTER": "1",
    }
    code, msg = gate_exit_code(ALL_GPU, env=env)
    assert code == 0
    assert "GPU path active" in msg


# ------------------------------- flag set + seam fell back to CPU = non-zero, named
def test_single_flag_but_cpu_fallback_exits_nonzero_and_names_seam():
    code, msg = gate_exit_code(ALL_CPU, env={"URBANOS_GPU_GRAPH": "1"})
    assert code == 5
    assert "graph" in msg
    assert "URBANOS_GPU_GRAPH" in msg
    assert "cugraph" in msg          # expected backend named
    assert "networkx" in msg         # what we actually got named


def test_each_seam_gates_independently():
    cases = [
        ("URBANOS_GPU_GRAPH", "graph"),
        ("URBANOS_GPU_DF", "ingest"),
        ("URBANOS_GPU_FLOW", "flow"),
        ("URBANOS_GPU_CLUSTER", "cluster"),
    ]
    for flag, seam in cases:
        code, msg = gate_exit_code(ALL_CPU, env={flag: "1"})
        assert code == 5, f"{flag} requested but CPU should fail"
        assert seam in msg


def test_mixed_some_gpu_some_degraded_exits_nonzero_naming_only_degraded():
    # graph requested + on GPU; flow requested + degraded to CPU.
    backends = dict(ALL_GPU)
    backends["flow"] = "networkx"
    env = {"URBANOS_GPU_GRAPH": "1", "URBANOS_GPU_FLOW": "1"}
    code, msg = gate_exit_code(backends, env=env)
    assert code == 5
    assert "flow" in msg
    # The healthy requested seam is not flagged as degraded.
    assert "graph (set" not in msg


def test_unrequested_cpu_seam_does_not_trip_the_gate():
    # Only ingest is requested (and on GPU); the other three are CPU but unrequested.
    backends = dict(ALL_CPU)
    backends["ingest"] = "cudf-polars"
    code, _ = gate_exit_code(backends, env={"URBANOS_GPU_DF": "1"})
    assert code == 0


def test_polars_without_cudf_is_a_degraded_df_request():
    # URBANOS_GPU_DF requested but cudf-polars unavailable -> seam reports "polars".
    code, msg = gate_exit_code({**ALL_CPU, "ingest": "polars"},
                               env={"URBANOS_GPU_DF": "1"})
    assert code == 5
    assert "ingest" in msg
    assert "polars" in msg

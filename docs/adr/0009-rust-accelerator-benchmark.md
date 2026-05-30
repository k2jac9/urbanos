# ADR-0009: Build & benchmark the Rust transport accelerator (validating ADR-0004)

- Status: Accepted
- Date: 2026-05-30
- Relates to: ADR-0004 (Rust core as an optional accelerator)

## Context

ADR-0004 introduced `native/` (a PyO3 crate, module `urban_os_native`) as a
**drop-in accelerator** for the kernel's hot path, `accel.transport_step`. The
numpy reference in `src/urban_os/kernel/accel.py` is always present and is the
bit-for-bit contract; the Rust crate, when built, is supposed to make the
"N× real-time" number real. ADR-0004 asserted a speedup but never *measured* one.

This workstream BUILDS the crate on the target box (NVIDIA GX10, aarch64) and
benchmarks it against numpy to (a) prove numerical parity and (b) quantify the
actual speedup — turning ADR-0004's claim into a measured fact (or, as it turns
out, a measured caveat).

Deliverables:
- `scripts/bench_urbanos_accel.py` — parity assertion + wall-clock timing that
  runs anywhere and degrades gracefully to a numpy-only baseline when the crate
  is absent (it prints "rust not built, numpy only" and exits 0).
- `make urbanos-bench` — convenience target.
- This ADR, with the **real numbers measured on the box**.

## What was measured (on the box: `asus@gx10-4428`, aarch64, Python 3.12)

Build via `make urbanos-accel` (maturin develop --release): the crate compiled
in ~0.2s (release) and installed cleanly; `accel.backend_name()` returned
`rust`. No aarch64 / pyo3 / maturin build issues were encountered — the existing
`native/Cargo.toml` (pyo3 0.22, `extension-module` + `abi3-py38`,
`crate-type = ["cdylib"]`) builds out of the box on ARM64.

`PYTHONPATH=src python scripts/bench_urbanos_accel.py` reported, with
`active backend : rust`:

**Numerical parity — PASS (bit-for-bit).** On both the real downtown substrate
and a 3,969-node / 15,277-edge synthetic graph, `max|Δ|` between the numpy
reference and the live rust backend was **0.000e+00** for both returned arrays
(`out_load`, `arrived_delta`). The line-for-line f64 port matches numpy exactly.

**Wall-clock speedup — size-dependent, and this is the real finding:**

| substrate                         | numpy/step | rust/step  | speedup |
|-----------------------------------|-----------:|-----------:|--------:|
| downtown (N=9, E=9) — the demo    |  ~8.4 µs   |  ~3.0 µs   | **2.8×** |
| synthetic (N=196, E=654)          |  ~12.9 µs  |  ~52 µs    |  0.25×  |
| synthetic (N=3969, E=15277)       |  ~88 µs    | ~1631 µs   |  0.05×  |

Rust is ~2.8× faster on the **downtown graph that the demo actually runs**, but
becomes progressively *slower* than numpy as the graph grows. The crossover is
small (already lost by N≈200).

## Root cause of the large-graph regression (researched on the box)

The Rust compute is not the problem — it is trivially fast. The cost is the
**Python⇄Rust boundary**. `native/lib.rs` declares its inputs as `Vec<f64>` /
`Vec<i64>`, and `accel.py` therefore marshals each numpy array through
`.tolist()` before the call. Direct measurement on the box (2,000 calls on the
N=3969 instance):

```
per-call tolist-marshalling : ~700 µs   (building 4·N + 2·E Python objects)
per-call native call+convert: ~710 µs   (PyO3 unpacking that list into Vec<T>)
```

So ~1.4 ms/step is spent creating and re-parsing Python-object lists, dwarfing
both the numpy vectorized step (~88 µs) and the actual Rust arithmetic. I also
tested passing the numpy arrays to the crate *directly* (no `.tolist()`): PyO3
accepts them via the sequence protocol but it is **worse** (~1.8 ms/step),
because it iterates numpy scalar wrappers one-by-one. `.tolist()` is the faster
of the two boundary options available *without changing the Rust signature*.

## Decision

1. **Keep the numpy reference as the default and the bit-for-bit contract.**
   `accel.py` already does this and importing it never raises; left intact.
2. **Ship the benchmark + `make urbanos-bench`** so the claim is reproducible
   and the size-dependence is visible, not hidden.
3. **Record ADR-0004's claim as VALIDATED for the demo (2.8× on downtown) and
   CAVEATED for large substrates** — the current crate is the right backend for
   the small, fixed downtown graph the hackathon demo uses, and the numpy path
   is correct (and faster) for anything large.
4. **Do not "fix" the regression by hacking the list boundary** (the two options
   that don't touch the Rust signature are both at-or-worse than numpy). I did
   NOT edit `accel.py`'s call path: the only honest fix is in the crate, and the
   crate is owned by the `native/` workstream (out of scope for this branch).

## Recommended follow-up (for the `native/` owner)

Make the boundary zero-copy: depend on the `numpy` crate and take
`PyReadonlyArray1<f64>` / `PyReadonlyArray1<i64>` (return `PyArray1`) instead of
`Vec<T>`. That lets Rust read the numpy buffer in place (no per-element Python
object churn) and `accel.py` can drop the `.tolist()`. With the ~1.4 ms/step
boundary removed, the Rust arithmetic (sub-µs on these sizes) should beat numpy
at every size, and the speedup would *grow* with graph size instead of
inverting. Until then, the demo runs fine: the downtown graph is small, where
rust already wins 2.8×, and the numpy fallback covers everything else.

## Consequences

- ADR-0004's "optional accelerator, numpy always correct" architecture is
  vindicated: parity is exact, and the fallback is not just safe but is the
  *faster* path above a tiny graph size — so nothing regresses by leaving rust
  unbuilt.
- The hackathon claim is now honest and reproducible: "Rust core, 2.8× on the
  live downtown step, bit-for-bit identical to the numpy reference," with a
  documented, scoped path to make it win at scale.
- `make urbanos-bench` runs offline anywhere and degrades gracefully, so a
  teammate without the crate still gets a numpy baseline rather than an error.

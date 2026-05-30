# ADR-0004 — Rust core is an optional drop-in accelerator, numpy is the always-present fallback

- **Status:** accepted
- **Date:** 2026-05-29

## Context

The Spark Story wants an "N× real-time" number, and a Rust simulation core is the
honest way to earn it. But a Rust/pyo3 build adds a toolchain (cargo + maturin +
aarch64 cross-build) that we have little time to debug live, and a broken native
build must never be able to take down the demo. The project already has a
governing pattern for exactly this risk: "no model → deterministic fallback."

## Decision

Apply the same pattern to acceleration. A single kernel seam — `transport_step`
in `urban_os/kernel/accel.py` — has a **pure-numpy reference implementation that
is always present**, and *optionally* dispatches to a compiled Rust module
(`urban_os_native`, built with maturin/pyo3) when it is importable. `accel.py`
exposes `BACKEND` ∈ {"rust","numpy"}. The kernel's `Operators.transport` calls
`accel.transport_step`; nothing else in the kernel knows or cares which backend
ran. The Rust and numpy paths implement the identical capacitated-drainage
algorithm (ADR-0002) and are tested to agree within 1e-9.

## Consequences

- `make test` and `make demo` run with **zero** Rust present. The Rust core is a
  measured speedup we *show*, not a dependency we *need*.
- The "N× real-time" claim is backed by a real numpy-vs-rust benchmark on the
  downtown substrate; if Rust isn't built on the box, we quote the numpy rate and
  say so — no fabricated number.
- The native crate builds on aarch64 via `cd native && maturin develop --release`.
  Build instructions live in `native/` and `docs/ON_THE_BOX.md`.
- Risk contained: a native ABI/build failure degrades performance, never
  correctness or availability.

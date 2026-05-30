//! Optional Rust acceleration core for the Urban-OS transport step.
//!
//! This is a DROP-IN ACCELERATOR: `src/urban_os/kernel/accel.py` always ships a
//! pure-numpy reference and only routes here when this crate is built and
//! importable as the Python module `urban_os_native`. The algorithm below is a
//! line-for-line port of the numpy reference (pure capacitated drainage), kept
//! in f64 so results match numpy to ~1e-9.
//!
//! Build into the project venv (aarch64 / ARM64 box):
//!     cd native && maturin develop --release
//! Or build a wheel:
//!     cd native && maturin build --release            # auto-detects aarch64
//! Cross / explicit target:
//!     maturin build --release --target aarch64-unknown-linux-gnu

use pyo3::prelude::*;

/// One capacitated-drainage transport step.
///
/// Inputs are flat vectors (the numpy<->Vec conversion happens in `accel.py`):
/// - `load`         : (N) people held at each node
/// - `edge_src`     : (E) tail node index per edge
/// - `edge_dst`     : (E) head node index per edge
/// - `edge_cap`     : (E) link throughput (persons / minute)
/// - `dist_to_sink` : (N) graph distance to nearest sink
/// - `is_sink`      : (N) 1 if node absorbs arriving load, else 0
/// - `dt`           : timestep
///
/// Returns `(out_load, arrived_delta)`, two length-N f64 vectors. Inputs are
/// not mutated. People-conserving to f64 round-off.
#[pyfunction]
fn transport_step(
    load: Vec<f64>,
    edge_src: Vec<i64>,
    edge_dst: Vec<i64>,
    edge_cap: Vec<f64>,
    dist_to_sink: Vec<f64>,
    is_sink: Vec<i64>,
    dt: f64,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let n = load.len();
    let e = edge_src.len();

    // Per-edge: draining iff head strictly closer to an exit than tail;
    // edge_supply = cap*dt on draining edges, else 0. Accumulate per-tail total.
    let mut edge_supply = vec![0.0f64; e];
    let mut tail_tot = vec![0.0f64; n];
    for i in 0..e {
        let s = edge_src[i] as usize;
        let d = edge_dst[i] as usize;
        let supply = if dist_to_sink[d] < dist_to_sink[s] {
            edge_cap[i] * dt
        } else {
            0.0
        };
        edge_supply[i] = supply;
        tail_tot[s] += supply;
    }

    // tail_scale = min(1, load/tail_tot), with safe-divide (tail_tot<=0 -> 0).
    let mut tail_scale = vec![0.0f64; n];
    for node in 0..n {
        if tail_tot[node] > 0.0 {
            let r = load[node] / tail_tot[node];
            tail_scale[node] = if r < 1.0 { r } else { 1.0 };
        } else {
            tail_scale[node] = 0.0;
        }
    }

    // edge_flow = edge_supply * tail_scale[src]; gather out_per / in_per.
    let mut out_per = vec![0.0f64; n];
    let mut in_per = vec![0.0f64; n];
    for i in 0..e {
        let s = edge_src[i] as usize;
        let d = edge_dst[i] as usize;
        let flow = edge_supply[i] * tail_scale[s];
        out_per[s] += flow;
        in_per[d] += flow;
    }

    // out_load = clip(load - out_per + (in_per where not sink), 0, inf)
    // arrived_delta = in_per where sink else 0
    let mut out_load = vec![0.0f64; n];
    let mut arrived_delta = vec![0.0f64; n];
    for node in 0..n {
        let mut v = load[node] - out_per[node];
        if is_sink[node] != 0 {
            arrived_delta[node] = in_per[node];
        } else {
            v += in_per[node];
        }
        out_load[node] = if v < 0.0 { 0.0 } else { v };
    }

    Ok((out_load, arrived_delta))
}

/// Python module `urban_os_native`.
#[pymodule]
fn urban_os_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(transport_step, m)?)?;
    Ok(())
}

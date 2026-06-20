"""Action-Matching FLOOR — a learned velocity field on the substrate (ADR-0028).

Phase 2 of the data-driven roadmap (``docs/research/tpf-and-data-driven-lenses.md``
§8.3). Phase 1 (``CongestionNowcastLens``) asked *how far the kernel's crowd profile
sits from the observed counts*. Phase 2 asks the next, sharper question: **does a field
learned directly from the observed marginals beat the deterministic kernel at all?** —
the "Action Matching floor" the roadmap calls for before any TPF machinery is justified.

What this is (and the honest descope)
-------------------------------------
Action Matching (Neklyudov 2022, the simpler ancestor of TPF) learns a velocity field
``u(x,t)`` from *uncorrelated temporal marginals* — exactly the shape Toronto's TMC
15-min counts have (mass per place per bin, no per-person trajectories). The canonical AM
loss trains a neural action ``s(x,t)`` (with ``u = ∇s``) by stochastic gradient descent.
We have **numpy only — no torch, no autodiff** (see ``requirements.txt``). Rather than
fake a neural loop, we ship the roadmap's *explicitly sanctioned* floor: a **deterministic
least-squares velocity fit on the graph that obeys the same continuity law** Action
Matching's velocity satisfies, then a rollout and an apples-to-apples scoring against the
kernel and the observed counts. This still answers the Phase-2 question; it just answers
it with a closed-form fit instead of SGD. The boundary is stated here on purpose.

The graph velocity field (continuity = the AM constraint)
---------------------------------------------------------
The substrate is a small directed graph. A velocity field on it is a **per-edge flow
rate** ``f_e`` (people/bin along edge ``e``). The marginal evolution it induces is fixed
by discrete continuity — the graph analogue of ``∂ρ/∂t + ∇·(ρu) = 0`` that AM's velocity
obeys: a node's mass change over a bin equals (inflow − outflow) along its edges,

    Δc_i(t) = Σ_{e into i} f_e(t) − Σ_{e out of i} f_e(t).

Stacked over all nodes this is a linear system ``B f = Δc`` where ``B`` is the (signed)
node–edge incidence. We solve it per bin by **ridge least squares** (a tiny ``λ`` keeps
the null space — flows around cycles that move no net mass — small and the fit unique).
That ``f`` *is* the learned field: the minimum-energy edge flow whose divergence
reproduces the observed per-node mass changes. (Minimum-energy because ridge picks the
smallest-norm solution — the honest, fishing-resistant default when continuity alone
under-determines circulation, which §2's "no a-priori curl control" caveat warns about.)

Rollout + the comparison (the actual deliverable)
-------------------------------------------------
Seed a density at the last *training* bin, push it forward bin-by-bin with the learned
flows (clamped non-negative, mass-checked), and obtain a **learned marginal series**. We
then score, on a held-out tail of the observed bins, the shape agreement (cosine, the same
scale-free primitive Phase 1 uses — the two series share no absolute scale) of

  * the **kernel**'s node-load profile vs the observed counts, and
  * the **learned** rollout's profile vs the observed counts,

and report whether learned beats kernel (``learned_better``) and by how much. That single
boolean + margin is the Phase-2 finding.

Honesty constraints (roadmap §7 — none regressed)
-------------------------------------------------
1. **Learned predicts, exact kernel decides.** This module is advisory/diagnostic ONLY. It
   exposes *no* lever and feeds *no* cost into ``J``; it is consulted alongside a finished
   run, exactly like ``surrogate.py`` is recorded next to the optimizer's exact ``J`` and
   never decides. No headline number, chosen lever, or priced-lens figure can move.
2. **Opt-in + CPU fallback.** Gated behind ``URBANOS_LEARNED_DYNAMICS``; off (or absent
   training data → fewer than three usable bins) it is a clean no-op (``available=False``).
   numpy-only, deterministic — CI/dev never need a trained model or CUDA.
3. **Provenance honesty.** Every output is labelled ``provenance="learned/approximate"``,
   distinct from the kernel-exact fields, so a learned number is never mistaken for one.
4. **Narrator boundary.** Nothing here touches ``narrate.py``; a learned value reaching the
   guarded narration would need its own evidence kind (out of scope, roadmap §7.4).
5. **No private deps.** A from-scratch least-squares fit — never vendors ``flanch`` /
   ``hdfx`` / ``hdfv``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from .kernel.loop import SimResult
from .kernel.state import Substrate

# Label stamped on every learned output so the UI / logs can keep it visually distinct
# from kernel-exact fields (roadmap §7.3). Mirrors the ``*_BACKEND`` provenance markers.
PROVENANCE = "learned/approximate"

# Ridge weight for the per-bin velocity solve. Small, fixed, and documented (not tuned
# against the score — that would be fishing): just enough to make the under-determined
# incidence system well-posed and pick the minimum-energy flow.
_RIDGE = 1e-3


def learned_dynamics_enabled() -> bool:
    """Opt-in: set ``URBANOS_LEARNED_DYNAMICS=1`` (mirrors ``URBANOS_SURROGATE`` /
    ``URBANOS_GPU_GRAPH``). Off by default → the metric is a no-op and CI, the demo
    venv, and the golden numbers are untouched."""
    return os.environ.get("URBANOS_LEARNED_DYNAMICS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Scale-free shape agreement of two non-negative profiles in ``[0, 1]`` (the same
    primitive Phase 1's calibration uses; 0.0 when either profile is all-zero)."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(np.clip(np.dot(a, b) / (na * nb), 0.0, 1.0))


def _incidence(sub: Substrate) -> np.ndarray:
    """Signed node–edge incidence ``B`` (N×E): ``+1`` at an edge's head, ``-1`` at its
    tail. ``B @ f`` is then the net inflow per node induced by edge flows ``f`` — the
    discrete divergence that continuity ties to the observed mass change."""
    n, e = sub.n, sub.n_edges
    B = np.zeros((n, e), dtype=float)
    for k in range(e):
        B[int(sub.edge_src[k]), k] -= 1.0
        B[int(sub.edge_dst[k]), k] += 1.0
    return B


def _observed_matrix(
    node_counts: dict[str, dict[float, float]], sub: Substrate
) -> tuple[np.ndarray, list[float]]:
    """Bake the ``{node: {minute: count}}`` series into a dense ``(B, N)`` matrix over the
    common sorted bins (rows = bins, cols = substrate nodes), plus the bin list. Missing
    cells are 0.0."""
    bins: set[float] = set()
    for series in node_counts.values():
        bins.update(float(m) for m in series)
    ordered = sorted(bins)
    mat = np.zeros((len(ordered), sub.n), dtype=float)
    for bi, b in enumerate(ordered):
        for ni, nid in enumerate(sub.ids):
            mat[bi, ni] = float(node_counts.get(nid, {}).get(b, 0.0))
    return mat, ordered


def _fit_edge_flows(B: np.ndarray, dc: np.ndarray) -> np.ndarray:
    """Ridge least-squares edge flow ``f`` whose divergence ``B f`` best matches the
    observed mass change ``dc`` (one bin). Solves the normal equations
    ``(BᵀB + λI) f = Bᵀ dc`` — closed form, deterministic, numpy-only. The ``λI`` makes
    the (generally rank-deficient) incidence system unique and selects the minimum-energy
    flow, so circulation the data does not demand is not invented."""
    e = B.shape[1]
    gram = B.T @ B + _RIDGE * np.eye(e)
    return np.linalg.solve(gram, B.T @ dc)


def _rollout(B: np.ndarray, flows: list[np.ndarray], seed: np.ndarray) -> list[np.ndarray]:
    """Push the seed marginal forward with the learned per-bin flows: each step adds the
    flow divergence ``B f`` (the mass continuity says moved), clamps to non-negative
    (densities are physical), and renormalises to the pre-clip total so the rollout
    conserves people across the clamp — the same conservation discipline the kernel's
    noised transport keeps (loop.py). The returned list has ``len(flows) + 1`` profiles
    (the seed plus one per flow)."""
    rho = np.clip(seed.astype(float), 0.0, None)
    out = [rho.copy()]
    for f in flows:
        before = float(rho.sum())
        rho = rho + B @ f
        np.clip(rho, 0.0, None, out=rho)
        after = float(rho.sum())
        if after > 0.0:
            rho *= before / after
        out.append(rho.copy())
    return out


@dataclass
class LearnedDynamicsReport:
    """Result of the Action-Matching-floor diagnostic. All fields advisory; ``provenance``
    keeps them labelled learned/approximate so no consumer mistakes them for kernel-exact.

    ``available`` is False whenever the diagnostic could not run (opt-out, too few bins, or
    no kernel frames) — callers then show "not evaluated", never a misleading 0.0."""

    available: bool = False
    learned_fit: float = 0.0       # mean cosine: learned rollout vs observed (held-out)
    kernel_fit: float = 0.0        # mean cosine: kernel load vs observed (held-out)
    margin: float = 0.0            # learned_fit - kernel_fit (>0 => learned beats kernel)
    learned_better: bool = False
    n_eval_bins: int = 0           # held-out bins actually scored
    n_train_bins: int = 0          # bins used to fit the velocity field
    provenance: str = PROVENANCE
    note: str = ""

    def as_dict(self) -> dict:
        """JSON-safe summary for the advisory API block (native floats, no numpy leak)."""
        return {
            "available": bool(self.available),
            "learned_fit": round(float(self.learned_fit), 3),
            "kernel_fit": round(float(self.kernel_fit), 3),
            "margin": round(float(self.margin), 3),
            "learned_better": bool(self.learned_better),
            "n_eval_bins": int(self.n_eval_bins),
            "n_train_bins": int(self.n_train_bins),
            "provenance": self.provenance,
            "note": self.note,
        }


def _kernel_profile_at(result: SimResult, t: float) -> np.ndarray | None:
    """The kernel's recorded ``load`` profile at the frame nearest sim-time ``t``; None
    when the run has no frames. Read-only — never mutates the result."""
    if not result.frames:
        return None
    times = np.array([float(fr["t"]) for fr in result.frames], dtype=float)
    j = int(np.argmin(np.abs(times - t)))
    return np.asarray(result.frames[j]["load"], dtype=float)


def evaluate(
    node_counts: dict[str, dict[float, float]] | None,
    result: SimResult,
    *,
    train_fraction: float = 0.6,
    force: bool = False,
) -> LearnedDynamicsReport:
    """Fit the learned velocity field on the first ``train_fraction`` of observed bins,
    roll it out, and score learned-vs-kernel on the held-out tail.

    Advisory only: consulted *alongside* a finished kernel ``result`` (never inside the
    loop, never feeding ``J``). Returns ``available=False`` — a clean no-op — when the
    feature is off, the data is too thin (< 3 observed bins), or the run has no frames.
    ``force`` runs the math regardless of the env flag (for tests); production callers
    leave it False so the flag governs.

    Inputs are validated at this boundary: a ``None``/empty series, a frame-less result,
    or a degenerate split all short-circuit to the no-op report rather than raising.
    """
    if not force and not learned_dynamics_enabled():
        return LearnedDynamicsReport(note="disabled (URBANOS_LEARNED_DYNAMICS unset)")
    if not node_counts:
        return LearnedDynamicsReport(note="no observed series")
    if not result.frames:
        return LearnedDynamicsReport(note="run produced no frames")

    sub = result.substrate
    obs, bins = _observed_matrix(node_counts, sub)
    n_bins = len(bins)
    if n_bins < 3:
        return LearnedDynamicsReport(note="too few observed bins (<3)")

    # Train/eval split: fit the field on the leading bins, score on the held-out tail so
    # the comparison is genuinely predictive (no fitting on what we then grade).
    n_train = max(2, int(round(n_bins * float(np.clip(train_fraction, 0.1, 0.9)))))
    n_train = min(n_train, n_bins - 1)  # always leave at least one eval bin
    if n_train < 2:
        return LearnedDynamicsReport(note="split leaves <2 training bins")

    B = _incidence(sub)
    # Fit one edge-flow field per training transition from the observed mass changes.
    flows = [_fit_edge_flows(B, obs[k + 1] - obs[k]) for k in range(n_train - 1)]
    # Mean field = the average learned velocity; reused to extrapolate over the eval tail
    # (we learn the typical bin-to-bin transport, then predict forward — the honest test
    # of a *learned dynamic*, not a per-bin interpolation that would peek at the answer).
    mean_flow = (
        np.mean(np.stack(flows, axis=0), axis=0) if flows else np.zeros(sub.n_edges)
    )
    horizon = n_bins - n_train  # eval bins to predict
    seed = obs[n_train - 1]      # last training marginal = rollout seed
    rollout = _rollout(B, [mean_flow] * horizon, seed)

    # Score the held-out tail: learned rollout vs observed, kernel load vs observed.
    # Sim time for an observed bin = its minute on the rebased observed axis (the ingest
    # rebases the first observed bin to 0; the kernel clock starts at 0 too).
    learned_scores: list[float] = []
    kernel_scores: list[float] = []
    eval_bins = 0
    for h in range(1, horizon + 1):
        bin_idx = n_train - 1 + h
        observed_prof = obs[bin_idx]
        if float(observed_prof.sum()) <= 0.0:
            continue
        learned_prof = rollout[h]
        kernel_prof = _kernel_profile_at(result, bins[bin_idx])
        if kernel_prof is None:
            continue
        learned_scores.append(_cosine(learned_prof, observed_prof))
        kernel_scores.append(_cosine(kernel_prof, observed_prof))
        eval_bins += 1

    if eval_bins == 0:
        return LearnedDynamicsReport(
            n_train_bins=n_train, note="no scorable held-out bins"
        )

    learned_fit = float(np.mean(learned_scores))
    kernel_fit = float(np.mean(kernel_scores))
    margin = learned_fit - kernel_fit
    return LearnedDynamicsReport(
        available=True,
        learned_fit=learned_fit,
        kernel_fit=kernel_fit,
        margin=margin,
        learned_better=margin > 0.0,
        n_eval_bins=eval_bins,
        n_train_bins=n_train,
        note="Action-Matching floor (least-squares velocity fit; advisory)",
    )

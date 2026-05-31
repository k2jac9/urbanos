"""Spatial risk-hotspot clustering (ADR-0025): a genuine cuML use.

Groups scored civic addresses into K geographic *risk hotspots* — clustering on
(lat, lng) weighted toward high-risk sites — so the Safety lens can say "the city's
risk collapses into N hotspots" instead of listing 27 pins. This is a NEW analysis,
not a retrofit: cuML's GPU KMeans (sklearn-compatible) runs it when available; a
small, deterministic, dependency-free numpy KMeans is the fallback so it works
offline and in CI. The clustering itself is identical in shape either way; only the
compute backend differs (the GPU win is at city scale, not the demo's ~27 pins).
"""
from __future__ import annotations

import math
import os

import numpy as np

# Which backend produced the last clustering: "cuml" (RAPIDS GPU) or "numpy" (CPU).
CLUSTER_BACKEND: str = "numpy"


def _gpu_cluster_enabled() -> bool:
    """Opt-in: ``URBANOS_GPU_CLUSTER=1`` on a box with RAPIDS ``cuml`` installed."""
    return os.environ.get("URBANOS_GPU_CLUSTER", "").strip().lower() in {"1", "true", "yes"}


def _features(addresses: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """(N,2) lat/lng matrix + (N,) risk weight (max of the two indices)."""
    pts, risk = [], []
    for a in addresses:
        lat, lng = a.get("lat"), a.get("lng")
        if lat is None or lng is None:
            continue
        pts.append((float(lat), float(lng)))
        risk.append(max(float(a.get("risk_safety", 0.0)), float(a.get("risk_activity", 0.0))))
    return np.array(pts, dtype=float), np.array(risk, dtype=float)


def _kmeans_numpy(x: np.ndarray, k: int, *, seed: int = 0, iters: int = 50) -> np.ndarray:
    """Deterministic Lloyd's k-means → (N,) integer labels. Seeded, fixed iterations
    so the CPU result is reproducible (offline-safe, no sklearn dependency)."""
    n = len(x)
    rng = np.random.default_rng(seed)
    # k-means++-lite: first centroid random, rest are the farthest points (seeded).
    centroids = [x[rng.integers(n)]]
    for _ in range(1, k):
        d = np.min([np.sum((x - c) ** 2, axis=1) for c in centroids], axis=0)
        centroids.append(x[int(np.argmax(d))])
    cen = np.array(centroids)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dists = np.stack([np.sum((x - c) ** 2, axis=1) for c in cen])
        new = np.argmin(dists, axis=0)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            members = x[labels == j]
            if len(members):
                cen[j] = members.mean(axis=0)
    return labels


def risk_hotspots(addresses: list[dict], *, k: int = 4, seed: int = 0) -> list[dict]:
    """Cluster scored addresses into ``k`` geographic risk hotspots, hottest first.

    Uses cuML's GPU KMeans when enabled+installed, else the deterministic numpy
    KMeans. Returns one dict per non-empty cluster: centroid lat/lng, member count,
    and mean/max risk — ordered by mean risk (the hottest zone first)."""
    global CLUSTER_BACKEND
    pts, risk = _features(addresses)
    if len(pts) == 0:
        CLUSTER_BACKEND = "numpy"
        return []
    k = max(1, min(int(k), len(pts)))

    labels = None
    if _gpu_cluster_enabled():
        try:
            from cuml.cluster import KMeans as cuKMeans  # type: ignore

            labels = cuKMeans(n_clusters=k, random_state=seed).fit_predict(pts)
            labels = np.asarray(labels).astype(int)
            CLUSTER_BACKEND = "cuml"
        except Exception:  # cuml missing / runtime error → CPU
            labels = None
    if labels is None:
        labels = _kmeans_numpy(pts, k, seed=seed)
        CLUSTER_BACKEND = "numpy"

    out: list[dict] = []
    for j in range(int(labels.max()) + 1 if len(labels) else 0):
        sel = labels == j
        if not sel.any():
            continue
        cl_pts, cl_risk = pts[sel], risk[sel]
        out.append({
            "centroid_lat": round(float(cl_pts[:, 0].mean()), 6),
            "centroid_lng": round(float(cl_pts[:, 1].mean()), 6),
            "size": int(sel.sum()),
            "mean_risk": round(float(cl_risk.mean()), 3),
            "max_risk": round(float(cl_risk.max()), 3),
        })
    out.sort(key=lambda c: c["mean_risk"], reverse=True)
    return out

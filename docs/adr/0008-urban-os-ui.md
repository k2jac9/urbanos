# ADR-0008 — Urban-OS offline map UI: heatmap, time-slider, lever, before/after

- **Status:** accepted
- **Date:** 2026-05-30

## Context

Urban-OS already exposes three same-origin JSON endpoints (`/scenario`,
`/simulate`, `/optimize`) and a single-file map page (`urban_os.html`). The
demo's job is to make the simulation *legible on the map*: an operator should
see where the post-event crowd crush builds (a congestion/risk **heatmap**),
scrub the simulation over time (a **time-slider** over `/simulate` frames),
pull a **staggered-release lever** and watch the peak flatten, and read a
grounded **before/after** briefing from `/optimize` (cited insight + dollars
saved).

Two hard constraints shaped the design:

1. **100% offline (project invariant).** The map must work on the GX10 with no
   network: no CDN, no tile server, no external script/style. The repo already
   vendors MapLibre GL JS/CSS, the PMTiles JS, and a self-hosted
   `toronto.pmtiles` basemap under `civic_analyst/.../static`, which the API
   mounts at `/static`. The UI may reference **only** `/static` and same-origin
   API paths.
2. **One single-file page, < 500 lines.** Keeping the whole UI in one
   dependency-free HTML file (no build step, no npm) is what makes it trivially
   offline and reviewable.

The starting page already had the slider, the lever, and the before/after
panel, plus per-node colored circles. What it lacked was an actual **heatmap**
(the task calls for a congestion/risk heatmap over the substrate nodes, not
just discrete dots) and an offline-safety regression test.

## Decision

**Heatmap as a MapLibre `heatmap` layer over the existing `nodes` source.**
Rather than a second data source or a separate fetch, the heatmap reuses the
same GeoJSON `nodes` source that already drives the circles. Each node feature
gains a `weight` property derived from the *current frame*: clamped congestion
(or risk, when toggled), with sinks/exits forced to `0` so they never glow. The
heatmap layer sits **below** the circle + label layers so the precise dots and
names stay readable on top of the glow. `setData` on the shared source updates
both layers every time the slider/lever/optimize changes the frame — no extra
plumbing.

**Two client-only toggles, no refetch.** A `🔥 Heatmap` button flips
`heatmap-opacity` (0 ↔ 0.75) so an operator can fall back to the discrete view;
a `Weight: congestion/risk` button re-derives the per-node weight from the
*same already-loaded frame* and calls `refreshNodes()`. Neither toggle hits the
network — they are pure presentation over data we already have, which keeps
them instant and offline-trivial.

**Same-origin everything.** Vendored assets are referenced by `/static/...`
paths; the PMTiles URL is built at runtime as
`pmtiles://${location.origin}/static/toronto.pmtiles` (same-origin by
construction); the three endpoints are fetched by bare absolute paths
(`/scenario`, `/simulate?...`, `/optimize`). No absolute external URL exists in
the file.

**Offline-safety regression test (`tests/test_urban_ui_offline.py`).** The test
fetches `/` through a FastAPI `TestClient` (exercising the real route) and
asserts three things: (1) no external/CDN/tile-server host appears — a curated
forbidden-substring list (unpkg, jsdelivr, cdnjs, mapbox, cartocdn,
tile.openstreetmap, demotiles.maplibre, protocol-relative `//host`, etc.) plus
a regex that rejects any concrete `http(s)://host` other than the OSM
attribution credit and the same-origin `location.origin` template; (2) the
vendored assets are both *referenced* and *actually served* (status 200, plus a
Range request on the PMTiles); (3) the load-bearing UI hooks exist — slider,
release lever, play, heatmap layer + toggle, optimize button + output panel —
and that the page really wires a `type: 'heatmap'` layer and consumes all three
endpoints. A refactor that drops any of these fails loudly.

## Consequences

- The crush is now visible as a **glow that grows and drains** as you scrub
  time or pull the lever, which reads instantly in a demo; the discrete dots
  remain for exact per-node inspection (hover popups unchanged).
- The offline invariant is now **machine-enforced**, not just convention: a
  stray CDN `<script>` can no longer slip into the demo unnoticed — CI catches
  it. This is the most valuable part of the workstream for demo safety.
- The heatmap/weight toggles add **no network dependency and no new endpoint**;
  they are pure client transforms over data already fetched, so they cannot
  break the offline guarantee.
- I deliberately did **not** add a risk-specific `/simulate` parameter or a
  separate heatmap data source. The frames already carry `risk` per node, so
  the risk view is a free client-side re-weighting. Less surface area, same
  capability.
- Trade-off: the OSM attribution string `© OpenStreetMap` stays as a credit
  (required by the basemap licence) but is **not** a fetched URL. The test
  allows only the bare attribution host and nothing else, so the credit can't
  be mistaken for an offline-violating resource.
- The page is 336 lines — comfortably under the 500-line cap — and remains
  build-free single-file HTML, so it stays trivially auditable and offline.

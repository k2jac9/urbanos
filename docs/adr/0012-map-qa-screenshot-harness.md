# ADR-0012 — Map QA via a Playwright CDP harness, not one-shot headless

## Status
Accepted.

## Context
The maps (core civic map + Urban-OS) are WebGL2 + a PMTiles vector basemap. We
need an agent/CI-runnable way to screenshot them for visual QA after dependency
bumps (MapLibre v5, pmtiles v4, the glyphs fix), instead of always needing a
human to eyeball a real browser.

One-shot headless captures do **not** work for this stack. Tried on both a
GPU-less laptop (SwiftShader) and the GPU box, across flag combinations:

    chromium --headless=new [--enable-unsafe-swiftshader] \
             --virtual-time-budget=20000 --screenshot=out.png URL

Every attempt produced a blank basemap with the panel stuck on "Loading…". Root
cause is `--virtual-time-budget`: it freezes the wall clock and captures when the
virtual budget is spent, but MapLibre's async PMTiles range-request loading +
WebGL2 render pipeline never settle under frozen time, so the map's `load` event
(which the page's data fetches are gated on) never fires. This is independent of
GPU vs software rendering — it's a timing-model problem, not a rasterizer one.

## Decision
Add `scripts/screenshot_map.py` — a Playwright (CDP) harness that drives a real
browser with **real time flowing** and explicitly waits for the map to finish
before capturing:

1. launch chromium with GPU-friendly args (`--use-gl=angle --use-angle=gl-egl
   --ignore-gpu-blocklist`), falling back to SwiftShader when no GPU;
2. `goto(url)`, wait for the `.maplibregl-canvas`, then `networkidle` (PMTiles
   range requests settle), then a page-agnostic readiness probe (canvas drawn +
   the "Loading…" placeholder cleared, honouring `window.__mapReady` if a page
   sets it);
3. a short settle, then `screenshot()`.

Run it **on the box** (real NVIDIA GPU → faithful render) from a dedicated QA
venv so the demo venv stays pristine:

    python3 -m venv ~/.qa-venv
    ~/.qa-venv/bin/pip install playwright && ~/.qa-venv/bin/playwright install chromium
    ~/.qa-venv/bin/python scripts/screenshot_map.py http://localhost:8001/ /tmp/shot.png

`make screenshot URL=… OUT=…` wraps the local invocation.

## Consequences
- Off-box agents can self-verify the maps (basemap, pins, 3D skyline, heatmap,
  labels) by capturing on the box and pulling the PNG — no human eyeball needed
  for routine checks. Verified rendering MapLibre v5 + pmtiles v4 + glyphs.
- The QA venv + Playwright chromium live on the box only (not committed); this
  ADR records the setup. It is a QA tool, never part of the served demo.
- Re-confirmed invariant: the demo itself is offline; the harness only loads
  same-origin localhost pages.

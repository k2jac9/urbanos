#!/usr/bin/env python3
"""Render a MapLibre+PMTiles page to a PNG, waiting until the map is actually drawn.

Why this exists: one-shot headless captures (`chrome --screenshot
--virtual-time-budget=...`) freeze the clock mid-load, so the WebGL2 + PMTiles
basemap never finishes rendering and you get a blank map. This drives a real
browser via CDP (Playwright), lets real time flow, and waits for the map's
`load` event before capturing — so off-box agents can self-verify the maps
instead of needing a human to eyeball them.

Run it on the box (real NVIDIA GPU) for faithful rendering:

    ~/.qa-venv/bin/python scripts/screenshot_map.py http://localhost:8001/ /tmp/shot.png

Readiness is detected without modifying the page: we wait for the map canvas to
exist, for network to go idle (PMTiles range requests settle), and — when the
page exposes one — a `window.__mapReady`/`map.loaded()` signal; then a short
settle for the final tile paint.
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

# Args chosen so headless chromium uses the real GPU when present (the box) and
# still works on a GPU-less host (SwiftShader) — just slower.
_LAUNCH_ARGS = [
    "--use-gl=angle",
    "--use-angle=gl-egl",
    "--ignore-gpu-blocklist",
    "--enable-unsafe-swiftshader",  # harmless when a real GPU is used
    "--no-sandbox",
    "--hide-scrollbars",
]

# JS that resolves true once MapLibre has fired 'load' on the page's map. The
# maps keep `map` module-scoped, so we sniff the rendered canvas + the absence of
# the panel's "Loading…" placeholder as a page-agnostic readiness proxy.
_READY_JS = """() => {
  const c = document.querySelector('.maplibregl-canvas');
  if (!c || c.width === 0) return false;
  if (window.__mapReady === true) return true;       // honoured if a page sets it
  const body = document.body ? document.body.innerText : '';
  return !/Loading(\\b|\\u2026|\\.\\.\\.)/i.test(body); // 'Loading…' cleared
}"""


def shoot(url: str, out: str, settle_ms: int = 2500, timeout_ms: int = 30000) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.goto(url, wait_until="load", timeout=timeout_ms)
        page.wait_for_selector(".maplibregl-canvas", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass  # networkidle is best-effort; the readiness probe is the gate
        try:
            page.wait_for_function(_READY_JS, timeout=timeout_ms)
        except Exception:
            print("warn: map-ready probe timed out; capturing current frame", file=sys.stderr)
        page.wait_for_timeout(settle_ms)  # final tile paint
        page.screenshot(path=out)
        browser.close()


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: screenshot_map.py <url> <out.png> [settle_ms]", file=sys.stderr)
        return 2
    settle = int(sys.argv[3]) if len(sys.argv) > 3 else 2500
    shoot(sys.argv[1], sys.argv[2], settle_ms=settle)
    print(f"wrote {sys.argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

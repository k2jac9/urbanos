# Antigravity Browser QA prompts

Reusable prompts for the **Antigravity agent's Browser Control** to QA the demo.
Paste these into the **Antigravity conversation** (not the Claude Code terminal) — the
Antigravity agent is what drives the live browser overlay.

**Before running:** start the demo (`make demo`) so the server is up on
<http://localhost:8000/>. Pins are **clicked on the map** (there is no search box), and
each "✓ verify" link reveals a grounded source line.

---

## Quick smoke test

```
Open http://localhost:8000/ in the browser.

Verify the Toronto Civic Risk Analyst demo works end-to-end:
1. Wait for the map to finish loading. Confirm the offline basemap renders
   (Toronto streets + the lake) and that ~17 colored risk pins appear
   (red = high risk, green = low). The right panel should say
   "N addresses. Click a pin."
2. Click one of the RED pins in the upper-center of the map (the Bloor St area).
3. Confirm the right "Assessment" panel populates with: a large risk score number,
   the address, agent findings (retrieval / compliance lines), and a list of claims.
4. Click a green "✓ verify" link next to a claim. Confirm a grey source line
   appears beneath it, starting with "↳ source E1: [Building Permits …]".
5. Report PASS/FAIL with a screenshot of the populated panel.
```

---

## Thorough QA (offline + robustness)

```
Open http://localhost:8000/ and do a QA pass on the Toronto Civic Risk Analyst:

A. Offline integrity: open DevTools → Network, hard-reload, and confirm NO requests
   go to any external/CDN/tile-server domain — everything should be same-origin
   (/static, /addresses, /analyze). Flag any external request.
B. Map render: confirm streets, water, and ~17 risk pins draw with no console errors.
C. Interaction: click several different pins; each time the right panel should
   refresh with that address's score, findings, and claims.
D. Click-to-verify: for a pin with claims, click each "✓ verify" link and confirm
   each reveals its own "↳ source …" line (and that they start hidden).
E. Resize the window narrow/wide and confirm the layout (map + side panel) stays usable.

Give me a PASS/FAIL per section (A–E) with screenshots and any console errors.
```

---

## Targeting a specific address (deterministic)

Picking the exact "500 Bloor St W" pin visually is hard. To target it deterministically,
tell the agent:

```
In the DevTools console run:  analyze('500 BLOOR ST W')
Then click the first "✓ verify" link and confirm the "↳ source …" line appears.
```

`analyze(address)` is a hoisted global; calling it is equivalent to clicking that
address's pin. This is the same hook the scripted check
(`scripts/e2e_click.py`) uses.

## See also

- `scripts/e2e_click.py` — headless Playwright version of the same click-to-verify check.
- `docs/ON_THE_BOX.md` — GX10-day runbook.
```

# ADR-0034 — Unify the source packages under `urbanos`

**Status:** Accepted · **Date:** 2026-06-20 · **Relates:** ADR-0033 (UrbanOS platform
unification — this completes its deferred step 4), ADR-0001 (kernel-on-civic architecture) ·
**Supersedes:** the *deferral* in ADR-0033 §Decision-4

## Context

ADR-0033 unified the product as **UrbanOS** but deliberately **deferred** the source-package
rename (a large refactor: imports, tests, 30+ ADR refs). So the Python packages stayed
`urban_os` (the simulation kernel + the unified shell/API and its lenses) and `civic_analyst`
(the address-level civic-risk engine, now surfaced as the Risk lens). With the UX redesign arc
landed and CI-green, the package names were the last thing still reading as "two apps."

## Decision

Consolidate both packages under one top-level `urbanos` package:

| Was | Now |
|-----|-----|
| `urban_os` | `urbanos.kernel` |
| `civic_analyst` | `urbanos.risk` |
| `urban_os.kernel` (the simulation-kernel subpackage) | `urbanos.kernel.kernel` |

- **Mechanical, behaviour-preserving.** Every import, test path, uvicorn target, Makefile /
  Dockerfile module path, the MCP entry (`urbanos.risk.mcp_server`), and the `_OFFLINE_ASSETS`
  static-dir computation were updated. The suite stays **584 passed / 1 skipped**.
- **Run targets:** `urbanos.kernel.api:app` (the shell at `/`), `urbanos.risk.api.server:app`
  (the Risk engine, mounted at `/civic`), CLIs `urbanos.kernel.cli` / `urbanos.risk.cli`.
- **Left unchanged on purpose:**
  - the Rust accelerator's compiled module name **`urban_os_native`** — a box-only, aarch64
    build artifact; renaming it is orthogonal and would force a rebuild. `accel.py` still
    imports it; the numpy fallback is unchanged.
  - the static filename **`urban_os.html`** (the classic single-view page).
  - **ADRs ≤ 0033**, which reference the former package names `urban_os` / `civic_analyst` and
    are **preserved as historical records** — this ADR is the forward pointer.

## Known wrinkle

`urbanos.kernel.kernel` (the simulation kernel *inside* the kernel app) is doubled. It is the
faithful, minimal-surprise mapping of `urban_os` → `urbanos.kernel`; a future cleanup could
rename the inner module if the doubling proves annoying.

## Honesty / invariants (unchanged)

A pure rename — no behaviour change. The golden numbers (do-nothing **J $323,222** → best
**$105,050**), the 100%-offline map, the hallucination guard, and all data contracts hold. The
local **folder** rename (`…\spark-hack-toronto` → `…\UrbanOS`) remains a separate, manual final
step — a live working directory can't be renamed mid-session.

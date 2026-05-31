# ADR-0023 — Decouple the two apps via public seams

**Status:** Accepted · **Date:** 2026-05-31 · **Relates:** ADR-0001 (urban-os kernel on civic), ADR-0022 (api structure)

## Context

`urban_os` is genuinely built *on* `civic_analyst` (ADR-0001), but the two were
joined at two brittle seams the audit flagged as failing *invisibly*:

1. **Private-global mount hack.** `urban_os/api.py::_load_civic_graph` reached into
   `civic_analyst.api.server._graph`, `.load_into_graph`, and `.settings` to
   reproduce the civic lifespan (a mounted sub-app's lifespan does not reliably fire
   under this Starlette version). Any rename in civic's server would silently yield an
   empty `/civic/*` — and the `except Exception: pass` swallowed it with no signal.
2. **In-adapter import + unresettable global.** `adapters/toronto.py::_civic_addresses`
   imported `civic_analyst.mcp_server` inside the function and memoised into a
   module-global cache. A "Toronto adapter" shouldn't know civic's loader is
   non-idempotent, and the process-global cache couldn't be reset by tests.

## Decision

1. **Public load entrypoint.** `civic_analyst.api.server` now exposes `load_graph()`
   (idempotent clear+reload, returns the summary) and `ensure_loaded()` (load only if
   empty). Civic's own lifespan uses `load_graph()`. `urban_os._load_civic_graph` calls
   that public function instead of poking private globals, and **logs** a failure
   instead of silently swallowing it.
2. **Injectable address provider.** `civic_safety_by_node(substrate, *, address_provider=None)`
   takes an optional `() -> list[dict]` provider. The default still pulls from
   civic_analyst (standalone behaviour unchanged), but tests/other adapters can inject
   their own, so the adapter no longer *hard*-depends on civic internals. Added
   `reset_civic_address_cache()` so the process-global cache is resettable.

## Consequences

- A civic-side refactor can no longer silently break `/civic/*`; the coupling is a
  named public function, and a load failure is now visible in logs.
- The Toronto adapter's civic dependency is the *default*, not the *only* path — the
  fusion is unit-testable in isolation (an injected provider, no civic import), and the
  synthetic offline fallback is exercised directly.
- **Behaviour-preserving:** all endpoints and the `/civic` mount behave identically;
  `make urbanos-cli` unchanged (3.73× / 14-min / ~$218k). 401 tests pass.

## Tests

`tests/test_app_decoupling.py`: public `load_graph`/`ensure_loaded` exist and work; an
injected provider drives the overlay with no civic import; a failing/empty provider
falls back to the synthetic overlay; the cache reset is callable.

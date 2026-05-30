.PHONY: install install-hooks data serve cli test demo demo-public funnel-off demo-cli demo-data \
        urbanos urbanos-cli urbanos-accel urbanos-bench

# demo  -> real downtown-Toronto slice (demo_data/), pins land on the offline map.
# demo-cli/tests -> synthetic, deterministic fixtures/.
DEMO_DATA ?= demo_data
FIXTURES ?= fixtures

# Prefer the project venv if present, so `make test` works whether or not the
# venv is activated in the current shell. Override with `make PYTHON=...`.
PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python)

install:
	$(PYTHON) -m pip install -r requirements.txt

# Run once per clone (you AND your teammate). Enables the shared pre-push hook
# that blocks pushing a red test suite. Bypass an emergency push with --no-verify.
install-hooks:
	chmod +x scripts/hooks/*
	git config core.hooksPath scripts/hooks
	@echo "Pre-push hook enabled (core.hooksPath=scripts/hooks)."

data:
	$(PYTHON) scripts/download_data.py

serve:
	$(PYTHON) -m uvicorn civic_analyst.api.server:app --reload --port 8000 --app-dir src

cli:
	$(PYTHON) -m civic_analyst.cli analyze "100 Queen St W"

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

# One-command demo: serve the API + offline map against REAL downtown Toronto data.
demo:
	@echo "Serving REAL downtown Toronto data (demo_data/). Once up:"
	@echo "  open http://localhost:8000/                 # offline map, real establishments"
	@echo "  curl 'http://localhost:8000/health'"
	DATA_DIR=$(DEMO_DATA) $(PYTHON) -m uvicorn civic_analyst.api.server:app --port 8000 --app-dir src

# Public demo: same as `make demo`, but also flips this box's Tailscale Funnel
# ON (public read-only HTTPS URL) for the session and turns it OFF on exit.
# Funnel is best-effort: off-box / without operator+policy it just runs local.
# See docs/REMOTE_ACCESS.md.
demo-public:
	@echo "Public demo: real downtown data + Tailscale Funnel (read-only HTTPS)."
	@if command -v tailscale >/dev/null 2>&1 && tailscale funnel --bg 8000 >/dev/null 2>&1; then \
	  url=$$(tailscale funnel status 2>/dev/null | grep -oE 'https://[^ ]+' | head -1); \
	  echo "  PUBLIC: $$url   (share with judges)"; \
	  echo "  Stop with Ctrl-C. If the public URL stays up afterwards, run: make funnel-off"; \
	  trap 'tailscale funnel --https=443 off >/dev/null 2>&1' EXIT INT TERM; \
	else \
	  echo "  (Funnel unavailable — serving local-only; see docs/REMOTE_ACCESS.md)"; \
	fi; \
	echo "  LOCAL:  http://localhost:8000/"; \
	DATA_DIR=$(DEMO_DATA) $(PYTHON) -m uvicorn civic_analyst.api.server:app --port 8000 --app-dir src

# Reliably take the public demo URL down (Funnel off). Run after a public demo.
funnel-off:
	@tailscale funnel --https=443 off 2>/dev/null && echo "Funnel off — public URL is down." \
	  || echo "Funnel was not on (or tailscale unavailable)."

# Rebuild the real downtown slice from the live dataset.
demo-data:
	PYTHONPATH=src $(PYTHON) scripts/build_demo_slice.py

# Quick deterministic check (synthetic fixtures): prints a populated report and exits.
demo-cli:
	DATA_DIR=$(FIXTURES) PYTHONPATH=src $(PYTHON) -m civic_analyst.cli analyze "100 Queen St W"

# ---- Urban-OS: the dynamics-kernel demo (event egress → optimized intervention) ----

# Serve the Urban-OS simulation + offline heatmap/time-slider map at :8000.
urbanos:
	@echo "Urban-OS map at http://localhost:8000/ (offline). Endpoints: /scenario /simulate /optimize"
	PYTHONPATH=src $(PYTHON) -m uvicorn urban_os.api:app --port 8000 --app-dir src

# One-shot CLI: run + optimize the downtown egress scenario, print the cited insight.
urbanos-cli:
	PYTHONPATH=src $(PYTHON) -m urban_os.cli

# Build the optional Rust accelerator (aarch64) and report the active backend.
# Falls back to numpy automatically if this is skipped — the demo never needs it.
urbanos-accel:
	$(PYTHON) -m pip install -q maturin
	$(dir $(PYTHON))maturin develop --release -m native/Cargo.toml
	@PYTHONPATH=src $(PYTHON) -c "from urban_os.kernel import accel; print('Urban-OS transport backend:', accel.backend_name())"

# Benchmark the active transport backend vs the numpy reference: asserts f64
# parity (when rust is built) and reports the wall-clock speedup. Runs anywhere
# and degrades to a numpy-only baseline when the rust core is absent.
urbanos-bench:
	PYTHONPATH=src $(PYTHON) scripts/bench_urbanos_accel.py

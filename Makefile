.PHONY: install install-linux install-hooks data serve cli test demo demo-public funnel-off funnel-off-all \
        demo-cli demo-data urbanos urbanos-cli urbanos-accel urbanos-bench screenshot \
        gpu-install gpu-check gpu-check-wsl llm-check dev dev-down dev-status

# demo  -> real downtown-Toronto slice (demo_data/), pins land on the offline map.
# demo-cli/tests -> synthetic, deterministic fixtures/.
DEMO_DATA ?= demo_data
FIXTURES ?= fixtures

# Prefer a project venv if present, so `make test` works whether or not the venv
# is activated in the current shell. Order: WSL-native .venv-linux (the checked-in
# .venv may be a Windows venv that WSL can't run), then POSIX .venv, then python.
# Override with `make PYTHON=...`.
PYTHON ?= $(shell [ -x .venv-linux/bin/python ] && echo .venv-linux/bin/python || ([ -x .venv/bin/python ] && echo .venv/bin/python || echo python))

install:
	$(PYTHON) -m pip install -r requirements.txt

# Build a WSL/Linux venv (.venv-linux) from the pinned lock with uv. Use this on
# WSL where the checked-in .venv is a Windows venv (Scripts/, not bin/) and can't run.
# Needs `uv` (https://docs.astral.sh/uv/). After this, `make test` / `make dev` just work.
install-linux:
	uv venv .venv-linux --python 3.12
	uv pip install --python .venv-linux -r requirements.lock

# Install the optional RAPIDS GPU accelerators — ON THE BOX ONLY (aarch64 + CUDA).
# The app falls back to CPU without these, so dev/CI never need them.
gpu-install:
	$(PYTHON) -m pip install --extra-index-url=https://pypi.nvidia.com -r requirements-gpu.txt

# Prove which backend each GPU seam actually used (nx-cugraph / cuDF-Polars). On the
# box with gpu-install done, expect "cugraph" / "cudf-polars"; elsewhere CPU fallback.
gpu-check:
	URBANOS_GPU_GRAPH=1 URBANOS_GPU_DF=1 PYTHONPATH=src $(PYTHON) scripts/gpu_check.py

# Re-runnable one-shot that proves the GPU seams (cugraph + cudf-polars) GENUINELY
# run on a consumer NVIDIA GPU in WSL-native ext4 (proven on an RTX 2060). It applies
# the two non-obvious fixes (cudart-headers 12.9.* pin + LD_LIBRARY_PATH from the venv's
# native-lib dirs) then runs scripts/gpu_check.py. Run from Windows: shells into WSL and
# uses the ext4 runtime clone at ~/spark-hack-toronto (override WSL_REPO / WSL_DISTRO).
# Expects "GPU paths active: {'graph': 'cugraph', 'ingest': 'cudf-polars'}". The env must
# already exist (make install-linux + RAPIDS accelerators — see the script header).
WSL_DISTRO ?= Ubuntu-24.04
WSL_REPO   ?= ~/spark-hack-toronto
gpu-check-wsl:
	wsl.exe -d $(WSL_DISTRO) -- bash -lc 'cd $(WSL_REPO) && ./scripts/gpu_check_wsl.sh'

# Prove which LLM runtime serves the narrator (ADR-0027). On the box with the model
# behind trtllm-serve + LLM_RUNTIME=tensorrt-llm, expect "tensorrt-llm" + a tok/s
# number; elsewhere it reports the configured runtime or an honest offline result.
llm-check:
	PYTHONPATH=src $(PYTHON) scripts/llm_check.py

# Run once per clone (you AND your teammate). Enables the shared pre-push hook
# that blocks pushing a red test suite. Bypass an emergency push with --no-verify.
install-hooks:
	chmod +x scripts/hooks/*
	git config core.hooksPath scripts/hooks
	@echo "Pre-push hook enabled (core.hooksPath=scripts/hooks)."

data:
	$(PYTHON) scripts/download_data.py

serve:
	$(PYTHON) -m uvicorn urbanos.risk.api.server:app --reload --port 8000 --app-dir src

cli:
	$(PYTHON) -m urbanos.risk.cli analyze "100 Queen St W"

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

# One-command demo: the UNIFIED UrbanOS platform (one app, every lens) on REAL data.
# Serves the UrbanOS shell at / and the Risk lens (civic risk) at /civic — one front door.
demo:
	@echo "Serving the unified UrbanOS platform on REAL downtown data (demo_data/). Once up:"
	@echo "  open http://localhost:8000/                 # UrbanOS shell — lenses over one map"
	@echo "  open http://localhost:8000/civic/           # Risk lens — address-level civic risk"
	DATA_DIR=$(DEMO_DATA) PYTHONPATH=src $(PYTHON) -m uvicorn urbanos.kernel.api:app --port 8000 --app-dir src

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
	DATA_DIR=$(DEMO_DATA) $(PYTHON) -m uvicorn urbanos.risk.api.server:app --port 8000 --app-dir src

# Reliably take the urbanos.risk public demo URL down (Funnel :443 off). Run after a public demo.
funnel-off:
	@tailscale funnel --https=443 off 2>/dev/null && echo "Funnel off — urbanos.risk public URL is down." \
	  || echo "Funnel was not on (or tailscale unavailable)."

# Take BOTH public demo URLs down: urbanos.risk (:443->:8000) AND urbanos.kernel (:8443->:8001).
# Use this on the box when wrapping up — the urbanos.kernel Funnel isn't covered by `make funnel-off`.
funnel-off-all:
	@tailscale funnel --https=443 off 2>/dev/null && echo "Funnel off — urbanos.risk (:443) public URL is down." \
	  || echo "urbanos.risk Funnel was not on (or tailscale unavailable)."
	@tailscale funnel --https=8443 off 2>/dev/null && echo "Funnel off — urbanos.kernel (:8443) public URL is down." \
	  || echo "urbanos.kernel Funnel was not on (or tailscale unavailable)."

# Rebuild the real downtown slices from the live datasets (static civic + dynamic
# multimodal counts). Both are offline-safe: a network failure leaves existing
# slices in place and the synthetic fallbacks cover dev/CI.
demo-data:
	PYTHONPATH=src $(PYTHON) scripts/build_demo_slice.py
	PYTHONPATH=src $(PYTHON) scripts/fetch_tmc.py
	PYTHONPATH=src $(PYTHON) scripts/fetch_bikeshare.py
	PYTHONPATH=src $(PYTHON) scripts/fetch_ttc_boardings.py
	PYTHONPATH=src $(PYTHON) scripts/fetch_gtfs_supply.py

# Quick deterministic check (synthetic fixtures): prints a populated report and exits.
# 100 Queen St W → two independent indices (ADR 0014):
#   safety 0.593 (medium, 2 adverse visits) · activity 0.113 (low, 2 open permits).
demo-cli:
	DATA_DIR=$(FIXTURES) PYTHONPATH=src $(PYTHON) -m urbanos.risk.cli analyze "100 Queen St W"

# ---- Urban-OS: the dynamics-kernel demo (event egress → optimized intervention) ----

# Serve the Urban-OS simulation + offline heatmap/time-slider map at :8000.
urbanos:
	@echo "Urban-OS map at http://localhost:8000/ (offline). Endpoints: /scenario /simulate /optimize"
	PYTHONPATH=src $(PYTHON) -m uvicorn urbanos.kernel.api:app --port 8000 --app-dir src

# One-shot CLI: run + optimize the downtown egress scenario, print the cited insight.
urbanos-cli:
	PYTHONPATH=src $(PYTHON) -m urbanos.kernel.cli

# Build the optional Rust accelerator (aarch64) and report the active backend.
# Falls back to numpy automatically if this is skipped — the demo never needs it.
urbanos-accel:
	$(PYTHON) -m pip install -q maturin
	$(dir $(PYTHON))maturin develop --release -m native/Cargo.toml
	@PYTHONPATH=src $(PYTHON) -c "from urbanos.kernel.kernel import accel; print('Urban-OS transport backend:', accel.backend_name())"

# Benchmark the active transport backend vs the numpy reference: asserts f64
# parity (when rust is built) and reports the wall-clock speedup. Runs anywhere
# and degrades to a numpy-only baseline when the rust core is absent.
urbanos-bench:
	PYTHONPATH=src $(PYTHON) scripts/bench_urbanos_accel.py

# Render a map page to a PNG, waiting until the WebGL+PMTiles map has drawn (one-
# shot headless can't — see ADR-0012). Needs Playwright + chromium; run on the
# box (real GPU) for a faithful render. Usage:
#   make screenshot URL=http://localhost:8001/ OUT=/tmp/map.png
screenshot:
	$(PYTHON) scripts/screenshot_map.py "$(URL)" "$(OUT)"

# ---- Local dev stack (WSL/Linux): live Ollama narrator + BOTH apps in background ----
# `make dev` brings up ollama (if installed; pulls + pins the dev model) and serves
# urbanos.risk (:8000) + urbanos.kernel (:8001) in the background, then prints the URLs.
# Degrades gracefully with no ollama (deterministic narrator). Stop with `make dev-down`.
# Override the model/ports via env: LLM_MODEL=... CIVIC_PORT=... URBAN_PORT=...
dev:
	DEV_PY=$(PYTHON) bash scripts/dev.sh up

dev-down:
	bash scripts/dev.sh down

dev-status:
	bash scripts/dev.sh status

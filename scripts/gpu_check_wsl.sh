#!/usr/bin/env bash
# Re-runnable one-shot that proves the urbanos.kernel RAPIDS GPU seams (nx-cugraph for the
# graph substrate + cuDF-Polars for ingest) run GENUINELY GPU-active in WSL-native
# ext4 on a consumer NVIDIA GPU (proven on an RTX 2060). It wraps scripts/gpu_check.py
# with the two non-obvious fixes that are the whole reason the GPU path lights up:
#
#   1. The cudart-headers wheel pin `nvidia-cuda-runtime-cu12==12.9.*`. Without it the
#      system CUDA 13.3 fp8/fp6/fp4 NVRTC headers don't match the cu12.9 toolchain, so
#      nx-cugraph's JIT relabel kernel SILENTLY fails to compile and [graph] falls back
#      to CPU networkx (no error — just a quietly wrong result). This script ensures the
#      pin is present (installing it via `uv pip` only if missing — dev-only, never
#      touches requirements.txt/.lock).
#   2. LD_LIBRARY_PATH must include the venv's native-lib dirs or `libcugraph.so` /
#      `libnvrtc.so.12` won't load (ImportError -> CPU fallback). We derive it from the
#      ACTIVE venv: every dir under site-packages that holds a .so. That covers both
#      `nvidia/*/lib` (nvrtc, cublas, ...) AND the RAPIDS `*/lib64` dirs (libcugraph,
#      libcudf, librmm, ...) where the cuxx native libs actually live.
#
# MUST run in WSL-native ext4 (`~`), NOT under /mnt/c — drvfs corrupts RAPIDS'
# native-lib relocation and the import fails. The env is built by `make install-linux`
# (uv + requirements.lock) PLUS the RAPIDS accelerators:
#   uv pip install --extra-index-url=https://pypi.nvidia.com \
#       nx-cugraph-cu12 cudf-polars-cu12 numba-cuda
#   uv pip install nvidia-cuda-runtime-cu12==12.9.*        # fix #1, see above
#
# Usage (from the repo root inside WSL):
#   scripts/gpu_check_wsl.sh                 # uses .venv-linux (or $VENV)
#   VENV=/path/to/venv scripts/gpu_check_wsl.sh
#
# Exit codes: 0 = ran (the gpu_check.py result is the value); non-zero = a boundary
# was violated (not Linux / no GPU / venv missing) — we fail loudly rather than
# silently "pass" on CPU, so this can gate "is the GPU path reproducible?".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

err() { printf '[gpu-check-wsl] ERROR: %s\n' "$*" >&2; }
log() { printf '[gpu-check-wsl] %s\n' "$*"; }

# --- boundary 1: Linux (WSL-native ext4, not /mnt/c) ------------------------------
if [ "$(uname -s)" != "Linux" ]; then
  err "must run on Linux (WSL Ubuntu). Use 'make gpu-check-wsl' from Windows, which"
  err "shells into WSL for you. (On Windows the GPU seams have no RAPIDS to bind to.)"
  exit 2
fi
case "$ROOT" in
  /mnt/*)
    err "repo is under '$ROOT' (a /mnt drvfs path). RAPIDS native-lib relocation is"
    err "corrupted on drvfs -> imports fail. Clone into WSL-native ext4 (e.g. ~/) and"
    err "run from there. See the recipe header in this script."
    exit 3 ;;
esac

# --- boundary 2: a usable venv ----------------------------------------------------
VENV="${VENV:-$ROOT/.venv-linux}"
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  err "venv python not found at '$PY'."
  err "Build it with:  make install-linux  &&  RAPIDS accelerators (see script header)."
  exit 4
fi

# --- boundary 3: a CUDA GPU is actually present -----------------------------------
if ! command -v nvidia-smi >/dev/null 2>&1; then
  err "nvidia-smi not found — no NVIDIA GPU visible to WSL. Install the Windows NVIDIA"
  err "driver with WSL CUDA support; the GPU seams can't run without it."
  exit 5
fi
if ! nvidia-smi -L >/dev/null 2>&1; then
  err "nvidia-smi present but lists no GPU. Check the driver / 'nvidia-smi'."
  exit 5
fi
log "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"

# --- fix #1: ensure the cudart-headers pin (12.9.*) is installed -------------------
# It resolves the CUDA-13.3-vs-cu12.9 NVRTC header skew that otherwise silently forces
# [graph] to CPU. We check the ACTIVE venv and only install if absent (dev-only; never
# edits requirements.txt/.lock). `uv` does the install if available; otherwise we warn.
if "$PY" -c 'import importlib.metadata as m, sys; v=m.version("nvidia-cuda-runtime-cu12"); sys.exit(0 if v.startswith("12.9.") else 1)' 2>/dev/null; then
  log "cudart-headers wheel OK: nvidia-cuda-runtime-cu12==$("$PY" -c 'import importlib.metadata as m; print(m.version("nvidia-cuda-runtime-cu12"))' 2>/dev/null)"
else
  log "cudart-headers pin missing/mismatched -> installing nvidia-cuda-runtime-cu12==12.9.* (dev-only)"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PY" 'nvidia-cuda-runtime-cu12==12.9.*'
  else
    "$PY" -m pip install 'nvidia-cuda-runtime-cu12==12.9.*' \
      || { err "neither 'uv' nor a working pip in the venv could install the cudart pin."; \
           err "Install uv (https://docs.astral.sh/uv) or add pip to the venv, then re-run."; \
           exit 6; }
  fi
fi

# --- fix #2: derive LD_LIBRARY_PATH from the venv's native-lib dirs ----------------
# Every dir under site-packages that contains a .so — i.e. nvidia/*/lib AND the RAPIDS
# */lib64 dirs (libcugraph, libcudf, librmm, ...). Without these, libcugraph.so /
# libnvrtc.so.12 don't load and [graph] ImportErrors back to CPU networkx.
LIBS="$("$PY" - <<'PY'
import os, glob, sysconfig
sp = sysconfig.get_paths()["purelib"]
dirs = sorted({os.path.dirname(p)
               for p in glob.glob(os.path.join(sp, "**", "*.so*"), recursive=True)})
print(os.pathsep.join(dirs))
PY
)"
if [ -z "$LIBS" ]; then
  err "found no .so libraries under the venv site-packages — is RAPIDS installed?"
  err "Run the accelerator install from the script header, then re-run."
  exit 7
fi
export LD_LIBRARY_PATH="${LIBS}${LD_LIBRARY_PATH:+$( [ -n "${LD_LIBRARY_PATH:-}" ] && printf ':%s' "$LD_LIBRARY_PATH")}"
log "LD_LIBRARY_PATH primed with $(printf '%s' "$LIBS" | tr "$(printf ':')" '\n' | grep -c .) native-lib dirs from the venv"

# --- run the seam check with the GPU paths opted in -------------------------------
log "running scripts/gpu_check.py (URBANOS_GPU_GRAPH=1 URBANOS_GPU_DF=1)"
echo "---------------------------------------------------------------------------"
URBANOS_GPU_GRAPH=1 URBANOS_GPU_DF=1 PYTHONPATH=src "$PY" scripts/gpu_check.py

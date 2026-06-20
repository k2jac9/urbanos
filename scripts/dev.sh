#!/usr/bin/env bash
# One-command local dev stack for WSL/Linux: a live Ollama narrator + BOTH apps
# (urbanos.risk :8000, urbanos.kernel :8001) running in the background. This is the
# local-dev convenience the box doesn't need — on the GB10 the narrator is Nemotron
# behind Ollama/TRT-LLM and the systemd services own the lifecycle (docs/ON_THE_BOX.md).
#
#   scripts/dev.sh up       # start ollama (if installed) + pull/pin the model + both apps
#   scripts/dev.sh down     # stop both apps (leaves ollama running — it's user-global)
#   scripts/dev.sh status   # what's up
#
# Everything degrades gracefully: no ollama -> apps still run on the deterministic
# narrator (the app is offline-safe; we never "fix" the fallback). Override anything:
#   DEV_PY=...  LLM_MODEL=...  CIVIC_PORT=...  URBAN_PORT=...  OLLAMA_BIN=...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_DIR="$ROOT/.dev"; mkdir -p "$RUN_DIR"

CIVIC_PORT="${CIVIC_PORT:-8000}"
URBAN_PORT="${URBAN_PORT:-8001}"
LLM_MODEL="${LLM_MODEL:-llama3.2:3b}"   # best fit for a 6GB-VRAM dev GPU; fully GPU-resident
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

# Python: prefer the WSL-native venv, then a POSIX .venv, then system python. The
# project's checked-in .venv may be a *Windows* venv (Scripts/, not bin/) which WSL
# cannot run — hence .venv-linux as the WSL interpreter (make install-linux builds it).
pick_py() {
  if [ -n "${DEV_PY:-}" ]; then echo "$DEV_PY"; return; fi
  for p in .venv-linux/bin/python .venv/bin/python; do
    [ -x "$p" ] && { echo "$p"; return; }
  done
  command -v python3 || command -v python
}
PY="$(pick_py)"
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/.local/bin/ollama")}"

log() { printf '[dev] %s\n' "$*"; }

ollama_up() {
  if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then log "ollama already serving ($OLLAMA_URL)"; return 0; fi
  if [ ! -x "$OLLAMA_BIN" ]; then
    log "ollama not installed -> apps will use the deterministic narrator (offline-safe)."
    return 1
  fi
  log "starting ollama serve ..."
  nohup "$OLLAMA_BIN" serve >"$RUN_DIR/ollama.log" 2>&1 &
  echo $! > "$RUN_DIR/ollama.pid"
  for _ in $(seq 1 60); do curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && break; sleep 1; done
  curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1 || { log "ollama failed to start (see $RUN_DIR/ollama.log)"; return 1; }
}

ensure_model() {
  # Match the full model name (repo:tag) as a fixed string — stripping the tag would
  # treat a different tag of the same repo as "already pulled" and skip the pull.
  if ! "$OLLAMA_BIN" list 2>/dev/null | grep -qF "$LLM_MODEL"; then
    log "pulling $LLM_MODEL (one-time) ..."; "$OLLAMA_BIN" pull "$LLM_MODEL"
  fi
  # Pin the model resident so dev iterations never pay the cold-load (first cold call
  # can exceed the client's 120s timeout -> 500 -> silent deterministic fallback).
  curl -sf "$OLLAMA_URL/api/generate" -d "{\"model\":\"$LLM_MODEL\",\"keep_alive\":-1}" >/dev/null 2>&1 \
    && log "pinned $LLM_MODEL resident (keep_alive=-1)"
}

kill_port() { # $1 = port (returns 0 even when nothing was listening, so `set -e` is happy)
  local pid; pid="$(ss -ltnp 2>/dev/null | grep ":$1 " | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2 || true)"
  if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; log "stopped pid $pid on :$1"; fi
}

start_app() { # $1=label $2=module:app $3=port $4=extra_env
  kill_port "$3"
  log "starting $1 on :$3 ..."
  # shellcheck disable=SC2086
  env $4 LLM_BASE_URL="$OLLAMA_URL/v1" LLM_API_KEY=ollama LLM_RUNTIME=ollama \
      LLM_MODEL="$LLM_MODEL" LLM_BATCH_MODEL="$LLM_MODEL" LLM_REASONING_EFFORT= LLM_PREWARM=true \
      PYTHONPATH=src nohup "$PY" -m uvicorn "$2" --host 127.0.0.1 --port "$3" --app-dir src \
      >"$RUN_DIR/$1.log" 2>&1 &
  echo $! > "$RUN_DIR/$1.pid"
}

wait_health() { # $1=port $2=label
  for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$1/health" >/dev/null 2>&1 && { log "$2 healthy: http://localhost:$1/"; return 0; }; sleep 1; done
  log "$2 did NOT come up on :$1 (see $RUN_DIR/$2.log)"; return 1
}

cmd_up() {
  log "python = $PY"
  if ollama_up; then ensure_model; fi
  start_app civic  urbanos.risk.api.server:app "$CIVIC_PORT" "DATA_DIR=demo_data"
  start_app urban  urbanos.kernel.api:app             "$URBAN_PORT" ""
  wait_health "$CIVIC_PORT" civic || true
  wait_health "$URBAN_PORT" urban || true
  log "narrator: $(curl -s "http://127.0.0.1:$CIVIC_PORT/health" | grep -oE '"interactive_model":"[^"]*"' || echo '?')"
  log "up. stop with: make dev-down"
}

cmd_down() {
  for n in civic urban; do
    [ -f "$RUN_DIR/$n.pid" ] && { kill "$(cat "$RUN_DIR/$n.pid")" 2>/dev/null || true; rm -f "$RUN_DIR/$n.pid"; }
  done
  kill_port "$CIVIC_PORT"; kill_port "$URBAN_PORT"
  log "apps stopped (ollama left running — 'kill \$(cat $RUN_DIR/ollama.pid)' to stop it too)."
}

cmd_status() {
  curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && log "ollama: up" || log "ollama: down"
  for pair in "civic:$CIVIC_PORT" "urban:$URBAN_PORT"; do
    n="${pair%%:*}"; p="${pair##*:}"
    curl -sf "http://127.0.0.1:$p/health" >/dev/null 2>&1 && log "$n: up (http://localhost:$p/)" || log "$n: down"
  done
}

case "${1:-up}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  *)      echo "usage: scripts/dev.sh {up|down|status}" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
# Run an end-to-end smoke test of tinker-nemogym on nemo-gym's
# example_single_tool_call environment.
#
# Requires:
#   - TINKER_API_KEY in env (https://tinker-console.thinkingmachines.ai)
#   - nemo-gym installed at ../nemo-gym (sibling directory)
#   - poetry env configured for this repo (`poetry install` once)
#
# What it does:
#   1. Launch nemo-gym HeadServer + resources + SimpleAgent via `ng_run`
#      (pointed at http://127.0.0.1:8001 as the policy model — that's our
#      FastAPI shim).
#   2. Wait for the HeadServer to come up on :11000.
#   3. Launch the tinker-nemogym trainer, which:
#        - spawns its own FastAPI shim in-process on :8001,
#        - snapshots a Tinker LoRA sampling client into it,
#        - iterates `training.n_steps` rollouts against
#          http://127.0.0.1:11001 (the agent),
#        - runs forward_backward + optim_step + hot-swap after each.
#   4. On exit (or Ctrl-C), SIGTERM nemo-gym.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEMO_GYM_DIR="$(cd "$REPO_ROOT/../nemo-gym" && pwd)"
NG_RUN="$REPO_ROOT/../.venv/bin/ng_run"

echo "[smoke] repo root:    $REPO_ROOT"
echo "[smoke] nemo-gym dir: $NEMO_GYM_DIR"
echo "[smoke] ng_run:       $NG_RUN"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
    echo "[smoke] ERROR: TINKER_API_KEY not set. Grab one from"
    echo "        https://tinker-console.thinkingmachines.ai and re-run."
    exit 1
fi

if [[ ! -x "$NG_RUN" ]]; then
    echo "[smoke] ERROR: ng_run not found at $NG_RUN."
    echo "        Install nemo-gym into the parent .venv first:"
    echo "          cd $(dirname "$NEMO_GYM_DIR") && uv venv && uv sync --extra dev"
    exit 1
fi

RESOURCES_YAML="$REPO_ROOT/configs/nemogym_resources.yaml"
AGENT_YAML="$REPO_ROOT/configs/nemogym_agent.yaml"
SMOKE_YAML="$REPO_ROOT/configs/smoke_single_tool.yaml"

# --------------------------------------------------------------------------
# 1. Start nemo-gym (resources + agent + policy_model shim pointer) in bg.
# --------------------------------------------------------------------------
echo "[smoke] Starting nemo-gym (ng_run)..."
cd "$NEMO_GYM_DIR"
"$NG_RUN" "+config_paths=[$RESOURCES_YAML,$AGENT_YAML]" \
    +policy_base_url=http://127.0.0.1:8001/v1 \
    +policy_api_key=tinker-nemogym-shim \
    +policy_model_name=tinker \
    > /tmp/tinker_nemogym_ng_run.log 2>&1 &
NG_PID=$!
echo "[smoke] ng_run pid=$NG_PID (logs: /tmp/tinker_nemogym_ng_run.log)"

cleanup() {
    echo "[smoke] Cleaning up nemo-gym (pid=$NG_PID)..."
    if kill -0 "$NG_PID" 2>/dev/null; then
        kill -TERM "$NG_PID" 2>/dev/null || true
        # Give it a few seconds, then force-kill.
        for _ in 1 2 3 4 5; do
            kill -0 "$NG_PID" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$NG_PID" 2>/dev/null && kill -KILL "$NG_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# --------------------------------------------------------------------------
# 2. Wait for the HeadServer to respond on :11000.
# --------------------------------------------------------------------------
echo "[smoke] Waiting for HeadServer on http://127.0.0.1:11000 ..."
for i in $(seq 1 60); do
    if curl -fs http://127.0.0.1:11000/ >/dev/null 2>&1 ||
       curl -fs http://127.0.0.1:11000/status >/dev/null 2>&1; then
        echo "[smoke] HeadServer up after ${i}s"
        break
    fi
    if ! kill -0 "$NG_PID" 2>/dev/null; then
        echo "[smoke] ERROR: ng_run exited early. Tail of log:"
        tail -40 /tmp/tinker_nemogym_ng_run.log || true
        exit 1
    fi
    sleep 1
done

# --------------------------------------------------------------------------
# 3. Launch tinker-nemogym trainer (fg, so we can see its logs).
# --------------------------------------------------------------------------
echo "[smoke] Starting tinker-nemogym trainer..."
cd "$REPO_ROOT"
unset VIRTUAL_ENV
poetry run python launch_training.py --config "$SMOKE_YAML"

echo "[smoke] trainer exited cleanly"

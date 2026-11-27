#!/usr/bin/env bash
# Run a live-Tinker smoke test on nemo-gym's `example_multi_step` environment
# (multi-turn tool calling). Mirrors scripts/smoke_single_tool.sh but uses the
# multi_step YAMLs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEMO_GYM_DIR="$(cd "$REPO_ROOT/../nemo-gym" && pwd)"
NG_RUN="$REPO_ROOT/../.venv/bin/ng_run"

echo "[smoke-multi] repo root:    $REPO_ROOT"
echo "[smoke-multi] nemo-gym dir: $NEMO_GYM_DIR"
echo "[smoke-multi] ng_run:       $NG_RUN"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
    echo "[smoke-multi] ERROR: TINKER_API_KEY not set."
    exit 1
fi

if [[ ! -x "$NG_RUN" ]]; then
    echo "[smoke-multi] ERROR: ng_run not found at $NG_RUN."
    exit 1
fi

RESOURCES_YAML="$REPO_ROOT/configs/nemogym_multi_step_resources.yaml"
AGENT_YAML="$REPO_ROOT/configs/nemogym_multi_step_agent.yaml"
SMOKE_YAML="${SMOKE_YAML:-$REPO_ROOT/configs/smoke_multi_step.yaml}"

echo "[smoke-multi] Starting nemo-gym (ng_run)..."
cd "$NEMO_GYM_DIR"
"$NG_RUN" "+config_paths=[$RESOURCES_YAML,$AGENT_YAML]" \
    +policy_base_url=http://127.0.0.1:8001/v1 \
    +policy_api_key=tinker-nemogym-shim \
    +policy_model_name=tinker \
    > /tmp/tinker_nemogym_ng_run_multi.log 2>&1 &
NG_PID=$!
echo "[smoke-multi] ng_run pid=$NG_PID (logs: /tmp/tinker_nemogym_ng_run_multi.log)"

cleanup() {
    echo "[smoke-multi] Cleaning up nemo-gym (pid=$NG_PID)..."
    if kill -0 "$NG_PID" 2>/dev/null; then
        kill -TERM "$NG_PID" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "$NG_PID" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$NG_PID" 2>/dev/null && kill -KILL "$NG_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

echo "[smoke-multi] Waiting for HeadServer on http://127.0.0.1:11000 ..."
for i in $(seq 1 60); do
    if curl -fs http://127.0.0.1:11000/ >/dev/null 2>&1 ||
       curl -fs http://127.0.0.1:11000/status >/dev/null 2>&1; then
        echo "[smoke-multi] HeadServer up after ${i}s"
        break
    fi
    if ! kill -0 "$NG_PID" 2>/dev/null; then
        echo "[smoke-multi] ERROR: ng_run exited early. Tail of log:"
        tail -40 /tmp/tinker_nemogym_ng_run_multi.log || true
        exit 1
    fi
    sleep 1
done

echo "[smoke-multi] Starting tinker-nemogym trainer with $SMOKE_YAML ..."
cd "$REPO_ROOT"
unset VIRTUAL_ENV
poetry run python launch_training.py --config "$SMOKE_YAML"

echo "[smoke-multi] trainer exited cleanly"

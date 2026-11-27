#!/usr/bin/env bash
# Live-Tinker smoke test that exercises every diagnostic field:
#
#   * sampler_version pinning on every rollout
#   * β (precision-gap) measurement via training.measure_precision_gap
#   * per-rollout sample_latency_ms + step-level p50/p95 aggregation
#   * staleness aggregates when in-flight rollouts survive a hot-swap
#
# Same shape as scripts/smoke_mcqa.sh — starts nemo-gym's mcqa env, points
# the trainer at configs/smoke_diagnostics.yaml (which has
# measure_precision_gap: true), and runs 5 training steps. Compare the
# per-step console lines against docs/diagnostics.md to interpret β.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEMO_GYM_DIR="$(cd "$REPO_ROOT/../nemo-gym" && pwd)"
NG_RUN="$REPO_ROOT/../.venv/bin/ng_run"

echo "[smoke-diag] repo root:    $REPO_ROOT"
echo "[smoke-diag] nemo-gym dir: $NEMO_GYM_DIR"
echo "[smoke-diag] ng_run:       $NG_RUN"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
    echo "[smoke-diag] ERROR: TINKER_API_KEY not set."
    exit 1
fi

if [[ ! -x "$NG_RUN" ]]; then
    echo "[smoke-diag] ERROR: ng_run not found at $NG_RUN."
    exit 1
fi

RESOURCES_YAML="$REPO_ROOT/configs/nemogym_mcqa_resources.yaml"
AGENT_YAML="$REPO_ROOT/configs/nemogym_mcqa_agent.yaml"
SMOKE_YAML="${SMOKE_YAML:-$REPO_ROOT/configs/smoke_diagnostics.yaml}"

echo "[smoke-diag] Starting nemo-gym (ng_run)..."
cd "$NEMO_GYM_DIR"
"$NG_RUN" "+config_paths=[$RESOURCES_YAML,$AGENT_YAML]" \
    +policy_base_url=http://127.0.0.1:8001/v1 \
    +policy_api_key=tinker-nemogym-shim \
    +policy_model_name=tinker \
    > /tmp/tinker_nemogym_ng_run_diag.log 2>&1 &
NG_PID=$!
echo "[smoke-diag] ng_run pid=$NG_PID (logs: /tmp/tinker_nemogym_ng_run_diag.log)"

cleanup() {
    echo "[smoke-diag] Cleaning up nemo-gym (pid=$NG_PID)..."
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

echo "[smoke-diag] Waiting for HeadServer on http://127.0.0.1:11000 ..."
for i in $(seq 1 60); do
    if curl -fs http://127.0.0.1:11000/ >/dev/null 2>&1 ||
       curl -fs http://127.0.0.1:11000/status >/dev/null 2>&1; then
        echo "[smoke-diag] HeadServer up after ${i}s"
        break
    fi
    if ! kill -0 "$NG_PID" 2>/dev/null; then
        echo "[smoke-diag] ERROR: ng_run exited early. Tail of log:"
        tail -40 /tmp/tinker_nemogym_ng_run_diag.log || true
        exit 1
    fi
    sleep 1
done

echo "[smoke-diag] Starting tinker-nemogym trainer with $SMOKE_YAML ..."
echo "[smoke-diag] Watch for beta_* / sample_latency_ms_* / staleness_* in step logs."
cd "$REPO_ROOT"
unset VIRTUAL_ENV
poetry run python launch_training.py --config "$SMOKE_YAML"

echo "[smoke-diag] trainer exited cleanly"

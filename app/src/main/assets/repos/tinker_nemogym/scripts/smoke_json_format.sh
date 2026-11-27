#!/usr/bin/env bash
# Live-Tinker smoke test for `tng_json_format` — JSON-output compliance —
# against NVIDIA-Nemotron-3-Nano-30B-A3B-BF16. Mirrors scripts/smoke_mcqa.sh
# but points at the json_format YAMLs.
#
# Self-contained: the `tng_json_format` resources_server code lives INSIDE
# tinker-nemogym (tinker_nemogym/environments/json_format/nemogym_server/).
# This script file-symlinks it into nemo-gym's resources_servers/ tree at
# startup so ng_run's directory-name discovery picks it up, and removes the
# links on exit (EXIT/INT/TERM trap).
#
# No manual sibling-repo edits required. Just: `bash scripts/smoke_json_format.sh`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEMO_GYM_DIR="$(cd "$REPO_ROOT/../nemo-gym" && pwd)"
NG_RUN="$REPO_ROOT/../.venv/bin/ng_run"

echo "[smoke-json] repo root:    $REPO_ROOT"
echo "[smoke-json] nemo-gym dir: $NEMO_GYM_DIR"
echo "[smoke-json] ng_run:       $NG_RUN"

SKIP_TINKER="${SKIP_TINKER:-0}"

if [[ "$SKIP_TINKER" != "1" && -z "${TINKER_API_KEY:-}" ]]; then
    echo "[smoke-json] ERROR: TINKER_API_KEY not set." >&2
    exit 1
fi

if [[ ! -x "$NG_RUN" ]]; then
    echo "[smoke-json] ERROR: ng_run not found at $NG_RUN." >&2
    exit 1
fi

RESOURCES_YAML="$REPO_ROOT/configs/nemogym_json_format_resources.yaml"
AGENT_YAML="$REPO_ROOT/configs/nemogym_json_format_agent.yaml"
SMOKE_YAML="${SMOKE_YAML:-$REPO_ROOT/configs/smoke_json_format_nemotron.yaml}"

NG_LOG="/tmp/tinker_nemogym_ng_run_json_format.log"

# ---------------------------------------------------------------------------
# Embed the resources_server into nemo-gym's discovery tree via symlinks.
# ng_run finds servers by the directory name under resources_servers/; we
# keep our real code in tinker-nemogym and link individual files in, so
# `dir_path.resolve() / "../../pyproject.toml"` still points to nemo-gym's
# pyproject.toml (editable-install detection stays correct).
# ---------------------------------------------------------------------------
SERVER_SRC="$REPO_ROOT/tinker_nemogym/environments/json_format/nemogym_server"
SERVER_DST="$NEMO_GYM_DIR/resources_servers/tng_json_format"
CACHE_DIR="${TINKER_NEMOGYM_CACHE_DIR:-$HOME/.cache/tinker_nemogym}"
CACHED_VENV="$CACHE_DIR/tng_json_format.venv"

CLEANUP_DIR=""

link_server_code() {
    # Robustness checks ------------------------------------------------------
    if [[ ! -d "$SERVER_SRC" ]]; then
        echo "[smoke-json] ERROR: embedded resources_server not found at $SERVER_SRC" >&2
        exit 1
    fi

    if [[ -e "$SERVER_DST" || -L "$SERVER_DST" ]]; then
        # If somebody already set this up with the same files pointing at
        # our src, leave it alone. Otherwise refuse to clobber user data.
        if [[ -L "$SERVER_DST/app.py" ]] && \
           [[ "$(readlink -f "$SERVER_DST/app.py")" == "$(readlink -f "$SERVER_SRC/app.py")" ]]; then
            echo "[smoke-json] Existing symlinks at $SERVER_DST already point at $SERVER_SRC — leaving as-is."
            return 0
        fi
        echo "[smoke-json] ERROR: $SERVER_DST already exists and is NOT our symlink set." >&2
        echo "              Remove it manually before re-running this script." >&2
        exit 1
    fi

    mkdir -p "$SERVER_DST"
    ln -s "$SERVER_SRC/app.py"  "$SERVER_DST/app.py"
    ln -s "$SERVER_SRC/configs" "$SERVER_DST/configs"
    if [[ -f "$SERVER_SRC/README.md" ]]; then
        ln -s "$SERVER_SRC/README.md" "$SERVER_DST/README.md"
    fi
    # requirements.txt is NOT symlinked: its `-e ... @ ../../` path needs to
    # resolve relative to the *destination* (nemo-gym/), not the embedded
    # source (tinker-nemogym/). Write a fresh copy at the destination — the
    # embedded nemogym_server/requirements.txt is kept only as a template.
    cat > "$SERVER_DST/requirements.txt" <<'REQS'
-e nemo-gym[dev] @ ../../
REQS

    # Speed-up: if a previous run populated a .venv, restore it so we skip
    # the multi-minute uv install. It'll be re-created on first run otherwise.
    if [[ -d "$CACHED_VENV" && ! -e "$SERVER_DST/.venv" ]]; then
        ln -s "$CACHED_VENV" "$SERVER_DST/.venv"
    fi

    CLEANUP_DIR="$SERVER_DST"
    echo "[smoke-json] Linked $SERVER_DST -> $SERVER_SRC"
}

link_server_code

NG_PID=""

cleanup() {
    local ec=$?
    echo "[smoke-json] Cleaning up..."
    if [[ -n "$NG_PID" ]] && kill -0 "$NG_PID" 2>/dev/null; then
        kill -INT "$NG_PID" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "$NG_PID" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$NG_PID" 2>/dev/null && kill -KILL "$NG_PID" 2>/dev/null || true
    fi
    if [[ -n "$CLEANUP_DIR" && -d "$CLEANUP_DIR" ]]; then
        # Stash the .venv back to the cache so the next run is fast.
        if [[ -d "$CLEANUP_DIR/.venv" && ! -L "$CLEANUP_DIR/.venv" && ! -d "$CACHED_VENV" ]]; then
            mkdir -p "$CACHE_DIR"
            mv "$CLEANUP_DIR/.venv" "$CACHED_VENV" || true
        fi
        rm -rf "$CLEANUP_DIR"
        echo "[smoke-json] Removed symlink dir $CLEANUP_DIR"
    fi
    exit "$ec"
}
trap cleanup EXIT INT TERM

echo "[smoke-json] Starting nemo-gym (ng_run)..."
cd "$NEMO_GYM_DIR"
"$NG_RUN" "+config_paths=[$RESOURCES_YAML,$AGENT_YAML]" \
    +policy_base_url=http://127.0.0.1:8001/v1 \
    +policy_api_key=tinker-nemogym-shim \
    +policy_model_name=tinker \
    +skip_venv_if_present=true \
    > "$NG_LOG" 2>&1 &
NG_PID=$!
echo "[smoke-json] ng_run pid=$NG_PID (logs: $NG_LOG)"

echo "[smoke-json] Waiting for HeadServer on http://127.0.0.1:11000 ..."
for i in $(seq 1 180); do
    if curl -fs http://127.0.0.1:11000/ >/dev/null 2>&1 ||
       curl -fs http://127.0.0.1:11000/status >/dev/null 2>&1 ||
       curl -fs http://127.0.0.1:11000/server_instances >/dev/null 2>&1; then
        echo "[smoke-json] HeadServer up after ${i}s"
        break
    fi
    if ! kill -0 "$NG_PID" 2>/dev/null; then
        echo "[smoke-json] ERROR: ng_run exited early. Tail of log:" >&2
        tail -40 "$NG_LOG" >&2 || true
        exit 1
    fi
    sleep 1
done

if [[ "$SKIP_TINKER" == "1" ]]; then
    echo "[smoke-json] SKIP_TINKER=1 — nemo-gym stack is up, trainer skipped. Exiting cleanly."
    exit 0
fi

# Kick off a tiny side-task that prints the wandb run URL as soon as the
# trainer logs one. Harmless if wandb is offline.
(
    WANDB_DIR="$REPO_ROOT/wandb"
    for _ in $(seq 1 120); do
        latest="$(ls -dt "$WANDB_DIR"/latest-run 2>/dev/null || true)"
        if [[ -n "$latest" ]]; then
            url=$(grep -h 'wandb: .* https://' "$latest"/logs/debug.log 2>/dev/null | tail -1 || true)
            [[ -n "$url" ]] && echo "[smoke-json][wandb] $url" && break
        fi
        sleep 2
    done
) &

echo "[smoke-json] Starting tinker-nemogym trainer with $SMOKE_YAML ..."
cd "$REPO_ROOT"
unset VIRTUAL_ENV
poetry run python launch_training.py --config "$SMOKE_YAML" \
    2>&1 | tee "/tmp/tinker_nemogym_json_format.log"

echo "[smoke-json] trainer exited cleanly"

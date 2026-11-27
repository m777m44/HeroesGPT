#!/usr/bin/env bash
# Live observability helper for tinker-nemogym runs. Shows:
#   - latest trainer log tail with "Step N:" progress lines
#   - last few wandb debug log entries
#   - currently listening nemo-gym ports (:11xxx)
#
# Exit with Ctrl-C.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

latest_log() {
    ls -t /tmp/tinker_nemogym_*.log 2>/dev/null | head -1 || true
}

latest_wandb_dir() {
    ls -dt "$REPO_ROOT"/wandb/latest-run "$REPO_ROOT"/wandb/offline-run-* "$REPO_ROOT"/wandb/run-* 2>/dev/null \
        | head -1 || true
}

print_header() {
    local title="$1"
    printf '\n\033[1;34m== %s ==\033[0m\n' "$title"
}

while :; do
    clear
    printf '\033[1;32mtinker-nemogym monitor\033[0m  |  %s  |  Ctrl-C to exit\n' "$(date '+%H:%M:%S')"

    LOG="$(latest_log)"
    print_header "trainer log: ${LOG:-<none>}"
    if [[ -n "$LOG" && -f "$LOG" ]]; then
        # Recent Step lines + last 5 lines for context.
        grep -E 'Step [0-9]+:|mean_reward|loss|save_count|ERROR|Traceback' "$LOG" \
            2>/dev/null | tail -12 || true
        echo "--- (tail -3) ---"
        tail -3 "$LOG" 2>/dev/null || true
    else
        echo "  (no /tmp/tinker_nemogym_*.log yet)"
    fi

    WDIR="$(latest_wandb_dir)"
    print_header "wandb: ${WDIR:-<none>}"
    if [[ -n "$WDIR" && -d "$WDIR" ]]; then
        tail -5 "$WDIR/logs/debug.log" 2>/dev/null || echo "  (no debug.log yet)"
    else
        echo "  (no wandb dir yet — running offline or not started)"
    fi

    print_header "nemo-gym ports (ss -tlnp | grep :11)"
    ss -tlnp 2>/dev/null | awk '/:11[0-9]{3}/ {print "  " $0}' | head -10 \
        || echo "  (none)"

    sleep 2
done

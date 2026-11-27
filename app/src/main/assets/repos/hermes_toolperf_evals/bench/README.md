# bench_tools.py — baseline task battery (11 tasks)

The earlier, broader benchmark that ran BEFORE the fixes were designed: 8
generic core-tool tasks + 3 hint-targeted tasks, driven through `hermes chat`
with NeMo Relay ATOF/ATIF tracing. It established the baseline waste profile
that `analysis/CANDIDATES.md` quantifies; the sharper 9-task A/B harness in
`abeval/` superseded it for before/after measurement.

Tasks: `edit_dedup`, `big_file_nav`, `search_misc`, `term_state`,
`bg_server`, `refactor`, `diag_fail`, `git_flow` (generic), plus
`hint_python`, `hint_module`, `hint_fields` (targeted at the recovery-hint
PRs).

Scores per trajectory: total turns, tool calls, tool errors, wasted turns
(retry-after-error, exact duplicates), wall time, tool-result bytes.

## Note on paths

Originally recovered from the Hermes session DB after `/tmp` was wiped; now
parameterized like the A/B harness:

```bash
export BENCH_ROOT=/tmp/bench-workspace      # results + sandboxes (default ./bench-workspace)
export BENCH_REPO=/path/to/hermes-agent     # tree to benchmark (required)
export BENCH_HOME=/path/to/eval-home        # configured Hermes home (default $BENCH_ROOT/home)
export BENCH_MODEL=provider/model-id        # optional model override

python bench_tools.py run   --tag baseline --repeat 2
python bench_tools.py score --tag baseline
```

The `abeval/` harness is the maintained before/after entrypoint; this battery
is kept for the broader task mix and the 3 hint tasks not carried into the
A/B set.

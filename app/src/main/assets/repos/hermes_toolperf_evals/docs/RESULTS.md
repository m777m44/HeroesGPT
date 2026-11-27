# A/B eval results (2026-08-02 original run — published to tracker #77056)

> **Note:** the raw traces of this run were lost with `/tmp`; the tables below
> are the published record. The canonical, fully reproducible dataset with
> checked-in traces is `results/2026-08-06_rerun/`, which also documents where
> the rerun differs from (and where it corroborates) these numbers.

**Setup:** baseline = clean hermes-agent `origin/main`; fixes = all-15-PR
integration branch. Arms differ ONLY by `PYTHONPATH`. 9 error-inducing tasks
derived from the mined production waste classes × 2 models × 2 arms × 3 reps
(108 runs + 6 re-runs after purging startup-crashed records). Metrics from
NeMo Relay ATOF traces: LLM turns, tool calls, tool errors, retry-after-error,
result KB into context, wall clock, task success.

## Aggregate

| model | arm | ok% | llm turns | tool calls | tool errs | retries | result KB | wall |
|---|---|---|---|---|---|---|---|---|
| qwen3-coder-30b (weak) | baseline | 74% | 3.8 | 2.8 | 0.1 | 0.1 | 12 | 22s |
| qwen3-coder-30b (weak) | **fixes** | 67% | **3.0 (−21%)** | **2.0 (−29%)** | **0.0** | **0.0** | **8 (−33%)** | **17s (−23%)** |
| sonnet-4.5 (strong) | baseline | 89% | 2.8 | 2.1 | 0.0 | 0.0 | 17 | 14s |
| sonnet-4.5 (strong) | fixes | 85% | 2.9 | 2.2 | 0.0 | 0.0 | 19 | 15s |

## Per-task highlights (weak model, where the waste manifests)

| task (targets PR) | baseline | fixes |
|---|---|---|
| err_python_env (#76992 hints) | 6.7 turns, 0.7 errs, 23s | **3.3 turns, 0 errs, 14s** — hint ends the python→python3/venv flail |
| err_case_search (#77011 probe) | 4.0 turns | **3.0 turns** — casing hint saves the retry |
| err_big_file_read (#76996 limit) | 5.0 turns, 88KB, 75s | **3.7 turns, 51KB, 39s** — one read instead of pagination churn |
| err_replay_patch (#76998) | 3.0 turns, exactly-once edit | same, both arms clean |

## Honest readout

- **Weak model: clear, consistent efficiency win.** −21% turns, −29% tool
  calls, errors and retries to zero, −23% wall, −33% result bytes. This is
  the population the fixes target.
- **Strong model: parity.** Sonnet already recovers from most induced errors
  in one turn; deltas are within n=3 noise (89 vs 85% ok is 1 run). The fixes
  don't slow it down; result-KB +2 is the added hint/metadata fields.
- **Success-rate deltas are small-n noise, not regressions:** every sub-100%
  fixes cell was audited run-by-run. 6 sonnet/fixes records from the first
  pass were startup crashes (0.7s, empty output — eval-infra flake, purged and
  re-run clean; the harness now retries these instead of recording them); one
  grading marker had wrong expected arithmetic (fixed in `abeval/ab_eval.py`);
  the rest are single-run strict-answer misses on n=3.
- **The eval caught a real product gap:** `err_hidden_search` fails on BOTH
  arms for sonnet — the #77011 hidden-file probe only fires on *total* zero
  matches, but this task has one visible match plus one hidden match, so no
  hint fires. Follow-up filed: compare visible vs `--hidden --no-ignore`
  counts on all searches and warn when hidden matches exceed visible.
- **Strongest always-on wins are mechanical and model-independent:** #77023
  schema diet (~700 tokens/request), #77095 skill_view dedup (~24.8k tokens
  per repeat view, measured live), #76996 read-limit (44% of truncated
  first-reads become single-call against the production distribution).

## The 16 merged PRs

#76992 terminal failure hints · #76996 read_file default 2000 ·
#76998 patch already-applied no-op · #77001 patch multi-match locations ·
#77004 terminal cwd echo · #77011 search zero-match probes + multi-path ·
#77013 process wait clarity · #77017 blocked-command recovery recipes ·
#77023 schema diet · #77024 patch whitespace diagnosis ·
#77041 recoverable truncation spill · #77055 write_file verification ·
#77095 skill_view repeat-view dedup · #77102 search auto-multiline ·
#77106 execute_code sandbox hints · #77128 integration fix (rg-path early
return in #77102 silently bypassed #77011's probes — caught by the merge
sequence's fresh CI, guard test added on main).

Raw per-run data (meta.jsonl + ATOF traces) lived in `/tmp/hermes-abeval/`
on the original run box and was not preserved; the harness in `abeval/` is
the reproducible path to regenerate it.

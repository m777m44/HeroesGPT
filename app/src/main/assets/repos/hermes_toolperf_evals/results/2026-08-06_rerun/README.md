# Rerun 2026-08-06 — full reproducible battery, checked-in data

108 runs (2 models × 2 arms × 9 tasks × 3 reps), zero infra crashes, executed
with the checked-in harness at this repo's `abeval/` (commit noted below).

## Pinned configuration

| what | value |
|---|---|
| baseline tree | hermes-agent `5b4d20b524` — last commit BEFORE the 15-PR batch landed |
| fixes tree | hermes-agent `f01c193be4` — last tool-batch commit (schema diet) |
| models | `anthropic/claude-sonnet-4.5`, `qwen/qwen3-coder-30b-a3b-instruct` (via OpenRouter) |
| reps | 3 per cell, `--max-turns 30`, 600s timeout |
| eval home | isolated `HERMES_HOME` (OpenRouter key only, nemo_relay plugin enabled) |

Arms differ by exactly the 15-PR batch (`git log 5b4d20b524..f01c193be4` minus
the unrelated a2a/desktop/gateway commits that rode the same day — those are
identical on both arms' relevant tool paths only insofar as they don't touch
tools/; the batch commits are the tool-layer diff).

## Data in this directory

- `report.txt` — full scored tables as printed by `ab_eval.py report`
- `<model>/<arm>/meta.jsonl` — per-run records (run_id, wall, exit, output tail)
- `atof-traces.tgz` — every per-run NeMo Relay ATOF trace (~100MB unpacked)

Regenerate the tables from raw data any time:

```bash
tar xzf atof-traces.tgz -C /tmp/abeval-workspace-restore
ABEVAL_ROOT=/tmp/abeval-workspace-restore python3 ../../abeval/ab_eval.py report \
  --models "anthropic/claude-sonnet-4.5,qwen/qwen3-coder-30b-a3b-instruct"
```

## Aggregate

| model | arm | ok% | llm turns | tool calls | errs | retries | result KB | wall |
|---|---|---|---|---|---|---|---|---|
| sonnet-4.5 | baseline | 89% | 2.9 | 2.2 | 0.0 | 0.0 | 17 | 16s |
| sonnet-4.5 | fixes | 85% | 2.8 | 2.1 | 0.0 | 0.0 | 17 | 22s |
| qwen3-coder-30b | baseline | 70% | 3.8 | 2.8 | 0.1 | 0.1 | 16 | 27s |
| qwen3-coder-30b | fixes | 81% | 4.9 | 3.9 | 0.1 | 0.1 | 33 | 42s |

## Honest readout — this rerun does NOT simply reproduce the Aug 2 numbers

The Aug 2 published run showed the weak model getting *faster* on fixes
(−21% turns). This rerun shows the weak model getting *more successful* on
fixes (70% → 81% ok) while spending more turns doing it. Per-task audit of
where the deltas come from:

- **`err_inline_script` baseline 33% → fixes 100% (qwen).** The blocked-command
  recovery recipes (#77017) doing exactly their job: baseline runs die at the
  parser block; fixes runs recover and finish. The extra turns ARE the win —
  a completed recovery costs more turns than an abandoned task.
- **`err_big_output` baseline 0% → fixes 33% (qwen).** Same shape: baseline
  gives up on the truncated output; fixes uses the spill file (#77041) and
  sometimes finds the token. The 85KB fixes cell is the spill being read.
- **`err_big_file_read` fixes 100% vs baseline 67% (qwen)** at +3 turns/+68KB:
  the raised read limit (#76996) gets qwen to the anomaly line reliably, but
  qwen re-reads more than it needs to.
- **`err_case_search` fixes regression (9.3 turns vs 3.3, qwen).** Real
  finding, not noise: the zero-match probe output sends qwen into extra
  exploratory searches on 2 of 3 reps. Sonnet shows no such effect. Filed
  mentally as: probe phrasing may over-stimulate weak models — worth a look.
- **`err_hidden_search` 0-33% on BOTH arms, both models.** The known product
  gap from the original run, still present at the pinned SHAs by design
  (the visible+hidden mixed case doesn't fire the probe).
- **Provider-side noise (qwen):** 5 baseline / 2 fixes runs ended with raw
  `<function=...>` XML in the final output — OpenRouter chat-template
  breakage, unrelated to either arm. This deflates qwen ok% on both arms and
  is visible in the meta.jsonl tails.
- **Sonnet: parity**, consistent with the original run. 89 vs 85% is one run
  of n=27; the 72s `err_inline_script` fixes cell is one rep hitting the
  approval-path retry.

## What both runs agree on

- Strong model: parity — the fixes cost nothing.
- Weak model: the targeted failure classes (parser blocks, truncation,
  big-file reads) flip from abandoned to completed.
- `err_hidden_search` gap is real and still open.
- The always-on mechanical wins (schema diet, skill_view dedup, read-limit)
  are not measured by this battery and stand on their own direct measurements.

## Differences in methodology vs the Aug 2 run

The Aug 2 run used the pre-merge integration branch as the fixes arm and
origin/main of that morning as baseline; this rerun brackets the batch by SHA
on main after everything landed (rebase-merge preserved the commits). The
Aug 2 raw traces were lost with `/tmp`; this run's traces are checked in, so
this is the canonical reproducible dataset going forward.

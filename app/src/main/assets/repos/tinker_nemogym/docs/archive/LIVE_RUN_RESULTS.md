# Live-Tinker End-to-End Validation Results

Date: 2026-04-22
Session: follow-up to commit `a558e63` (first live-Tinker smoke passing).
Budget: ~30 training steps consumed across 4 live runs (all Llama-3.1-8B-Instruct LoRA r=32).

## TL;DR

| Phase | Description                                     | Status  |
| ----- | ----------------------------------------------- | ------- |
| 1     | Wire varied-reward single-turn env (mcqa)       | **PASS** |
| 2     | Live mcqa run — 5 steps, loss + reward variance | **PASS** |
| 3     | Multi-turn env (example_multi_step)             | **PASS** (pipeline) |
| 4     | Checkpoint resume roundtrip                     | **PASS** |
| 5     | Wandb offline logging                           | **PASS** |
| 6     | Regression: 156 tests / ruff / mypy / e2e-fake  | **PASS** |

All success criteria met. All stretch goals met.

## Phase 1–2: Varied-reward single-turn env (mcqa)

- **Env picked**: `mcqa` (nemo-gym/resources_servers/mcqa) — single-turn
  multiple-choice QA, 10 options per question, reward = 0.0 / 1.0 depending
  on whether `\boxed{<letter>}` matches `expected_answer`. Five examples
  bundled at `tinker_nemogym/environments/mcqa/dataset.jsonl`.
- **Config**: `configs/smoke_mcqa.yaml`, `configs/nemogym_mcqa_resources.yaml`,
  `configs/nemogym_mcqa_agent.yaml`.
  - base_model: `meta-llama/Llama-3.1-8B-Instruct`
  - lora_rank: 32, learning_rate: 5e-4, loss: importance_sampling
  - n_steps: 5, batch_size: 2, group_size: 8, temperature: 1.0
  - drop_constant_reward: **true** (the whole point)
- **Launcher**: `scripts/smoke_mcqa.sh` (mirrors `scripts/smoke_single_tool.sh`).
- **Log**: `/tmp/live_run_mcqa.log`.

### Per-step results (final run, n_steps=5)

| step | mean_reward | n_datums | dropped | save_count (hot-swap) | loss     |
| ---- | ----------- | -------- | ------- | --------------------- | -------- |
| 0    | 0.688       | 8        | 1       | 2                     | -3.0095  |
| 1    | 0.312       | 8        | 1       | 3                     | 23.6185  |
| 2    | 1.000       | 0        | 2       | (skipped — constant)  | —        |
| 3    | 0.438       | 8        | 1       | 4                     |  0.1169  |
| 4    | 1.000       | 0        | 2       | (skipped — constant)  | —        |

Checkpoints saved at steps 2 and 4 (save_every=2 cadence honored).
Hot-swap verified: `save_count` advances 1→2→3→4 across training steps.

### Checkpoint URIs captured

```
tinker://a2bfc5f6-b6aa-54ac-a211-44b3bc0fb530:train:0/weights/smoke_mcqa-step-2
tinker://a2bfc5f6-b6aa-54ac-a211-44b3bc0fb530:train:0/weights/smoke_mcqa-step-4
```

(These are printed by the trainer via a new INFO log line — see the fix list
below.)

## Phase 3: Multi-turn env (example_multi_step)

- **Launcher**: `scripts/smoke_multi_step.sh` (new — mirrors smoke_mcqa.sh).
- **Log**: `/tmp/live_run_multi_step.log`.
- 2 steps completed, checkpoint saved at step 2.
  ```
  Step 0: mean_reward=0.000 n_datums=0 dropped=2
  Step 1: mean_reward=0.000 n_datums=0 dropped=2
  Checkpoint saved: label=smoke_multi_step-step-2 uri=tinker://dd9c582c-...
  ```
- Rewards were constant 0.0 on this small 5-row example (model never nailed
  the full synonym-extraction sequence) so `drop_constant_reward=true`
  skipped training — **pipeline is healthy**; `extract_trajectory` +
  `build_datum` handled the multi-turn rollouts without errors (would have
  raised otherwise, per gap 1 coverage).

## Phase 4: Checkpoint resume

- **Config**: `configs/smoke_mcqa_resume.yaml` (copies smoke_mcqa.yaml, sets
  `tinker.resume_from_checkpoint` = the step-4 URI from Phase 2).
- **Log**: `/tmp/live_run_mcqa_resume.log`.
- Evidence:
  ```
  Resuming from checkpoint: tinker://a2bfc5f6-...-b3bc0fb530:train:0/weights/smoke_mcqa-step-4
  Initial sampling client ready (save #1)
  Step 0: mean_reward=1.000 n_datums=0 dropped=2
  Step 1: mean_reward=0.500 n_datums=0 dropped=2
  Checkpoint saved: label=smoke_mcqa_resume-step-2 uri=tinker://d11e75ab-...
  ```
- **PASS**: load_state_async invoked before the first sampler snapshot, the
  trainer proceeds normally afterward, and a new checkpoint is saved under a
  fresh session run_id (Tinker spins up a new session client per run).

## Phase 5: Wandb logging

- **Config**: `configs/smoke_mcqa_wandb.yaml` (wandb_project=tinker-nemogym-live-test,
  wandb_name=smoke-mcqa). Driven in offline mode via `WANDB_MODE=offline`
  set by the launcher.
- **Log**: `/tmp/live_run_mcqa_wandb.log`.
- Artifacts: `wandb/wandb/offline-run-20260422_114753-4dzl8acz/`.
- Evidence (tail of log):
  ```
  wandb: Run history:
  wandb:        train/loss █▁
  wandb: train/mean_reward █▁
  wandb:    train/n_datums █▁
  wandb:   train/n_dropped ▁█
  wandb: Run summary:
  wandb:        train/loss 16.54378
  wandb: train/mean_reward 0.4375
  wandb:    train/n_datums 8
  wandb:   train/n_dropped 1
  ```
- wandb.init + per-step logging + wandb.finish all confirmed. **PASS**.

## Phase 6: Regression

- `poetry run pytest tests/ -q` → **156 passed**, 3 deselected, 4 warnings.
- `poetry run ruff check tinker_nemogym/ tests/ scripts/` → `All checks passed!`.
- `poetry run mypy tinker_nemogym` → `Success: no issues found in 15 source files`.
- `bash scripts/e2e_fake.sh` → `=== E2E PASSED ===` (fake Tinker).

## Bugs found + fixed in this session

See `docs/E2E_FIXES.md` for full detail. Summary:

1. **Per-step log opacity** — the INFO line only emitted `step / mean_reward /
   n_datums / dropped`. For live validation we needed `save_count` (to prove
   hot-swap happens every training step) and `loss` (to prove the gradient
   actually computes). Patched `trainer.py::run` to append both when
   available. This also unlocks easy grep-based post-mortem of multi-step
   runs.
2. **Checkpoint URI not logged** — `save_state_async()` returns a response
   whose `.path` is the `tinker://<run-id>/weights/<label>` URI needed by
   `load_state_async(path=...)`. We were awaiting but discarding it, so
   operators had no way to supply `resume_from_checkpoint` for the next run
   without digging into Tinker server logs. Patched
   `trainer.py::_maybe_save_checkpoint` to emit
   `Checkpoint saved: label=<L> uri=<U>` after successful save.
3. **group_size=4 too small for mcqa smoke** — at T=1.0 on an 8B Instruct,
   4-sample groups on 5 prompts tended to collapse to all-correct or
   all-wrong, starving GRPO of advantage signal. Bumped to
   `group_size: 8` in `smoke_mcqa.yaml` with an explanatory comment. Not a
   code bug, but a parameter that matters for the smoke.

No changes needed to rollout_driver, extract_trajectory, build_datum,
build_batch, or the FastAPI shim. Multi-turn + varied-reward + resume all
exercise those code paths and all came through green.

## Tinker credit / budget note

- 4 live runs, each with the 8B LoRA r=32 training client.
- Training steps with forward_backward actually fired: 3 (mcqa smoke) + 0
  (mcqa resume — both steps dropped by GRPO) + 2 (wandb smoke) + 0
  (multi_step — both dropped) = **5 training steps** of real
  forward_backward + optim_step, plus setup/hot-swap on each run.
- Well under the 30-40 step cap.

## Open issues

- The ng_run subprocess dumps a core on shutdown ("Aborted (core dumped)").
  This is pre-existing behavior coming from nemo-gym's Ray cluster teardown
  — not something tinker-nemogym triggers. Cleanup still completes, the
  trainer exits 0, and next run starts cleanly. Leaving as-is; noted here
  for visibility.
- Llama-3.1-8B on the 5-example `example_multi_step` row gets reward 0 on
  every rollout, so `drop_constant_reward=true` causes training to be
  skipped. To exercise actual gradient flow on this env, we'd need either
  a stronger base model, more examples so some groups have variance, or a
  task-easier subset. Not a bug in tinker-nemogym — it's working as designed.

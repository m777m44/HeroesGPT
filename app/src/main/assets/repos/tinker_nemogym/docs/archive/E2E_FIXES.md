# E2E Live-Run Fixes

Running-log of bugs found and patches applied while doing live-Tinker
end-to-end validation beyond the minimal `smoke_single_tool` path. For the
original session (first-ever live run) see commit `a558e63` — this document
covers follow-ups.

## 2026-04-22 — Varied-reward / multi-step / resume / wandb validation

### Fix #1: per-step INFO line missing hot-swap id + loss

**Symptom**: `/tmp/live_run_mcqa.log` showed only
`Step N: mean_reward=X n_datums=Y dropped=Z`. No way to tell from that line
alone whether the hot-swap fired or what the loss was, so the exercise of
"prove hot-swap IDs progress between steps + prove loss is computed" had to
fall back to reading wandb artifacts or Tinker server logs.

**Fix**: `tinker_nemogym/trainer.py::run` now appends ` save_count=<N>
loss=<F>` to the INFO line whenever those keys are present in the metrics
dict. `save_count` is only populated when the hot-swap succeeded, and `loss`
only when `forward_backward_async` returned a metrics dict (tinker SDK
convention: `loss:sum`). Constant-reward skipped steps have neither — the
string remains unchanged for them, preserving backward-compatible log output
for those cases.

### Fix #2: Checkpoint URI not surfaced to operator

**Symptom**: `Saving checkpoint label=smoke_mcqa-step-2 (logical path: ...)`
tells the operator the local dir name but not the `tinker://<run-id>/.../<label>`
URI that `load_state_async` expects. Previously we were awaiting the save
future and discarding its `.path`. So after a run, if you wanted to
`resume_from_checkpoint`, you had to ask Tinker admin for the run_id.

**Fix**: `_maybe_save_checkpoint` now captures `result = await
future.result_async()`, reads `result.path`, and emits a second INFO line:
`Checkpoint saved: label=<L> uri=tinker://<run-id>:train:0/weights/<L>`.
That URI is now copy-pasteable into `tinker.resume_from_checkpoint` for
the next run. Phase 4 of the live validation relies on this.

### Config tweak: mcqa smoke needs group_size=8 (not 4)

**Symptom**: first mcqa smoke with group_size=4 gave 1/5 step with
n_datums>0; the other four all collapsed to constant reward (0 or 1) within
each group and were dropped.

**Fix**: bump `group_size: 8` in `configs/smoke_mcqa.yaml`. At T=1.0 with
10-option MCQ on an 8B Instruct, 8 samples gives consistent intra-group
variance. Confirmed: 3/5 steps produce n_datums=8, advantages + loss fire.

Not a code fix — parameters only. Documented in the YAML with a comment so
future operators don't regress it.

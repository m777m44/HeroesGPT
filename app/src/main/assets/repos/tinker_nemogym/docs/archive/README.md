# Archive

Historical artifacts from the pre-shipping phase of **tinker-nemogym**.
Preserved for provenance. Nothing here is load-bearing for current
builds — if it turns out to be, that's a bug; fix the live docs instead.

## What's in here

### `plans/`

The original pre-implementation plan (`2026-04-21-tinker-nemogym-mvp.md`).
Written before any code existed; self-labeled as a frozen historical
reference. The shipped code deviated in several places — use the live
source + `CHANGELOG.md` for ground truth.

### `reviews/`

Seven pre-shipping code-review reports (`01_*`–`07_*`), plus
`ADDRESSED.md` tracking which findings landed. Line numbers and file
layouts referenced in the reports are from the 0.1.0 era and no longer
match HEAD. Actionable findings that shipped are captured in
`CHANGELOG.md` at v0.1.0.

### `E2E_FIXES.md`, `LIVE_RUN_RESULTS.md`

Postmortem notes from the first live-Tinker end-to-end run (2026-04-22).
Describes three bugs the live run surfaced + the fixes that landed
before 0.1.0.

### `run_postmortem.html`, `run_postmortem_full.png`, `e2e_walkthrough_curves.png`

Visualizations produced during that same postmortem — loss curves from
the first successful 5-step run plus a multi-panel explanation diagram.
Kept as a visual snapshot of the shape of convergence we saw on the
baseline config.

## If you're looking for…

- **How the code works today** → `README.md`, `docs/architecture.html`,
  `docs/quickstart.md`, `docs/diagnostics.md`
- **How to add a custom env** → `docs/custom_env_walkthrough.md`
- **What changed recently** → `CHANGELOG.md`
- **How to end-to-end test** → the "End-to-end testing" section of
  `README.md` (spoiler: `bash scripts/smoke_*.sh` with `TINKER_API_KEY`
  set — live Tinker is the only supported e2e path)

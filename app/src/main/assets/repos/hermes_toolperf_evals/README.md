# hermes-toolperf-evals

The complete eval set behind the hermes-agent core-toolset performance batch —
15 PRs + 1 integration fix, all merged
(tracker: [hermes-agent#77056](https://github.com/NousResearch/hermes-agent/issues/77056)).

Built from production session-DB mining (~1.5M messages), a schema token
audit, and NVIDIA NeMo Relay ATOF traces for ground-truth turn accounting.

## Layout

| dir | what |
|---|---|
| `abeval/` | The hard A/B eval: 9 error-inducing benchmark cases, baseline-tree vs fixes-tree (arms differ only by `PYTHONPATH`), 2 models × 3 reps, ATOF-scored. This is the harness behind the published before/after numbers. Parameterized — see its README. |
| `bench/` | The earlier 11-task baseline battery (8 generic + 3 hint-targeted) that established the waste profile. Preserved as recovered; original hardcoded paths noted in its README. |
| `analysis/` | The mined data: `CANDIDATES.md` (P1–P14 pain points with magnitudes from the 400k-message window) and `PR_DESIGNS.md` (per-PR designs with the DB frequency justifying each rule). |
| `results/` | Checked-in run data. `2026-08-06_rerun/` is the canonical reproducible dataset: pinned SHAs, meta.jsonl per cell, full ATOF traces, regeneration instructions, and an honest readout vs the Aug 2 published numbers. |
| `docs/` | `METHODOLOGY.md` — how the targets were derived (the answer to "how did you find these"); `RESULTS.md` — the Aug 2 published A/B tables + readout (raw traces lost; superseded as canonical by `results/2026-08-06_rerun/`). |

## The 9 A/B benchmark cases

`err_python_env`, `err_replay_patch`, `err_ambiguous_edit`, `err_case_search`,
`err_hidden_search`, `err_big_output`, `err_multi_dir`, `err_inline_script`,
`err_big_file_read` — each derived from a mined production waste class, with a
sandbox fixture and a deterministic success marker.

## Headline numbers (weak model, where tool-ergonomics waste manifests)

−21% LLM turns · −29% tool calls · tool errors and retry-after-error → 0 ·
−33% result bytes into context · −23% wall clock. Strong model: parity (it
already recovers in one turn — which is why weak-model runs are the signal).

## Running the A/B eval against your own model (e.g. Nemotron Ultra)

```bash
cd abeval
./run_all.sh <baseline-tree> <fixes-tree> [reps] [models...]
```

The harness shells out to the `hermes` CLI; any provider model id works.
Startup crashes (nonzero exit, empty output) retry on resume instead of being
recorded as data points. Report the mean of ≥3 reps per cell; n=3 deltas
under a few percent are noise.

The A/B harness also ships inside hermes-agent at `scripts/toolperf_abeval/`
(landed in PR #79162); this repo is the canonical home for the full eval set
including the pieces that don't belong in the product tree.

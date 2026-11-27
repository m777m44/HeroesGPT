# Methodology: how the optimization targets were derived

The 15-PR core-toolset batch (tracker: [hermes-agent#77056](https://github.com/NousResearch/hermes-agent/issues/77056))
was not driven by intuition. Every candidate came from mining production data,
and every merged fix was validated with a before/after A/B eval. Two-stage
method:

## Stage 1 — Session-DB mining for a real error taxonomy

Hermes logs every message to a local SQLite store (`~/.hermes/state.db`,
~1.5M messages at the time of the study). A recent 400k-message window was
analyzed read-only:

- **Per-tool volume and error-shape histograms.** Normalize result messages
  (paths → `<PATH>`, digit runs → `N`), then `Counter` top-N error shapes per
  tool. This turns 40k raw error strings into a ranked taxonomy of failure
  classes with real frequencies.
- **Wasted-turn detection.** Build a `tool_call_id → (name, args)` map from
  assistant `tool_calls`, walk each session's call→result sequence, and count:
  exact consecutive duplicate calls, same-tool retry immediately after an
  error result, and ≥3-failure streaks.
- **Attribution.** Failures are attributed back to the specific command/arg
  through `tool_call_id`, so "9,175 gh `Unknown JSON field` failures" points
  at the exact flag surface, not a vague bucket.

Concrete yields (see `analysis/CANDIDATES.md` for the full P1–P14 table):
60.2% of 104k terminal calls carried `cd X && ...` prefixes (~925k tokens of
pure prefix); 74.3% of 28.5k file reads truncated, triggering 12k re-reads and
4.6k fallbacks to `cat`/`sed` (tool distrust); 13.9% of searches returned zero
matches as a silent dead turn; ~33k tokens of tool schemas on every request.

## Stage 2 — NeMo Relay ATOF traces for ground-truth turn accounting

Session-DB mining finds the waste classes; NVIDIA NeMo Relay's ATOF traces
provide per-run ground truth when measuring a fix: LLM turns, tool calls, tool
errors, retry-after-error, result bytes into context, wall clock, and task
success — all from the trace, not from self-reported agent logs.

## Stage 3 — Candidate → design → PR → A/B validation

1. Mined pain points ranked by magnitude → `analysis/CANDIDATES.md`
2. Per-PR designs with the DB frequency justifying each rule →
   `analysis/PR_DESIGNS.md`
3. One PR per candidate (15 total, plus #77128 integration fix)
4. Hard A/B eval (`abeval/`): baseline tree vs all-fixes tree, arms differing
   ONLY by `PYTHONPATH`, 9 error-inducing tasks derived from the mined waste
   classes, weak + strong model, 3 reps/cell. Weak-model results are the
   signal: strong models mask tool-ergonomics waste by recovering in one turn.

Results: `docs/RESULTS.md`.

## Design principles that fell out of the data

- **Auto-DO recovery beats hint-only** where safe; otherwise put one
  actionable hint in the result the model actually reads.
- **Measure before building.** Several plausible candidates died on the data
  (auto-`ls` after cd: only 0.2% of successful bare-cds were followed by a
  listing; read_file truncation economics: the targeted cap fired on 0.04% of
  reads).
- **A/B on a weak model.** The eval caught a real product gap
  (`err_hidden_search` failing on both arms) that strong-model testing would
  never have surfaced.

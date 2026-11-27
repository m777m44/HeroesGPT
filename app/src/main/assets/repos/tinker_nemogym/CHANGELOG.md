# Changelog

All notable changes to **tinker-nemogym** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
* **Precision-gap (β) diagnostic** — opt-in shadow `forward_async` pass
  that diffs trainer-side logprobs against sampler-side logprobs (see
  `tinker_nemogym/precision_gap.py` + `docs/diagnostics.md`). Controlled
  by `training.measure_precision_gap: bool = False`. Implements the
  measurement from the HuggingFace BF16-mismatch paper.
* **Sampler-version pinning** — every `RawTrajectory` now carries the
  `save_count` of the `SamplingClient` snapshot that produced it. The
  shim stamps it on every response; the trainer computes per-step
  staleness aggregates (`staleness_mean` / `staleness_max` /
  `staleness_n_stale`).
* **Per-rollout latency** — shim stamps `sample_latency_ms` +
  `sample_started_at` on every response; trainer aggregates to
  `sample_latency_ms_mean` / `p50` / `p95` / `max`.
* **`prompt_logprobs` / `topk_prompt_logprobs` passthrough** — shim
  accepts the flags off the request body, forwards to Tinker, surfaces
  on the response.
* **`sampling_params_used` echo** — every response now echoes the actual
  `SamplingParams` sent to Tinker (including defaults) for
  reproducibility.
* **`configs/smoke_diagnostics.yaml`** + **`scripts/smoke_diagnostics.sh`**
  — canonical example config + launcher that exercises every diagnostic
  end-to-end against live Tinker.
* **`build_batch_with_trajectories`** — variant of `build_batch` that
  also returns the surviving `RawTrajectory`s (aligned with the datums)
  so callers can pair them for the β shadow pass.
* **Wandb metrics** — the `_log_wandb_metrics` emitter now also logs
  `beta_*`, `sample_latency_ms_*`, `staleness_*`, `prompt_tokens_mean`,
  `completion_tokens_mean` when present.

### Changed
* **`set_sampling_client(client, version=N)`** — the hot-swap primitive
  now takes an optional `version` kwarg so the shim can stamp responses
  accurately. Backwards-compatible (defaults to preserving the previous
  version).
* **`docs/reviews/` and postmortem docs** moved to `docs/archive/` —
  they describe pre-shipping review rounds and the first live-Tinker
  run. Kept for provenance; no longer surfaced in the main docs tree.

### Removed
* **`scripts/e2e_fake.sh`** + **`scripts/e2e_fake.py`** — the offline
  no-API-key driver. Live Tinker is now the only supported end-to-end
  path; see the "End-to-end testing" section of the README for the full
  matrix of `smoke_*.sh` scripts. The pytest-internal fakes
  (`tinker_nemogym/testing/`) remain for unit/integration tests — those
  are explicitly internal-only and not a public extension point.
* **`_find_training_output` helper** in `tinker_nemogym/datum_builder.py`
  — dead code; `_collect_training_outputs` was the only caller-facing
  extractor.

## [0.1.0] — 2026-04-23

First tagged release. Public API stabilised; live-validated against the
Tinker cloud on `meta-llama/Llama-3.1-8B-Instruct` + the `mcqa` env.

### Added
* Exception hierarchy — `TinkerNeMoGymError` base plus `ConfigError`,
  `TrainingError`, `ShimError`, `SamplerNotReadyError`, `AgentDiscoveryError`,
  `CheckpointError`. One `except TinkerNeMoGymError` catches every library
  error.
* `tinker_nemogym.train(config)` — synchronous one-liner wrapper around the
  async trainer. Accepts a YAML path or a `TinkerNeMoGymConfig`.
* Top-level public API: `tinker_nemogym` re-exports `TinkerNeMoGymConfig`,
  `TinkerNeMoGymTrainer`, `RawTrajectory`, `build_datum`, `build_batch`,
  `compute_advantages`, and the full error hierarchy. Short aliases
  `Trainer` / `Config` / `Trajectory` are also exported.
* `__version__` read from package metadata (`importlib.metadata`).
* `py.typed` marker — downstream type checkers now see our inline
  annotations as authoritative (PEP 561).
* `schema_version: int = 1` top-level config field; loader rejects future
  versions with a migration message.
* Eager config validation — `from_yaml` / `TinkerNeMoGymConfig(...)` now
  fails fast when:
  * `nemogym.dataset_jsonl` doesn't exist (opt out via `strict: false` or
    the `@createme` suffix for deferred-create workflows),
  * `tinker.checkpoint_dir` has no existing ancestor within 2 parent levels,
  * `tinker.base_model` contains characters outside `[A-Za-z0-9_\-./:]`.
* `SamplingClientProtocol` + `TrainingClientProtocol` + DI seam
  (`service_client_factory`) for test/extension.
* Preflight reachability checks (HeadServer + base-model allow-list) with
  actionable errors.
* Structured logging + `run_id` contextvar propagation.
* Checkpoint resume-state metadata artifact.
* Supported environments: `single_tool_call`, `multi_step`, `mcqa`.
* Offline e2e fakes + `scripts/e2e_fake.sh` (runs without TINKER_API_KEY).
* CI: GitHub Actions matrix (Python 3.12) + pre-commit config.

### Changed
* Default `base_model` is `meta-llama/Llama-3.1-8B-Instruct`
  (on Tinker's allow-list; the 1B variant is not).
* `agent_url` defaults to `null` in smoke configs; trainer discovers the
  SimpleAgent port dynamically via the HeadServer `/server_instances`
  endpoint instead of hard-coding `:11001`.
* Checkpoint labels passed to Tinker's `save_state_async` are derived as
  `[A-Za-z0-9._-]+` from `checkpoint_dir`; filesystem-looking paths are
  rejected by Tinker.
* `tinker_responses_model.py` — 503 vs 500 classification now uses
  `isinstance(e, SamplerNotReadyError)` instead of a substring match on
  the error message.
* Trainer training-call errors are wrapped as `TrainingError` with step /
  operation context. Checkpoint failures wrap as `CheckpointError`.
* `from_yaml` wraps `OSError` / `YAMLError` as `ConfigError`.

### Fixed
* Three real-server bugs surfaced by the first live Tinker run (see
  `docs/E2E_FIXES.md` + `docs/LIVE_RUN_RESULTS.md`).

### Quality
* 211 unit + integration tests passing; 3 opt-in slow tests for live
  Tinker / live `ng_run`.
* `ruff check` + `mypy` clean across `tinker_nemogym/`, `tests/`, `scripts/`.

## [0.0.1] — 2025-??-??

Initial snapshot. Live-Tinker end-to-end validated on
`meta-llama/Llama-3.1-8B-Instruct` + `mcqa` env.

### Added
* Pydantic configuration schema (`TinkerNeMoGymConfig`) with four
  sub-blocks: `tinker`, `model_server`, `nemogym`, `training`.
* Async trainer (`TinkerNeMoGymTrainer`) with:
  * LoRA training client + periodic weights/sampler hot-swap,
  * Rollout driver (`aiohttp` session pooled for the trainer's lifetime),
  * GRPO advantage computation + `max_trainer_tokens` cap,
  * Dynamic agent URL discovery via the nemo-gym HeadServer,
  * Optional wandb integration (`cfg.tinker.wandb_project`),
  * Resume-from-checkpoint support (`cfg.tinker.resume_from_checkpoint`),
  * Narrow exception handling (auth errors fatal, rate-limit / transient
    errors skip the step).
* FastAPI shim (`tinker_responses_model`) implementing
  `/v1/chat/completions` and `/v1/responses` with the
  TokenIDLogProbMixin contract; propagates `session` cookies for
  stateful multi-turn envs.
* Pure datum builder (`datum_builder`) — `extract_trajectory`,
  `build_datum`, `build_batch`, `compute_advantages`.
* Offline test fakes (`tinker_nemogym.testing.fakes`):
  `FakeServiceClient`, `FakeLoRATrainingClient`, `FakeSamplingClient`,
  `FakeWandb` + `make_fake_tinker_module()`, `patch_wandb()`
  context managers.
* CLI (`tinker-nemogym-train`, `tinker-nemogym-serve`) with
  `--log-level` and `--version`.
* Environment bundles: `single_tool_call`, `multi_step`, `mcqa`.
* E2E harness (`scripts/e2e_fake.sh`, `tests/integration/test_e2e_fake.py`)
  that runs without TINKER_API_KEY or nemo-gym subprocesses.
* CI: GitHub Actions matrix (Python 3.12) + pre-commit config.

[Unreleased]: https://github.com/nousresearch/tinker-nemogym/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nousresearch/tinker-nemogym/releases/tag/v0.1.0
[0.0.1]: https://github.com/nousresearch/tinker-nemogym/releases/tag/v0.0.1

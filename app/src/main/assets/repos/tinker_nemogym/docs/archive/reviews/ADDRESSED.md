# Review Fix-List — Addressed Findings

This document cross-references every review finding addressed in the
"review fix-up" sprint (see `git log --grep "Review"` for the commits).

## Review 01 — Tinker API correctness

| § | Title | Commit |
|---|-------|--------|
| 1.1 / 7 | Drop deprecated `name=` kwarg on `save_weights_and_get_sampling_client_async` | `feat(sdk-compat): drop deprecated name kwarg + fix adam_eps default` |
| 1.2 / 12 | Default `base_model` → `Llama-3.2-1B-Instruct` + warn on non-chat | `feat(config): default to Instruct base model + warn on non-chat models` |
| 1.5 / 9 | `adam_eps` default 1e-8 → 1e-12 (SDK default) | `feat(sdk-compat): drop deprecated name kwarg + fix adam_eps default` |
| 1.6 / 2 | Logprob sentinel (1.0 vs 0.0) — keep 1.0 + document | `feat(sdk-compat): drop deprecated name kwarg + fix adam_eps default` |

## Review 02 — NeMo-Gym integration

| § | Title | Commit |
|---|-------|--------|
| 1.3 | Propagate `session` cookie in shim for multi-turn envs | `feat(shim): propagate session cookies for stateful multi-turn envs` |
| 1.4 | Dynamic agent URL discovery via HeadServer | `feat(trainer): dynamic agent URL discovery via HeadServer` |
| 4.1 | (Deferred) adopt nemo-gym `ServerClient` for polling | **deferred** — current httpx polling works and doesn't block anything; adding the `ServerClient` dependency surface on the discover path adds ray/hydra imports we don't need in the thin trainer. Re-evaluate once we migrate the trainer onto nemo-gym's main process. |
| 4.2 | Harvest `response.usage` / `.id` / `n_turns` into metadata | `feat(datum): harvest response.usage/id into trajectory metadata` |

## Review 03 — Atropos architectural parity

| § | Title | Commit |
|---|-------|--------|
| 2.2 | `max_trainer_tokens` cap to prevent Tinker `max_seq_len` overflow | `feat(datum): max_trainer_tokens cap to prevent Tinker overflow` |

## Review 04 — Software quality

| § | Title | Commit |
|---|-------|--------|
| 2.1 / 6.1 | Pydantic range validators + path-traversal guard | `feat(config): default to Instruct base model + warn on non-chat models` |
| 2.3 | aiohttp `ClientSession` pooling at trainer lifetime | `refactor(rollout): hoist aiohttp ClientSession to trainer lifetime` |
| 2.4 | Narrow broad `except Exception` clauses + rate-limit handling | `refactor(trainer): narrow except clauses + split _run_step` |
| 2.5 | Split `trainer._run_step` into 3 helpers | `refactor(trainer): narrow except clauses + split _run_step` |
| 3.1 | Mypy configuration + fix non-strict errors | `chore(tooling): mypy config + pre-commit hooks` |
| 3.2 | Pre-commit config (not installed, just committed) | `chore(tooling): mypy config + pre-commit hooks` |
| 3.3 | GitHub Actions CI workflow | `chore(ci): GitHub Actions workflow` |
| 5.1 | CLI `--log-level`, `--version`, `ValidationError` wrapping | `feat(cli): --log-level + --version + ValidationError wrapping` |
| 5.2 | Shared `conftest.py` autouse reset fixture | `feat(testing): shared conftest reset fixture for module globals` |

## Out of scope (per user directive)

* **Auth / CORS / rate-limit on the FastAPI shim** — local-only use,
  explicitly excluded.
* **Dockerfile / Helm / K8s manifests** (Review 07 §5) — local-only use.
* **OpenTelemetry tracing** (Review 07 §4) — overkill for current scope.

## Skipped with rationale

* **Review 02 §4.1** (ServerClient drop-in) — see table above.

## Review 05 — FAANG architectural review

| § | Title | Commit |
|---|-------|--------|
| 4.1 | Exception hierarchy (`TinkerNeMoGymError` + subclasses) | `feat(errors): exception hierarchy` |
| 4.1 | Replace substring-match dispatch with `isinstance(SamplerNotReadyError)` | `refactor(server): use SamplerNotReadyError instead of substring-match` |
| 4.1 | Wrap training-call errors as `TrainingError` with context | `refactor(trainer): wrap training-call errors as TrainingError with context` |
| 4.2 | `py.typed` PEP 561 marker | `chore(packaging): add py.typed marker` |
| 4.3 | Populate top-level `__init__.py` (public API + aliases) | `feat(api): re-export public symbols + stable aliases in __init__.py` |
| 4 (D1) | `service_client_factory` DI seam | `feat(trainer): preflight reachability checks ...` (introduced) + `feat(trainer): service_client_factory DI seam for test/extension` (finalised) |
| 4 (D2) | `schema_version` field with upgrade-path validation | `feat(config): schema_version field with upgrade-path validation` |
| 4 (D3) | `SamplingClientProtocol` + `TrainingClientProtocol` | `feat(interfaces): SamplingClientProtocol + TrainingClientProtocol` |

## Review 06 — Library-author review

| § | Title | Commit |
|---|-------|--------|
| 6 (B1) | `tinker_nemogym.train()` sync wrapper | `feat(api): tinker_nemogym.train() sync wrapper` |
| 6 (B2) | Eager config validation (paths + model id regex) | `feat(config): eager validation of paths + base_model pattern` |
| 6 (B3) | `CHANGELOG.md` | `docs: CHANGELOG.md + quickstart.md` |
| 6 (B4) | `docs/quickstart.md` (programmatic-first) | `docs: CHANGELOG.md + quickstart.md` |

## Review 07 — Production operability review

| § | Title | Commit |
|---|-------|--------|
| 3 (C1) | Structured logger + `run_id` contextvar propagation | `feat(utils): structured logging + run_id contextvar propagation` |
| 3 (C2) | Preflight reachability checks with actionable errors | `feat(trainer): preflight reachability checks with actionable errors` |
| 3 (C3) | Resume-state metadata artifact (`<label>.meta.json`) | `feat(checkpoint): resume-state metadata artifact` |

## Deferred from this sprint (reviews 05/06/07)

* **Review 05 §3 full roadmap** — we ship the surgical subset (§4.1-4.3,
  D1-D3). The broader restructure (splitting the trainer into a driver +
  strategy pattern) is high blast-radius; left as a follow-up.
* **Review 06 §3 v0.2 API** — only `train()` + public-surface stabilisation
  landed. Streaming callbacks + pluggable loss-fns deferred.
* **Review 07 §4 metrics backend / Prometheus** — we ship structured
  logging only; Prometheus / OpenTelemetry are out of scope for a local-only
  library. Wandb already covers the production path.
* **Review 07 §5 container / deployment** — local-only per user directive.

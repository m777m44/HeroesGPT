# Review 03 — Architectural Parity with `tinker-atropos`

**Scope.** Side-by-side audit of `tinker-nemogym` against the canonical
reference `NousResearch/tinker-atropos` (pattern we were asked to emulate). No
code was modified in this pass; this document records verdicts and proposals
only.

**Sources.**
- Us: `tinker-nemogym/` (HEAD).
- Reference: `tinker-atropos/` (HEAD on `main`).
- Prior analysis: `analysis/03_tinker_atropos_reference.md` (590 lines).

---

## §1. Feature Parity Matrix

Legend: ✅ = have, ❌ = missing, ⚠️ = divergent (intentional or accidental).

| # | `tinker-atropos` feature | Ours (`tinker-nemogym`) | Status | Evidence |
|---|---|---|---|---|
| 1 | 3-process launcher bash (`run_logp_steering.sh`) | 1-process + optional nemo-gym subproc (`scripts/smoke_single_tool.sh`, spawns `ng_run`) | ⚠️ | atropos `run_logp_steering.sh:26-42` vs our `scripts/smoke_single_tool.sh:52-100` |
| 2 | Polling-based trainer (`GET /batch` w/ retry) — trainer is a *consumer* | Push-based trainer — trainer *drives* rollouts via `rollout_driver.rollout_batch` | ⚠️ intentional | `trainer.py:104-129` vs our `trainer.py:282-288` |
| 3 | `pad_data_to_good_offset` (pre-built tokens+masks+ref-logprobs per trajectory) | `datum_builder.build_batch` (tokens from nemo-gym response output) | ⚠️ | `trainer.py:174-365` vs `datum_builder.py:203-312` |
| 4 | Loss = `"importance_sampling"` hardcoded | Loss = Literal["importance_sampling","ppo","cispo","dro"], default IS | ⚠️ (superset) | `trainer.py:422-424` vs `config.py:24` |
| 5 | On-policy distillation (overwrite `advantages = logp_t − logp_s`) | ❌ no distillation path | ❌ | `trainer.py:262-293` |
| 6 | `/logprobs` endpoint (teacher-forcing fwd) | ❌ | ❌ | `trainer.py:777-830` |
| 7 | `/v1/completions` (plain) | ❌ (only `/v1/chat/completions` + `/v1/responses`) | ❌ | `trainer.py:558-615` |
| 8 | `/generate` SGLang-shape | ❌ | ❌ (N/A — no SGLang consumer) | `trainer.py:687-774` |
| 9 | `/v1/chat/completions` | ✅ | ✅ | `tinker_responses_model.py:260-315` |
| 10 | `/v1/responses` (OpenAI Responses API) | ✅ (ours) | ⚠️ divergent — nemo-gym-native | `tinker_responses_model.py:318-384` |
| 11 | `/health` | ✅ | ✅ | `tinker_responses_model.py:199-205` |
| 12 | `/wandb_info` (let env discover wandb group) | ❌ | ❌ | `trainer.py:618-626` |
| 13 | Standalone `serve.py` (inference-only, `--weights tinker://…`) | ✅ (`serve.py` but shares trainer setup; no `--weights` override) | ⚠️ | atropos `serve.py:1-163` vs ours `serve.py` (14 lines → `cli.serve` which runs `trainer.setup()`) |
| 14 | `download_weights.py` utility | ❌ | ❌ | `tinker_atropos/utils/download_weights.py` |
| 15 | CLI = argparse | CLI = click (group + train/serve subcommands) | ⚠️ intentional | `launch_training.py:10-39` vs `cli.py:32-90` |
| 16 | `fwd_bwd` and `optim_step` pipelined (enqueue both before `.result_async`) | ✅ identical pipeline pattern | ✅ | `trainer.py:422-436` vs our `trainer.py:337-345` |
| 17 | Hot-swap sampling client via `save_weights_for_sampler` + `create_sampling_client` | ✅ equivalent `save_weights_and_get_sampling_client_async` | ✅ (newer SDK path) | `trainer.py:475-480` vs our `trainer.py:373-377` |
| 18 | Drop groups with zero-variance advantages | ✅ (`drop_constant_reward=True`) | ✅ | `trainer.py:221-223` vs `datum_builder.py:299-301` |
| 19 | GRPO advantage = `scores − mean(scores)` | ✅ identical | ✅ | `trainer.py:214-216` vs `datum_builder.py:198-200` |
| 20 | Magic port 8001 hardcoded in 4 places | Port is configurable (`ModelServerConfig.port=8001` default) | ✅ fixed | `config.py:35-41` |
| 21 | Global mutable `trainer` module var (FastAPI reads it) | Module-global `_current_sampling_client` behind a `Lock` | ⚠️ narrower surface | `trainer.py:543` vs `tinker_responses_model.py:46-62` |
| 22 | CLI override `to_dict()`-round-trip (lossy for `@property` keys) | Click options not applied on top of YAML yet (only `--config`) | ❌ no CLI overrides | `launch_training.py:76-80` vs `cli.py:37-54` |
| 23 | Pydantic validators | Minimal (type hints only; no cross-field validators) | ⚠️ weaker | `config.py:42-55` vs our `config.py:15-84` |
| 24 | Test coverage: `test_logprob_alignment`, `test_distillation`, `test_logprobs_endpoint`, `test_managed_server`, `test_serve_integration`, `test_logp_steering_env` | `test_datum_builder`, `test_trainer`, `test_rollout_driver`, `test_tinker_responses_model`, `test_cli`, `test_config`, `test_fakes`, + 8 integration tests | ⚠️ different surface — we test more integration paths, no distillation tests | ours `tests/` |
| 25 | Error recovery: `tenacity` retries on `/batch`; asserts crash on length mismatch | Best-effort: try/except around rollout + fwd_bwd + hot-swap; `rollout_group_with_retry` available | ⚠️ ours more forgiving | `trainer.py:125-129` vs our `trainer.py:282-381` |
| 26 | Resume-from-checkpoint (not supported in `tinker-atropos`) | ✅ `tinker.resume_from_checkpoint` → `load_state_async` | ✅ extra | our `trainer.py:133-148` |
| 27 | Staleness control (`max_batches_offpolicy=3`) via Atropos-side queue | ❌ no staleness window (push model makes staleness == 0) | ⚠️ by construction | `config.py:20` |
| 28 | Server-side batch aggregation across env workers | N/A (single-process rollout driver) | ❌ cannot scale horizontally | Atropos API architecture |
| 29 | `uvicorn.run` in daemon thread with `asyncio.sleep(3)` readiness hack | `uvicorn.Server` in daemon thread polled on `server.started` until bound | ✅ better | `launch_training.py:130-131` vs our `trainer.py:218-234` |
| 30 | `logprob_stats` / `advantage_stats` / `distil_stats` wandb keys | `train/mean_reward`, `train/loss`, `train/n_datums`, `train/n_dropped`, `train/sampler_version` | ⚠️ different key namespace, fewer aggregates | `trainer.py:310-360` vs our `trainer.py:385-411` |

---

## §2. Deep Dive: `pad_data_to_good_offset()` vs `datum_builder.build_batch`

### 2.1 What `pad_data_to_good_offset` actually does

Despite its name, `pad_data_to_good_offset` **does not pad or pack** in the
usual ML sense. Reading `trainer.py:174-365` line by line:

1. **Per-trajectory conversion, not batch padding.** The function iterates over
   `item["tokens"][i]` and emits *one* `tinker.Datum` per trajectory. There is
   no tensor batch, no attention mask on pad tokens, no right/left padding to
   `max_len`. Each Datum carries its own variable-length sequence — Tinker's
   server-side batcher handles pad/pack on its end.
2. **"Good offset" = next-token-shift alignment.** The "offset" refers to
   `tokens[:-1]` / `tokens[1:]` and `trajectory_logprobs[1:]` (`trainer.py:247-
   250`). That's a 1-position shift so the logprob array aligns with target
   tokens — identical to what we do in `build_datum` (`datum_builder.py:240-
   259`).
3. **Prompt masking via sentinel.** `1.0` in `inference_logprobs` marks prompt
   positions; the function maps those to `advantage=0.0`
   (`trainer.py:252`). We use the **same sentinel** (`PROMPT_LOGPROB_
   SENTINEL=1.0`) but we **construct** the sentinel block at Datum-build time
   rather than consuming it from upstream (`datum_builder.py:211-213, 254-
   256`). Functionally equivalent; the mechanism just lives on a different
   side of the producer/consumer boundary.
4. **GRPO advantage centering.** `advantages = scores − mean(scores)` per
   group, skip group if `all(advantages==0)`: lines 214-223. We do the same in
   `compute_advantages` + `build_batch(drop_constant_reward=True)`.
5. **Optional per-token advantage override for distillation.** Lines 262-286
   overwrite `advantages[t] = logp_teacher[t] − logp_student[t]`. **We do not
   have this path.** See §5 item 5 for the proposal.
6. **No multi-datum-per-trajectory splitting.** A long trajectory is not split
   into chunks — it becomes one Datum. Trainer length cap
   (`max_token_trainer_length=2048`, `config.py:47`) is advisory; it's not
   enforced in the adapter. Ours has no trainer-length cap at all either.

### 2.2 Do we need padding/packing?

**No, not at the client side.** Tinker's `forward_backward_async(List[Datum])`
accepts variable-length Datums and handles pad/pack server-side. Adding
client-side padding would be **wasted work** and would lie to the
server-side sample-packer. Both implementations correctly stay out of this
business.

**We should, however, enforce a trainer-length cap** (see §5 item 1). A
runaway multi-turn trajectory from nemo-gym can blow through Tinker's
`max_seq_len` silently; atropos at least surfaces this as a config value
users see. **Proposal:** add `training.max_tokens_trainer: int = 2048` to
`TrainingConfig`; in `build_datum`, log-warn (not raise) when
`len(input_tokens) > max_tokens_trainer` and optionally truncate from the
left (preserving response tail).

### 2.3 Do we need a distillation path?

**Yes, as an opt-in feature.** The elegance of atropos's approach is that
the **loss function is unchanged** (`importance_sampling`); only the
`advantages` tensor gets overwritten. That means distillation support is a
~30-line feature in `build_datum` keyed off an optional
`RawTrajectory.teacher_logprobs: list[float] | None` field. See §5 item 5.

---

## §3. Process Model Diff

### 3.1 `tinker-atropos`: 3 processes

```
P1  uvicorn atroposlib.api.server:app      :8000  (Atropos Trajectory API)
P2  python launch_training.py              :8001  (Trainer + FastAPI shim daemon-thread)
P3  python -m tinker_atropos.environments.logp_steering serve (env worker)
```

Rollout flow: P3 env worker → P2 `/v1/chat/completions` for generation → P2
`/logprobs` for teacher lps → P3 scores → P3 `POST :8000/scored` → P1 queues
→ P2 `GET :8000/batch` → train.

P1 is an **Atropos-provided** central broker; staleness is enforced at the
broker (`max_batches_offpolicy=3`). P2 and P3 are loosely coupled — P2 never
initiates traffic to P3.

### 3.2 `tinker-nemogym`: 2 processes (+ optional 3rd)

```
P1  ng_run … (nemo-gym HeadServer 11000 + SimpleAgent 11001 + ...)
P2  python launch_training.py              :8001  (Trainer + FastAPI shim daemon-thread)
```

Rollout flow: P2 `rollout_batch` → POST `agent_url/run` on P1 → agent calls
P2 `/v1/chat/completions` for generation → agent returns scored response → P2
builds Datums → train.

**Key differences:**
- **No central broker.** P2 initiates every rollout; no queue, no staleness
  window. Staleness is always 0 by construction. For short-horizon smoke
  tests this is fine; for long training runs it prevents horizontal scaling
  of env workers (§5 item 9).
- **Fewer processes.** P2 drives everything. This is simpler to operate but
  couples rollout-latency to train-step latency 1:1.
- **Optional 3rd** — `scripts/smoke_single_tool.sh` spawns `ng_run` as a
  subprocess of the test harness, but in production the user's expected to
  own the nemo-gym deployment.

### 3.3 Verdict

The push model is a **defensible intentional divergence** — it matches
nemo-gym's `SimpleResponsesAPIAgent` which is a *pull* consumer expecting
the policy model on the other side of HTTP. But we should **explicitly
document** that this precludes multi-env-worker scaling (§7).

---

## §4. OpenAI-Endpoint Coverage Gap

| Endpoint | atropos | ours | Needed? |
|---|---|---|---|
| `POST /v1/chat/completions` | ✅ | ✅ | yes |
| `POST /v1/responses` | ❌ | ✅ | yes for nemo-gym Responses-API agents |
| `POST /v1/completions` | ✅ | ❌ | **unlikely** — nemo-gym agents don't use plain completions |
| `POST /generate` (SGLang) | ✅ | ❌ | **no** — SGLang schema is Atropos-specific (`ManagedServer`) |
| `POST /logprobs` | ✅ | ❌ | **yes, if we add distillation** (§5 item 6) |
| `GET /health` | ✅ | ✅ | yes |
| `GET /wandb_info` | ✅ | ❌ | nice-to-have; see §5 item 12 |

**Genuine gap:** `/logprobs` — blocks any future distillation env. Atropos's
implementation is a thin wrapper over `sampling_client.compute_logprobs_async`;
it would be ~40 lines in `tinker_responses_model.py`.

**Non-gaps:**
- `/v1/completions`: nemo-gym has moved to chat / Responses; no consumer.
- `/generate` (SGLang): specific to Atropos's `ManagedServer`; nemo-gym has
  no analogue.

---

## §5. Per-Item Verdicts (15 Items from the Brief)

### 1. `pad_data_to_good_offset()` ▶ do we need padding/packing?
**Verdict:** No padding/packing needed (see §2.2). **BUT** we should add
`training.max_tokens_trainer` + a soft truncation in `build_datum`.
**Proposal:** 15-line patch to `config.py` + `datum_builder.py`; ship warning
at INFO on first truncation per run.

### 2. Loss function choice
**Verdict:** We're a strict superset (4 options vs 1). **Caveat:** the other
three (`ppo`, `cispo`, `dro`) are Tinker server-side names — untested by us;
Literal accepts them but we have no integration test. Either keep IS as the
only tested path and constrain Literal, or add a 1-step smoke per loss.
**Proposal:** narrow Literal to `"importance_sampling"` for now, expand when
we actually verify the others end-to-end.

### 3. Config structure vs ours
**Verdict:** Structurally comparable (4 nested blocks vs 3+`openai` list).
Missing fields worth copying:
  - `max_token_trainer_length` / `max_token_length` — context budgets.
  - `save_checkpoint_interval` — we have `save_every` (equivalent).
  - `max_batches_offpolicy` — N/A (push model).
  - `max_num_workers` — N/A (no broker).
**Proposal:** add `training.max_tokens_trainer` (see §5.1). Keep the rest as
intentional divergence.

### 4. 3-process vs 2-process orchestration
**Verdict:** Intentional divergence. **Proposal:** add an ADR in
`docs/reviews/` or `docs/architecture.md` stating "no central broker → env
workers cannot scale horizontally on our stack; if required, introduce an
Atropos-style queue in front of `rollout_driver`."

### 5. Distillation support (`logp_steering`)
**Verdict:** Missing but architecturally cheap. **Proposal:**
  1. Extend `RawTrajectory` with `teacher_logprobs: list[float] | None =
     None`.
  2. In `build_datum`, if teacher_logprobs is not None and its length matches
     `response_logprobs`, overwrite the response-region advantages as
     `teacher_logprobs[i] - response_logprobs[i]`.
  3. Add one test mirroring `test_distillation.py` invariants.
  4. Document that this is independent of nemo-gym's env contract —
     nemo-gym env just needs to surface teacher lps as an extra field.
Effort: ~40 LOC; zero loss-function changes needed.

### 6. Serve-only mode
**Verdict:** Divergent. Our `serve.py` calls `trainer.setup()` which spins up
a LoRA **training** client. Atropos's `serve.py` uses a plain `SamplingClient`
and accepts `--model <hf>` or `--weights tinker://…`.
**Proposal:** split `cli.serve` into two modes:
  - `serve` (current): for in-the-training-stack testing — keep as is.
  - `serve-only`: no training client, accepts `--weights` tinker path, mirrors
    atropos `serve.py:1-204`. ~60 LOC.

### 7. OpenAI-compatible endpoints coverage
**Verdict:** See §4. One genuine gap (`/logprobs`); the rest are N/A.
**Proposal:** add `/logprobs` alongside distillation work (§5 item 5).

### 8. `download_weights.py` utility
**Verdict:** Missing but trivial. **Proposal:** add
`tinker_nemogym/utils/download_weights.py` — a 20-line click/argparse command
that wraps `rc.get_checkpoint_archive_url_from_tinker_path`. Register as
`tinker-nemogym-download-weights` entry point.

### 9. Batch polling vs push
**Verdict:** Intentional divergence (push). See §3.3. **Proposal:** document
this limit-scaling property in the architecture doc; add a `# scaling note`
comment in `rollout_driver.rollout_batch`.

### 10. Metrics/logging
**Verdict:** Divergent. We log fewer aggregates (`mean_reward`, `loss`,
`n_datums`, `n_dropped`). Atropos logs logprob moments
(`logprobs/{mean,std,min,p50}`) and advantage moments
(`advantages/{mean,std,sum}`) — these are **genuinely useful** for RL
debugging.
**Proposal:** extend `_run_step` to compute
`logprobs_stats`/`advantages_stats` from the Datum tensors before the fwd_bwd
call; add those keys to `_log_wandb_metrics`. ~30 LOC, no external deps.

### 11. CLI (argparse vs click)
**Verdict:** Click is the better choice (subcommands, automatic help,
`Path(exists=True)` validation). **Keep.** However our Click version
**doesn't support CLI overrides** — atropos has `--base-model`,
`--learning-rate`, `--num-steps`, `--no-wandb`, etc. (even if their override
mechanism is buggy — `launch_training.py:78-80`).
**Proposal:** add click `--set tinker.learning_rate=1e-4` repeating option
that patches nested pydantic fields before `model_validate`. ~25 LOC; cleaner
than atropos's broken property round-trip.

### 12. Error recovery patterns
**Verdict:** Ours is more defensive (try/except in `_run_step` around
rollout, fwd_bwd, and hot-swap, each with a logged-and-continue path). Their
`tenacity`-based retry on `/batch` is `@retry(wait_fixed=10)` infinite
(`trainer.py:126`), which is fine-grained for one call but has no step-level
resilience.
**Proposal:** adopt tenacity for `rollout_driver._call_once` (we already have
a hand-rolled retry in `rollout_group_with_retry`). And add
`exponential_backoff` with a max-attempts cap — the current hand-rolled retry
is linear with no backoff. ~15 LOC.

### 13. Test coverage parity
**Verdict:** Different shapes. We're **stronger on integration** (concurrency,
checkpoint-resume, varied rewards, long-run, multi-turn, wandb, error
recovery). **Weaker on:**
  - No logprob-alignment test (atropos's `test_logprob_alignment.py`
    validates that `logprobs[1:]` + shift equals sampled lps).
  - No distillation test (obviously — we don't have that path).
  - No `/logprobs` endpoint test (we don't have that endpoint).
**Proposal:** port `test_logprob_alignment.py` into
`tests/unit/test_datum_builder.py` — a single parametrized case that
constructs a known trajectory and asserts Datum tensor content byte-for-byte.

### 14. Hardcoded ports / magic numbers
**Verdict:** We are **strictly better**. Our default `ModelServerConfig.port
= 8001` lives in exactly one place (`config.py:39`); everything else reads
`cfg.model_server.port`. Atropos hardcodes `8001` in **4 places**
(`trainer.py:837`, `config.py:66,94`, `logp_steering.py:69`).
**Proposal:** none. Document this as a win in §7.

### 15. Config validation with Pydantic validators
**Verdict:** Weaker than atropos. Our config uses only type hints + Literal;
no cross-field validators. Atropos also doesn't use `@field_validator`, but
it has a smarter property layer. **Proposal:** add a few validators we
actually need:
  - `NeMoGymConfig`: `group_size >= 1`.
  - `TrainingConfig`: `batch_size >= 1`, `n_steps >= 0`, `save_every >= 0`,
    `max_tokens >= 1`.
  - `TinkerConfig`: `0 < lora_rank <= 256`, `learning_rate > 0`,
    `0 < adam_beta1 < 1`, `0 < adam_beta2 < 1`, `adam_eps > 0`.
  - `ModelServerConfig`: `1024 <= port <= 65535`.
~30 LOC of `@field_validator` / `Field(gt=, le=)`.

---

## §6. Recommended Adoptions — Ordered by Impact / Effort

Scored ~rough~ (1-5). **I/E ratio** = higher is better.

| Rank | Item | Impact | Effort | I/E | Why |
|---|---|---|---|---|---|
| 1 | Logprob/advantage stats in wandb (§5.10) | 4 | 1 | 4.0 | RL debugging gets much easier; tiny code |
| 2 | Pydantic validators for numeric ranges (§5.15) | 3 | 1 | 3.0 | Catches bad configs at load time |
| 3 | `max_tokens_trainer` cap + warning (§5.1) | 4 | 1 | 4.0 | Silent oversize trajectories explode on the server |
| 4 | `download_weights` utility (§5.8) | 2 | 1 | 2.0 | Parity for users pulling final LoRAs |
| 5 | Tenacity-based retry in `_call_once` (§5.12) | 3 | 1 | 3.0 | Clean up hand-rolled retry |
| 6 | CLI `--set key=value` overrides (§5.11) | 3 | 2 | 1.5 | Composability with shell scripts / CI |
| 7 | Distillation path (`teacher_logprobs` on `RawTrajectory`) (§5.5) | 5 | 2 | 2.5 | Unlocks `logp_steering`-class envs |
| 8 | `/logprobs` endpoint (§5.7) | 4 | 2 | 2.0 | Paired with 7; standalone useful for eval tools |
| 9 | Logprob-alignment unit test (§5.13) | 3 | 1 | 3.0 | Regression guard against datum-builder drift |
| 10 | Split `serve` into `serve` + `serve-only` w/ `--weights` (§5.6) | 2 | 2 | 1.0 | Matches atropos UX; not urgent |

**Top 3 recommendation (this PR or next):** items 1, 3, 5. Each is <20 LOC,
pure plus. 7+8 (distillation) are the highest-impact future feature.

---

## §7. Recommended Intentional Divergences (Do NOT Adopt)

These are divergences that should **stay** divergent — we've considered them
and prefer our way.

1. **Push-based rollout driver (no central broker, 2-process vs 3-process).**
   Matches nemo-gym's agent contract and keeps the stack one fewer moving
   piece for users. Cost: no horizontal env-worker scaling. Document this
   explicitly in the architecture doc.

2. **Click CLI with subcommands, not argparse.** Click gives us
   `Path(exists=True)` validation, grouped help, and clean subcommand
   dispatch. The one drawback (no overrides yet) is fixable (§5.11) without
   reverting to argparse.

3. **Configurable port in one place (`ModelServerConfig.port`)**, not
   hardcoded `8001` in 4 places. Pure win.

4. **Module-global sampling client behind a `Lock`**, not module-global
   *trainer*. Our surface for globals is narrower and re-entrancy-safe.

5. **Server-start readiness via `uvicorn.Server.started` poll**, not
   `asyncio.sleep(3)` guess. Correct-by-construction.

6. **Step-level try/except in `_run_step`** — a bad rollout/fwd_bwd/hot_swap
   does not kill the run. Atropos leaves those uncaught; long training runs
   benefit from step-level resilience.

7. **`/v1/responses` endpoint instead of `/v1/completions`**. nemo-gym
   agents use the Responses API; plain completions is legacy.

8. **`save_weights_and_get_sampling_client_async` (one call)** vs atropos's
   two-step `save_weights_for_sampler` + `create_sampling_client`. Atomic,
   newer Tinker SDK path.

9. **Resume-from-checkpoint (`load_state_async`)**. Atropos does not support
   this. Our addition is non-breaking and useful.

10. **No SGLang `/generate` endpoint.** nemo-gym has no SGLang-shape
    consumer; adding this would be dead code.

---

## Appendix A. Cross-file Evidence Links

- `pad_data_to_good_offset`: `tinker-atropos/tinker_atropos/trainer.py:174-365`
- `build_datum`/`build_batch`: `tinker-nemogym/tinker_nemogym/datum_builder.py:203-312`
- Atropos FastAPI shim: `tinker-atropos/tinker_atropos/trainer.py:546-837`
- Our FastAPI shim: `tinker-nemogym/tinker_nemogym/tinker_responses_model.py:196-384`
- Atropos launcher: `tinker-atropos/run_logp_steering.sh`
- Our launcher (dev): `tinker-nemogym/scripts/smoke_single_tool.sh`
- Atropos trainer loop: `tinker-atropos/tinker_atropos/trainer.py:393-513`
- Our trainer loop: `tinker-nemogym/tinker_nemogym/trainer.py:240-383`
- Distillation validator: `tinker-atropos/tinker_atropos/trainer.py:131-172`
- Reference logprobs shift: `tinker-atropos/tinker_atropos/trainer.py:247-260`
  vs ours `tinker-nemogym/tinker_nemogym/datum_builder.py:240-259`.


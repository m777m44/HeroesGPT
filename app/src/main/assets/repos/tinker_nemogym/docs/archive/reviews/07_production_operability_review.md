# Review #7 — Production Operability / SRE

**Scope.** 7th and final architectural review. Lens: *would I be comfortable
operating this at 3am?* Everything here is about **day-2** concerns —
observability, failure modes, runbooks, resumability, deployment,
multi-tenancy, supply-chain. No source code has been modified.

**Posture acknowledged up front.** This repo is a *research-lab-local*
training bridge, not a hosted service. The four prior reviews applied the
obvious dev-quality hardening (see `docs/reviews/ADDRESSED.md`). Nothing
below should be read as "your MVP is unsafe." The question this review
asks is narrower: **if this tool becomes load-bearing for a multi-day
training run or a multi-researcher shared box, what will go wrong at 3am,
and what do we need in place before that moment?**

Priors read first (to avoid re-reporting):
`docs/reviews/{01_tinker_api_correctness, 02_nemogym_integration_review,
03_atropos_architectural_parity, 04_software_quality_review}.md`,
`docs/reviews/ADDRESSED.md`. Explicitly excluded from this pass:
- `ClientSession` pooling (01/04 — fixed).
- Config validators, path-traversal guards (04 — fixed).
- 429 handling / narrow-except in trainer (04 — fixed).
- mypy/ruff/CI wiring (04 — fixed).
- Auth / CORS / rate-limit on the FastAPI shim (ADDRESSED.md: out of scope).

---

## §0. Operability Scorecard

| Axis                     | Grade | One-line justification |
|--------------------------|:-----:|------------------------|
| Observability            | **D+** | Stdlib `logging` only. No structured JSON, no request-id / run-id / step-id propagation, no Prometheus/OTel, no histograms on rollout latency. `/health` exists; nothing else. |
| Failure handling         | **B-** | Narrow-except + continue is the right dev-default (post-04). But **no circuit breakers**, no consecutive-failure escalation, no uvicorn-thread liveness probe, no alerting hooks. A silent stuck-at-zero-reward loop is possible. |
| Resumability             | **D** | `resume_from_checkpoint` restores **weights only**. Step counter, dataset cursor, wandb step, sampler version, RNG state are all **lost**. Resume means "continue training from fresh step 0 with warm weights" — not what operators expect from the word *resume*. |
| Deployment               | **F** | No Dockerfile, no Makefile, no Helm chart, no systemd unit, no entrypoint script that composes trainer + nemo-gym + wandb. "Clone repo + `poetry install` + `bash scripts/smoke_*.sh`" is the only documented path. CI builds nothing deployable. |
| Runbook                  | **F** | Absent. README is a quickstart; there is no `docs/runbook.md` explaining *how to diagnose a stuck run, restart after a crash, roll back to a prior checkpoint, or bleed a TINKER_API_KEY leak*. E2E_FIXES.md is a post-mortem journal, not operator material. |
| Multi-tenancy            | **D** | Two users on one box collide on `:8001` (shim), `:11000` (nemo-gym head), `./checkpoints`, and wandb run name. The FastAPI app uses **module-global state**, so even in-process multiplexing is architecturally impossible. |
| Supply-chain             | **C** | `poetry.lock` present and comprehensive. Python `^3.12` pinned. **No** `pip-audit`/`safety` in CI, no SBOM, no image-hash pin, no renovate/dependabot config, `nemo-gym` is a `path` dep with `develop = true` (irreproducible across boxes). |

**Overall**: **C / D+**. Dev-quality is good (B+ from Review 04); ops-readiness
is nascent. Acceptable for a single-engineer single-run-at-a-time usage; not
acceptable for a "launch it, go to bed, wake up to a trained model" workflow
without the additions below.

---

## §1. Executive Summary — "Things That Will Bite You at 3am"

Prioritized. Each item answers: *what happens, how will you find out, what
do you do?*

1. **Silent stuck-at-zero-reward run.** If the nemo-gym agent quietly returns
   empty trajectories (env bug, resource starvation, cookie loss for stateful
   envs), each step logs a single `WARNING: no usable rollouts; skipping
   training step` at INFO, `mean_reward=0.0` goes to wandb, **and the run
   keeps going for hours** burning no Tinker budget. No alert, no circuit
   breaker. (`trainer.py:416-418`.) → Add consecutive-failure counter
   (§2.2, §2.16).

2. **Resume ≠ resume.** `resume_from_checkpoint` loads LoRA weights. It does
   *not* restore `step` (loop starts at 0), the dataset cursor
   (`step * batch_size % len(dataset)` — so batch 0 re-runs), wandb `step`
   counter (collides with existing run), or sampler hot-swap version. An
   operator restarting a crashed run 12h in will silently redo the first
   12h of data, and wandb will plot monotonically-decreasing step indices
   against pre-crash step indices. (`trainer.py:148-163, 284`.) → §2.5.

3. **No request-id / run-id.** One bad rollout that produces an
   `extract_trajectory` failure logs
   `Step 4 prompt 2: extract_trajectory failed: KeyError('response')`.
   You have no way to correlate that log line with the nemo-gym `/run`
   call that caused it, the agent-side logs, the Tinker sampler version
   in flight, or the wandb step. The SRE hour spent reading logs is >>
   the cost of propagating a UUID. → §3 (observability layer).

4. **Uvicorn daemon thread can die and nobody notices.** `_start_server_thread`
   polls `server.started` once at startup, then forgets about it. If the
   thread crashes mid-run (e.g. OOM in renderer), subsequent `sample_async`
   calls inside the trainer *still work* (they don't go through the shim),
   but any in-flight nemo-gym agent request from a multi-turn env hangs
   on a dead socket until aiohttp-client-side timeout. The trainer's
   `_do_rollouts` returns None, `mean_reward=0`, see #1. (`trainer.py:233-274`.)
   → §2.4, §4.

5. **SIGTERM mid-step = corrupt wandb + orphaned Tinker optim_step.**
   There is **no** `signal.signal(SIGTERM, ...)` handler, **no**
   `asyncio.CancelledError` re-raise discipline at the `_do_training_step`
   level (only `raise` inside the except branches). Kubernetes-style
   `SIGTERM → 30s → SIGKILL` will land mid-`optim_step_async` — Tinker's
   server accepted the fwd_bwd enqueue, our process dies, wandb never
   sees a `finish()`, next resume starts fresh → silently-double-optimized
   weights. (`trainer.py:280-317, 624-637`.) → §2.4, §4.

6. **Shared `./checkpoints` + shared `:8001` + shared wandb name** on a
   multi-user box. Two simultaneous `tinker-nemogym-train --config=...`
   runs will (a) wandb-collide if `wandb_name` isn't parameterised,
   (b) uvicorn `[Errno 98] Address already in use` abort, (c) checkpoint
   label collision (`tinker.save_state_async(name="checkpoints-step-10")`
   is a *global* tinker label!). → §2.13.

7. **No Tinker-reachability probe at startup.** `TinkerNeMoGymTrainer.setup`
   calls `ServiceClient()` → `create_lora_training_client_async` which
   *may* block for ~10s on a quota check. If `TINKER_API_KEY` is unset,
   the failure surfaces from deep inside the tinker SDK with a stack
   trace. No early self-test. → §2.19.

8. **`wandb.finish()` can be missed.** `run()` has a `try/finally` that
   calls `_finish_wandb()`. But if `setup()` itself raises after
   `_maybe_init_wandb()` succeeds (e.g. dataset file missing), the
   `finally` branch runs → good. *But* if the process is OS-killed, the
   wandb run stays in "running" state for 24h until wandb's reaper. Not
   fatal; noisy. (`trainer.py:212-231, 573-585`.)

9. **Disk-full during checkpoint is silent.** `_maybe_save_checkpoint`
   wraps the entire `save_state_async` call in `except Exception: warn +
   continue`. After N consecutive failures the run is accumulating
   un-saved work without surfacing a single ERROR or wandb alert.
   (`trainer.py:587-622`.) → §2.2, §4.

10. **Tokenizer / HF-token expiry mid-run.** The tokenizer is loaded in
    `setup()` via `get_tokenizer(base_model)` which hits Hugging Face on
    first call. If the HF cache is cold and `HF_TOKEN` is unset / has
    expired, `setup()` raises. If the HF *download* succeeds but a future
    `renderer.parse_response` needs a vocab file (some `AutoTokenizer`
    backends), hour 8 of a run could trip on a stale CDN 403.
    (`trainer.py:116-122`.) → §2.2.

11. **Dataset is loaded fully into memory.** `load_jsonl` returns a
    `list[dict]` — a 5M-row dataset is ~5-20 GB of Python dicts. On a
    developer laptop this is fine; on a shared SRE box it's an OOM.
    Not a bug, a sizing surprise. (`rollout_driver.py:211-229`.)

12. **No reproducibility story.** No `seed` in `TrainingConfig`. Dataset
    order is deterministic (`step * batch_size % len(dataset)`) but
    rollout sampling temperature is non-zero and *nowhere* is a
    `sampling_params.seed` set. A failed run is therefore impossible to
    rerun bit-for-bit. (`config.py:152-168`, `tinker_responses_model.py:143-147`.)
    → §2.12.

---

## §2. Per-checklist Findings + Proposed Implementations

### 2.1 Observability — the three pillars

**Findings.**
- **Logs**: every module uses `logger = logging.getLogger(__name__)`; levels
  are sensible (Review 04 §6 confirmed). Format is `%(asctime)s %(levelname)s
  %(name)s: %(message)s` — fine for a TTY, useless for a log aggregator.
  *Not structured.* No `extra={...}` fields. No log-correlation id.
- **Metrics**: only wandb (`train/mean_reward`, `train/loss`,
  `train/n_datums`, `train/n_dropped`, `train/sampler_version`,
  `train/prompt_tokens_mean`, `train/completion_tokens_mean`).
  **No** Prometheus endpoint, **no** OpenTelemetry exporter, **no**
  per-rollout histogram (p50/p95/p99 rollout latency is unknowable). Wandb
  is per-step scalar — good for research curves, blind for SRE.
- **Traces**: zero. No OTel spans around
  `_do_rollouts` / `_build_datums_from_rollouts` / `_do_training_step`.
  No distributed trace context propagated from trainer → nemo-gym agent
  → back into the shim.

**Proposed.** §3 below lays out a concrete design. Minimum viable:
a JSON log formatter, a `contextvars.ContextVar("run_id")` +
`contextvars.ContextVar("step")` wired into a `logging.Filter`, and a
Prometheus scrape endpoint on the shim port (`/metrics`).

### 2.2 Failure modes catalog

For each failure, I audited (a) detection, (b) logging/alerting,
(c) recovery, (d) post-mortem artifacts.

See §4 for the full table. Summary deltas vs. what's there:

- ✅ `tinker.RateLimitError`, `AuthenticationError`, `SidecarDiedError` are
  now classified correctly (04 §2.4 fixed).
- ❌ **Consecutive-failure escalation missing.** A WARN on step 0 through
  step 999 is not an alert. Recommend: `max_consecutive_failed_steps:
  int = 5` → `RuntimeError` that the outer loop re-raises.
- ❌ **Save-failure escalation missing.** Same pattern — `_maybe_save_checkpoint`
  should count failures and either fail the run or emit a `train/save_failure`
  metric that monitoring can alert on.
- ❌ **Stuck-at-zero-reward detector.** If `mean_reward == 0.0` AND
  `n_datums == 0` for `N` steps in a row, bail with a specific
  `EmptyTrainingStream` error.
- ❌ **Tokenizer/HF failure** surfaces as a cryptic `OSError` at
  `setup()` line 120. Wrap with a named exception.

### 2.3 Health checks

**Findings.** `/health` returns
`{"status": "ok", "sampling_client_ready": bool, "renderer_ready": bool}`.
It is the *only* endpoint that could serve as a probe. No `/livez` vs
`/readyz` distinction. The trainer itself has *no* HTTP surface other
than the shim, so a Kubernetes liveness probe on the trainer is impossible.

**Proposed.** Split semantics:

```python
# tinker_responses_model.py
@app.get("/livez")
async def _livez() -> dict:
    """Cheapest possible — we're alive if this returns.
    Returns 200 unconditionally (assumes process is up)."""
    return {"status": "alive"}

@app.get("/readyz")
async def _readyz(response: Response) -> dict:
    """Ready iff (a) init() was called AND (b) a sampling client is set.
    Returns 503 when either condition fails so k8s probes bounce us."""
    ready = _tokenizer is not None and get_sampling_client() is not None
    if not ready:
        response.status_code = 503
    return {
        "ready": ready,
        "sampling_client_ready": get_sampling_client() is not None,
        "renderer_ready": _renderer is not None,
    }

@app.get("/startupz")
async def _startupz() -> dict:
    """True once the process has ever observed a ready state.
    Used by k8s startupProbe to grant extra time before livez kicks in."""
    return {"started": _HAS_EVER_BEEN_READY}
```

Add a `GET /trainer/status` (optional) on a separate port so an operator
can `curl localhost:$TRAINER_PORT/status | jq` and see
`{step, total_steps, last_mean_reward, last_loss, sampler_version,
consecutive_failures, save_count, run_id}` without wandb.

### 2.4 Graceful shutdown

**Findings.**
- No `signal.signal` handler anywhere.
- `asyncio.run(trainer.run())` on `SIGINT`/`SIGTERM` raises `CancelledError`
  inside the current await; the `finally` branch of `run()` fires
  `_cleanup()` + `_finish_wandb()` — good.
- But: `_do_training_step` uses `await fwd_future.result_async()` *without*
  `asyncio.shield`. A cancel mid-result abandons a remote optim_step that
  the Tinker server has already accepted. The local state (save_count,
  sampler_version) and the remote state diverge.
- `_cleanup()` does `await self._http_session.close()` and
  `self._server.should_exit = True` + `thread.join(5.0)`. A non-cooperative
  uvicorn (stuck in a `sample_async` inside the shim) will miss the
  5s window; the process is forced down.

**Proposed.**

```python
import signal

class TinkerNeMoGymTrainer:
    async def run(self) -> None:
        self._shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown.set)
        await self.setup()
        try:
            for step in range(self.cfg.training.n_steps):
                if self._shutdown.is_set():
                    logger.warning("Shutdown requested; stopping cleanly at step %d", step)
                    break
                await self._run_step_shielded(step)
        finally:
            await self._drain_in_flight()   # NEW
            self._finish_wandb()
            await self._cleanup()

    async def _run_step_shielded(self, step: int) -> None:
        # Protect the short, stateful tail of a step (fwd_bwd_result +
        # optim_step + save_state) from mid-run cancellation.
        await asyncio.shield(self._run_step(step))
```

And a `_drain_in_flight()` that gives the server thread `grace_sec: float = 15.0`
(config-controlled), checks `asyncio.all_tasks()` for straggling sample_async
coroutines, and only then closes the session.

### 2.5 Resumability

**Findings.**
- `resume_from_checkpoint` calls `load_state_async(path)` — weights only.
- Step counter: `for step in range(n_steps)` starts at 0. Always.
- Dataset cursor: `_pick_batch` uses `step * batch_size % len(dataset)` —
  deterministic function of `step`, so restart-with-step-0 repeats batch 0.
- Wandb step: `wandb.log(..., step=step+1)` — collides with pre-crash data.
- RNG state: unset globally.

**Proposed.** Introduce a `run_state.json` alongside every checkpoint:

```json
{
  "run_id": "20260422-1200-abc123",
  "step": 127,
  "dataset_cursor": 508,
  "wandb_run_id": "abc123",
  "sampler_save_count": 128,
  "seed": 42,
  "git_sha": "69e51bb",
  "config_sha256": "...",
  "created_at": "2026-04-22T12:00:00Z"
}
```

`setup()` should, when `resume_from_checkpoint` is set, *also* look for
a sibling `run_state.json` and restore `step`, `dataset_cursor`,
`wandb_run_id` (→ `wandb.init(id=..., resume="must")`), and `_save_count`.
If `run_state.json` is absent, log a loud WARNING that "resume will be
weights-only; step counter resets" — so the operator is not silently
surprised.

### 2.6 Long-run stability (24h)

**Findings.**
- `ClientSession` is now hoisted (Review 04 fixed) → no per-step leak.
- Tinker `SamplingClient` is replaced every step; the *old* client is
  dereferenced but not explicitly closed. Unknown whether the tinker
  SDK leaks sockets on GC. File upstream question.
- `wandb.log` grows an in-memory history; wandb's own ring buffer flushes,
  should be fine at 10k steps.
- `_tokenizer`, `_renderer` module-globals never rotate.
- FastAPI shim has **no lifespan** context; `app` is constructed at
  import time. Any middleware/state added later would accumulate.
- No TIME_WAIT management. With pooled `ClientSession` and keep-alive,
  port exhaustion should not happen, but worth a `netstat -an | grep
  TIME_WAIT | wc -l` during a 24h run.
- Wandb run stays open. If the local clock diverges from wandb's server
  clock (common on VMs), late flushes can produce out-of-order timestamps.

**Proposed.** Build a nightly "soak" test: `scripts/soak_test.sh` that runs
`tinker-nemogym train --config=configs/soak.yaml --n_steps=10000` against
the fake harness, asserts RSS growth `<5%` over the run, and fails CI on
regression. Add it as a weekly cron on the infra that can afford it.

### 2.7 Dependency pinning & supply-chain

**Findings.**
- `poetry.lock` (721 KB) is committed. ✅
- Top-level deps in `pyproject.toml`: floors only (`>=3.12`, `>=0.118`, etc.).
  The *lock file* is what reproduces; the pyproject floors permit SDK
  upgrades without code review, which is the right default for a research
  repo and the wrong default for production.
- `nemo-gym` is a `path = "../nemo-gym"` dep with `develop = true`. This
  means CI-on-a-fresh-VM fails unless nemo-gym is checked out as a sibling
  directory — our CI (`.github/workflows/ci.yml`) does not do this, so
  the CI is effectively running against whatever `poetry install` manages
  to resolve from the float (which will fail on a standard GitHub runner).
  **Confirm this by reading `.github/workflows/ci.yml`** — indeed no
  `git clone` of nemo-gym. CI is either broken or running against a stale
  cache.
- No `pip-audit` / `safety` / `snyk` step in CI.
- No SBOM (`cyclonedx-bom` or `syft` would work).
- No renovate.yml / dependabot.yml.

**Proposed.**
1. Add `pip-audit -r <(poetry export --with dev -f requirements.txt)` as a
   CI step, allowed-to-fail initially, enforced after 2 weeks of triage.
2. Fix CI: either `git clone https://github.com/NVIDIA-NeMo/Gym.git
   ../nemo-gym` step, or (better) wait until nemo-gym is on PyPI and
   switch to a versioned dep.
3. Commit a `.github/dependabot.yml` with a `poetry` ecosystem watcher.
4. Add `cyclonedx-bom` generation into CI artifact output so releases ship
   an SBOM.

### 2.8 Version compatibility matrix

**Findings.**
- Python `^3.12` — documented in `pyproject.toml` + README.
- `tinker >= 0.18.0` — documented as a floor. **Which versions are
  verified?** No matrix test. Review 01 called out the
  `save_weights_and_get_sampling_client_async` kwarg change from 0.17 → 0.18.
- `nemo-gym` — path dep, no version pin. "The version in
  `../nemo-gym/main` at the time you cloned" is the de-facto pin.
- `tinker-cookbook >= 0.3.0`.
- No `transformers` version matrix; we rely on tokenizers/renderers
  across versions.

**Proposed.** A `docs/COMPATIBILITY.md`:

```markdown
| Component         | Verified version | Verified against     | Status  |
|-------------------|------------------|----------------------|---------|
| Python            | 3.12.3           | all tests            | OK      |
| tinker            | 0.18.0 .. 0.19.x | live run 2026-04-20  | OK      |
| tinker-cookbook   | 0.3.0            | offline e2e          | OK      |
| nemo-gym          | main@<sha>       | smoke_single_tool.sh | OK      |
| transformers      | 4.50.x .. 4.58.x | tokenizer load       | OK      |
| wandb             | 0.21.x           | _log_wandb_metrics   | OK      |
```

Tie this to the nightly contract test (§2.9, §2.20).

### 2.9 Upgrade safety

**Findings.** No scheduled "does the real Tinker API still work?" test.
`tests/integration/` has 3 slow tests gated on `TINKER_API_KEY` — they're
deselected by default and never run in CI.

**Proposed.** A `.github/workflows/nightly.yml`:

```yaml
on:
  schedule: [{cron: "0 7 * * *"}]   # 07:00 UTC daily
jobs:
  live-tinker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: live slow suite
        env:
          TINKER_API_KEY: ${{ secrets.TINKER_API_KEY }}
        run: poetry run pytest -v -m slow
      - name: notify slack on failure
        if: failure()
        uses: slackapi/slack-github-action@v1.x
        with: {channel-id: tinker-nemogym-alerts, text: "Nightly contract test failed: ${{ github.sha }}"}
```

### 2.10 Configuration drift

**Findings.** YAML → Pydantic round-trip is deterministic. But we never
*emit* the effective config anywhere durable. `wandb.init(config=cfg.model_dump())`
captures it inside wandb, which is the one existing artifact — fine as long
as wandb is enabled.

**Proposed.** On `setup()`, write
`{checkpoint_dir}/run_{run_id}/effective_config.yaml` plus a
`ran_with.lock` copy of `poetry.lock`. Disaster recovery §2.14 depends
on this.

### 2.11 Resource accounting

**Findings.** None. An operator has *no way* to estimate "this 100-step run
with group_size=4 batch_size=4 will consume ~N Tinker tokens and cost $X"
before launching. Post-hoc: wandb logs `completion_tokens_mean` /
`prompt_tokens_mean` per step (Review 02 §4.2, fixed), which is enough
for a retrospective estimate. Not enough for budget control.

**Proposed.**
1. Add `cli.estimate` subcommand: loads config + dataset, computes
   `n_steps × batch_size × group_size × (max_tokens + mean_prompt_tokens)`.
2. Add `training.max_total_tokens: int | None` hard cap; the training
   loop tracks cumulative tokens and breaks when exceeded.
3. Emit `train/cumulative_completion_tokens` to wandb so you can put a
   real-time budget bar in the dashboard.

### 2.12 Reproducibility

**Findings.**
- No `seed` in `TrainingConfig`. No `numpy.random.seed(...)`, no
  `random.seed(...)`, no `torch.manual_seed(...)` (we don't train locally
  so torch doesn't matter), no `tt.SamplingParams(seed=...)` (temperature
  sampling is therefore non-reproducible).
- No `--dry-run` mode.
- Dataset order is deterministic.

**Proposed.**
1. `TrainingConfig.seed: int = 42`.
2. `_route_to_tinker` should thread the seed through: step-level seed =
   `hash((run_seed, step, prompt_idx, group_slot)) & 0xFFFFFFFF` passed
   as `tt.SamplingParams(seed=...)`.
3. `cli.train --dry-run`: run `setup()` + one fake rollout (returns fixed
   tokens), write `effective_config.yaml`, exit 0. Useful for smoke-testing
   a config before spending GPU time.

### 2.13 Multi-tenancy

**Findings.** Already enumerated in §1 #6. Concretely:

| Resource          | Collision point                              |
|-------------------|----------------------------------------------|
| shim port         | `ModelServerConfig.port = 8001` default      |
| nemo-gym head     | `NeMoGymConfig.head_url = :11000` default    |
| checkpoint dir    | `TinkerConfig.checkpoint_dir = "./checkpoints"` default |
| Tinker ckpt label | `f"{dir_basename}-step-{step+1}"` — `dir_basename` is typically `checkpoints` for everyone |
| wandb run name    | `TinkerConfig.wandb_name` — no default uniqueness |
| FastAPI app       | module-global state — one shim per process   |

**Proposed.** A `RunContext` that derives a `run_id` (UTC ISO date +
short hash of config + pid) on `setup()`:

```python
from datetime import datetime, timezone
import hashlib, os

def make_run_id(cfg: TinkerNeMoGymConfig) -> str:
    cfg_hash = hashlib.sha256(
        json.dumps(cfg.model_dump(), sort_keys=True).encode()
    ).hexdigest()[:8]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{ts}-{cfg_hash}-{os.getpid()}"
```

Then: `checkpoint_dir/run_{run_id}/`, Tinker label
`{run_id}-step-{n}`, wandb `name=cfg.wandb_name or run_id`,
port defaults switch to `pick_free_port` when 8001 is busy.

### 2.14 Disaster recovery

**Findings.** If a run dies mid-training, you have:
- Last checkpoint (maybe) in Tinker (tinker:// URI).
- `./checkpoints/step_{n}` — logical marker file? Review the code:
  `_maybe_save_checkpoint` only logs, doesn't write a local file. So
  no, the `checkpoint_dir` is **never written to locally**. It's a lie
  of a directory — Tinker owns the weights.
- Whatever you captured via `2>&1 | tee` (you didn't).
- Wandb run (if enabled).
- Agent-side logs (nemo-gym's own server_utils logs go elsewhere).

**Proposed.** `{checkpoint_dir}/run_{run_id}/` contents:

```
effective_config.yaml     # config as actually seen by Pydantic
poetry.lock               # copy of the lock at launch time
run_state.json            # §2.5
stdout.log                # tee of stdout
stderr.log                # tee of stderr
metrics.jsonl             # per-step metrics, one JSON per line
checkpoints.jsonl         # record of every save: {step, uri, label, ts}
crash.py                  # if the run crashed, a py3.12 traceback dump
```

`metrics.jsonl` + `checkpoints.jsonl` are the artifacts that turn a 3am
page into a 3:15am resolution.

### 2.15 Deployment packaging

**Findings.** `poetry install` + `bash scripts/smoke_*.sh`. No Dockerfile,
no Makefile, no systemd unit, no Helm chart.

**Proposed.** Minimum viable:

```dockerfile
# Dockerfile
FROM python:3.12-slim-bookworm AS builder
RUN pip install poetry==1.8.3
WORKDIR /app
COPY pyproject.toml poetry.lock ./
COPY tinker_nemogym tinker_nemogym
COPY ../nemo-gym ../nemo-gym
RUN poetry config virtualenvs.create false && poetry install --no-dev

FROM python:3.12-slim-bookworm
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /app /app
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["tinker-nemogym"]
CMD ["train", "--config", "/etc/tnng/config.yaml"]
```

Plus a `Makefile`:

```makefile
.PHONY: install test lint type smoke fmt
install: ; poetry install
test:    ; poetry run pytest -v
lint:    ; poetry run ruff check tinker_nemogym tests scripts
type:    ; poetry run mypy tinker_nemogym
fmt:     ; poetry run ruff format tinker_nemogym tests scripts
smoke:   ; bash scripts/smoke_single_tool.sh
fake-e2e:; bash scripts/e2e_fake.sh
docker:  ; docker build -t tinker-nemogym:$(shell git rev-parse --short HEAD) .
```

A `tools/tnng.sh` wrapper for on-call:

```bash
#!/usr/bin/env bash
# One command to rule them all.
# Usage: tnng.sh {train|resume|inspect|stop} [args]
```

### 2.16 Runbook

**Findings.** Absent.

**Proposed.** `docs/runbook.md` with the skeleton below. Concrete contents
belong in a separate PR; this is the table of contents:

```markdown
# tinker-nemogym Runbook

## 0. On-call prerequisites
- TINKER_API_KEY secret, where stored.
- wandb API key, where stored.
- ssh to the training box.

## 1. Starting a job
`bash scripts/launch.sh <env-name>` → reads `configs/prod/<env>.yaml`.

## 2. Inspecting a running job
- `curl localhost:8001/readyz`
- `curl localhost:8001/trainer/status | jq`
- `tail -f {checkpoint_dir}/run_{run_id}/stdout.log`
- `wandb run show tinker-nemogym/<run_id>`

## 3. Stopping a job
- Clean: `pkill -TERM tinker-nemogym-train` (waits ≤15s for drain).
- Hard: `pkill -KILL ...` — expect orphaned Tinker optim step. See §5.

## 4. Resuming after a crash
- `cat {checkpoint_dir}/run_{run_id}/run_state.json`
- `tinker-nemogym train --config=... --resume={checkpoint_dir}/run_{run_id}`

## 5. Rolling back to a prior checkpoint
- List checkpoints: `jq '.uri' {checkpoint_dir}/run_{run_id}/checkpoints.jsonl`
- Edit config `resume_from_checkpoint: <uri>`.

## 6. Diagnosing a stuck run
- Symptoms: `mean_reward == 0.0` for >3 steps.
- Check agent: `curl {agent_url}/health`.
- Check shim: `curl localhost:8001/readyz`.
- Check Tinker quota: ...

## 7. Diagnosing a Tinker 429 storm
- Symptoms: repeated `tinker rate limit — skipping this step`.
- Back off the fleet: ...

## 8. Diagnosing a tokenizer/HF 403
- Symptoms: `setup()` fails with `OSError` mentioning huggingface.co.
- Fix: `export HF_TOKEN=...; rm -rf ~/.cache/huggingface/hub/<model>`.

## 9. Rotating a leaked TINKER_API_KEY
- Immediately: ...
```

### 2.17 On-call ergonomics

**Findings.** If paged at 3am, you have:
- `ps aux | grep tinker-nemogym` — is it alive?
- `curl localhost:8001/health` — is the shim alive? (It says nothing
  about the training loop.)
- Scrollback / wandb dashboard — is training progressing?

There is no **one command** that answers "what is the current state?".

**Proposed.** `tinker-nemogym inspect --run-dir={checkpoint_dir}/run_{run_id}`
that reads `run_state.json`, tails `metrics.jsonl`, queries `/readyz`,
and prints:

```
run_id:           20260422T1200-abc12345-12345
step:             127 / 1000  (12.7%)
last_mean_reward: 0.42  (last 10: 0.38 0.40 0.39 0.42 ...)
last_loss:        0.18
sampler_version:  128
consecutive_fail: 0
shim:             ready (http://127.0.0.1:8001)
agent:            ready (http://127.0.0.1:11001)
wandb:            https://wandb.ai/nous/tinker-nemogym/runs/...
```

### 2.18 Chaos readiness

**Findings.** Zero chaos-style tests. The test suite has a
`FakeSamplingClient` that can be made to error but no explicit
"kill the agent mid-rollout" / "return 500 with 20% probability" /
"delay the response by 30s" tests.

**Proposed.** Add `tests/integration/test_chaos.py`:

```python
@pytest.mark.parametrize("failure_rate", [0.1, 0.5])
async def test_trainer_survives_agent_flakiness(failure_rate):
    # FakeAgent that returns 500 with failure_rate probability.
    # Assert: trainer completes N steps, logs warnings, mean_reward > 0.

async def test_trainer_survives_sigterm_mid_step(): ...
async def test_trainer_survives_disk_full(monkeypatch, tmp_path): ...
async def test_trainer_survives_tinker_429_storm(): ...
async def test_trainer_survives_tokenizer_decode_error(): ...
```

### 2.19 Dependency health checks at startup

**Findings.** `setup()` runs in this order:
1. Load tokenizer+renderer (HF network). No probe, no retry.
2. wandb init (best-effort).
3. `ServiceClient()` + `create_lora_training_client_async` (Tinker network).
4. Load dataset from local FS.
5. Discover agent URL (nemo-gym network, if not configured).
6. Create shared aiohttp session.

**None of steps 1, 3, 5 are probes.** They're production calls that happen
to surface errors. A probe pattern would be:

```python
async def _preflight(self) -> None:
    """Quick reachability + auth + config-sanity checks. Runs before
    any expensive operation (tokenizer download, LoRA alloc)."""
    # 1. Env-var check.
    if not os.environ.get("TINKER_API_KEY"):
        raise RuntimeError("TINKER_API_KEY is not set; refusing to start")
    # 2. Reachability (cheap HEAD request).
    if self.cfg.nemogym.agent_url:
        await self._check_http_reachable(self.cfg.nemogym.agent_url + "/health", timeout=5)
    # 3. Dataset existence (avoid loading into RAM yet).
    p = Path(self.cfg.nemogym.dataset_jsonl)
    if not p.exists():
        raise RuntimeError(f"dataset_jsonl does not exist: {p}")
    # 4. Disk space for checkpoint_dir.
    stat = shutil.disk_usage(Path(self.cfg.tinker.checkpoint_dir).parent)
    if stat.free < 1 * 1024**3:
        logger.warning("Only %.1f GB free on checkpoint disk", stat.free / 1024**3)
```

**Proposed.** Add `_preflight` as the first action in `setup()`. Any
failure here should *not* be retriable; fail fast with a named error.

### 2.20 Contract testing

**Findings.** Three slow tests in `tests/integration/` mark
`@pytest.mark.slow` and require `TINKER_API_KEY`. They *are* a
contract-test scaffold. What's missing is scheduling + alerting.

**Proposed.** See §2.9. Also: add a `pytest` mark `@pytest.mark.contract`
distinct from `slow`, and document the distinction:
- `slow`: any test >5s.
- `contract`: talks to a real external service; should run on schedule.
- `chaos`: simulates failures; should run on PR.

---

## §3. Proposed Observability Layer

This is the single biggest operational gap (D+ in §0). Concrete design
below. All code snippets are illustrative — they compile but have not
been wired into the repo (per task: *do not modify source*).

### 3.1 Structured logging via `contextvars`

```python
# tinker_nemogym/observability/log.py
from __future__ import annotations
import json
import logging
from contextvars import ContextVar
from typing import Any

# Propagates across await boundaries automatically.
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_step: ContextVar[int | None] = ContextVar("step", default=None)
_prompt_idx: ContextVar[int | None] = ContextVar("prompt_idx", default=None)
_traj_id: ContextVar[str | None] = ContextVar("traj_id", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        record.step = _step.get()
        record.prompt_idx = _prompt_idx.get()
        record.traj_id = _traj_id.get()
        return True


class JsonFormatter(logging.Formatter):
    _STD_KEYS = {"args", "asctime", "created", "exc_info", "exc_text",
                 "filename", "funcName", "levelname", "levelno", "lineno",
                 "message", "module", "msecs", "msg", "name", "pathname",
                 "process", "processName", "relativeCreated", "stack_info",
                 "thread", "threadName"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%03dZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for attr in ("run_id", "step", "prompt_idx", "traj_id"):
            val = getattr(record, attr, None)
            if val is not None:
                payload[attr] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Any LoggerAdapter `extra` keys come in as record attributes.
        for k, v in record.__dict__.items():
            if k not in self._STD_KEYS and k not in payload:
                payload[k] = v
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure(level: str = "INFO", json: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    h = logging.StreamHandler()
    h.addFilter(ContextFilter())
    h.setFormatter(JsonFormatter() if json else
                   logging.Formatter(
                       "%(asctime)s %(levelname)s %(name)s "
                       "[run=%(run_id)s step=%(step)s]: %(message)s"))
    root.handlers.clear()
    root.addHandler(h)
```

Wire points in `trainer.py`:

```python
from .observability.log import _run_id, _step, _prompt_idx

async def run(self) -> None:
    _run_id.set(self._run_id)          # set once
    await self.setup()
    for step in range(self.cfg.training.n_steps):
        _step.set(step)
        ...
```

And per-prompt in `_build_datums_from_rollouts`:

```python
for i, group in enumerate(groups_raw):
    tok = _prompt_idx.set(i)
    try:
        ...
    finally:
        _prompt_idx.reset(tok)
```

### 3.2 Prometheus metrics

Expose on the shim port. Minimal counter + histogram set:

```python
# tinker_nemogym/observability/metrics.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

STEP_DURATION = Histogram(
    "tnng_step_duration_seconds",
    "Time to complete one RL step.",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200),
)
ROLLOUT_DURATION = Histogram(
    "tnng_rollout_duration_seconds",
    "Single rollout latency (one /run call).",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
ROLLOUT_ERRORS = Counter(
    "tnng_rollout_errors_total",
    "Rollout errors by type.",
    ["error_type"],  # "timeout" | "5xx" | "network" | "parse"
)
TINKER_ERRORS = Counter(
    "tnng_tinker_errors_total",
    "Tinker SDK errors by class.",
    ["error_class"],  # "RateLimitError" | "AuthenticationError" | "SidecarDiedError" | ...
)
SAMPLER_VERSION = Gauge(
    "tnng_sampler_version",
    "Current sampler save_count (monotonically increasing).",
)
MEAN_REWARD = Gauge(
    "tnng_last_step_mean_reward",
    "Last step's mean reward across the batch.",
)
CONSECUTIVE_FAILURES = Gauge(
    "tnng_consecutive_step_failures",
    "Steps since last successful training step.",
)


def mount(app):
    @app.get("/metrics")
    async def _metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

Instrumentation hooks (in `trainer.py`):

```python
async def _run_step(self, step: int) -> dict:
    with STEP_DURATION.time():
        ...

async def _do_rollouts(self, step, batch_prompts):
    try:
        with ROLLOUT_DURATION.time():
            return await rollout_batch(...)
    except TimeoutError:
        ROLLOUT_ERRORS.labels(error_type="timeout").inc()
        raise
    except aiohttp.ClientResponseError:
        ROLLOUT_ERRORS.labels(error_type="5xx").inc()
        raise
    ...
```

### 3.3 Run-id propagation to nemo-gym + Tinker

Add `X-Run-Id` and `X-Trajectory-Id` headers to every outbound request
so the agent-side logs can join back:

```python
# rollout_driver.py
async def _call_once(session, url, payload, timeout_sec, headers=None):
    ...
    async with session.post(url, json=payload, timeout=timeout,
                            headers=headers) as resp:
        ...

# in rollout_batch — pass headers threaded from context:
headers = {
    "X-Run-Id": _run_id.get() or "",
    "X-Trajectory-Id": str(uuid.uuid4()),
}
```

The shim should echo an inbound `X-Run-Id` in its response headers and
stash it into `_traj_id` before calling `_route_to_tinker`. End-to-end,
one rollout is now greppable by UUID across: trainer log, nemo-gym agent
log, shim log.

### 3.4 OpenTelemetry (optional, future)

If/when the infra supports it:

```python
from opentelemetry import trace
tracer = trace.get_tracer("tinker-nemogym")

async def _run_step(self, step):
    with tracer.start_as_current_span("run_step", attributes={"step": step}) as sp:
        with tracer.start_as_current_span("rollouts"):
            ...
        with tracer.start_as_current_span("build_datums"):
            ...
        with tracer.start_as_current_span("train"):
            ...
        sp.set_attribute("mean_reward", metrics["mean_reward"])
```

---

## §4. Failure-Mode Table

| # | Failure | Current detection | Current recovery | User-visible impact | Proposed improvement |
|--:|---|---|---|---|---|
| 1 | Tinker `RateLimitError` | ✅ narrow-caught (`trainer.py:480`) | Skip step, continue | WARN log, wandb shows a zero-reward step | Add `tnng_tinker_errors_total{error_class="RateLimitError"}` counter + alerting; implement exponential backoff (`await asyncio.sleep(2**consecutive_429)`) |
| 2 | Tinker `AuthenticationError` | ✅ narrow-caught, re-raised (`trainer.py:475`) | Kill run (correct) | Full traceback; run dies | ✅ OK; add preflight env-var check (§2.19) |
| 3 | Tinker `SidecarDiedError` | ✅ narrow-caught (`trainer.py:488`) | Skip step | WARN log | Add consecutive-failure counter: after 3 back-to-back `SidecarDiedError` → raise |
| 4 | nemo-gym agent crash mid-run | `aiohttp.ClientError` → `_do_rollouts` returns None | Skip step, WARN | Step logs "skipping step" | Add `consecutive_rollout_failures` counter + `/readyz` check on agent before continuing |
| 5 | Network partition shim↔Tinker | Tinker SDK raises `RequestFailedError` | Skip step (`trainer.py:488`) | WARN log | Metric + exponential backoff + eventually raise |
| 6 | Network partition trainer↔agent | aiohttp `ClientConnectorError` | Skip step | WARN log | Health-poll the agent at step start; if down for >30s, raise |
| 7 | Disk full during checkpoint | `except Exception` swallows it | WARN, continue | **Silent data loss**: no checkpoint saved | Consecutive-save-failure counter → raise on 3rd fail; `shutil.disk_usage` in `_preflight` |
| 8 | OOM in shim | OS kills uvicorn thread | Nothing — thread is `daemon=True` | Subsequent `/v1/responses` hangs until agent-side timeout; trainer sees zero-reward steps (see #1 exec summary) | Liveness probe of `self._server_thread.is_alive()` at start of each `_run_step`; raise if dead |
| 9 | OOM in trainer | OS kills process | Nothing | Run dead; wandb run marked "crashed" after ~24h | Add `resource.setrlimit(RLIMIT_AS, ...)` soft cap; structured crash log via `sys.excepthook` |
| 10 | Tokenizer HF 403 | Raises in `setup()` | None | Stack trace | Named exception `TokenizerLoadError`; preflight HF reachability |
| 11 | Dataset file missing | `FileNotFoundError` in `load_jsonl` | None | Stack trace | Preflight check in `_preflight` |
| 12 | Dataset corruption (bad JSON) | `ValueError` with line number | None | Stack trace | Named exception `DatasetCorruptError`; `--strict` vs `--skip-bad-lines` flag |
| 13 | SIGTERM mid-step | `CancelledError` → `finally` runs cleanup | Wandb finish, uvicorn stop, session close | Possible: orphan remote optim_step; inconsistent `save_count` local vs remote | `asyncio.shield(_run_step_tail)` + signal handler (see §2.4) |
| 14 | SIGKILL | None | None | Wandb run stuck "running"; no crash artifact | Out-of-band systemd/supervisor with post-death hook |
| 15 | Clock skew | None | None | wandb timestamps lie; causality confused | NTP on host; log `time.monotonic()` + `time.time()` delta every 1k steps |
| 16 | wandb.init failure | ✅ caught, logs WARN, disables | Continue without wandb | INFO log only | OK — but add a metric `tnng_wandb_enabled` so dashboards don't silently drop |
| 17 | wandb.log failure mid-run | ✅ caught, logs WARN | Continue | WARN log only | OK |
| 18 | Hot-swap failure | ✅ caught (`trainer.py:536`) | Keep prev sampler | `hot_swap_error` in metrics dict | Add metric `tnng_hot_swap_failures_total`; after 3 → raise |
| 19 | `extract_trajectory` KeyError | ✅ caught per-trajectory | Drop that trajectory | WARN log | Count `tnng_rollout_errors_total{error_type="parse"}`; if all rollouts in a step fail parse → louder signal |
| 20 | Uvicorn port already bound | `setup()` → `_start_server_thread` → never observes `server.started`, returns after 10s with started=False | Silent false-negative! | Next POST from agent fails, trainer logs zero-reward step | Check started flag; if False after 10s, raise `ServerStartTimeout` |
| 21 | HF_TOKEN expired | Appears as 401 inside `get_tokenizer` | None | Stack trace at setup | Named exception; suggest `huggingface-cli login` in the error message |
| 22 | Agent returns malformed JSON | `aiohttp.ContentTypeError` caught as `ClientError` in `_do_rollouts` | Skip step | WARN log | Count under `tnng_rollout_errors_total{error_type="malformed"}` |
| 23 | HeadServer down when `discover_agent_url` polls | `TimeoutError` after 60s | Crash | Stack trace | Preflight; also accept fallback to `agent_url` even if `head_url` set |
| 24 | `max_trainer_tokens` saturated on every datum | `n_dropped_oversize` in metrics; WARN | Continue with fewer datums | WARN, smaller batch | Metric `tnng_datums_dropped_oversize_total`; alert if `>50%` for 5 consecutive steps |
| 25 | Tinker session/token expiry mid-run | Unknown — SDK behavior not documented | Probably `AuthenticationError` → kill run | As #2 | Open upstream ticket to Tinker; add session-lifetime tracking |

---

## §5. Day-1 Ops Quickstart

Minimal ops commands for a first-day operator. Assumes the `tools/tnng.sh`
wrapper from §2.15 plus the observability endpoints from §3.

```bash
# 0. Preflight
export TINKER_API_KEY=...
export WANDB_API_KEY=...
export HF_TOKEN=...
tinker-nemogym --version                    # sanity: binary works
tinker-nemogym train --config=configs/prod.yaml --dry-run   # preflight only

# 1. Start a job (backgrounded + logged)
RUN_DIR=./checkpoints/run_$(date -u +%Y%m%dT%H%M%S)
mkdir -p "$RUN_DIR"
nohup tinker-nemogym train \
    --config=configs/prod.yaml \
    --run-dir="$RUN_DIR" \
    >"$RUN_DIR/stdout.log" 2>"$RUN_DIR/stderr.log" &
echo $! > "$RUN_DIR/pid"

# 2. Inspect state (one line, any time)
tinker-nemogym inspect --run-dir="$RUN_DIR"
curl -s localhost:8001/readyz | jq
curl -s localhost:8001/metrics | grep tnng_last_step_mean_reward

# 3. Follow logs
tail -f "$RUN_DIR/stdout.log" | jq -c '{ts, level, step, msg}'

# 4. Stop cleanly (waits ≤15s for drain; shielded step completes)
kill -TERM $(cat "$RUN_DIR/pid")
wait $(cat "$RUN_DIR/pid")

# 5. Resume after a clean stop
tinker-nemogym train \
    --config=configs/prod.yaml \
    --resume="$RUN_DIR" \
    --run-dir="$RUN_DIR"

# 6. Resume from a specific Tinker checkpoint (no local run_state)
CKPT=$(jq -r '.uri' "$RUN_DIR/checkpoints.jsonl" | tail -1)
tinker-nemogym train \
    --config=configs/prod.yaml \
    --resume-checkpoint="$CKPT"

# 7. Archive a finished run
tar czf "${RUN_DIR}.tar.gz" "$RUN_DIR"
```

Roughly 7 commands covers: launch, inspect, follow, stop, resume-soft,
resume-hard, archive. Everything else (reconfiguring, scaling, rolling
back weights by 5 steps, rotating keys) belongs in the runbook.

---

## §6. Production-Readiness Checklist

Priority legend:
- **P0** — block production use.
- **P1** — fix before a 24h run or multi-user box.
- **P2** — fix before the next major users onboard.
- **P3** — nice-to-have; tech debt.

### Observability (P0/P1)
- [ ] **P0** Structured JSON logs with `run_id` / `step` / `prompt_idx` / `traj_id` (§3.1).
- [ ] **P1** Prometheus `/metrics` on the shim (§3.2).
- [ ] **P1** `X-Run-Id` / `X-Trajectory-Id` on all outbound requests (§3.3).
- [ ] **P2** OpenTelemetry spans around rollout/build/train (§3.4).
- [ ] **P2** `metrics.jsonl` + `checkpoints.jsonl` per run (§2.14).

### Health & readiness (P0/P1)
- [ ] **P0** `/livez` + `/readyz` distinction (§2.3).
- [ ] **P0** `_preflight()` checking env vars, dataset path, disk, Tinker reachability, agent reachability (§2.19).
- [ ] **P1** `/trainer/status` or equivalent inspect command (§2.17).
- [ ] **P1** Uvicorn-thread liveness probe inside `_run_step` (§4 #8).

### Reliability (P0/P1)
- [ ] **P0** Consecutive-failure counter → raise after N (§2.2, §4 #3, #4, #18).
- [ ] **P0** Save-failure counter → raise after N (§4 #7).
- [ ] **P0** `asyncio.shield` on training tail + signal handler for SIGTERM/SIGINT (§2.4, §4 #13).
- [ ] **P1** Exponential backoff on Tinker 429 (§4 #1).
- [ ] **P1** Agent `/health` poll before every step (§4 #6).

### Resumability (P0)
- [ ] **P0** `run_state.json` with step, cursor, wandb id, save_count, seed, config hash (§2.5).
- [ ] **P0** wandb `resume="must"` wiring for crash-restart (§2.5).
- [ ] **P1** CLI `--resume=<run-dir>` with local state (§5).

### Reproducibility (P1/P2)
- [ ] **P1** `TrainingConfig.seed` + threaded into `SamplingParams.seed` (§2.12).
- [ ] **P2** `--dry-run` mode (§2.12).
- [ ] **P2** Effective-config snapshot in `{run_dir}/effective_config.yaml` (§2.10).

### Multi-tenancy (P1/P2)
- [ ] **P1** `run_id` in Tinker checkpoint label (§2.13).
- [ ] **P1** `run_id` in default wandb name (§2.13).
- [ ] **P2** Default `ModelServerConfig.port = 0` (auto-free) when unspecified (§2.13).
- [ ] **P2** `checkpoint_dir / run_{run_id}` per-run subdirectory (§2.13).

### Supply chain (P1/P2)
- [ ] **P1** `pip-audit` in CI (§2.7).
- [ ] **P1** Fix CI to actually install nemo-gym (§2.7).
- [ ] **P2** SBOM generation on release (§2.7).
- [ ] **P2** `COMPATIBILITY.md` matrix + nightly contract test (§2.8, §2.9).
- [ ] **P3** Dependabot / Renovate config (§2.7).

### Deployment (P1/P2)
- [ ] **P1** `Dockerfile` + `Makefile` (§2.15).
- [ ] **P1** `tools/tnng.sh` wrapper (§2.15).
- [ ] **P2** `docs/runbook.md` populated (§2.16).
- [ ] **P3** Helm chart / systemd unit (§2.15).

### Budget & resource accounting (P2)
- [ ] **P2** `tinker-nemogym estimate --config=...` (§2.11).
- [ ] **P2** `training.max_total_tokens` hard cap (§2.11).
- [ ] **P2** Cumulative-token metric (§2.11).

### Testing (P1/P2)
- [ ] **P1** Chaos tests: agent flakiness, 429 storm, disk full (§2.18).
- [ ] **P1** Nightly contract test workflow (§2.9).
- [ ] **P2** 24h soak test on fake harness; RSS regression gate (§2.6).

### Disaster recovery (P1/P2)
- [ ] **P1** `metrics.jsonl` + `checkpoints.jsonl` artifact (§2.14).
- [ ] **P2** Crash traceback via `sys.excepthook` → `{run_dir}/crash.py` (§2.14).
- [ ] **P2** `inspect` tool parses these artifacts (§2.17).

### Documentation (P2/P3)
- [ ] **P2** `docs/runbook.md` (§2.16).
- [ ] **P2** `docs/OBSERVABILITY.md` (§3).
- [ ] **P2** `docs/COMPATIBILITY.md` (§2.8).
- [ ] **P3** `SECURITY.md`, `CHANGELOG.md`, `CONTRIBUTING.md` (already flagged by Review 04).

---

**Summary.** Code quality is B+; ops-readiness is C/D+. The gap is entirely
fillable without changing the core architecture — it's day-2 plumbing
(observability layer + runbook + resumability artifacts + preflight
+ circuit breakers). A focused 1-week sprint on the P0 + P1 items would
move the scorecard from C to B across the board.

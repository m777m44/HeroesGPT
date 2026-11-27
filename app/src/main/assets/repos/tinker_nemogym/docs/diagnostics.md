# Diagnostics

`tinker-nemogym` emits a set of per-step diagnostic scalars alongside the
usual `loss` / `mean_reward` / `n_datums` metrics. Most are on by default;
one (β precision-gap) is opt-in because it roughly halves throughput.

All diagnostic scalars flow through to **wandb** via the trainer's
`_log_wandb_metrics` emitter (prefix: `train/`), into **stdout logs** (one
line per step), and into the **metrics dict** returned from `_run_step`
for downstream tooling.

See the HuggingFace BF16-mismatch paper for the academic background:
<https://huggingface.co/spaces/aminediroHF/trainer-generator-bf16-mismatch>.

## The metrics, grouped

### Sampler version + staleness (always on)

Every response from the FastAPI shim is stamped with the `save_count` of
the `tinker.SamplingClient` snapshot that produced it. That number
becomes `RawTrajectory.sampler_version`. The trainer compares it to the
**current** `save_count` at the moment the step assembles its batch:

| key | meaning |
| --- | --- |
| `staleness_mean` | mean of `current_save_count − trajectory.sampler_version` across all rollouts in the step |
| `staleness_max` | worst offender |
| `staleness_n_stale` | number of rollouts with staleness > 0 |

**How to read it:** fresh rollouts have staleness 0. Non-zero values mean
an in-flight rollout survived a hot-swap — the logprobs on that trajectory
were computed under older weights than the current ones. Small non-zero
staleness (1) is normal and GRPO handles it. Large or growing staleness
means rollouts take longer than a step and you're training on
increasingly off-policy data; reduce `batch_size` or increase optim throughput.

### Per-rollout latency (always on)

The shim records `time.monotonic` around each `sample_async` call:

| key | meaning |
| --- | --- |
| `sample_latency_ms_mean` | mean of per-rollout sample wall time |
| `sample_latency_ms_p50` | median |
| `sample_latency_ms_p95` | 95th percentile (nearest-rank) |
| `sample_latency_ms_max` | slowest single rollout |

**How to read it:** p95 / p50 ratio above ~2× usually means Tinker is
queueing requests. If this creeps up across a run, you're hitting the
rate limit or another process is contending for GPUs.

### Precision gap β (opt-in)

Turned on by setting `training.measure_precision_gap: true` in your config.

When enabled, the trainer runs **one extra `forward_async` call per
step** with the `cross_entropy` loss surrogate *before* the real
`forward_backward_async`. This gives us the **trainer-side** per-token
logprobs. We diff them against the **sampler-side** logprobs already
stamped on each `RawTrajectory`:

$$\beta_t = f_\text{train}(a_t; W_k) - f_\text{sampler}(a_t; W_k)$$

Crucially both are at the same weights `W_k` (the pre-optim weights that
produced the rollout), so any non-zero β is pure kernel / precision
drift, not legitimate policy change.

| key | meaning |
| --- | --- |
| `beta_mean` | signed mean of `trainer − sampler` per-token logprob diff |
| `beta_std` | spread |
| `beta_abs_mean` | \|β\| mean — the one to watch |
| `beta_max` | worst single token |
| `beta_n_tokens` | total response tokens diffed |
| `beta_n_datums` | number of datums that contributed |
| `beta_n_skipped_datums` | datums skipped (None trainer logprobs, etc.) |

**How to read it:**

- `beta_abs_mean < 0.01` is "basically free" — sampler and trainer agree
  to three decimal places.
- `beta_abs_mean ≈ 0.05–0.2` is suspicious — PPO-style clipping may fire
  spuriously because the importance-sampling ratio is being driven by
  kernel noise.
- `beta_abs_mean > 0.5` means the sampler and trainer are using
  incompatible paths (usually BF16-vs-something-else). At this point the
  paper recommends using the **trainer's** recomputed logprobs as the
  `log π_old` in the RL loss instead of the sampler's stamped ones.

**Cost:** one extra forward per step, no backward. Throughput roughly
halves. Leave off for production runs; flip on when auditing a new base
model or when training stops improving and you want to rule out β as the
cause.

### Reproducibility echoes (always on)

Every response echoes back:

| shim response field | meaning |
| --- | --- |
| `sampling_params_used` | `{temperature, top_p, top_k, seed, max_tokens, stop}` with Tinker defaults filled in |
| `prompt_logprobs` | present if the request set `include_prompt_logprobs: true` |
| `topk_prompt_logprobs` | present if the request set `topk_prompt_logprobs: N > 0` |

These fields land on `RawTrajectory.metadata` and are not aggregated to
step scalars by default — they're there for custom downstream analysis
(distillation, KL-divergence monitoring, bug reports).

## Turning it all on

The canonical example config + script:

```bash
# configs/smoke_diagnostics.yaml sets training.measure_precision_gap: true
bash scripts/smoke_diagnostics.sh
```

Watch the per-step console lines — you'll see `beta_abs_mean=...`,
`sample_latency_ms_p95=...`, `staleness_max=...` alongside the usual
`loss` / `mean_reward`.

## Turning just β off

Most smoke configs ship with `measure_precision_gap: false`. If you
inherit from `smoke_diagnostics.yaml` and want to opt out, set:

```yaml
training:
  measure_precision_gap: false
```

and you'll still keep sampler-version / staleness / latency — those are
free.

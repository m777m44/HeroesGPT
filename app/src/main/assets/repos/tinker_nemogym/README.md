# tinker-nemogym

RL trainer that bridges **NVIDIA NeMo-Gym** environments to **Thinking Machines Tinker**'s managed LoRA training.

## Ready to go

```bash
# 1. Install
cd tinker-nemogym
poetry install

# 2. Set your Tinker key (https://tinker-console.thinkingmachines.ai)
export TINKER_API_KEY=tml-...

# 3. Run a live end-to-end smoke — boots nemo-gym + trainer against real Tinker
bash scripts/smoke_json_format.sh
```

Or programmatically:

```python
import tinker_nemogym as tng

summary = tng.train("configs/smoke_mcqa.yaml")
```

## High-level architecture

```
┌──────────────┐    POST /run        ┌──────────────────┐   sample_async    ┌───────────────┐
│  trainer     │ ─────────────────▶  │  nemo-gym        │ ────────────────▶ │  Tinker       │
│  (this repo) │                     │  SimpleAgent     │                    │  (managed GPU)│
│              │ ◀─── {reward,       │  + Resources     │ ◀─── tokens +     │  LoRA client  │
│              │    tokens, lp}      │  server          │    logprobs       │               │
└────┬─────────┘                     └──────────────────┘                    └───────────────┘
     │  forward_backward + optim_step + save_weights
     ▼
  ┌──────────────────────────┐
  │ FastAPI shim :8001       │  ◀── hot-swap SamplingClient after each optim step
  │ (in-process w/ trainer)  │
  └──────────────────────────┘
```

- The trainer hosts an in-process FastAPI shim that **impersonates** a nemo-gym `SimpleResponsesAPIModel`.
- nemo-gym's `SimpleAgent` sees a normal policy model on `:8001`, but every completion is routed through a `tinker.SamplingClient`.
- After each `optim_step_async`, the trainer **hot-swaps** in a fresh sampling client. Next rollout samples from updated weights.
- `datum_builder` converts agent `/run` responses → `tinker.Datum` with GRPO group-normalised advantages.

## Features

- 🔥 **Hot-swap sampler** — zero-downtime weight updates between RL steps (no SGLang server restart)
- 🎯 **GRPO advantages** — group-normalised, drops constant-reward groups automatically
- 🔌 **Dynamic agent discovery** — `agent_url: null` → resolved via HeadServer at runtime
- 🔬 **Precision-gap (β) diagnostics** — opt-in shadow forward pass measures sampler↔trainer numeric drift (HuggingFace BF16-mismatch paper) with `training.measure_precision_gap: true`
- 📏 **Per-step diagnostics** — sampler-version pinning, rollout latency p50/p95, staleness aggregates, prompt-logprob passthrough
- 🧯 **Preflight checks** — bad `TINKER_API_KEY` / unsupported `base_model` / missing files fail at config load, not step 6
- 🔁 **Resume-from-checkpoint** — `tinker.resume_from_checkpoint: <label>` → `load_state_async` + restored metadata
- 📊 **Wandb wired** — per-step `loss`, `mean_reward`, `n_datums`, `n_dropped`, `beta_*`, latency/staleness (offline mode works)
- 🛑 **Typed errors** — `ConfigError`, `TrainingError`, `ShimError`, `AgentDiscoveryError`, `CheckpointError` (no substring matching)
- ✅ **Live-validated** against Tinker cloud on Llama-3.1-8B-Instruct + Nemotron-Nano-30B — run `bash scripts/smoke_mcqa.sh` with your `TINKER_API_KEY` set

## End-to-end testing

The **only** end-to-end path is live Tinker. There is no offline stand-in — every `scripts/smoke_*.sh` spins up real nemo-gym and hits real Tinker GPUs with your `TINKER_API_KEY`.

| Script | Env | What it exercises |
| --- | --- | --- |
| `scripts/smoke_single_tool.sh` | `example_single_tool_call` | Forward/backward + hot-swap wire path (constant reward; gradients are no-op) |
| `scripts/smoke_mcqa.sh` | `mcqa` (varied reward) | Full GRPO training signal with non-zero advantages |
| `scripts/smoke_diagnostics.sh` | `mcqa` + β measurement | Everything above **plus** precision-gap (β), latency p50/p95, staleness aggregates |
| `scripts/smoke_multi_step.sh` | `example_multi_step` | Multi-turn rollouts with tool calls |
| `scripts/smoke_json_format.sh` | `json_format` (self-contained) | Minimal custom env bundled with this repo |

All of them require `TINKER_API_KEY` and a running nemo-gym stack (the scripts launch `ng_run` for you).

## Define your own env in 5 minutes

Full end-to-end example is ready to run: **`bash scripts/smoke_json_format.sh`**. Here's what it builds.

### 1. nemo-gym resources server — the reward function

`tinker_nemogym/environments/json_format/nemogym_server/app.py`:

```python
from nemo_gym.base_resources_server import (
    BaseRunRequest, BaseVerifyRequest, BaseVerifyResponse, SimpleResourcesServer,
)

class JSONRunRequest(BaseRunRequest):
    required_keys: list[str] | None = None
    expected_count: int | None = None

class JSONVerifyRequest(JSONRunRequest, BaseVerifyRequest): pass

server = SimpleResourcesServer[JSONVerifyRequest, BaseVerifyResponse](...)

@server.app.post("/verify")
async def verify(req: JSONVerifyRequest) -> BaseVerifyResponse:
    text = _extract_text(req.response)
    try:
        parsed = json.loads(_strip_fence(text))
    except json.JSONDecodeError:
        return BaseVerifyResponse(reward=0.0)           # bad JSON → 0
    if _keys_match(parsed, req.required_keys, req.expected_count):
        return BaseVerifyResponse(reward=1.0)           # perfect → 1
    return BaseVerifyResponse(reward=0.5)               # parseable but wrong keys → 0.5
```

### 2. Dataset — one JSON-line per prompt

`tinker_nemogym/environments/json_format/dataset.jsonl`:

```json
{"responses_create_params": {"input": [{"role":"user","content":"List 3 fruits as a JSON array with keys \"name\" and \"color\"."}]}, "required_keys": ["name","color"], "expected_count": 3}
{"responses_create_params": {"input": [{"role":"user","content":"Give 2 planets with keys \"name\" and \"distance_au\"."}]}, "required_keys": ["name","distance_au"], "expected_count": 2}
```

### 3. Trainer config — pick a model, wire it up

`configs/smoke_json_format_nemotron.yaml`:

```yaml
schema_version: 1
tinker:
  base_model: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16   # on Tinker allow-list
  lora_rank: 32
  learning_rate: 5.0e-4
  loss_fn: importance_sampling
  wandb_project: tinker-nemogym-json-format                # live monitoring
  checkpoint_dir: ./checkpoints/smoke_json_format

model_server: { host: 127.0.0.1, port: 8001 }              # our FastAPI shim
nemogym:
  agent_url: null                                          # auto-discover
  head_url: http://127.0.0.1:11000
  dataset_jsonl: tinker_nemogym/environments/json_format/dataset.jsonl
  group_size: 8

training: { n_steps: 5, batch_size: 2, max_tokens: 512, temperature: 1.0 }
```

### 4. Run it

```bash
export TINKER_API_KEY=tml-...
bash scripts/smoke_json_format.sh
```

The script boots nemo-gym (HeadServer + agent + resources server via symlinks to our embedded code), launches the trainer, prints the wandb URL, and cleans everything up on exit. Expected output:

```
[smoke-jsonfmt] trainer step 0: mean_reward=0.550 n_datums=14 loss=-2.1
[smoke-jsonfmt] trainer step 1: mean_reward=0.688 n_datums=12 loss=12.3
...
```

Full walkthrough: [`docs/custom_env_walkthrough.md`](docs/custom_env_walkthrough.md).

## Requires

- Python 3.12 + [poetry](https://python-poetry.org/)
- `nemo-gym` cloned as a sibling directory (`../nemo-gym`) with its own `.venv/bin/ng_run`
- `TINKER_API_KEY` env var (unless you're using `tinker_nemogym.testing` fakes)

## License

MIT — see [`LICENSE`](LICENSE).

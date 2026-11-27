# Quickstart

Three progressive examples — start with the 5-line offline one, then
graduate.

## 1. Five-line offline hello-world (no API key, no nemo-gym)

Smoke-test the library without talking to Tinker or nemo-gym — useful for
CI or sanity-checking your install:

```python
from tinker_nemogym.datum_builder import RawTrajectory, build_datum

traj = RawTrajectory(prompt_tokens=[1, 2, 3], response_tokens=[4, 5],
                     response_logprobs=[-0.1, -0.2], reward=1.0)
datum = build_datum(traj, advantage=0.5)
print(datum)
```

That's the pure data-path, no network, no GPU.

## 2. Fifteen-line real training (YAML config)

The canonical flow. Write a YAML (see `configs/smoke_mcqa.yaml` for a full
example), export your `TINKER_API_KEY`, then:

```python
import os
import tinker_nemogym

os.environ.setdefault("TINKER_API_KEY", "<your-key-here>")

# Start nemo-gym in another terminal:
#   ng_run examples/mcqa/resources.yaml examples/mcqa/agent.yaml
# (or set cfg.nemogym.agent_url to a live URL).

summary = tinker_nemogym.train("configs/smoke_mcqa.yaml")
print("done, save_count =", summary["save_count"])
```

`tinker_nemogym.train()` accepts either a YAML path or a pre-built
`TinkerNeMoGymConfig`. It runs the full async trainer under `asyncio.run`
and returns a summary dict. Eager validation fires at YAML-load time —
typos in `base_model`, missing dataset files, or unreachable checkpoint
dirs surface before any Tinker call.

## 3. Thirty-line custom config (programmatic, no YAML)

For library users who'd rather build configs in code:

```python
import asyncio
from tinker_nemogym import (
    TinkerNeMoGymConfig,
    TinkerNeMoGymTrainer,
)
from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TrainingConfig,
)

cfg = TinkerNeMoGymConfig(
    tinker=TinkerConfig(
        base_model="meta-llama/Llama-3.1-8B-Instruct",
        lora_rank=32,
        learning_rate=5e-4,
        wandb_project="my-runs",
        checkpoint_dir="./checkpoints/my-run",
    ),
    model_server=ModelServerConfig(port=8001),
    nemogym=NeMoGymConfig(
        dataset_jsonl="./data/prompts.jsonl",
        agent_url=None,   # discover via HeadServer
        head_url="http://127.0.0.1:11000",
        group_size=4,
    ),
    training=TrainingConfig(n_steps=100, batch_size=4, save_every=25),
)

trainer = TinkerNeMoGymTrainer(cfg)
asyncio.run(trainer.run())
```

Drop into the async trainer directly when you need to drive the loop
yourself (custom rollouts, custom optimizer schedules, distributed
orchestration, etc.).

## Errors you might see

All library errors derive from `tinker_nemogym.TinkerNeMoGymError`:

* `ConfigError` — bad YAML / missing dataset / invalid `base_model`.
* `TrainingError` — forward_backward / optim_step / hot-swap failed.
* `SamplerNotReadyError` — FastAPI shim was hit before the trainer wired
  the initial sampling client. HTTP 503.
* `AgentDiscoveryError` — nemo-gym HeadServer unreachable (start
  `ng_run` first).
* `CheckpointError` — save_state / load_state failed.

Catch any one of them, or `TinkerNeMoGymError` for all.

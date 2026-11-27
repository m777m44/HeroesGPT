# tinker-nemogym MVP Implementation Plan

> **NOTE:** This is the original pre-implementation plan, frozen for
> historical reference. Current state: see [README.md](../../README.md).
> Some details (default base model, dynamic agent-port discovery, exception
> hierarchy, sync `tng.train()` wrapper) diverged during reviews 01–07 —
> see `docs/reviews/ADDRESSED.md` for the per-finding changelog.

> **For Hermes:** Use `subagent-driven-development` skill to implement this plan task-by-task.

**Goal:** Build a working bridge that lets Tinker train a LoRA policy against any NVIDIA NeMo-Gym environment, with trajectories, rewards, and token-level logprobs flowing cleanly between the two systems. Ship an end-to-end smoke test on a simple single-tool-call nemo-gym env.

**Architecture:** Single-process trainer hosts a FastAPI server that (a) implements NeMo-Gym's `SimpleResponsesAPIModel` contract — speaking `/v1/chat/completions` and `/v1/responses` — and (b) routes every completion through a hot-swappable `tinker.SamplingClient`. The trainer drives rollouts by POSTing dataset rows to the nemo-gym agent's `/run` endpoint, harvests `{reward, response_with_token_ids_and_logprobs}`, converts to `list[tinker.Datum]`, runs `forward_backward_async(loss_fn="importance_sampling")` + `optim_step_async`, then calls `save_weights_and_get_sampling_client_async()` to hot-swap the sampler so the next rollout uses fresh weights.

**Tech Stack:** Python 3.12, `tinker==0.18.1`, `tinker-cookbook==0.3.0`, `nemo-gym==0.3.0rc0`, FastAPI + uvicorn, aiohttp, pydantic v2, Hydra/OmegaConf (from nemo-gym), tiktoken/transformers tokenizers.

**Decision memo (why this shape):**

Two designs were considered:

| Design | Description | Weights sync | Verdict |
|---|---|---|---|
| **A. Sampler-in-the-middle** (verifiers_rl style) | tinker-nemogym runs ONE FastAPI server that IS a nemo-gym `SimpleResponsesAPIModel`. Every completion call hits `tinker.SamplingClient`. After each optim step, we swap in a fresh sampling client. | ✅ Always fresh | **CHOSEN** |
| B. Atropos-style decoupled poller | Nemo-gym runs a vllm_model server; trainer polls `agent/run` only. | ❌ vllm_model weights go stale — need explicit weight-push | Rejected |

Design A also mirrors exactly what `tinker-cookbook/tinker_cookbook/recipes/verifiers_rl/tinker_openai.py::TinkerAsyncOpenAIClient` does, and what `tinker-atropos/tinker_atropos/trainer.py:546` does with its `:8001` FastAPI shim — so we have TWO reference implementations.

**Analysis references (read before implementing):**

- `../../analysis/01_nemogym_architecture.md` — 528-line nemo-gym deep-dive
- `../../analysis/02_tinker_integration_surface.md` — 951-line Tinker API surface
- `../../analysis/03_tinker_atropos_reference.md` — 590-line reference impl walkthrough

---

## Repo layout (target)

```
tinker-nemogym/
├── pyproject.toml
├── README.md
├── configs/
│   ├── default.yaml                    # top-level run config (model, lora_rank, lr, env)
│   └── smoke_single_tool.yaml          # tiny reference config
├── tinker_nemogym/
│   ├── __init__.py
│   ├── config.py                       # Pydantic config schema
│   ├── datum_builder.py                # core Datum construction
│   ├── tinker_responses_model.py       # FastAPI server: nemo-gym SimpleResponsesAPIModel → Tinker sampler
│   ├── trainer.py                      # main training loop
│   ├── rollout_driver.py               # POST to nemo-gym agent/run in parallel
│   ├── nemogym_launcher.py             # spawn nemo-gym resources/agent subprocesses
│   ├── utils/
│   │   ├── tokenizer.py                # tokenizer + renderer helpers
│   │   └── logging.py
│   └── environments/
│       └── single_tool_call/           # first supported env (reuses nemo-gym's example)
│           ├── __init__.py
│           └── config.yaml
├── launch_training.py                  # entry point (mirrors tinker-atropos/launch_training.py)
├── serve.py                            # standalone model server (no training)
├── scripts/
│   └── smoke_single_tool.sh            # 3-line launcher script
└── tests/
    ├── unit/
    │   ├── test_datum_builder.py
    │   ├── test_tinker_responses_model.py
    │   └── test_config.py
    └── integration/
        └── test_smoke_single_tool.py   # end-to-end ≤10-step run
```

---

## Phase 0: Project setup

### Task 0.1: Initialize pyproject.toml

**Objective:** Make the repo pip-installable and declare deps.

**Files:**
- Create: `tinker-nemogym/pyproject.toml`

**Complete file:**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "tinker-nemogym"
version = "0.0.1"
description = "Bridge between NVIDIA NeMo-Gym RL environments and Thinking Machines Tinker"
requires-python = ">=3.12"
authors = [{name = "Nous Research"}]
dependencies = [
    "tinker>=0.18.0",
    "tinker-cookbook>=0.3.0",
    "nemo-gym>=0.3.0rc0",
    "fastapi>=0.118",
    "uvicorn>=0.35",
    "aiohttp>=3.12",
    "pydantic>=2.11",
    "pyyaml>=6.0",
    "click>=8.3",
    "tqdm>=4.67",
    "wandb>=0.21",
    "transformers>=4.50",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.25", "ruff>=0.8"]

[project.scripts]
tinker-nemogym-train = "tinker_nemogym.cli:train"
tinker-nemogym-serve = "tinker_nemogym.cli:serve"

[tool.setuptools.packages.find]
include = ["tinker_nemogym*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Verify:**
```bash
cd /home/phuc/workspace/rl/small_prs/pr003_tinker_nemogym_integration/tinker-nemogym
source ../.venv/bin/activate
uv pip install -e .
python -c "import tinker_nemogym; print('ok')"
```
Expected: `ok`

**Commit:** `chore: initialize pyproject.toml`

---

### Task 0.2: Create package skeleton

**Objective:** Empty `__init__.py` files + minimal README.

**Files:**
- Create: `tinker_nemogym/__init__.py` (empty)
- Create: `tinker_nemogym/utils/__init__.py` (empty)
- Create: `tinker_nemogym/environments/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/unit/__init__.py` (empty)
- Create: `tests/integration/__init__.py` (empty)

**Commit:** `chore: package skeleton`

---

## Phase 1: Config schema

### Task 1.1: Pydantic config

**Objective:** Mirror `tinker-atropos`'s `TinkerAtroposConfig` but point at nemo-gym.

**Files:**
- Create: `tinker_nemogym/config.py`

**Key design:** Four nested blocks — `tinker`, `model_server`, `nemogym`, `training`.

**Code:**

```python
# tinker_nemogym/config.py
from __future__ import annotations
from typing import Literal
from pathlib import Path
from pydantic import BaseModel, Field
import yaml


class TinkerConfig(BaseModel):
    base_model: str = "meta-llama/Llama-3.2-1B"
    lora_rank: int = 32
    learning_rate: float = 5e-4
    adam_beta1: float = 0.9
    adam_beta2: float = 0.95
    adam_eps: float = 1e-8
    loss_fn: Literal["importance_sampling", "ppo", "cispo", "dro"] = "importance_sampling"
    wandb_project: str | None = None
    wandb_name: str | None = None
    checkpoint_dir: str = "./checkpoints"


class ModelServerConfig(BaseModel):
    """The FastAPI server that looks like a nemo-gym model to the agent."""
    host: str = "127.0.0.1"
    port: int = 8001
    # Stop sequences exposed to callers; typically the tokenizer's special EOT tokens.
    stop_tokens: list[str] = Field(default_factory=list)


class NeMoGymConfig(BaseModel):
    """How we talk to nemo-gym."""
    agent_url: str = "http://127.0.0.1:11001"        # SimpleAgent /run endpoint
    head_url: str = "http://127.0.0.1:11000"         # HeadServer
    dataset_jsonl: str                                # path to input dataset (agent-style rows)
    group_size: int = 4                               # samples per prompt for GRPO
    # If empty, we expect the user to launch nemo-gym themselves via `ng_run`.
    # If populated, we'll spawn it as a subprocess.
    ng_run_yamls: list[str] = Field(default_factory=list)


class TrainingConfig(BaseModel):
    n_steps: int = 100
    batch_size: int = 4                               # problems per step
    max_tokens: int = 512
    temperature: float = 1.0
    save_every: int = 10
    eval_every: int = 20


class TinkerNeMoGymConfig(BaseModel):
    tinker: TinkerConfig
    model_server: ModelServerConfig
    nemogym: NeMoGymConfig
    training: TrainingConfig

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TinkerNeMoGymConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
```

**Test:** `tests/unit/test_config.py`

```python
from tinker_nemogym.config import TinkerNeMoGymConfig

MINIMAL = """
tinker:
  base_model: meta-llama/Llama-3.2-1B
model_server:
  port: 8001
nemogym:
  dataset_jsonl: /tmp/x.jsonl
training:
  n_steps: 4
"""

def test_config_roundtrip(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL)
    cfg = TinkerNeMoGymConfig.from_yaml(p)
    assert cfg.tinker.lora_rank == 32
    assert cfg.training.n_steps == 4
```

**Run:** `pytest tests/unit/test_config.py -v` → PASS

**Commit:** `feat(config): Pydantic schema`

---

## Phase 2: Datum builder (the heart of the bridge)

### Task 2.1: Token extraction from nemo-gym response

**Objective:** Pull out `(prompt_token_ids, generation_token_ids, generation_log_probs)` from a nemo-gym `/run` response.

**Context:** Per `analysis/01` §2.26, `vllm_model`'s `TokenIDLogProbMixin` attaches these fields on the `NeMoGymResponse`. For OpenAI-backed models they are NOT present — the user must use `vllm_model` OR we tokenize+lookup manually (MVP: require vllm_model or our own TinkerResponsesAPIModel).

**Files:**
- Create: `tinker_nemogym/datum_builder.py`

**Step 1: Failing test**

```python
# tests/unit/test_datum_builder.py
import numpy as np
from tinker_nemogym.datum_builder import extract_trajectory, RawTrajectory

SAMPLE_RESPONSE = {
    "reward": 0.75,
    "response": {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "hi"}]}
        ],
        "prompt_token_ids": [10, 20, 30],
        "generation_token_ids": [40, 50, 60, 70],
        "generation_log_probs": [-0.1, -0.2, -0.3, -0.4],
    },
}

def test_extract_trajectory_basic():
    t = extract_trajectory(SAMPLE_RESPONSE)
    assert isinstance(t, RawTrajectory)
    assert t.reward == 0.75
    assert t.prompt_tokens == [10, 20, 30]
    assert t.response_tokens == [40, 50, 60, 70]
    assert len(t.response_logprobs) == 4
```

Run: `pytest tests/unit/test_datum_builder.py::test_extract_trajectory_basic -v`
Expected: FAIL — module not defined.

**Step 2: Implementation**

```python
# tinker_nemogym/datum_builder.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np

import tinker
from tinker import types as tt


@dataclass
class RawTrajectory:
    """One rollout's worth of tokens + reward, ready to convert to a Datum."""
    prompt_tokens: list[int]
    response_tokens: list[int]
    response_logprobs: list[float]   # logprobs of the sampled response tokens under the sampling policy
    reward: float
    metadata: dict[str, Any]


def extract_trajectory(run_response: dict) -> RawTrajectory:
    """Parse a nemo-gym agent /run response into a RawTrajectory.

    Requires the model server to attach `prompt_token_ids`, `generation_token_ids`,
    and `generation_log_probs` to the response (as vllm_model and our
    TinkerResponsesAPIModel do via TokenIDLogProbMixin).
    """
    resp = run_response["response"]
    reward = float(run_response["reward"])

    prompt_tokens = resp.get("prompt_token_ids")
    gen_tokens = resp.get("generation_token_ids")
    gen_logprobs = resp.get("generation_log_probs")

    if prompt_tokens is None or gen_tokens is None or gen_logprobs is None:
        raise ValueError(
            "Response is missing token_ids/logprobs. Ensure the nemo-gym model "
            "server subclasses TokenIDLogProbMixin (use vllm_model or "
            "TinkerResponsesAPIModel)."
        )

    return RawTrajectory(
        prompt_tokens=list(prompt_tokens),
        response_tokens=list(gen_tokens),
        response_logprobs=list(gen_logprobs),
        reward=reward,
        metadata={k: v for k, v in run_response.items() if k not in ("reward", "response")},
    )
```

Run: `pytest tests/unit/test_datum_builder.py::test_extract_trajectory_basic -v` → PASS

**Commit:** `feat(datum): trajectory extraction`

---

### Task 2.2: Group-centered advantages (GRPO)

**Objective:** Given N rollouts for the same prompt, center their rewards.

**Files:**
- Modify: `tinker_nemogym/datum_builder.py` (add `compute_advantages`)
- Modify: `tests/unit/test_datum_builder.py` (add `test_compute_advantages`)

**Test first:**

```python
def test_compute_advantages_zero_mean():
    rewards = [1.0, 0.5, 0.0, 0.5]
    adv = compute_advantages(rewards)
    import numpy as np
    assert abs(np.mean(adv)) < 1e-6
    assert adv[0] > adv[2]          # higher reward → higher advantage
```

**Implementation (append to `datum_builder.py`):**

```python
def compute_advantages(rewards: list[float]) -> list[float]:
    """GRPO: subtract the group mean. No standardization (matches tinker-cookbook)."""
    import numpy as np
    arr = np.array(rewards, dtype=np.float32)
    return (arr - arr.mean()).tolist()
```

Run: pass. Commit: `feat(datum): group-centered advantages`.

---

### Task 2.3: Build a `tinker.Datum` from one trajectory

**Objective:** Convert `(RawTrajectory, advantage)` → `tinker.Datum` with correct shifts and dtypes.

**Context:** Per `analysis/02` §3 and `supervised/common.py:45-98`:
- Concatenate `prompt_tokens + response_tokens` → `all_tokens`
- `input_tokens = all_tokens[:-1]`  → `ModelInput.from_ints`
- `target_tokens = all_tokens[1:]`  → int64 array
- `advantages`: float32 per target position; **0 on prompt positions, `adv` on response positions** (masks out prompt loss)
- `logprobs`: float32 per target position; **1.0 sentinel on prompt positions** (matches tinker-atropos convention at `trainer.py:283`), actual response logprobs on response positions

**Files:**
- Modify: `tinker_nemogym/datum_builder.py`
- Modify: `tests/unit/test_datum_builder.py`

**Test first:**

```python
def test_build_datum_shapes():
    import numpy as np
    from tinker_nemogym.datum_builder import build_datum, RawTrajectory

    traj = RawTrajectory(
        prompt_tokens=[10, 20, 30],
        response_tokens=[40, 50, 60, 70],
        response_logprobs=[-0.1, -0.2, -0.3, -0.4],
        reward=0.5,
        metadata={},
    )
    datum = build_datum(traj, advantage=0.25)
    # target length = total - 1 = 6
    target = datum.loss_fn_inputs["target_tokens"].to_numpy()
    adv = datum.loss_fn_inputs["advantages"].to_numpy()
    lp = datum.loss_fn_inputs["logprobs"].to_numpy()
    assert target.shape == (6,)
    assert target.dtype == np.int64
    assert adv.shape == (6,)
    assert adv.dtype == np.float32
    # 2 prompt-shift positions (len(prompt)-1 = 2) should have advantage 0
    assert (adv[:2] == 0.0).all()
    # 4 response positions should have advantage = 0.25
    assert (adv[2:] == 0.25).all()
    # prompt-shift positions should have logprob sentinel 1.0
    assert (lp[:2] == 1.0).all()
    # response positions should match the provided logprobs
    np.testing.assert_allclose(lp[2:], [-0.1, -0.2, -0.3, -0.4], atol=1e-6)
```

**Implementation (append):**

```python
PROMPT_LOGPROB_SENTINEL = 1.0  # Tinker convention: 1.0 means "don't compute loss here"


def build_datum(traj: RawTrajectory, advantage: float) -> tinker.Datum:
    """Construct a tinker.Datum for importance_sampling loss.

    Shifts follow next-token-prediction:
      input  = all_tokens[:-1]    (sent to model)
      target = all_tokens[1:]     (what to predict)

    For target position i:
      - If i < len(prompt) - 1: this predicts a prompt token. advantage=0, logprob=SENTINEL.
      - Otherwise: this predicts a response token. advantage=adv, logprob=observed.
    """
    all_tokens = traj.prompt_tokens + traj.response_tokens
    input_tokens = all_tokens[:-1]
    target_tokens = all_tokens[1:]

    n_prompt_targets = len(traj.prompt_tokens) - 1      # prompt positions in the target array
    n_response_targets = len(traj.response_tokens)       # == total targets - n_prompt_targets
    assert n_prompt_targets + n_response_targets == len(target_tokens)

    advantages = np.concatenate([
        np.zeros(n_prompt_targets, dtype=np.float32),
        np.full(n_response_targets, advantage, dtype=np.float32),
    ])
    logprobs = np.concatenate([
        np.full(n_prompt_targets, PROMPT_LOGPROB_SENTINEL, dtype=np.float32),
        np.asarray(traj.response_logprobs, dtype=np.float32),
    ])

    model_input = tt.ModelInput.from_ints(input_tokens)
    return tinker.Datum(
        model_input=model_input,
        loss_fn_inputs={
            "target_tokens": tt.TensorData.from_numpy(np.asarray(target_tokens, dtype=np.int64)),
            "advantages":    tt.TensorData.from_numpy(advantages),
            "logprobs":      tt.TensorData.from_numpy(logprobs),
        },
    )
```

Run test → PASS. Commit: `feat(datum): build tinker.Datum with correct shifts`.

---

### Task 2.4: Batch builder

**Objective:** Given a dict `{prompt_id: [RawTrajectory, ...]}`, produce `list[tinker.Datum]` ready for `forward_backward_async`. Skip constant-reward groups (every advantage would be 0 → zero gradient).

**Files:**
- Modify: `tinker_nemogym/datum_builder.py`
- Modify: `tests/unit/test_datum_builder.py`

**Append:**

```python
def build_batch(
    trajectory_groups: dict[str, list[RawTrajectory]],
    drop_constant_reward: bool = True,
) -> tuple[list[tinker.Datum], dict]:
    """Convert groups of RawTrajectories into a list of Datums.

    Returns (datums, metadata). metadata includes mean_reward, n_groups, n_dropped.
    """
    all_datums: list[tinker.Datum] = []
    dropped = 0
    rewards_all: list[float] = []
    for _prompt_id, group in trajectory_groups.items():
        rewards = [t.reward for t in group]
        rewards_all.extend(rewards)
        if drop_constant_reward and len(set(rewards)) <= 1:
            dropped += 1
            continue
        advantages = compute_advantages(rewards)
        for traj, adv in zip(group, advantages, strict=True):
            all_datums.append(build_datum(traj, advantage=float(adv)))
    meta = {
        "mean_reward": float(np.mean(rewards_all)) if rewards_all else 0.0,
        "n_groups": len(trajectory_groups),
        "n_dropped_constant": dropped,
        "n_datums": len(all_datums),
    }
    return all_datums, meta
```

Test: group of [1.0, 1.0] gets dropped; group of [1.0, 0.0] produces 2 datums with opposite advantages. Commit.

---

## Phase 3: TinkerResponsesAPIModel server

### Task 3.1: Skeleton FastAPI server implementing nemo-gym model contract

**Objective:** Expose `/v1/chat/completions` and `/v1/responses` on port 8001. Route every request through a global `current_sampling_client` (hot-swappable).

**Context:** Per `analysis/03` §Shim, tinker-atropos does this with a module-global `trainer` variable and `current_sampling_client`. We follow the same pattern — it's ugly but it's the ONLY way to let `uvicorn.run()` in a thread see trainer state.

Per `analysis/01` §7 (responses_api_models), we must subclass `SimpleResponsesAPIModel`. Look at `nemo_gym/responses_api_models/vllm_model/app.py` for the reference shape. Also per §2.26, inherit `TokenIDLogProbMixin` so we can attach `generation_token_ids` + `generation_log_probs`.

**Files:**
- Create: `tinker_nemogym/tinker_responses_model.py`

**Skeleton (implementer must verify exact base class + mixin paths by reading `nemo-gym/nemo_gym/responses_api_models/__init__.py` and `vllm_model/app.py` before writing the final version):**

```python
# tinker_nemogym/tinker_responses_model.py
"""FastAPI server that masquerades as a nemo-gym ResponsesAPIModel and routes
completions through a Tinker SamplingClient.

The SamplingClient is hot-swappable via `set_sampling_client()` so the trainer
can update weights between RL steps.
"""
from __future__ import annotations
import threading
from typing import Any

import tinker
from tinker import types as tt

# Module-global state (the only way to share across uvicorn workers / routes)
_sampling_client_lock = threading.Lock()
_current_sampling_client: tinker.SamplingClient | None = None
_tokenizer = None           # set by init()
_renderer = None            # set by init()
_model_config = None        # set by init()


def set_sampling_client(client: tinker.SamplingClient) -> None:
    """Called by the trainer after each optim_step."""
    global _current_sampling_client
    with _sampling_client_lock:
        _current_sampling_client = client


def init(base_model: str, tokenizer, renderer) -> None:
    global _tokenizer, _renderer, _model_config
    _tokenizer = tokenizer
    _renderer = renderer
    _model_config = {"base_model": base_model}


# TODO (implementer): import the real base classes from nemo-gym. Verify exact
# import path — likely:
#   from nemo_gym.responses_api_models.common import SimpleResponsesAPIModel
#   from nemo_gym.responses_api_models.common import TokenIDLogProbMixin
#
# Then subclass SimpleResponsesAPIModel + TokenIDLogProbMixin and override
# the chat_completions / responses handlers to call _route_to_tinker() below.

async def _route_to_tinker(
    prompt_messages: list[dict],
    max_tokens: int,
    temperature: float,
    stop: list[str] | None,
) -> dict:
    """Run one completion via the current SamplingClient. Returns dict with
    text, prompt_token_ids, generation_token_ids, generation_log_probs."""
    if _current_sampling_client is None:
        raise RuntimeError("Sampling client not initialized; call set_sampling_client() first.")
    if _renderer is None or _tokenizer is None:
        raise RuntimeError("init() not called.")

    model_input = _renderer.build_generation_prompt(prompt_messages)
    prompt_token_ids = list(model_input.to_ints())   # TODO verify: ModelInput has to_ints()?

    sampling_params = tt.SamplingParams(
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop or _renderer.get_stop_sequences(),
    )
    with _sampling_client_lock:
        client = _current_sampling_client
    result = await client.sample_async(
        prompt=model_input,
        num_samples=1,
        sampling_params=sampling_params,
    )
    seq = result.sequences[0]
    # Decode text for the response body
    parsed_msg, _ = _renderer.parse_response(seq.tokens)
    text = parsed_msg["content"][0]["text"] if parsed_msg.get("content") else ""

    return {
        "text": text,
        "prompt_token_ids": prompt_token_ids,
        "generation_token_ids": list(seq.tokens),
        "generation_log_probs": list(seq.logprobs),
        "stop_reason": seq.stop_reason,
    }


# TODO (implementer): wire _route_to_tinker() into the nemo-gym server's
# chat_completions / responses route handlers. See:
#   nemo-gym/nemo_gym/responses_api_models/vllm_model/app.py  (reference)
#   nemo-gym/nemo_gym/responses_api_models/openai_model/app.py
```

**Follow-up tasks (3.2 - 3.5):**

- **3.2:** Read `nemo-gym/nemo_gym/responses_api_models/vllm_model/app.py` front-to-back. Identify the exact subclass signature + method overrides (`chat_completions`, `responses`) and the serialization helpers for attaching `prompt_token_ids`/`generation_token_ids`/`generation_log_probs` (TokenIDLogProbMixin contract).
- **3.3:** Replace `# TODO (implementer)` blocks with the real subclass + route overrides.
- **3.4:** Unit test: start the server in a thread with a **mock SamplingClient** (returns canned `SampleResponse`). POST a `/v1/chat/completions` request via `httpx.AsyncClient`. Assert the response JSON has `text`, `prompt_token_ids`, `generation_token_ids`, `generation_log_probs`.
- **3.5:** Unit test: `set_sampling_client(new_client)` → next call uses new client. (Verify hot-swap works.)

**Commits:** `feat(server): …` per task.

---

## Phase 4: Rollout driver

### Task 4.1: Async `/run` caller

**Objective:** Given a prompt spec, POST N copies in parallel to `agent/run`, collect responses.

**Files:**
- Create: `tinker_nemogym/rollout_driver.py`

**Reference:** `analysis/01` §3.11 (`ng_collect_rollouts`) — ~50-line driver in nemo-gym that already does this. Inspect it before writing.

```python
# tinker_nemogym/rollout_driver.py
from __future__ import annotations
import asyncio
import json
import aiohttp
from typing import Any


async def _call_once(session: aiohttp.ClientSession, url: str, payload: dict) -> dict:
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=600)) as r:
        r.raise_for_status()
        return await r.json()


async def rollout_group(
    agent_url: str,
    prompt_payload: dict,
    group_size: int,
) -> list[dict]:
    """Call nemo-gym agent /run group_size times in parallel. Returns list of
    {reward, response, ...} dicts."""
    url = agent_url.rstrip("/") + "/run"
    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(*[_call_once(session, url, prompt_payload) for _ in range(group_size)])


async def rollout_batch(
    agent_url: str,
    prompts: list[dict],
    group_size: int,
) -> list[list[dict]]:
    """For each prompt, do a group rollout; run all prompts concurrently."""
    return await asyncio.gather(*[rollout_group(agent_url, p, group_size) for p in prompts])


def load_jsonl(path: str) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
```

**Test:** aiohttp-mock or pytest-httpx with a canned `/run` response — verify `rollout_group` returns N items. Commit.

---

## Phase 5: Trainer

### Task 5.1: Trainer class

**Objective:** Wire everything together. Main loop: rollout → datum → fwd_bwd → optim → swap.

**Files:**
- Create: `tinker_nemogym/trainer.py`

**Reference:** `analysis/03` §Canonical call graph. Mirror structure.

```python
# tinker_nemogym/trainer.py
from __future__ import annotations
import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

import tinker
import uvicorn
from tinker import types as tt
from tinker_cookbook.renderers import get_renderer
from tinker_cookbook.tokenizer_utils import get_tokenizer
from tinker_cookbook.hyperparam_utils import get_lr
from tinker_cookbook import model_info

from .config import TinkerNeMoGymConfig
from . import tinker_responses_model as tmodel
from .rollout_driver import rollout_batch, load_jsonl
from .datum_builder import extract_trajectory, build_batch

logger = logging.getLogger(__name__)


class TinkerNeMoGymTrainer:
    def __init__(self, config: TinkerNeMoGymConfig):
        self.cfg = config
        self.service_client: tinker.ServiceClient | None = None
        self.training_client: tinker.LoRATrainingClient | None = None
        self.current_sampling_client: tinker.SamplingClient | None = None
        self.tokenizer = None
        self.renderer = None
        self._server_thread: threading.Thread | None = None
        self.dataset: list[dict] = []

    async def setup(self) -> None:
        # 1. Tokenizer + renderer
        self.tokenizer = get_tokenizer(self.cfg.tinker.base_model)
        renderer_name = model_info.get_recommended_renderer_name(self.cfg.tinker.base_model)
        self.renderer = get_renderer(renderer_name, self.tokenizer)

        # 2. Tinker service + training client (LoRA)
        self.service_client = tinker.ServiceClient()
        self.training_client = await self.service_client.create_lora_training_client_async(
            base_model=self.cfg.tinker.base_model,
            rank=self.cfg.tinker.lora_rank,
        )

        # 3. Initial sampling client
        self.current_sampling_client = await self.training_client.save_weights_and_get_sampling_client_async(
            name="step_0"
        )

        # 4. Initialize + start the nemo-gym model shim in a background thread
        tmodel.init(
            base_model=self.cfg.tinker.base_model,
            tokenizer=self.tokenizer,
            renderer=self.renderer,
        )
        tmodel.set_sampling_client(self.current_sampling_client)
        self._start_server_thread()

        # 5. Load dataset
        self.dataset = load_jsonl(self.cfg.nemogym.dataset_jsonl)
        logger.info(f"Loaded {len(self.dataset)} prompts")

    def _start_server_thread(self) -> None:
        # TODO (implementer): need the actual FastAPI `app` object from
        # tinker_responses_model once Task 3.3 is done.
        from .tinker_responses_model import app  # placeholder
        cfg = uvicorn.Config(
            app,
            host=self.cfg.model_server.host,
            port=self.cfg.model_server.port,
            log_level="warning",
        )
        server = uvicorn.Server(cfg)

        def _run():
            asyncio.run(server.serve())
        t = threading.Thread(target=_run, daemon=True, name="tinker-nemogym-server")
        t.start()
        self._server_thread = t

    async def run(self) -> None:
        await self.setup()
        adam = tinker.AdamParams(
            learning_rate=self.cfg.tinker.learning_rate,
            beta1=self.cfg.tinker.adam_beta1,
            beta2=self.cfg.tinker.adam_beta2,
            eps=self.cfg.tinker.adam_eps,
        )

        for step in range(self.cfg.training.n_steps):
            # Select batch
            start = (step * self.cfg.training.batch_size) % len(self.dataset)
            batch_prompts = [
                self.dataset[(start + i) % len(self.dataset)]
                for i in range(self.cfg.training.batch_size)
            ]

            # 1. Rollout in parallel
            groups_raw = await rollout_batch(
                self.cfg.nemogym.agent_url,
                batch_prompts,
                self.cfg.nemogym.group_size,
            )

            # 2. Convert to RawTrajectories
            trajectory_groups: dict[str, list] = {}
            for i, group in enumerate(groups_raw):
                trajectory_groups[f"p{step}_{i}"] = [extract_trajectory(r) for r in group]

            # 3. Build Datums
            datums, meta = build_batch(trajectory_groups)
            if not datums:
                logger.warning(f"Step {step}: all groups had constant reward, skipping")
                continue

            # 4. fwd_bwd + optim (enqueue both before awaiting — pipelines)
            fwd = await self.training_client.forward_backward_async(
                datums, loss_fn=self.cfg.tinker.loss_fn
            )
            opt = await self.training_client.optim_step_async(adam)
            await fwd.result_async()
            await opt.result_async()

            # 5. Swap sampling client
            self.current_sampling_client = await self.training_client.save_weights_and_get_sampling_client_async(
                name=f"step_{step+1}"
            )
            tmodel.set_sampling_client(self.current_sampling_client)

            logger.info(
                f"Step {step}: mean_reward={meta['mean_reward']:.3f} "
                f"n_datums={meta['n_datums']} dropped={meta['n_dropped_constant']}"
            )

            # 6. Checkpoint
            if (step + 1) % self.cfg.training.save_every == 0:
                path = Path(self.cfg.tinker.checkpoint_dir) / f"step_{step+1}"
                await self.training_client.save_state_async(name=str(path))
```

**Commit:** `feat(trainer): main loop`

---

### Task 5.2: CLI entry point

**Objective:** `launch_training.py --config configs/smoke_single_tool.yaml`

**Files:**
- Create: `launch_training.py` (repo root)
- Create: `tinker_nemogym/cli.py`

```python
# launch_training.py
import asyncio, argparse, logging
from tinker_nemogym.config import TinkerNeMoGymConfig
from tinker_nemogym.trainer import TinkerNeMoGymTrainer

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = TinkerNeMoGymConfig.from_yaml(args.config)
    trainer = TinkerNeMoGymTrainer(cfg)
    asyncio.run(trainer.run())

if __name__ == "__main__":
    main()
```

**Commit:** `feat(cli): launch_training entry`

---

## Phase 6: First env — single_tool_call

### Task 6.1: Dataset + configs

**Objective:** Reuse nemo-gym's `example_single_tool_call` env.

**Files:**
- Create: `configs/smoke_single_tool.yaml`
- Create: `configs/nemogym_single_tool_resources.yaml` (copies from nemo-gym's example)
- Create: `configs/nemogym_single_tool_model.yaml` (points at OUR `TinkerResponsesAPIModel` server)
- Create: `tinker_nemogym/environments/single_tool_call/dataset.jsonl` (or symlink from nemo-gym's)

**Key insight:** nemo-gym's `configs/nemogym_*_model.yaml` normally points at vllm_model or openai_model. We override to point at `http://127.0.0.1:8001` which is OUR server — implementer must verify the exact YAML schema by looking at `nemo-gym/nemo_gym/responses_api_models/vllm_model/configs/*.yaml`.

**`configs/smoke_single_tool.yaml`:**

```yaml
tinker:
  base_model: meta-llama/Llama-3.2-1B
  lora_rank: 32
  learning_rate: 5e-4
  loss_fn: importance_sampling

model_server:
  host: 127.0.0.1
  port: 8001

nemogym:
  agent_url: http://127.0.0.1:11001
  head_url: http://127.0.0.1:11000
  dataset_jsonl: tinker_nemogym/environments/single_tool_call/dataset.jsonl
  group_size: 4
  ng_run_yamls:
    - configs/nemogym_single_tool_resources.yaml
    - configs/nemogym_single_tool_model.yaml

training:
  n_steps: 10
  batch_size: 2
  max_tokens: 256
  temperature: 1.0
  save_every: 5
```

**Commit:** `feat(env): single_tool_call configs`

---

### Task 6.2: Launch script

**Files:**
- Create: `scripts/smoke_single_tool.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source ../.venv/bin/activate

# 1. Start nemo-gym resources + agent (leaves model server spot for us)
ng_run +resources_server=nemogym_single_tool_resources &
NG_PID=$!
trap "kill $NG_PID 2>/dev/null || true" EXIT

# 2. Wait for head server
until curl -sf http://127.0.0.1:11000/health; do sleep 1; done

# 3. Launch trainer (spawns TinkerResponsesAPIModel server internally on :8001)
python launch_training.py --config configs/smoke_single_tool.yaml
```

Commit: `feat(scripts): smoke launcher`

---

### Task 6.3: Integration test

**Objective:** Run `smoke_single_tool.sh` for 2 steps, verify a `step_2` checkpoint exists and no exceptions.

**Files:**
- Create: `tests/integration/test_smoke_single_tool.py`

Mark as `@pytest.mark.slow`; skip without `TINKER_API_KEY`. Commit.

---

## Phase 7: Polish

- **7.1** README.md with architecture diagram, quickstart, env setup
- **7.2** wandb integration (init in trainer.setup, log per-step metrics)
- **7.3** Resume-from-checkpoint support (`tinker.load_state_async`)
- **7.4** serve.py — standalone model server (no training)
- **7.5** `run_logp_steering.sh`-equivalent — multi-process launcher variant
- **7.6** Second env: multi_step example from nemo-gym → validates multi-turn tool-use works end-to-end

---

## Risks & open questions

1. **Tokenizer mismatch:** nemo-gym's agent calls our server via OpenAI-compatible schema (strings). We must tokenize *at the server* using the same tokenizer as Tinker's `base_model`. If the agent injects system/tool messages the renderer doesn't know, tokens will diverge. **Mitigation:** test early with `ProblemEnv`-style simple chat first, then layer tool-use.
2. **Stop sequence handling:** per `tinker-feedback` issue #90, Tinker's `/completions` strips special tokens like `<|eot_id|>` from the response text. We must preserve them in `generation_token_ids` (they're real tokens) even though the decoded text won't contain them.
3. **Logprob sentinel:** We use `1.0` as the "prompt token, don't compute loss" sentinel per tinker-atropos convention. Verify the `importance_sampling` loss actually honors this sentinel — if not, we'll need to zero-out weights via a `weights` tensor instead.
4. **Thread + async:** uvicorn in a `threading.Thread` with its own `asyncio.run()` — there's a real risk of event loop collision with the trainer's loop. **Mitigation:** test early; if it explodes, switch to `uvicorn.Server.run_in_thread()` or spawn a separate subprocess.
5. **Weight swap atomicity:** between `set_sampling_client(new)` and the next `/v1/responses` call, there's a window where an in-flight agent request might still use the old client. For MVP this is fine (occasional sampling from 1-step-old weights). For production we'd need a request-generation-counter.
6. **Python version:** everything pins to 3.12 because nemo-gym requires it.

---

## Implementation order summary

```
Phase 0 → Phase 1 → Phase 2 (unit tests alone = 80% of bridge logic validated)
       → Phase 3 (can unit-test with mock SamplingClient)
       → Phase 4 (can unit-test with mock agent)
       → Phase 5 (integration)
       → Phase 6 (end-to-end smoke)
       → Phase 7 (polish)
```

First stopping point for user feedback: **end of Phase 2**. Datum construction is the riskiest piece — if we get the shifts/dtypes/sentinels wrong, nothing else works. Verifying it in isolation with a mock means Phase 3+ has a stable foundation.

---

**A good plan makes implementation obvious.**

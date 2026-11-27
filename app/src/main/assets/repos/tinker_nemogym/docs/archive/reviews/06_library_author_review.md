# Review #6 — Library-Author Mindset

**Scope.** What would `pip install tinker-nemogym` feel like if we shipped it to
1,000 engineers tomorrow? The prior five passes covered SDK correctness
(01), nemo-gym integration (02), atropos parity (03), engineering hygiene
(04) and whatever the slot-5 pass added. This pass ignores bugs and
semantic correctness (all already green per `ADDRESSED.md`) and instead
audits *public-API ergonomics, extensibility, progressive disclosure,
discoverability, naming, and the pit of success*.

**Reviewer lens.** Kenneth Reitz / Encode (httpx, starlette) / Pallets
(flask, click) — the stuff you'd want on the box before you'd ever
recommend this to a colleague. "Beautiful to use" first.

**Reviewer stance.** We are not shipping. We are rehearsing the post-
release pull-requests we would regret not making.

---

## §0. Library-quality scorecard

| Axis              | Grade  | One-liner                                                                                                   |
|-------------------|:------:|-------------------------------------------------------------------------------------------------------------|
| Onboarding        | **D+** | 15-line hello-world is impossible today. Smoke path is `bash scripts/smoke_single_tool.sh` + sibling-dir install of nemo-gym. |
| API surface       | **D**  | `tinker_nemogym/__init__.py` re-exports *nothing*. `import tinker_nemogym` gives you `__version__` and silence. |
| Extensibility     | **D**  | Zero plugin points. `loss_fn` is `Literal[...]`; datum builder, rollout driver, metric sink are all concrete. |
| Error UX          | **B-** | Config validators land early (good). But `dataset_jsonl` isn't existence-checked; missing `TINKER_API_KEY` surfaces from deep in `tinker.ServiceClient()`; no "did you mean?" hints. |
| Docs              | **B**  | README is dense-but-good. No docs site, no examples/ dir in the classic sense, no CHANGELOG, no cookbook. Docstrings are excellent inside modules — but they're invisible without `help()`. |
| Naming            | **B-** | `TinkerNeMoGymTrainer`, `TinkerNeMoGymConfig`, `tinker_responses_model` — the package name is already `tinker_nemogym`; the prefix is self-redundant. `RawTrajectory` vs `Trajectory`. `_run_step` is documented as "exposed for unit tests" (contradiction). |

**Composite: C+ / B-.** The engine is A-grade; the *library* around it is
at the "internal research tool" tier. Four weekends of polish would
push it to B+/A-.

---

## §1. The "15-line hello world"

### What it looks like today

There is no hello-world. The shortest path for a new user is:

```bash
# 1. clone tinker-nemogym  (not on PyPI)
# 2. clone NVIDIA-NeMo/Gym AS A SIBLING DIR with its own .venv
# 3. poetry install  (in tinker-nemogym)
# 4. export TINKER_API_KEY=...
# 5. bash scripts/smoke_single_tool.sh      # spawns ng_run + trainer
# 6. ctrl-C and then go read the README for 20 minutes
```

Roughly **6 imperative steps, 2 repos, 2 virtualenvs, and one bash
script** before the user sees a single Python symbol they own. The
README acknowledges this ("see `scripts/smoke_single_tool.sh`"); the
README is the contract.

Programmatically, today's 15-line equivalent is:

```python
# ~25 lines + requires a running ng_run stack on :11000 + requires TINKER_API_KEY
import asyncio
from tinker_nemogym.config import (
    TinkerNeMoGymConfig, TinkerConfig, ModelServerConfig,
    NeMoGymConfig, TrainingConfig,
)
from tinker_nemogym.trainer import TinkerNeMoGymTrainer

cfg = TinkerNeMoGymConfig(
    tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct"),
    model_server=ModelServerConfig(),
    nemogym=NeMoGymConfig(
        agent_url=None,                                # auto-discover
        head_url="http://127.0.0.1:11000",
        dataset_jsonl="tinker_nemogym/environments/single_tool_call/dataset.jsonl",
    ),
    training=TrainingConfig(n_steps=2, batch_size=2),
)
asyncio.run(TinkerNeMoGymTrainer(cfg).run())
```

Problems:

1. **4 classes to import** to construct one config. This is the "Django
   settings.py" problem — you can't get past the constructor without a
   tour of the whole schema.
2. **No top-level re-exports.** `from tinker_nemogym import Trainer`
   fails; user must memorize the module tree.
3. **No sync wrapper** — the casual user has to understand that
   `run()` is a coroutine.
4. **The dataset path must exist before the call** — if the user
   mistypes, they get a `FileNotFoundError` at step 6 in
   `setup()`, not at construction.

### What it *should* look like (15 lines, including imports)

```python
# hello.py — train Llama-3.2-1B-Instruct for 2 steps against the single-tool env
import tinker_nemogym as tng

tng.train(
    base_model="meta-llama/Llama-3.2-1B-Instruct",
    env="single_tool_call",               # built-in sample env
    n_steps=2,
    batch_size=2,
    group_size=2,
    # auto-starts the ng_run stack if not already up, and tears it down on exit
    autostart_nemogym=True,
)
# ~8 lines of user code. The other 7 are blank / imports.
```

or the explicit variant:

```python
import tinker_nemogym as tng

cfg = tng.Config.quickstart(env="single_tool_call", n_steps=2)
trainer = tng.Trainer(cfg)
tng.run(trainer)        # sync wrapper around trainer.run()
```

Either of those satisfies the "copy-paste into a REPL, get a green
first step in ≤ 60 s with a fake backend" bar. Neither exists today.

---

## §2. Sixteen checklist items — findings + sketch

> The prior reviews covered correctness. This section is purely about
> the *library surface*. Where a finding overlaps with 01–04, I mark
> it `OVERLAP` and move on fast.

### 2.1 `import tinker_nemogym` — what does a user see?

**Finding.** `tinker_nemogym/__init__.py` is three lines: docstring +
`__version__`. IPython tab-completion against `tinker_nemogym.` shows
`cli, config, datum_builder, environments, rollout_driver, testing,
tinker_responses_model, trainer, utils` — every internal module, no
curated facade. The most important symbols
(`Trainer`, `Config`, `Datum`, `train`) require digging.

**Sketch — proposed `tinker_nemogym/__init__.py`:**

```python
"""tinker-nemogym: train Tinker LoRAs against NeMo-Gym envs."""
from __future__ import annotations

__version__ = "0.2.0"

# --- Stable public API -----------------------------------------------------
from .config import (
    TinkerNeMoGymConfig as Config,
    TinkerConfig,
    NeMoGymConfig,
    ModelServerConfig,
    TrainingConfig,
)
from .trainer import TinkerNeMoGymTrainer as Trainer
from .datum_builder import RawTrajectory as Trajectory, build_datum, build_batch
from ._high_level import train, train_async    # §2.2 below

# --- Sub-namespaces --------------------------------------------------------
from . import testing          # documented: stable public
from . import experimental     # §2.10 — empty for now but reserved

__all__ = [
    "Config", "Trainer", "Trajectory",
    "train", "train_async",
    "build_datum", "build_batch",
    "TinkerConfig", "NeMoGymConfig", "ModelServerConfig", "TrainingConfig",
    "testing", "experimental", "__version__",
]
```

Cost: **5 minutes**. Impact: every tutorial, docstring, and StackOverflow
answer for the next year gets 20 % shorter.

### 2.2 Hello-world onboarding / `train(...)` convenience

**Finding.** No one-line `train()`. Users must:
(1) construct a 4-level nested config,
(2) instantiate a trainer,
(3) know to `asyncio.run(trainer.run())`,
(4) realize they must have a running `ng_run` stack first.

**Sketch — `tinker_nemogym/_high_level.py`:**

```python
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any

from .config import (
    TinkerNeMoGymConfig, TinkerConfig, NeMoGymConfig,
    ModelServerConfig, TrainingConfig,
)
from .trainer import TinkerNeMoGymTrainer


_BUILTIN_ENVS = {
    "single_tool_call": "tinker_nemogym/environments/single_tool_call/dataset.jsonl",
    "multi_step":       "tinker_nemogym/environments/multi_step/dataset.jsonl",
}


def train(
    *,
    base_model: str = "meta-llama/Llama-3.2-1B-Instruct",
    env: str | Path | None = None,
    dataset_jsonl: str | Path | None = None,
    n_steps: int = 10,
    batch_size: int = 4,
    group_size: int = 4,
    learning_rate: float = 5e-4,
    head_url: str = "http://127.0.0.1:11000",
    autostart_nemogym: bool = False,        # §13 — not implemented yet
    **overrides: Any,
) -> dict:
    """Synchronous one-liner. Blocks until training completes.

    Either `env` (name of a built-in) or `dataset_jsonl` (path) is required.
    """
    return asyncio.run(train_async(
        base_model=base_model, env=env, dataset_jsonl=dataset_jsonl,
        n_steps=n_steps, batch_size=batch_size, group_size=group_size,
        learning_rate=learning_rate, head_url=head_url,
        autostart_nemogym=autostart_nemogym, **overrides,
    ))


async def train_async(**kw: Any) -> dict:
    cfg = _compose_config(**kw)
    trainer = TinkerNeMoGymTrainer(cfg)
    await trainer.run()
    return {"n_steps": cfg.training.n_steps}


def _compose_config(env=None, dataset_jsonl=None, **kw) -> TinkerNeMoGymConfig:
    if env is None and dataset_jsonl is None:
        raise ValueError(
            "Pass either env='single_tool_call' (built-in) or "
            "dataset_jsonl='/path/to/data.jsonl'."
        )
    if env is not None and dataset_jsonl is None:
        if env not in _BUILTIN_ENVS:
            raise ValueError(
                f"Unknown built-in env {env!r}; "
                f"valid: {sorted(_BUILTIN_ENVS)}. "
                "Pass dataset_jsonl=... for custom envs."
            )
        dataset_jsonl = _BUILTIN_ENVS[env]
    # ... compose nested config, forwarding overrides via dotted kwargs ...
```

Cost: **30 minutes** (excluding autostart_nemogym). Impact: README
shrinks to "`pip install tinker-nemogym && python -c 'import
tinker_nemogym as tng; tng.train(env=\"single_tool_call\", n_steps=2)'`".

### 2.3 Progressive disclosure

**Finding.** Today's public surface is binary: either run
`tinker-nemogym-train --config foo.yaml`, or read ~600 lines of
`trainer.py` and assemble your own loop. There is no middle tier.

**Proposal.** Three tiers (all exposed at top level):

| Tier      | Entry point                       | When to reach for it                                       |
|-----------|-----------------------------------|------------------------------------------------------------|
| Casual    | `tng.train(env="...", ...)`        | Tutorials, one-off experiments, "does it run?"             |
| Power     | `tng.Trainer(cfg).run()`           | You want a custom YAML / programmatic config.              |
| Custom    | Subclass `tng.Trainer` + override hooks (`_pick_batch`, `_do_rollouts`, `_build_datums_from_rollouts`, `_do_training_step`) | Novel sampling strategy, non-GRPO advantage, custom env. |

The "custom" tier requires the trainer's underscore-prefixed helpers to
become *public overridable hooks*. See §2.4.

### 2.4 Extensibility points

**Finding.** Zero plugin points. Concretely, the user cannot, without
forking:

- **Add a custom loss.** `TinkerConfig.loss_fn: Literal["importance_sampling","ppo","cispo","dro"]`.
  Closed set. Even though `forward_backward_async` accepts any string
  the Tinker backend knows, our pydantic `Literal` rejects new values.
- **Swap the datum builder.** `trainer._build_datums_from_rollouts` calls
  module-level `build_batch` + `extract_trajectory` directly. No `DatumBuilder` protocol.
- **Intercept the shim.** `tinker_responses_model._route_to_tinker` has
  no middleware hook. Users wanting to log prompts/responses or inject
  a guardrail must monkey-patch the module.
- **Plug a non-nemo-gym env.** `rollout_driver` assumes the target speaks
  nemo-gym's `/run` contract. No `Rollout` protocol.
- **Emit metrics to a sink other than wandb.** `_log_wandb_metrics`
  imports wandb directly; no `MetricsSink` ABC.

**Sketch — proposed protocols (`tinker_nemogym/protocols.py`):**

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable, Any
import tinker
from .datum_builder import RawTrajectory


@runtime_checkable
class DatumBuilder(Protocol):
    """Convert a group of raw rollouts into a list of tinker.Datums + meta."""
    def __call__(
        self,
        trajectory_groups: dict[str, list[RawTrajectory]],
        *,
        drop_constant_reward: bool = True,
        max_trainer_tokens: int | None = None,
    ) -> tuple[list[tinker.Datum], dict[str, Any]]: ...


@runtime_checkable
class RolloutDriver(Protocol):
    """Fire batch_size * group_size rollouts against whatever env we talk to."""
    async def rollout_batch(
        self, prompts: list[dict], group_size: int,
    ) -> list[list[dict]]: ...


@runtime_checkable
class MetricsSink(Protocol):
    def log(self, step: int, metrics: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class LossFn(Protocol):
    """Server-side loss name + any client-side per-datum transforms."""
    name: str
    def prepare(self, datum: tinker.Datum, advantage: float) -> tinker.Datum: ...
```

**Sketch — injection points on `Trainer`:**

```python
class Trainer:
    def __init__(
        self,
        config: Config,
        *,
        datum_builder: DatumBuilder | None = None,
        rollout_driver: RolloutDriver | None = None,
        metrics_sinks: list[MetricsSink] | None = None,
        # ...
    ) -> None:
        self._datum_builder = datum_builder or default_datum_builder
        self._rollout_driver = rollout_driver or NeMoGymHTTPDriver(config.nemogym)
        self._metrics_sinks = metrics_sinks or [WandbSink.from_config(config)]
```

Result: A user wanting a ClearML sink writes a 10-line subclass of
`MetricsSink` and passes it in. Today they'd fork `trainer.py`.

### 2.5 Configuration as code

**Finding.** Pydantic is good, but the ergonomics sting:

1. **Every sub-block is required.** `TinkerNeMoGymConfig(...)` without
   `tinker=...` errors. Each of the four nested models has sensible
   defaults except `nemogym.dataset_jsonl`. Make the outer model
   `TinkerNeMoGymConfig()` work with zero args and a sane default for
   dataset.
2. **`dataset_jsonl` typed as `str`.** `Path` would be friendlier and
   `pydantic` handles the coercion. Also: no existence check at
   validate-time. Users discover the typo at step 6 in `setup()`.
3. **No `.quickstart()` classmethod.** `Config.quickstart(env="...")`
   would crystalize the "I just want defaults" path.
4. **`from_yaml` exists; `to_yaml`, `from_dict`, `from_env` don't.**
   Round-tripping and env-var overrides are table stakes.

**Sketch:**

```python
class TinkerNeMoGymConfig(BaseModel):
    tinker:       TinkerConfig       = Field(default_factory=TinkerConfig)
    model_server: ModelServerConfig  = Field(default_factory=ModelServerConfig)
    nemogym:      NeMoGymConfig      = Field(default_factory=NeMoGymConfig)
    training:     TrainingConfig     = Field(default_factory=TrainingConfig)

    @classmethod
    def quickstart(cls, *, env: str = "single_tool_call", **kw) -> "TinkerNeMoGymConfig":
        """Preset for a 2-step fake-friendly smoke run."""
        return cls(
            nemogym=NeMoGymConfig(dataset_jsonl=_BUILTIN_ENVS[env]),
            training=TrainingConfig(n_steps=kw.get("n_steps", 2), batch_size=2),
        )

    def to_yaml(self, path: str | Path) -> None: ...
    @classmethod
    def from_env(cls, prefix: str = "TNG_") -> "TinkerNeMoGymConfig": ...
```

### 2.6 Async-friendliness

**Finding.** The trainer is async-native (`setup`, `run`, `_run_step`).
Good. But:

- `Trainer.run()` is the only public async method. The casual user
  has to know to `asyncio.run(...)` it — there's no sync `train()`
  facade (see §2.2).
- There's no `async def __aenter__` / `__aexit__`. Users who want to
  pair `trainer.setup()` with guaranteed `trainer._cleanup()` today
  must write `try/finally` manually.

**Sketch:**

```python
class Trainer:
    async def __aenter__(self) -> "Trainer":
        await self.setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._cleanup()

# usage
async def main():
    async with tng.Trainer(cfg) as t:
        await t.run_steps(5)
```

### 2.7 Error UX

**Finding.** Three failure modes ranked by painfulness for a new user:

| Failure                                   | Today                                           | Should be                                                                          |
|-------------------------------------------|-------------------------------------------------|------------------------------------------------------------------------------------|
| `TINKER_API_KEY` unset                    | Cryptic auth error 60 s into `setup()`.         | Checked at `Config` validation; `RuntimeError("Set TINKER_API_KEY=... — see docs/install.md")`. |
| `dataset_jsonl` path missing              | `FileNotFoundError` at step 6 in `setup()`.     | `pydantic.ValidationError` at config-load with the resolved absolute path.        |
| `nemogym` stack not running               | `aiohttp.ClientConnectorError` at step 7.       | "Could not reach HeadServer at http://127.0.0.1:11000. Did you start ng_run? See …". |
| `base_model` is a base, not Instruct      | `UserWarning` (good, landed in review 01).      | 👍                                                                                 |
| `n_steps=0`                               | Silent no-op training.                          | `warn("n_steps=0 — setup only, no training")`.                                     |

**Sketch — `config.py` additions:**

```python
class NeMoGymConfig(BaseModel):
    # ...
    @field_validator("dataset_jsonl")
    @classmethod
    def _check_dataset_exists(cls, v: str) -> str:
        if v.startswith(("http://", "https://", "hf://")):
            return v
        p = Path(v)
        if not p.exists():
            raise ValueError(
                f"dataset_jsonl={v!r} does not exist. "
                f"Resolved to {p.resolve()}. "
                "Use a built-in env name via tng.train(env='...') or point "
                "dataset_jsonl at an existing file."
            )
        return v


class TinkerConfig(BaseModel):
    # ...
    @model_validator(mode="after")
    def _check_api_key(self) -> "TinkerConfig":
        import os
        if os.environ.get("TINKER_API_KEY") is None and not _is_fake_mode():
            warnings.warn(
                "TINKER_API_KEY is not set; trainer.setup() will fail on "
                "tinker.ServiceClient(). Set the env var or use "
                "tinker_nemogym.testing.make_fake_tinker_module() for offline dev.",
                UserWarning, stacklevel=2,
            )
        return self
```

Philosophy: *turn the runtime traceback into a validation error*. Every
footgun caught at `Config.from_yaml` time is a minute saved per user
per mistake — probably 50 × 500 new users × 5 minutes = 20 staff-days
across the library's first year.

### 2.8 Naming

**Findings:**

| Today                          | Proposed                       | Why                                                                 |
|--------------------------------|--------------------------------|---------------------------------------------------------------------|
| `TinkerNeMoGymTrainer`         | `Trainer` (re-exported)        | Namespace already says `tinker_nemogym`. `Tinker*NeMoGym*Trainer` is triple-redundant. |
| `TinkerNeMoGymConfig`          | `Config`                       | Same.                                                               |
| `RawTrajectory`                | `Trajectory`                   | "Raw" implies a "Cooked" cousin; there is none. `Trajectory` is the dataclass, `Datum` is the built artifact. |
| `tinker_responses_model` (module) | `shim` or `model_server`    | "tinker_responses_model" reads as a model architecture.             |
| `_route_to_tinker`             | fine as internal.              | —                                                                   |
| `_run_step` (documented public)| `run_step` (real public)       | Either it's private (don't document it as "exposed for tests") or public (drop underscore). |
| `make_fake_tinker_module`      | `fake_tinker()` (context mgr)  | Python convention. Returns a context manager today; name it like one. |
| `TinkerResponsesAPIModel`      | fine — that's nemo-gym's class name. | —                                                                   |
| `set_sampling_client` / `get_sampling_client` (module globals) | `shim.set_client()` / `shim.current_client` | Function names betray the module-global antipattern. An object encapsulating state would name these `client.swap()` / `client.current`. See §2.1 / §3. |

### 2.9 Discoverability

**Finding.** IPython `tng.<TAB>` today: 9 submodules + `__version__`. No
curated dir(). `help(tinker_nemogym)` prints one-line docstring and
that's it. `help(tng.trainer.TinkerNeMoGymTrainer)` is rich (docstring
is actually great).

**Sketch.**

1. Module-level `__all__` (see §2.1) — this drives both
   star-imports and IDE hover.
2. Add a `py.typed` marker file under `tinker_nemogym/` so downstream
   type-checkers see our annotations.
3. Add a README badge: `import tinker_nemogym; help(tinker_nemogym)`
   prints a 10-line cheat-sheet.

```python
# __init__.py
__doc__ = """\
tinker-nemogym — RL trainer for Tinker × NeMo-Gym.

Quick start:
    import tinker_nemogym as tng
    tng.train(env="single_tool_call", n_steps=2)

Power user:
    cfg = tng.Config.from_yaml("my.yaml")
    trainer = tng.Trainer(cfg)
    asyncio.run(trainer.run())

Custom:
    class MyTrainer(tng.Trainer):
        async def _do_rollouts(self, step, batch):
            ...
"""
```

### 2.10 Versioning & stability

**Finding.** `__version__ = "0.0.1"` in `__init__.py` but
`pyproject.toml` says `0.0.1` too. No `experimental` namespace. No
`__deprecated__` wrapper. The `testing` namespace is documented in the
README as public but nothing in the code says *this* namespace is
stable across minor versions.

**Proposal.**

1. Add `tinker_nemogym/experimental/__init__.py` (empty for now but
   reserved — every pre-1.0 feature graduates through here).
2. Add a STABILITY.md at repo root:
   ```
   # Stability contract
   Stable (semver guaranteed):
     * tng.Config, tng.Trainer (public methods), tng.train, tng.Trajectory
     * tng.build_datum, tng.build_batch (pure functions, pinned shape contract)
     * tng.testing.*  (fakes)
   Experimental (may break in any 0.x release):
     * tng.experimental.*
     * Trainer._run_step and underscore-prefixed helpers (overridable but unstable)
   Internal (private; may be refactored silently):
     * tng.rollout_driver, tng.tinker_responses_model  (submodules)
     * Anything _-prefixed
   ```
3. Use `typing.deprecated` (3.13+) or `warnings.deprecated` on any
   symbol that's on its way out.

### 2.11 Testing story for downstream users

**Finding.** `tinker_nemogym.testing` has excellent fakes
(`FakeServiceClient`, `FakeSamplingClient`, `FakeLoRATrainingClient`,
`FakeWandb`, `make_fake_tinker_module`). They're re-exported from
`testing/__init__.py`. But:

- README mentions fakes but does not show them in a code block that a
  downstream user could copy. No `examples/test_with_fakes.py`.
- `make_fake_tinker_module()` monkey-patches `tinker.ServiceClient`
  globally. Elegant trick, but it's not pytest-fixtured for the common
  case; every downstream user reinvents a fixture wrapper.
- No pytest-plugin entry point — a `pytest-tinker-nemogym` plugin
  exposing `fake_tinker` / `fake_wandb` fixtures would be trivial
  (~40 LOC).

**Sketch — add to `tinker_nemogym/testing/__init__.py`:**

```python
import pytest

@pytest.fixture
def fake_tinker():
    """pytest fixture: drop-in fake Tinker SDK for the duration of the test."""
    with make_fake_tinker_module() as ctx:
        yield ctx

@pytest.fixture
def fake_wandb():
    with patch_wandb() as w:
        yield w
```

Then in `pyproject.toml`:

```toml
[tool.poetry.plugins."pytest11"]
tinker_nemogym = "tinker_nemogym.testing"
```

Result: downstream users write `def test_my_trainer(fake_tinker,
fake_wandb): ...` and our fakes are magically injected. This is the
httpx / starlette playbook — and it's the single biggest downstream-UX
win for ~20 minutes of work.

### 2.12 Documentation surface

**Finding.** Great docstrings inside modules, dense/good README, but:

- No docs site (no `mkdocs` / Sphinx config).
- No `examples/` directory in the canonical sense — everything is
  under `scripts/` which reads as "infra tooling" not "usage demos".
- No `CHANGELOG.md`.
- No `CONTRIBUTING.md`.
- Architecture docs are under `docs/` but intermingled with plan/fix-
  log files; a newcomer can't tell which is canonical.

**Proposal.** See §5 below for a full roadmap.

### 2.13 Dependencies

**Finding.** `datum_builder.py` is advertised as "pure" (see its
docstring) but imports `tinker` + `tinker.types`. That means a user
who wants to **validate their trajectory shape in isolation** (e.g. a
CI job that checks their env emits the right fields) has to install
Tinker — which needs a key to even work, per the README.

**Proposal.** Factor the dataclass and the numpy array-construction
logic out of `build_datum`:

```python
# tinker_nemogym/shapes.py  (no tinker dep)
@dataclass
class Trajectory:
    prompt_tokens: list[int]
    response_tokens: list[int]
    response_logprobs: list[float]
    reward: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if len(self.prompt_tokens) < 1: raise ValueError(...)
        if len(self.response_tokens) != len(self.response_logprobs): ...

def compute_advantages(rewards: list[float]) -> list[float]:
    ...   # numpy-only

# tinker_nemogym/datum_builder.py  (imports tinker + shapes)
from .shapes import Trajectory, compute_advantages
def build_datum(traj: Trajectory, advantage: float) -> tinker.Datum: ...
```

Users can then `from tinker_nemogym.shapes import Trajectory` in a
tinker-free environment. Bonus: `datum_builder` becomes ~half as long.

Also, `nemo-gym` as a `{path = "../nemo-gym", develop = true}`
dependency is not `pip install`-compatible. For external users, this is
**the single hardest install-time footgun**. Either:
(a) publish a minimal `nemo-gym-client` subpackage with just the types
we consume, or
(b) make the import optional and document the fallback path (we
already do (b) for `TinkerResponsesAPIModel` the subclass — extend
that discipline to the rest).

### 2.14 The "pit of success"

**Finding.** The smoke config is a faithful YAML; a user copying it
and tweaking `base_model` has a reasonable chance of succeeding. But
landmines lie in wait:

1. **`configs/smoke_single_tool.yaml` hardcodes `base_model:
   meta-llama/Llama-3.1-8B-Instruct`** — the config default is
   `1B`; the *smoke* config says `8B`. A user copying the smoke
   YAML for a "is this thing working?" run burns a lot more compute
   than necessary.
2. **`model_server.port: 8001`** is hardcoded in the config *and*
   in `nemogym_agent.yaml`'s `policy_model` pointer. If the user
   changes one, silently things break. A `port: auto` + discovery
   would remove the footgun.
3. **`dataset_jsonl` is a relative path** anchored to the CWD. Works
   when running from repo root, breaks silently from anywhere else.
   `Path(__file__).parent` relative resolution would fix this.
4. **`drop_constant_reward: true` is the default.** That's correct
   for GRPO but for the `single_tool_call` env which always returns
   reward=1.0, this causes "silently no gradient" runs. The smoke
   config sensibly overrides to `false` — but a user who *doesn't*
   copy the smoke config falls into this trap. Document prominently
   or change the default to `false` and let experienced users opt in.

### 2.15 README quality

**Finding.** The first 100 lines of the README are 40 % prerequisites,
40 % directory listing, 20 % architecture paragraph. For a user who
just `pip install`'d, the cognitive path is:

> "what is nemo-gym … why do I need a sibling directory … what is
> ng_run … what is HeadServer … oh I need TINKER_API_KEY too …"

**Proposal.** Rewrite order:

1. **What** (2 sentences, no architecture).
2. **Hello world** (the 15-line `tng.train(...)` above, runnable
   against fakes — no key, no nemo-gym install required).
3. **Install** (with both pip + poetry paths).
4. **Quickstart with a real Tinker key** (the single_tool smoke bash
   script).
5. **Concepts** (trainer, shim, rollouts, datums, hot-swap — one
   paragraph each).
6. **Architecture diagrams** (last, not first).
7. **Links to docs site.**

### 2.16 CHANGELOG & release hygiene

**Finding.** No `CHANGELOG.md`. No GitHub Releases plan. No version
bump discipline visible (`__version__ = "0.0.1"` static across 50+
commits).

**Proposal.** `CHANGELOG.md` with Keep-A-Changelog format:

```
## [0.2.0] - 2026-04-25
### Added
- Top-level re-exports: tng.Trainer, tng.Config, tng.train, tng.Trajectory
- tng.testing as a pytest plugin (fake_tinker, fake_wandb fixtures)
- Protocols for DatumBuilder, RolloutDriver, MetricsSink
### Changed
- Trainer._run_step → run_step (public, stable-overridable)
### Deprecated
- make_fake_tinker_module() → fake_tinker() (old name kept with warning through 0.3)
```

Plus a `towncrier` or `scriv` setup so every PR lands a newsfragment.

---

## §3. Proposed v0.2 public API

Explicit stability tags — `tng.STABILITY.md` canonical.

### Stable — semver-guaranteed across 0.x

```python
# Imports
from tinker_nemogym import (
    Trainer, Config, Trajectory,
    TinkerConfig, NeMoGymConfig, ModelServerConfig, TrainingConfig,
    train, train_async,
    build_datum, build_batch, compute_advantages,
)
from tinker_nemogym import testing              # full namespace stable
from tinker_nemogym.testing import (
    fake_tinker,                                # context manager (was make_fake_tinker_module)
    FakeSamplingClient, FakeLoRATrainingClient, FakeServiceClient, FakeWandb,
)

# Public methods on Trainer
trainer = Trainer(config, *, datum_builder=None, rollout_driver=None, metrics_sinks=None)
await trainer.setup(start_model_server=True)
await trainer.run()
await trainer.run_steps(n: int)                  # NEW — partial run
await trainer.run_step(step: int) -> dict        # WAS _run_step
async with trainer: ...                          # NEW — __aenter__/__aexit__

# Top-level functions
tng.train(env=..., dataset_jsonl=..., base_model=..., n_steps=..., **kw) -> dict
tng.train_async(...) -> Awaitable[dict]
```

### Experimental — may break in any 0.x minor

```python
from tinker_nemogym.experimental import (
    HydraConfig,            # future: Hydra-backed config layer
    MultiAgentRouter,       # future: routing tables for multi-agent runs
    OnPolicyDistillation,   # future: mirror tinker-atropos's distillation path
)
```

### Internal — private, no stability promise

```python
# Never import from these paths:
tinker_nemogym.rollout_driver            # details of our HTTP driver
tinker_nemogym.tinker_responses_model    # FastAPI shim internals
tinker_nemogym.utils.*                   # free-port picker, etc.
tinker_nemogym._high_level               # implementation of tng.train
anything _-prefixed on Trainer (still overridable but explicitly unstable)
```

**Protocol interfaces (v0.2+):**

```python
from tinker_nemogym.protocols import (
    DatumBuilder, RolloutDriver, MetricsSink, LossFn,
)
```

---

## §4. Progressive disclosure examples

### Tier 1 — the 5-line user (what 80 % of users should write)

```python
import tinker_nemogym as tng

tng.train(env="single_tool_call", n_steps=10, base_model="meta-llama/Llama-3.2-1B-Instruct")
print("done")
```

What they see: a progress bar, 10 log lines, mean_reward climbing.
What they never have to know: that there's a FastAPI shim, that
rollouts are POSTs to `/run`, that datums are a thing, that
`asyncio.run` exists.

### Tier 2 — the 20-line power user

```python
import asyncio
import tinker_nemogym as tng

cfg = tng.Config.from_yaml("configs/my_run.yaml")
# Programmatic overrides after YAML:
cfg.training.n_steps = 200
cfg.tinker.wandb_project = "my-exp-2026-04"
cfg.nemogym.group_size = 8

async def main():
    async with tng.Trainer(cfg) as trainer:
        for step in range(cfg.training.n_steps):
            metrics = await trainer.run_step(step)
            if metrics["mean_reward"] > 0.95:
                print(f"Early stop at step {step}")
                break

asyncio.run(main())
```

What they see: full control over the loop, the metrics dict, YAML +
code composition. What they still don't touch: datum building, shim
internals, rollout driver internals.

### Tier 3 — the 100-line full customizer

```python
"""Custom trainer: reward-model-weighted advantages + ClearML sink + MCP tools."""
from __future__ import annotations
import asyncio
import tinker_nemogym as tng
from tinker_nemogym.protocols import DatumBuilder, MetricsSink
from tinker_nemogym.shapes import Trajectory, compute_advantages
import tinker


# --- custom datum builder ---------------------------------------------------
class RMWeightedDatumBuilder:
    """Reweight GRPO advantages by an external reward-model score."""
    def __init__(self, rm_client):
        self._rm = rm_client

    def __call__(self, trajectory_groups, *, drop_constant_reward=True, max_trainer_tokens=None):
        datums, meta = [], {"mean_reward": 0.0, "n_datums": 0, "n_dropped_constant": 0}
        for group in trajectory_groups.values():
            rewards = [t.reward for t in group]
            rm_scores = [self._rm.score(t.prompt_tokens, t.response_tokens) for t in group]
            blended = [0.7*r + 0.3*s for r, s in zip(rewards, rm_scores)]
            if drop_constant_reward and len(set(blended)) <= 1:
                meta["n_dropped_constant"] += 1
                continue
            advs = compute_advantages(blended)
            for traj, adv in zip(group, advs):
                datums.append(tng.build_datum(traj, advantage=adv))
        meta["n_datums"] = len(datums)
        return datums, meta


# --- custom metrics sink ----------------------------------------------------
class ClearMLSink:
    def __init__(self, project: str, task: str):
        from clearml import Task
        self._task = Task.init(project_name=project, task_name=task)

    def log(self, step: int, metrics: dict) -> None:
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                self._task.get_logger().report_scalar("train", k, v, step)

    def close(self) -> None:
        self._task.close()


# --- subclass to intercept rollouts -----------------------------------------
class MyTrainer(tng.Trainer):
    async def _do_rollouts(self, step, batch_prompts):
        # Add MCP tool-context to every prompt before firing rollouts
        enriched = [{**p, "tools": self._load_mcp_tools()} for p in batch_prompts]
        return await super()._do_rollouts(step, enriched)

    def _load_mcp_tools(self):
        return [{"name": "web_search", "description": "..."}]


# --- compose and run --------------------------------------------------------
async def main():
    cfg = tng.Config.from_yaml("configs/custom.yaml")
    rm = MyRewardModel.load("rm.pt")

    async with MyTrainer(
        cfg,
        datum_builder=RMWeightedDatumBuilder(rm),
        metrics_sinks=[
            tng.testing.WandbSink.from_config(cfg) if cfg.tinker.wandb_project else None,
            ClearMLSink(project="rl", task="custom-run"),
        ],
    ) as trainer:
        await trainer.run()


asyncio.run(main())
```

Four extensibility knobs used: subclass hook, `DatumBuilder` protocol,
`MetricsSink` protocol, programmatic config. None of this requires a
fork.

---

## §5. Documentation roadmap

Target: `docs.tinker-nemogym.dev` (or a GitHub Pages MkDocs site)
structured as:

| Page                             | Audience   | Content                                                                                              |
|----------------------------------|------------|------------------------------------------------------------------------------------------------------|
| `index.md`                       | Everyone   | What it is, why, the 5-line hello world.                                                              |
| `install.md`                     | New user   | pip, poetry, the nemo-gym sibling-dir dance, TINKER_API_KEY, `tng.testing.fake_tinker` offline path. |
| `tutorial/01-hello-world.md`     | New user   | Run the 5-line example end to end (against fakes, no key required).                                  |
| `tutorial/02-real-training.md`   | New user   | Same but against live Tinker + live ng_run.                                                          |
| `tutorial/03-custom-env.md`      | Power user | Wire a brand-new nemo-gym resources server + agent into a `tng.train` run.                           |
| `tutorial/04-custom-loss.md`     | Power user | Pass `loss_fn="ppo"` / plug your own `LossFn` protocol.                                              |
| `concepts/trainer.md`            | Power user | What `Trainer.run` does, 1 diagram, the metric dict.                                                 |
| `concepts/shim.md`               | Power user | Hot-swap, thread safety, what "route_to_tinker" does.                                                |
| `concepts/datum.md`              | Power user | Why `PROMPT_LOGPROB_SENTINEL=1.0`, shape invariants, bring-your-own-datum-builder.                   |
| `concepts/rollouts.md`           | Power user | nemo-gym `/run` contract, `group_size`, how we parallelize.                                          |
| `cookbook/resume.md`             | Everyone   | `resume_from_checkpoint` — save & reload across runs.                                                |
| `cookbook/wandb.md`              | Everyone   | Enable / pick project / custom metric keys.                                                          |
| `cookbook/fake-tinker.md`        | Dev        | CI-friendly offline pipeline w/ `fake_tinker` fixture.                                               |
| `cookbook/multi-agent.md`        | Power user | Routing table across several nemo-gym agents (experimental).                                         |
| `api/config.md`                  | Reference  | Pydantic schema, every field, every default, every validator.                                        |
| `api/trainer.md`                 | Reference  | Every public method + docstring (auto-gen via mkdocstrings).                                         |
| `api/protocols.md`               | Reference  | `DatumBuilder`, `RolloutDriver`, `MetricsSink`, `LossFn`.                                            |
| `api/testing.md`                 | Reference  | Every fake, every fixture.                                                                           |
| `stability.md`                   | Everyone   | The §3 table above.                                                                                  |
| `changelog.md`                   | Everyone   | Auto-generated from `CHANGELOG.md`.                                                                  |
| `contributing.md`                | Dev        | How to run tests, how to add a review, the review pipeline.                                          |

Tooling: `mkdocs-material` + `mkdocstrings[python]`. Build in CI,
deploy on tag. Estimated 2 engineer-days for the initial site; 1 hour
per page after.

---

## §6. Top-10 quick wins (each < 30 min)

Ordered by impact / effort ratio.

1. **Re-export the public API in `__init__.py`** (§2.1). 5 min.
   Single biggest onboarding win. Every tutorial gets shorter today.

2. **Add `py.typed` marker file**. 30 s.
   Unblocks downstream type-checking.

3. **Add `Config.quickstart(env="single_tool_call")` classmethod** (§2.5). 10 min.
   Removes the 4-sub-block incantation from the hello-world.

4. **Add `tng.train(...)` top-level sync wrapper** (§2.2). 20 min.
   5-line hello-world becomes possible; `asyncio.run` disappears.

5. **Pydantic `@field_validator` for `dataset_jsonl` existence** (§2.7). 10 min.
   Converts a mid-run `FileNotFoundError` into a config-time error
   with the resolved path. One-line delta.

6. **`pytest11` entry-point exposing `fake_tinker` + `fake_wandb` fixtures** (§2.11). 15 min.
   Downstream users gain `def test_foo(fake_tinker): ...` for free.

7. **Add `async with Trainer(cfg) as trainer:` support** (§2.6). 10 min.
   Lifecycle correctness becomes automatic; matches every Python
   async library convention.

8. **Create `CHANGELOG.md` + `STABILITY.md`** (§2.10, §2.16). 15 min.
   Sets the contract for every future release.

9. **Rewrite README's first 100 lines with hello-world on top** (§2.15). 25 min.
   New-user activation rate — probably the second-biggest single win
   after §2.1.

10. **Rename `_run_step` → `run_step` (keep alias for one release)** (§2.8, §2.4). 10 min.
    A documented public hook can no longer be underscore-prefixed.
    Subclass users gain a first-class extension point.

**Total:** ≈ 2.5 hours. Post-sprint, the grade would move from `C+/B-`
to roughly `B+`.

---

## Appendix — what this review deliberately did *not* cover

- SDK correctness (review 01).
- nemo-gym protocol fidelity (review 02).
- atropos parity (review 03).
- Type safety / resource leaks / security (review 04).
- Test coverage shape (review 04 §2).
- Any finding already listed in `ADDRESSED.md`.

If a topic in §2 sounds like it overlaps an earlier review, I have
either explicitly layered a library-API lens over it (e.g. §2.7 error
UX vs. review 04's error handling), or the overlap is small and noted
as `OVERLAP`.

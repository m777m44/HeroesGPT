# Review #5 — FAANG-Scale Architectural Review

**Repo:** `tinker-nemogym` (HEAD, post-reviews-01..04 fix-up sprint)
**Reviewer pass:** 5 of 5 — **Staff SWE, Meta/Google-scale monorepo lens**
**Date:** 2026-04-22
**Ground rules:**
- Reviews 01–04 + `ADDRESSED.md` were read first; findings already fixed there are *not* re-raised here (the `_run_step` split, Pydantic range validators, path-traversal guards, `ClientSession` hoist, conftest reset, CI, mypy config, etc. are all taken as given).
- This review is a **critique only** — no source was modified.
- The lens is: *"if this landed in `fbsource` / `google3` in front of 100 engineers who would vendor pieces of it, what would phab / critique actually block?"*

---

## §0. FAANG-Standards Scorecard

| Axis | Grade | One-line justification |
|---|:-:|---|
| **Module boundaries** | **C+** | 6 first-party modules with mostly single responsibilities (`datum_builder` pure, `rollout_driver` pure) — **but** `trainer.py` (640 LoC) owns setup + rollouts + training + checkpointing + wandb + server thread-lifecycle + URL discovery, and `tinker_responses_model.py` (498 LoC) mixes a module-level FastAPI app + hot-swap state store + renderer init + optional nemo-gym subclass in one file. Nothing circular, but the "one trainer class that does everything" will not survive contact with a second backend or a second environment family. |
| **Dependency injection** | **D+** | `TinkerNeMoGymTrainer.__init__` takes exactly **one** argument (`config`) and constructs every collaborator inside `setup()` (`tinker.ServiceClient()` at `trainer.py:134`, tokenizer/renderer at `:120-122`, `aiohttp.ClientSession` at `:210`, uvicorn at `:246`, module-global `tmodel.set_sampling_client` at `:183, :529`). There is *no* seam for a fake `ServiceClient` in production code — `fakes.py:409` monkey-patches `tinker.ServiceClient = FakeServiceClient` at module scope, which is the exact anti-pattern that forces `conftest.py` autouse resets. A 100-engineer codebase would reject this at CR. |
| **Interface segregation** | **D** | One `TinkerNeMoGymTrainer` class exposes `setup`, `run`, `_run_step` (public-in-practice, tests reach in), `_do_rollouts`, `_build_datums_from_rollouts`, `_do_training_step`, `_start_server_thread`, `_maybe_init_wandb`, `_log_wandb_metrics`, `_finish_wandb`, `_maybe_save_checkpoint`, `_cleanup`, `_pick_batch` — **13 methods, 6 distinct responsibilities** (rollout, datum-building, training step, checkpoint lifecycle, wandb lifecycle, server lifecycle). Reviews 01–04 split `_run_step` cleanly (good), but did not split the **class**. |
| **Public API discipline** | **C** | `__all__` present in 7/8 modules (missing in `tinker_nemogym/__init__.py` — it only exports `__version__`). No `py.typed` marker file, so downstream users never get our annotations. Leading underscores used inconsistently: `_route_to_tinker` is in `__all__` (`tinker_responses_model.py:495` — leaking an internal), `_safe_resolve_path` is in `__all__` on `config.py:193`, `_call_once` is in `__all__` on `rollout_driver.py:238`. Either these are public (drop the underscore) or internal (remove from `__all__`). |
| **Breaking-change discipline** | **D** | `TinkerNeMoGymConfig` has no `schema_version` field. Any rename or removal of a field in `TinkerConfig` / `NeMoGymConfig` silently breaks every user YAML on the planet with a Pydantic `missing` error, with no migration hook. No `@deprecated` on anything, no `warnings.warn("use X instead", DeprecationWarning)` anywhere in the tree (grepped). `__version__ = "0.0.1"` in `__init__.py:3` + `version = "0.0.1"` in `pyproject.toml:3` are already **split sources of truth** — the CLI resolves via `importlib.metadata` which means `tinker_nemogym.__version__` can drift from the installed dist version. |
| **Testability at scale** | **B-** | 160+ hermetic tests, FakeSamplingClient / FakeLoRATrainingClient / FakeServiceClient / FakeWandb, conftest autouse reset — all excellent. **But:** module-global `_current_sampling_client` + `_tokenizer` + `_renderer` + `_model_config` in `tinker_responses_model.py` means you cannot run two `TinkerNeMoGymTrainer` instances in the same process (pytest-xdist is documented-unsafe in Review 04 §5). `fakes.py:409` monkey-patching `tinker.ServiceClient` globally is a test-isolation hazard. No DI point for the service client → tests have to reach into a module global to substitute it. |
| **Standardization / Python conventions** | **B** | pyproject-first, poetry-managed, ruff (E/F/I/UP/B), mypy configured, 3.12 pinned, `from __future__ import annotations` on every module, `logging.getLogger(__name__)` everywhere, `importlib.metadata.version()` for `--version`, no `print()` in production code. Flat (not `src/`) layout — debatable at FAANG scale, but defensible for a single-package library. **Missing:** `py.typed` marker, `CODEOWNERS`, Protocol-based seams, `NOTICE` file for Apache-2.0 transitive deps, entry-point **plugin hooks** (e.g., for alternate envs / renderers / loss functions). |

**Overall:** **C+**. Production-usable inside one team's sandbox, but wouldn't clear a phab / critique review at Meta/Google for inclusion in a shared monorepo without a round of SOLID-level refactors (see §3 roadmap). The MVP is *working* and *tested* — the architectural debt is all around **extensibility** and **process/monorepo ergonomics**, not correctness.

---

## §1. Executive Summary — "Would-Block-CR-at-Meta" list

Ranked by how quickly a staff reviewer would stamp *"please fix before land"*:

1. **[BLOCK]** **No DI seam for `tinker.ServiceClient`.** `TinkerNeMoGymTrainer.setup` constructs `tinker.ServiceClient()` inline at `trainer.py:134`. Test fakes work by globally monkey-patching `tinker.ServiceClient = FakeServiceClient` (`fakes.py:409`) — that is the code smell that a DI-accepting ctor (`Trainer(cfg, *, service_client_factory=tinker.ServiceClient)`) would eliminate. A staff reviewer will not accept a library that requires monkey-patching an imported symbol to test.
2. **[BLOCK]** **`tinker_responses_model` is four modules masquerading as one.** It holds (a) a stateful hot-swap primitive, (b) a renderer-init facade, (c) FastAPI route handlers, (d) an optional nemo-gym subclass — **all at module scope with four globals** (`_current_sampling_client`, `_tokenizer`, `_renderer`, `_model_config`). The fact that `conftest.py` must autouse-reset these globals (`tests/conftest.py:17-29`) is the existence proof that the module is a singleton shrink-wrapped around a class that should exist. Extract a `class SamplerRegistry` and move the app to a factory `make_app(registry)`.
3. **[BLOCK]** **`TinkerNeMoGymTrainer` is a god object.** 6 responsibilities, 13 methods, 640 LoC. Split into `Trainer` (owns `_run_step` loop), `Rollouter` (owns agent HTTP), `ServerLifecycle` (owns uvicorn thread + shim wiring), `CheckpointManager` (owns `_maybe_save_checkpoint` + resume), `MetricsSink` (wandb + structured logging). Each gets its own test file and its own contract.
4. **[MAJOR]** **No `TinkerNeMoGymError` base class.** Every failure today is `RuntimeError` / `ValueError` / `KeyError` / raw `tinker.*Error`. A downstream `except TinkerNeMoGymError` idiom is impossible. See §2 #15 — this is a 60-LOC ask and it unlocks taxonomic logging and monitoring.
5. **[MAJOR]** **Config has no `schema_version`.** `TinkerNeMoGymConfig.from_yaml(...)` (`config.py:180-184`) accepts any dict. In 6 months a field rename = silent break for every in-the-wild YAML. Add `schema_version: Literal[1] = 1` at the root and a `migrate_v0_to_v1` hook. Cheap insurance.
6. **[MAJOR]** **Public vs internal surface leaks.** `_route_to_tinker`, `_call_once`, `_safe_resolve_path` are all `_leading_underscore` **and** in `__all__` — contradictory signal. Pick a story: drop the underscore and make them stable, or drop them from `__all__`. Also: `tinker_nemogym/__init__.py` re-exports *nothing*; downstream users must spell `from tinker_nemogym.trainer import TinkerNeMoGymTrainer`. At scale this is a refactor tripwire.
7. **[MAJOR]** **No `Protocol` / ABC for the sampler or the agent.** `tinker.SamplingClient` is threaded through unmodified; the *nemo-gym agent* is a bare URL. Neither has a contract in our code. To hypothetically swap Tinker for another serverless trainer we'd have to rewrite `trainer.py`, `tinker_responses_model.py`, `datum_builder.py`, and `testing/fakes.py`. A thin `class SamplerProtocol(Protocol): async def sample_async(...) -> SampleResult` would sever that coupling.
8. **[MAJOR]** **No `py.typed`.** Downstream `mypy` won't see our annotations despite the effort spent putting them in. One file, 0 bytes, unlocks the whole ecosystem benefit.
9. **[MAJOR]** **Version string drift.** `__version__` in `tinker_nemogym/__init__.py:3` ≠ `importlib.metadata.version(...)` in `cli.py:36`. Canonical pattern: `__version__` resolves from `importlib.metadata` with a dev-fallback. Single source of truth.
10. **[MAJOR]** **Metrics / log schema is unversioned and unstructured.** `trainer.py:560-568` hard-codes `train/mean_reward`, `train/loss`, `train/n_datums`, `train/sampler_version` — good keys, but a downstream dashboard has no declared contract. No TypedDict, no Pydantic Metrics model, no JSON structured log. A dashboard that breaks on a rename has no way to know *what* it broke against.
11. **[MINOR]** **No `entry_points` plugin hook.** `loss_fn: Literal["importance_sampling","ppo","cispo","dro"]` (`config.py:67`) is a closed set; at scale, users want to register a custom loss (or a custom environment family) without forking. `[project.entry-points."tinker_nemogym.loss_fns"]` unlocks that.
12. **[MINOR]** **Global `uvicorn.run(asyncio.run(server.serve()))` in daemon thread** (`trainer.py:252`) creates a **nested event loop** when tests / users instantiate a trainer from within an already-running event loop. Swap to `loop.create_task(server.serve())` on the trainer's loop, or document the limitation.
13. **[MINOR]** **Circular-adjacent dependency: `trainer → tmodel` globals.** `trainer.py` imports `tmodel` as a module and mutates its globals (`tmodel.init(...)`, `tmodel.set_sampling_client(...)`). `tmodel` doesn't import `trainer`, so it's not a cycle *today*, but we've traded dependency cycles for temporal coupling (tmodel.init *must* happen before any request). A `SamplerRegistry(tokenizer, renderer)` dependency-injected into both sides eliminates the ordering contract.
14. **[MINOR]** **No `CODEOWNERS`, no `SECURITY.md`, no `CHANGELOG.md`.** Minor at MVP stage; standard at FAANG.
15. **[MINOR]** **Flat package layout.** `src/` layout is the Python-Packaging-Authority recommendation for libraries; it catches "accidentally importing from checkout root instead of installed wheel" bugs. Optional but conventional.

---

## §2. Per-Checklist-Item Findings

### 1. Module Boundaries

**Findings.**
- `datum_builder.py` — pure functions, no side effects, no I/O. **A.** Could live in `interfaces/` as-is and be vendored without the rest.
- `rollout_driver.py` — pure async I/O, no Tinker dep, no config dep. **A-**. Leaks `_call_once` via `__all__` — that's an internal.
- `config.py` — Pydantic-only, no runtime imports from sibling modules. **A.**
- `utils/process.py` — stdlib only, no Tinker / nemo-gym deps. **A.**
- `tinker_responses_model.py` — **C**. Four responsibilities in one file; module globals.
- `trainer.py` — **C-**. Six responsibilities in one class (see §2.3).
- `testing/fakes.py` — 476 LoC. Works, but should be a subpackage (`testing/sampling.py`, `testing/training.py`, `testing/service.py`, `testing/wandb.py`) for downstream import granularity.

**Concrete proposal — split `tinker_responses_model.py`:**

```
tinker_nemogym/
  serving/
    __init__.py           # re-exports for back-compat
    sampler_registry.py   # class SamplerRegistry: set/get/init with a threading.Lock
    app.py                # make_app(registry: SamplerRegistry) -> FastAPI
    routes.py             # chat_completions_endpoint, responses_endpoint, _route_to_tinker
    middleware.py         # _propagate_session_cookie
    nemogym_subclass.py   # optional TinkerResponsesAPIModel (conditional import)
```

And the trainer injects instead of mutating globals:

```python
# trainer.py
from .serving import SamplerRegistry, make_app

class TinkerNeMoGymTrainer:
    def __init__(self, config, *, sampler_registry: SamplerRegistry | None = None):
        self._sampler_registry = sampler_registry or SamplerRegistry()
        ...
    async def setup(self, ...):
        self._sampler_registry.init(base_model=..., tokenizer=..., renderer=...)
        self._sampler_registry.set(self.current_sampling_client)
        if start_model_server:
            app = make_app(self._sampler_registry)
            # uvicorn.run(app, ...)
```

### 2. Dependency Injection

**Findings.**
- `TinkerNeMoGymTrainer.__init__(config)` — single arg, constructs **every** collaborator in `setup()`. No seam for:
  - `tinker.ServiceClient` → (`trainer.py:134`)
  - Tokenizer / renderer → (`trainer.py:120-122`)
  - `aiohttp.ClientSession` → (`trainer.py:210`)
  - `uvicorn.Server` → (`trainer.py:246`)
  - `wandb` → (`trainer.py:220` lazy import + `wandb.init`)
  - The FastAPI app → (lives as module global `tmodel.app`, `tinker_responses_model.py:196`)
- Evidence that this is a real problem: `fakes.py:409` does `tinker.ServiceClient = FakeServiceClient` at module scope. This is how the production code gets faked — by mutating an imported third-party module.
- `tmodel.init(base_model, tokenizer, renderer)` at `trainer.py:178-182` **mutates** 3 module globals in `tinker_responses_model`. That's the smell.

**Concrete proposal — constructor injection with factories:**

```python
from collections.abc import Awaitable, Callable
from typing import Protocol

class ServiceClientFactory(Protocol):
    def __call__(self) -> "tinker.ServiceClient": ...

class HTTPSessionFactory(Protocol):
    def __call__(self) -> "aiohttp.ClientSession": ...

class TinkerNeMoGymTrainer:
    def __init__(
        self,
        config: TinkerNeMoGymConfig,
        *,
        service_client_factory: ServiceClientFactory = tinker.ServiceClient,
        http_session_factory: HTTPSessionFactory = aiohttp.ClientSession,
        sampler_registry: SamplerRegistry | None = None,
        wandb_module: Any | None = None,  # injected to avoid lazy-import guessing in tests
    ) -> None:
        self.cfg = config
        self._sc_factory = service_client_factory
        self._http_factory = http_session_factory
        self._sampler_registry = sampler_registry or SamplerRegistry()
        self._wandb = wandb_module  # None == lazy-import-or-disabled

    async def setup(self, start_model_server: bool = True) -> None:
        self.service_client = self._sc_factory()
        ...
        self._http_session = self._http_factory()
```

Tests stop monkey-patching and instead pass `service_client_factory=lambda: FakeServiceClient()`. Production code stays identical (factory defaults are live).

### 3. Interface Segregation

**Findings.**
`TinkerNeMoGymTrainer` today:

| Responsibility | Evidence | LoC budget |
|---|---|---|
| Setup (tokenizer/renderer, Tinker clients, sampler, dataset, agent URL, HTTP session) | `setup()` at :105-210 | 105 |
| RL loop / step orchestration | `run()` / `_run_step()` / `_pick_batch()` at :280-354 | 75 |
| Rollout | `_do_rollouts()` at :356-383 | 28 |
| Datum build + metrics assembly | `_build_datums_from_rollouts()` at :385-446 | 62 |
| Training step (fwd_bwd + optim + hot-swap) | `_do_training_step()` at :448-543 | 96 |
| Wandb lifecycle | `_maybe_init_wandb()` / `_log_wandb_metrics()` / `_finish_wandb()` at :212-231, :545-585 | 60 |
| Server lifecycle (uvicorn thread) | `_start_server_thread()` / `_cleanup()` at :233-274, :624-637 | 55 |
| Checkpoint save | `_maybe_save_checkpoint()` at :587-622 | 36 |

**Concrete proposal — extract 4 roles, keep `Trainer` as the composition root:**

```python
class Rollouter:
    """Owns: agent URL, http session, rollout_batch call, retry policy."""
    def __init__(self, cfg, *, http_session_factory=aiohttp.ClientSession): ...
    async def setup(self): ...
    async def rollout(self, step: int, prompts: list[dict]) -> list[list[dict]] | None: ...
    async def close(self): ...

class TrainingBackend:
    """Owns: tinker service_client, training_client, fwd_bwd+optim+hot-swap."""
    def __init__(self, cfg, registry: SamplerRegistry, *, service_client_factory=tinker.ServiceClient): ...
    async def setup(self): ...
    async def step(self, datums: list[tinker.Datum]) -> StepResult: ...
    async def save_checkpoint(self, step: int) -> str | None: ...

class ServingStack:
    """Owns: FastAPI app + uvicorn thread + sampler registry wiring."""
    def __init__(self, cfg, registry: SamplerRegistry): ...
    def start(self): ...
    def stop(self): ...

class MetricsSink:
    """Owns: wandb lifecycle + structured-log emission. Protocol-shaped."""
    def log(self, step: int, metrics: StepMetrics) -> None: ...
    def close(self) -> None: ...

class TinkerNeMoGymTrainer:
    """Composition root. ~200 LoC total."""
    def __init__(self, cfg, *, rollouter=None, backend=None, serving=None, sink=None): ...
    async def run(self):
        for step in range(...):
            prompts = self._pick_batch(step)
            groups = await self.rollouter.rollout(step, prompts)
            datums, metrics = build_datums_from_rollouts(step, groups, cfg=self.cfg)
            result = await self.backend.step(datums)
            self.sink.log(step, {**metrics, **result.to_dict()})
```

Each of the four roles is independently unit-testable. The `Trainer` orchestrator becomes ~150 LoC — comprehensible in one sitting.

### 4. Public vs Internal API

**Findings.**
- `tinker_nemogym/__init__.py` exports only `__version__`. No `TinkerNeMoGymConfig`, no `TinkerNeMoGymTrainer`, nothing. Downstream users must know the internal module paths. **Problem.**
- `__all__` inconsistencies:
  - `tinker_responses_model.py:490-498`: `__all__` includes `_route_to_tinker` (should be private) and both `TinkerResponsesAPIModel` (nemo-gym optional) and `init` (public facade).
  - `config.py:187-194`: `__all__` includes `_safe_resolve_path` — if it's public, rename; if not, drop.
  - `rollout_driver.py:232-239`: `__all__` includes `_call_once` — same.
  - `testing/fakes.py`: has no `__all__`, only `testing/__init__.py` does.
- `trainer.py:640`: `__all__ = ["TinkerNeMoGymTrainer"]` — but the class has 12 underscore-prefixed methods that tests call (`_run_step` is documented in its docstring as "exposed for unit tests", `trainer.py:54`). That's the opposite of private.
- No `py.typed` marker file in the package → downstream `mypy --strict` will skip us even though we have annotations.

**Concrete proposal — package API contract:**

```python
# tinker_nemogym/__init__.py
"""tinker-nemogym: bridge between NeMo-Gym RL environments and Tinker."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tinker-nemogym")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"

from .config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
from .errors import (  # new; see §15
    ConfigError,
    RolloutError,
    ShimError,
    TinkerNeMoGymError,
    TrainingError,
)
from .trainer import TinkerNeMoGymTrainer

__all__ = [
    "TinkerNeMoGymTrainer",
    "TinkerNeMoGymConfig",
    "TinkerConfig",
    "ModelServerConfig",
    "NeMoGymConfig",
    "TrainingConfig",
    "TinkerNeMoGymError",
    "ConfigError",
    "TrainingError",
    "RolloutError",
    "ShimError",
    "__version__",
]
```

Add an empty `tinker_nemogym/py.typed`. In each module, drop the underscore-prefixed names from `__all__`; the underscore already communicates "not public".

### 5. Breaking-Change Discipline

**Findings.**
- `TinkerNeMoGymConfig.from_yaml(path)` at `config.py:180-184` calls `cls.model_validate(data)` with no schema-version awareness. If a user's config is from v0.0.1 and we rename `nemogym.agent_url` → `nemogym.agent_base_url` in v0.1, every YAML breaks with a Pydantic `missing` error and no automatic upgrade.
- Zero `warnings.warn(..., DeprecationWarning)` and zero `@deprecated` (a `typing_extensions`-compatible decorator) in the tree.
- `__version__` is frozen at `"0.0.1"` in source (`__init__.py:3`). `pyproject.toml:3` is also `"0.0.1"`. The CLI picks it up via `importlib.metadata` (`cli.py:36`). Three places, no single source.
- No `CHANGELOG.md`.

**Concrete proposal — versioned config + migration registry:**

```python
# config.py
from typing import Literal

class TinkerNeMoGymConfig(BaseModel):
    schema_version: Literal[1] = 1
    tinker: TinkerConfig
    model_server: ModelServerConfig
    nemogym: NeMoGymConfig
    training: TrainingConfig

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TinkerNeMoGymConfig":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        data = _migrate(data)  # new
        return cls.model_validate(data)

_MIGRATORS: dict[int, Callable[[dict], dict]] = {}

def _migration(from_v: int):
    def deco(fn):
        _MIGRATORS[from_v] = fn
        return fn
    return deco

def _migrate(data: dict) -> dict:
    v = data.get("schema_version", 0)  # 0 == pre-versioned
    while v < 1:
        fn = _MIGRATORS.get(v)
        if fn is None:
            raise ConfigError(
                f"no migrator from schema_version={v} to {v + 1}; "
                "please upgrade your config manually"
            )
        data = fn(data)
        v += 1
        data["schema_version"] = v
    return data

@_migration(from_v=0)
def _v0_to_v1(data: dict) -> dict:
    # Example: older configs used `agent_url` at top level; move into nemogym.
    if "agent_url" in data:
        data.setdefault("nemogym", {})["agent_url"] = data.pop("agent_url")
    return data
```

And ship `docs/CONFIG_MIGRATIONS.md` describing the schema_version history.

### 6. Testability

**Findings.**
- 160+ tests pass hermetically in ~30 s. Strong.
- `conftest.py` autouse `_reset_for_tests()` (Review 04 §5.2-fixed) papers over the module-global issue. This is a symptom, not a cure.
- `fakes.py:409`: `tinker.ServiceClient = FakeServiceClient` — monkey-patches the third-party module **globally**. Any test that runs in the same interpreter as one that forgets to restore will see the fake. `contextlib.contextmanager` version (`make_fake_tinker_module`, lines 364-425) does restore, but the pattern is still fragile.
- `_run_step` is deterministically testable *now* (Review 04 §5.2 confirmed) — but only by constructing a whole trainer with fakes, not by testing sub-methods in isolation. `_do_training_step` in particular has 8 exception branches (`:475-507`) that are hard to exercise without a mock that can selectively raise `tinker.RateLimitError`.
- `uvicorn.Server` runs in a daemon thread with its own event loop (`trainer.py:249-252`). Test startup is the main bottleneck (3-5s per server spin-up).

**Concrete proposal — layered seams:**

1. Inject `service_client_factory` into `TinkerNeMoGymTrainer` (see §2). Eliminates the `tinker.ServiceClient = FakeServiceClient` hack.
2. Make `SamplerRegistry` a real class with a public constructor; pass it in. Tests create their own registry, trainer uses it, no module-globals.
3. Make `TrainingBackend` independently constructable so `test_training_backend.py` can exercise the exception ladder without a real trainer.
4. Provide a `TrainerTestHarness` in `tinker_nemogym/testing/` that wires a trainer + fakes + free-port registry for integration tests — one line per test instead of the current 30-line boilerplate.

### 7. Standardization

**Findings.**
- **Good:** pyproject-first (no setup.py), poetry-managed lockfile, ruff with sensible selections, mypy configured (`pyproject.toml:56-63`), 3.12 pinned, `from __future__ import annotations`, `logging.getLogger(__name__)`, `importlib.metadata` for `--version`, Apache-2.0 license, README + architecture docs.
- **Gaps vs. Python ecosystem norms:**
  - No `src/` layout. The PyPA's recommendation for libraries. Not a blocker; many major libs are flat.
  - No `py.typed` marker. **Blocker** for any downstream `mypy --strict`.
  - No `[project.entry-points]` plugin hooks. `loss_fn` is a closed `Literal` — user can't register a custom loss without editing our code.
  - No `CODEOWNERS`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`.
  - `pyproject.toml` uses `[tool.poetry]` (v1 style) rather than PEP-621 `[project]` — fine while on poetry<2, but upgrading to poetry 2.x (PEP-621-native) is mechanical and future-proofs the file.
- No `__all__` at `tinker_nemogym/__init__.py`. Re-export story is ad-hoc.

**Concrete proposal — ecosystem compliance in one commit:**

```
tinker_nemogym/py.typed           # empty file
tinker_nemogym/__init__.py        # populated __all__ (see §2.4)
CHANGELOG.md                      # seeded with 0.0.1
CONTRIBUTING.md                   # install/test/ruff flow
SECURITY.md                       # threat model one-pager
.github/CODEOWNERS                # @team-rl-infra tinker_nemogym/**
pyproject.toml                    # + [project.entry-points] "tinker_nemogym.loss_fns"
```

### 8. Abstraction Leaks

**Findings.**
- `tinker` types appear in *public* signatures:
  - `build_datum() -> tinker.Datum` (`datum_builder.py:223`) — ok, this is the contract.
  - `TinkerNeMoGymTrainer.current_sampling_client: Any` (attr, not param) — `tinker.SamplingClient` is implicitly required but typed `Any` at `trainer.py:71`.
  - `set_sampling_client(client: tinker.SamplingClient)` (`tinker_responses_model.py:54`) — tinker type in a facade function.
- `tinker` imports leaking through: `config.py` doesn't import `tinker` (good); `datum_builder` does (ok — pure conversion); `trainer` does (ok — needs Adam params + error classes); `tinker_responses_model` does (leaks).
- To swap backends hypothetically we'd rewrite: all three sampler / training client references in `trainer.py`, the entire `tinker_responses_model.py` (uses `tt.SamplingParams`, `client.sample_async`, `seq.stop_reason`), and the `build_datum` constructor.
- `RawTrajectory` (`datum_builder.py:42-52`) is backend-independent ✅.

**Concrete proposal — `interfaces` module with Protocols:**

```python
# tinker_nemogym/interfaces.py   (new)
from __future__ import annotations
from typing import Protocol, runtime_checkable, Any

@runtime_checkable
class SamplingClient(Protocol):
    async def sample_async(
        self, *, prompt: Any, num_samples: int, sampling_params: Any
    ) -> Any: ...

@runtime_checkable
class TrainingClient(Protocol):
    async def forward_backward_async(self, datums: list, loss_fn: str) -> Any: ...
    async def optim_step_async(self, adam_params: Any) -> Any: ...
    async def save_weights_and_get_sampling_client_async(self) -> SamplingClient: ...
    async def save_state_async(self, *, name: str) -> Any: ...
    async def load_state_async(self, path: str) -> Any: ...

@runtime_checkable
class ServiceClient(Protocol):
    async def create_lora_training_client_async(
        self, *, base_model: str, rank: int
    ) -> TrainingClient: ...
```

Then `trainer.py` annotates `self.service_client: ServiceClient`, `self.training_client: TrainingClient`. The Protocols are **duck-typed** (structural) so both `tinker.*` classes and `FakeServiceClient` satisfy them automatically. Production code unchanged; types clear.

### 9. Monorepo Ergonomics

**Findings.**
- If I wanted to fork `tinker-nemogym` → `tinker-atropos-v2`:
  - Fork + rename package: ~30 min. But then I'm maintaining a fork of `rollout_driver.py` that is 95% identical to ours.
  - There is no `tinker_common/` or `tinker_interfaces/` package that a fork could depend on.
  - `datum_builder.py`, `rollout_driver.py`, `utils/process.py` are *entirely* environment-agnostic — they could live in a shared package today.
- `tinker_responses_model.py` is 60% generic (hot-swap FastAPI shim) + 40% nemo-gym specific (TokenIDLogProbMixin shape, `NeMoGymResponse`-compatible output structure). Splitting would expose reusable bits.

**Concrete proposal — 3-package split (post-v1.0):**

```
tinker-core/            # datum-building, hot-swap registry, rollout_driver, utils
tinker-nemogym/         # nemo-gym-specific adapters (depends on tinker-core)
tinker-atropos/         # hypothetical future fork (depends on tinker-core)
```

Before the split is worth it, we need the Protocols from §8. Defer to post-v1.0.

### 10. Backwards Compatibility Contract

**Findings.**
- Zero uses of `warnings.warn(..., DeprecationWarning)` (grepped).
- Zero uses of `@deprecated` (from `typing_extensions` / `warnings.deprecated` in 3.13+).
- README documents usage; does not document **stability guarantees** — which imports are "you can depend on this", which are "will change without notice".
- No `CHANGELOG.md`.
- No semver policy stated.

**Concrete proposal — explicit stability contract:**

1. Add to `README.md`:
   > **API stability.** The following are public and follow semver from v0.1.0 onward: `TinkerNeMoGymTrainer`, `TinkerNeMoGymConfig` and its sub-configs, `build_datum`, `extract_trajectory`, `rollout_batch`, `RawTrajectory`. Everything else (modules starting with `_`, leading-underscore functions, `testing.*`) is unstable and may change in any release.
2. Add `CHANGELOG.md` following Keep-a-Changelog format.
3. Use `warnings.deprecated("use X; removed in Y")` (PEP 702, 3.13+) or a vendored back-port for any field/function slated for removal.

### 11. Type System Strictness

**Findings.**
- Review 04 §1 already sized: 43 `--strict` errors, mostly cosmetic.
- Real hotspots that actually matter:
  - `TinkerNeMoGymTrainer.service_client/training_client/current_sampling_client: Any` (`trainer.py:69-71`) — fixable with Protocols from §8.
  - `_extract_messages_chat(body: dict) -> list[dict]` (`tinker_responses_model.py:208`) — `dict` → `ChatMessage` TypedDict.
  - `run_response: dict` (`datum_builder.py:106`) — has an implicit shape that's documented in docstring only. TypedDict.
  - `FakeSamplingClient.sample_async(...)` return type is `Any` chain → should type as `FakeSampleResponse`.
- No `TypedDict` anywhere in the tree.

**Concrete proposal — add 4 TypedDicts:**

```python
# interfaces.py (or a new types.py)
from typing import TypedDict, Required, NotRequired

class ChatMessage(TypedDict):
    role: str
    content: str

class StepMetrics(TypedDict):
    step: int
    mean_reward: float
    n_datums: int
    n_dropped: int
    n_dropped_oversize: NotRequired[int]
    loss: NotRequired[float]
    sampler_version: NotRequired[int | None]
    save_count: NotRequired[int]
    fwd_bwd_error: NotRequired[str]
    hot_swap_error: NotRequired[str]
    prompt_tokens_mean: NotRequired[float]
    completion_tokens_mean: NotRequired[float]

class RawRunResponse(TypedDict):
    reward: Required[float]
    response: Required[dict]

class TokenIDLogProbItem(TypedDict):
    prompt_token_ids: list[int]
    generation_token_ids: list[int]
    generation_log_probs: list[float]
```

### 12. Logging Standardization

**Findings.**
- Every module uses `logging.getLogger(__name__)`. ✅
- Level discipline is correct (INFO for lifecycle, WARNING for degraded, ERROR for hot-swap/auth/timeout, DEBUG for per-POST). ✅
- **But:** free-form strings. Example: `trainer.py:298-305` logs step metrics via `logger.info("Step %d: mean_reward=%.3f ...")`. A log parser *can* regex this but no guarantee.
- No `extra={...}` with structured fields. No JSON logging. Google-style guidance is: for anything that will be scraped into a dashboard, emit structured fields.

**Concrete proposal — pragmatic upgrade:**

```python
# trainer.py _run_step end
logger.info(
    "step_completed",
    extra={
        "event": "step_completed",
        "step": metrics["step"],
        "mean_reward": metrics["mean_reward"],
        "n_datums": metrics["n_datums"],
        "n_dropped": metrics["n_dropped"],
        "loss": metrics.get("loss"),
    },
)
```

And wire a `JsonFormatter` onto `cli._configure_logging` behind a `--log-format json|human` flag. Human stays default for devs; JSON turns on in Docker/k8s.

### 13. Metrics Standardization

**Findings.**
- Today: `wandb.log({"train/mean_reward": ..., "train/loss": ..., "train/n_datums": ..., "train/n_dropped": ..., "train/sampler_version": ...}, step=...)` at `trainer.py:559-569`.
- Keys are **string literals at the call site**. A rename is a silent break. No OpenTelemetry, no Prometheus export, no versioned schema.
- `n_dropped` vs `n_dropped_constant` vs `n_dropped_oversize` — the trainer exposes `n_dropped` (constant-reward only) in the external metric name but `_build_datums_from_rollouts` produces both `n_dropped` and `n_dropped_oversize` (`trainer.py:429-430`). Only the first is surfaced to wandb. Missed observability.

**Concrete proposal — `MetricsSink` protocol + TypedDict:**

```python
# interfaces.py
class MetricsSink(Protocol):
    def emit(self, step: int, metrics: StepMetrics) -> None: ...
    def close(self) -> None: ...

# metrics_sinks.py
class WandbSink:
    SCHEMA_VERSION = 1
    def emit(self, step, metrics):
        payload = {
            "train/mean_reward": metrics["mean_reward"],
            "train/n_datums": metrics["n_datums"],
            "train/n_dropped_constant": metrics["n_dropped"],
            "train/n_dropped_oversize": metrics.get("n_dropped_oversize", 0),
            "train/schema_version": self.SCHEMA_VERSION,
            ...
        }
        wandb.log(payload, step=step + 1)

class PrometheusSink:
    """Optional opt-in; ships a /metrics endpoint."""

class CompositeSink:
    """Fan-out to multiple sinks."""
```

### 14. Configuration Hierarchy

**Findings.**
- 4 nested blocks today, each a Pydantic `BaseModel` with 5-10 fields. Readable.
- At 20 blocks this pattern gets unwieldy: no overlays, no inheritance, no interpolation, no CLI overrides, no env-var fallback.
- Review 02 §2.7 already flagged that nemo-gym uses Hydra; they recommended adopting it. That was deferred.
- FAANG-scale: neither Hydra nor OmegaConf are the only option. At Meta, Thrift-defined configs + typed Pydantic loaders are standard. At Google, protobuf-text configs. **The point is:** we should have a path, not a solution, picked before field count explodes.

**Concrete proposal — profile inheritance (pre-Hydra):**

```yaml
# configs/_base.yaml          (new)
tinker:
  base_model: meta-llama/Llama-3.2-1B-Instruct
  lora_rank: 32
  learning_rate: 5e-4
training:
  n_steps: 100
  batch_size: 4

# configs/smoke_mcqa.yaml
_extends: _base.yaml          # override-only; minimal surface
nemogym:
  dataset_jsonl: datasets/mcqa_smoke.jsonl
training:
  n_steps: 3
```

With a 20-line `_resolve_extends` preprocessor in `config.py`. Upgrade to Hydra post-v1.0 only if field count crosses ~50.

### 15. Error Taxonomy

**Findings.**
- `grep -rn "^class .*Error" tinker_nemogym/` → zero custom exceptions.
- Current error surface: `ValueError` (config / datum-builder malformed input), `RuntimeError` (sampler not initialized, dataset empty), `KeyError` (`run_response["reward"]`), `tinker.AuthenticationError` / `RateLimitError` / `RequestFailedError` / `SidecarDiedError` (passthrough), `aiohttp.ClientError`, `TimeoutError`, `asyncio.CancelledError`.
- Downstream `except TinkerNeMoGymError` — impossible.
- HTTP shim error-mapping lives in string comparisons: `tinker_responses_model.py:317` does `if "has not been called" in msg or "No active sampling client" in msg:`. **String-based exception dispatch is a bug waiting to happen.**

**Concrete proposal — custom error hierarchy (50 LoC):**

```python
# tinker_nemogym/errors.py   (new)
"""Typed exception hierarchy for tinker-nemogym.

Downstream users can catch ``TinkerNeMoGymError`` as a single umbrella.
Internal code narrows to the most specific subclass that applies.
"""

class TinkerNeMoGymError(Exception):
    """Base class. Never raise directly; use a subclass."""

class ConfigError(TinkerNeMoGymError, ValueError):
    """Config is malformed or semantically invalid."""

class ShimError(TinkerNeMoGymError):
    """FastAPI shim isn't correctly wired."""

class SamplerNotReadyError(ShimError):
    """Tried to serve a request before ``set_sampling_client`` was called."""

class ShimNotInitializedError(ShimError):
    """``tmodel.init(...)`` was never called."""

class RolloutError(TinkerNeMoGymError):
    """Rollout against the nemo-gym agent failed."""

class TrajectoryParseError(TinkerNeMoGymError, ValueError):
    """Agent response couldn't be converted to a RawTrajectory."""

class TrainingError(TinkerNeMoGymError):
    """forward_backward / optim_step / hot-swap failed."""
```

Then `tinker_responses_model._route_to_tinker` raises `ShimNotInitializedError` / `SamplerNotReadyError` instead of `RuntimeError` with magic strings. The endpoint can then dispatch on **type** instead of on substring match:

```python
except ShimError as e:
    raise HTTPException(status_code=503, detail=str(e)) from e
except TinkerNeMoGymError as e:
    raise HTTPException(status_code=500, detail=str(e)) from e
```

And `extract_trajectory` raises `TrajectoryParseError` rather than `ValueError`/`KeyError`, so the trainer's per-trajectory `except (ValueError, KeyError, TypeError)` at `trainer.py:409` becomes `except TrajectoryParseError`.

---

## §3. Refactor Roadmap (Priority Order)

| # | Refactor | Est. LoC | Breaking-change risk | Blast radius |
|---|---|---|:-:|---|
| 1 | Add `errors.py` + route all raises through the hierarchy | +50 / Δ30 | **Low** (additive; keep `isinstance(..., ValueError)` compat via multiple inheritance) | `tinker_responses_model`, `trainer`, `datum_builder`, `config`; 4-6 tests updated |
| 2 | Add `py.typed`, populate `__init__.py` re-exports, tidy `__all__` across modules | +40 / Δ20 | **Low** | Every module's `__all__`, `__init__.py`; no runtime behavior change |
| 3 | Introduce `interfaces.py` with Protocols + `StepMetrics` / `ChatMessage` / `RawRunResponse` TypedDicts | +80 / Δ15 | **Low** (annotation-only) | `trainer`, `tinker_responses_model`, `datum_builder`; type-only |
| 4 | Extract `SamplerRegistry` class from module globals in `tinker_responses_model`; keep `set_sampling_client` / `get_sampling_client` / `init` as backward-compat façade over a default module-level registry | +120 / Δ60 | **Medium** (module globals kept as deprecated aliases for one release; tests still pass via façade) | `tinker_responses_model` internal split; trainer passes a registry in; fakes simplify |
| 5 | Inject `service_client_factory` / `http_session_factory` into `TinkerNeMoGymTrainer.__init__` (default values preserve current behavior) | +30 / Δ10 | **Low** (kw-only with defaults) | `trainer.__init__` signature; tests can stop monkey-patching `tinker.ServiceClient` |
| 6 | Add `schema_version: Literal[1]` + `_migrate` hook in `config.py` | +40 | **Low** (field defaults to 1; existing configs that omit it still validate) | `config.py` + `CONFIG_MIGRATIONS.md` |
| 7 | Split `TinkerNeMoGymTrainer` into `Rollouter` / `TrainingBackend` / `ServingStack` / `MetricsSink` + orchestrator | +400 / Δ300 | **Medium-High** (re-organizes all `trainer.py` internals; tests that reach for `_run_step`/`_do_training_step` need updates) | `trainer.py` → 5 files; `tests/unit/test_trainer.py` rewritten; integration tests unaffected |
| 8 | Split `testing/fakes.py` into `testing/{sampling,training,service,wandb}.py` + re-export from `testing/__init__.py` | +0 / Δ20 | **Low** (imports preserved by `__init__.py`) | `testing/` subpackage only |
| 9 | Add `[project.entry-points]` plugin hook for custom loss functions; make `TinkerConfig.loss_fn` `str` (no Literal), validate against registry | +60 | **Medium** (widens accepted set; downstream that relied on Literal exhaustiveness in type-checking sees broader type) | `config.py`, `trainer.py._do_training_step` |
| 10 | Structured (JSON) logging behind `--log-format` flag; `MetricsSink` abstraction for wandb + optional Prometheus | +200 | **Low** (default human log unchanged) | `cli.py`, new `metrics_sinks.py`, `trainer.py` emit sites |
| 11 | Add `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `.github/CODEOWNERS`, stability section in `README.md` | +N/A docs | **Low** | Docs only |
| 12 | Migrate `pyproject.toml` from `[tool.poetry]` to PEP-621 `[project]` | Δ60 | **Medium** (requires poetry 2.x or pip-installable build) | Build system |
| 13 | (Post-v1.0) Extract `tinker-core` package: `datum_builder`, `rollout_driver`, `utils/process`, `interfaces`, `errors` | ±0 moving | **High** (import paths change for all downstream) | Whole tree |

---

## §4. Minimum Surgical Changes for "Readable at FAANG Code Review" (the 20%)

If the brief is "what's the smallest diff that gets a staff reviewer to stamp *Looks Good*?", it's roadmap items **1–6** together — ~400 LoC net, all low-risk:

1. **`errors.py` + narrowest swap**: raise `TinkerNeMoGymError` subclasses at the 5-7 sites that matter. Makes error dispatch **typed** instead of **string-matched**. (Rows 1)
2. **`py.typed` + `__init__.py` re-exports + `__all__` audit**: unlocks the type annotations we already have for downstream, fixes the leaking-internal `__all__` entries. (Row 2)
3. **`interfaces.py` with Protocols**: annotate `trainer.service_client` / `training_client` / `current_sampling_client` — types stop being `Any`. Fakes naturally conform. (Row 3)
4. **`SamplerRegistry` class**: module-level functions become thin façade; new registry class is instantiable. Eliminates the conftest-reset smell at the root cause. (Row 4)
5. **Factory injection in `Trainer.__init__`**: `service_client_factory`, `http_session_factory` as kw-only defaults. Eliminates `tinker.ServiceClient = FakeServiceClient` monkey-patch from fakes. (Row 5)
6. **`schema_version` + migration hook**: one field + 30 lines. Buys us 2 years of safe config renames. (Row 6)

These six changes, together, move us from **C+** to **B+** on every axis except "interface segregation" (which still needs the god-class split — but that is §3 Row 7, genuinely medium-risk).

**Order of landing** (smallest to largest CR):
1. Items 1+2+11 land together (one small CR) — docs, `__all__`, `py.typed`, errors.
2. Items 3+6 land together (one small CR) — Protocols + schema_version.
3. Items 4+5 land together (one medium CR) — `SamplerRegistry` + factory DI.

After those three CRs, you have a codebase a staff reviewer would *land*. Item 7 (god-class split) is a separate sprint.

---

## §5. Deferred Post-v1.0

Items that are architecturally right but not worth paying for pre-1.0:

- **Row 7: god-class split of `TinkerNeMoGymTrainer`**. Correct direction, but 400-LoC churn right now would regress the test suite's reliability during reorg. Land after v0.2 stabilizes the public API.
- **Row 9: plugin-hook loss functions.** Closed `Literal` is fine while we're the only consumers. Defer until an external user actually asks.
- **Row 10: OpenTelemetry / Prometheus sinks.** Wandb is the only observed consumer today. Structured JSON logging is cheap and should land early (optional `--log-format`); full OTLP is post-1.0.
- **Row 12: PEP-621 `[project]` migration.** Nice-to-have; poetry-1.x `[tool.poetry]` works fine and the tool handles PEP-621 translation in 2.x. Land opportunistically.
- **Row 13: extract `tinker-core` package.** Only worth it if and when a second fork (`tinker-atropos-v2`) actually materializes. Premature today.
- **Hydra / OmegaConf adoption for configs.** Review 02 §2.7 flagged this; also deferred. Profile-inheritance preprocessor (§2.14) is a 20-line stopgap that handles the next ~1 year of growth.
- **`src/` layout migration.** Non-breaking (mostly) but touches every test `conftest` + every import path dev-tool sees. Not worth it mid-stream.
- **`@deprecated` decorator rollout.** Only matters once we actually deprecate something. Adopt at first deprecation.
- **Multi-worker uvicorn support for the shim.** Review 04 §4 noted the `threading.Lock` vs `asyncio.Lock` split. Defer until a user demand materializes — current single-worker path is correct and tested.

---

## Appendix: What This Review Deliberately Did NOT Re-Raise

Every one of these is a real issue, but already covered by reviews 01–04 (see `ADDRESSED.md`):

- Deprecated `name=` kwarg on `save_weights_and_get_sampling_client_async` (01)
- Default `base_model` → Instruct variant (01 §1.2)
- `adam_eps` 1e-8 → 1e-12 default (01 §1.5)
- `session` cookie propagation in shim (02 §1.3)
- Dynamic agent URL discovery via HeadServer (02 §1.4)
- `response.usage` / `.id` / `n_turns` harvested (02 §4.2)
- `max_trainer_tokens` cap (03 §2.2)
- Pydantic range validators + path-traversal guard (04 §2.1)
- `aiohttp.ClientSession` pooling at trainer lifetime (04 §2.3)
- Narrowing `except Exception` + rate-limit handling (04 §2.4)
- `_run_step` split (04 §2.5)
- Mypy + pre-commit + CI (04 §3.1-3.3)
- CLI `--log-level`, `--version`, `ValidationError` wrapping (04 §5.1)
- Shared `conftest.py` autouse reset (04 §5.2)

If any of those regress, this review endorses re-opening them from the prior review rather than duplicating the finding here.

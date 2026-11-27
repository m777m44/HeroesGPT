"""In-process fakes that mimic the minimal Tinker SDK surface we use.

We duck-type rather than subclass so we don't have to satisfy Tinker's
Pydantic validators. Every method we fake in this module is used either by
:mod:`tinker_nemogym.trainer` or by :mod:`tinker_nemogym.tinker_responses_model`.

These are **offline only**: no HTTP, no tokenizer reliance. The only
external type we construct is a throwaway object that mimics
:class:`tinker.SampleResponse` (it exposes ``.sequences`` of
``FakeSampledSequence``, which carry ``tokens``, ``logprobs``, and
``stop_reason`` — the three fields :mod:`tinker_responses_model` reads).

Typical usage in tests::

    from tinker_nemogym.testing import make_fake_tinker_module

    with make_fake_tinker_module():
        await trainer.setup(start_model_server=False)
        await trainer._run_step(step=0)

Call history is recorded on ``FakeLoRATrainingClient.call_history`` so
callers can assert the full sequence of Tinker interactions (e.g. verify
hot-swap happened, that ``save_state_async`` fired on the right step).
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import tinker

# ---------------------------------------------------------------------------
# Result types (duck-typed to tinker.SampleResponse / SampledSequence).
# ---------------------------------------------------------------------------


@dataclass
class FakeSampledSequence:
    """Duck-typed mirror of ``tinker.SampledSequence``.

    Fields match the real type (see
    ``tinker.types.SampledSequence.model_fields``): ``tokens`` is a list of
    ints, ``logprobs`` is an optional list of floats (same length as
    ``tokens``), and ``stop_reason`` is either ``"length"`` or ``"stop"``.
    """

    tokens: list[int]
    logprobs: list[float] | None
    stop_reason: str  # "length" | "stop"


@dataclass
class FakeSampleResponse:
    """Duck-typed mirror of ``tinker.SampleResponse`` (only ``.sequences`` used)."""

    sequences: list[FakeSampledSequence]
    type: str = "sample"
    prompt_logprobs: list[float | None] | None = None
    topk_prompt_logprobs: Any = None


@dataclass
class FakeFuture:
    """Mirror of Tinker's ``APIFuture`` just enough for the trainer to await.

    The real Tinker future exposes ``result()`` (sync) and ``result_async()``
    (async). We implement both so tests calling either variant work.
    """

    _value: Any

    def result(self) -> Any:
        """Return the resolved value synchronously."""
        return self._value

    async def result_async(self) -> Any:
        """Return the resolved value from an async caller."""
        return self._value


# ---------------------------------------------------------------------------
# Sampling client
# ---------------------------------------------------------------------------


class FakeSamplingClient:
    """Deterministic, offline stand-in for :class:`tinker.SamplingClient`.

    Generates a pseudo-random token sequence seeded by the prompt content
    plus a caller-supplied ``seed``. Sequence length is bounded by
    ``sampling_params.max_tokens`` (or 20 when unspecified) and clamped to
    the ``[min_tokens, max_tokens_cap]`` range so tests get varied shapes
    without blowing up.

    The ``version`` attribute is bumped every time
    :meth:`FakeLoRATrainingClient.save_weights_and_get_sampling_client_async`
    is called, which lets tests verify a hot-swap swapped in a **new**
    sampling client between steps.
    """

    def __init__(
        self,
        seed: int = 0,
        version: int = 0,
        vocab_size: int = 32000,
        min_tokens: int = 10,
        max_tokens_cap: int = 50,
    ):
        self.seed = seed
        self.version = version
        self.vocab_size = vocab_size
        self.min_tokens = min_tokens
        self.max_tokens_cap = max_tokens_cap
        self.call_history: list[dict[str, Any]] = []

    # The real SamplingClient exposes both sample() and sample_async(); the
    # trainer + shim only hit sample_async(), so that's the only one we
    # implement. (sample() can be added later if a downstream user wants it.)
    async def sample_async(
        self,
        prompt: Any,
        num_samples: int,
        sampling_params: Any,
        include_prompt_logprobs: bool = False,
        topk_prompt_logprobs: int = 0,
    ) -> FakeSampleResponse:
        """Return ``num_samples`` deterministic pseudo-token sequences.

        Matches the signature of ``tinker.SamplingClient.sample_async``.
        """
        # Build a deterministic seed key from the prompt's int representation
        # (when available) plus the caller seed. ``ModelInput.to_ints`` is
        # the canonical way; fall back to repr() for duck-typed prompts.
        try:
            prompt_ints = list(prompt.to_ints())  # tinker.ModelInput
        except Exception:
            prompt_ints = []

        max_tokens = getattr(sampling_params, "max_tokens", None) or 20
        effective_max = min(int(max_tokens), self.max_tokens_cap)
        effective_max = max(effective_max, self.min_tokens)

        params_seed = getattr(sampling_params, "seed", None)
        base_seed = (
            (params_seed if params_seed is not None else 0)
            ^ self.seed
            ^ self.version
            ^ hash(tuple(prompt_ints[:64]))
        )

        self.call_history.append(
            {
                "method": "sample_async",
                "num_samples": num_samples,
                "max_tokens": effective_max,
                "prompt_len": len(prompt_ints),
                "seed": base_seed,
                "version": self.version,
            }
        )

        sequences: list[FakeSampledSequence] = []
        for i in range(num_samples):
            digest = hashlib.sha256(f"{base_seed}:{i}".encode()).digest()
            # Decide a length within [min_tokens, effective_max].
            length_range = max(1, effective_max - self.min_tokens + 1)
            length = self.min_tokens + (digest[0] % length_range)
            tokens: list[int] = []
            # Generate ``length`` pseudo-tokens from the hash, extending it as needed.
            j = 0
            while len(tokens) < length:
                j += 1
                chunk = hashlib.sha256(digest + j.to_bytes(2, "big")).digest()
                for k in range(0, len(chunk), 2):
                    if len(tokens) >= length:
                        break
                    tok = int.from_bytes(chunk[k : k + 2], "big") % self.vocab_size
                    # Avoid token 0 to dodge any tokenizer "pad" semantics downstream.
                    tokens.append(tok if tok != 0 else 1)
            # Logprobs are all negative (real logprobs always are).
            logprobs = [-0.1 - 0.0001 * t for t in tokens]
            stop_reason = "length" if len(tokens) >= effective_max else "stop"
            sequences.append(
                FakeSampledSequence(tokens=tokens, logprobs=logprobs, stop_reason=stop_reason)
            )
        return FakeSampleResponse(sequences=sequences)


# ---------------------------------------------------------------------------
# Training client
# ---------------------------------------------------------------------------


@dataclass
class _TrainerCall:
    """One entry in :attr:`FakeLoRATrainingClient.call_history`."""

    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeLoRATrainingClient:
    """Offline duck-type of Tinker's LoRA training client.

    Exposes just enough methods for :class:`tinker_nemogym.trainer.TinkerNeMoGymTrainer`
    to exercise an end-to-end step without a real Tinker backend:

    * :meth:`forward_backward_async` — returns a resolved :class:`FakeFuture`
      whose ``.result_async()`` yields a dict with ``loss`` + ``metrics``.
    * :meth:`optim_step_async` — returns a resolved :class:`FakeFuture` with
      a dict of fake optimizer metrics.
    * :meth:`save_weights_and_get_sampling_client_async` — returns a **new**
      :class:`FakeSamplingClient` with a bumped ``.version`` so tests can
      verify the trainer hot-swapped the sampler.
    * :meth:`save_state_async` — returns a resolved :class:`FakeFuture`.

    Every call is appended to :attr:`call_history` for assertions.
    """

    def __init__(self, base_model: str = "fake-model", rank: int = 8):
        self.base_model = base_model
        self.rank = rank
        self.call_history: list[_TrainerCall] = []
        self._version: int = 0
        # Path passed to the most recent load_state_async call (or None).
        self._loaded_state: str | None = None
        # Optional per-method error overrides; tests set e.g.
        # ``client.raise_on["forward_backward_async"] = RuntimeError(...)`` to
        # exercise trainer error recovery paths.
        self.raise_on: dict[str, Exception] = {}

    async def forward_backward_async(
        self,
        data: list[Any],
        loss_fn: str,
        loss_fn_config: dict[str, float] | None = None,
    ) -> FakeFuture:
        """Record the call and return a ready-to-resolve :class:`FakeFuture`."""
        self.call_history.append(
            _TrainerCall(
                method="forward_backward_async",
                kwargs={
                    "n_data": len(data),
                    "loss_fn": loss_fn,
                    "loss_fn_config": loss_fn_config,
                },
            )
        )
        if "forward_backward_async" in self.raise_on:
            raise self.raise_on["forward_backward_async"]
        # Shape is a trainer-private dict; trainer looks for "loss:sum"/"loss"
        # in ``metrics``. We supply both to be safe.
        result = {
            "loss": 0.5,
            "metrics": {"loss": 0.5, "loss:sum": 0.5 * max(len(data), 1)},
        }

        class _DuckResult:
            """Minimal object matching ``tinker.ForwardBackwardOutput`` duck-type."""

            def __init__(self, d: dict[str, Any]) -> None:
                self.loss = d["loss"]
                self.metrics = d["metrics"]

            def __getitem__(self, k: str) -> Any:
                return {"loss": self.loss, "metrics": self.metrics}[k]

        return FakeFuture(_value=_DuckResult(result))

    async def forward_async(
        self,
        data: list[Any],
        loss_fn: str,
        loss_fn_config: dict[str, float] | None = None,
    ) -> FakeFuture:
        """Duck-type of :meth:`tinker.TrainingClient.forward_async`.

        Used by the trainer's optional precision-gap shadow pass. When
        ``loss_fn == "cross_entropy"`` we return one ``LossFnOutput`` per
        datum with a ``"logprobs"`` TensorData (an object exposing ``.data``
        and ``.shape``) whose length matches the datum's target window — i.e.
        ``len(input) == len(target_tokens)``. The actual values are derived
        deterministically from the datum's ``advantages``/``target_tokens``
        so tests get a non-trivial β signal without randomness.
        """
        self.call_history.append(
            _TrainerCall(
                method="forward_async",
                kwargs={"n_data": len(data), "loss_fn": loss_fn},
            )
        )
        if "forward_async" in self.raise_on:
            raise self.raise_on["forward_async"]

        class _FakeTensor:
            def __init__(self, values: list[float]) -> None:
                self.data = list(values)
                self.shape = [len(values)]

        class _FakeForwardOutput:
            def __init__(self, outputs: list[dict[str, Any]]) -> None:
                self.loss_fn_outputs = outputs
                self.metrics: dict[str, float] = {}
                self.loss_fn_output_type = "FakeTensorData"

        outputs: list[dict[str, Any]] = []
        for datum in data:
            target_td = datum.loss_fn_inputs.get("target_tokens")
            if target_td is None:
                outputs.append({"logprobs": _FakeTensor([])})
                continue
            td_data = getattr(target_td, "data", None)
            if td_data is None and hasattr(target_td, "to_numpy"):
                try:
                    td_data = list(target_td.to_numpy().tolist())
                except Exception:
                    td_data = []
            target_len = len(td_data or [])
            # Derive per-token logprobs deterministically: "trainer" side
            # adds a tiny bias vs "sampler" side so compute_precision_gap
            # measures a non-trivial β in tests.
            values = [-0.1 - 0.0001 * (i % 13) for i in range(target_len)]
            outputs.append({"logprobs": _FakeTensor(values)})

        return FakeFuture(_value=_FakeForwardOutput(outputs))

    async def optim_step_async(self, adam_params: Any) -> FakeFuture:
        """Record the call and return a resolved :class:`FakeFuture`."""
        self.call_history.append(
            _TrainerCall(
                method="optim_step_async",
                kwargs={"adam_params": repr(adam_params)},
            )
        )
        return FakeFuture(_value={"metrics": {"lr": 5e-4}})

    async def save_weights_and_get_sampling_client_async(
        self, name: str | None = None, retry_config: Any = None
    ) -> FakeSamplingClient:
        """Record the call and return a **new** :class:`FakeSamplingClient`.

        ``name`` is accepted but ignored to match the real SDK (deprecated in
        tinker 0.18+). We still stash it in ``call_history`` for back-compat
        with older tests that asserted the pre-deprecation call shape.
        """
        self._version += 1
        self.call_history.append(
            _TrainerCall(
                method="save_weights_and_get_sampling_client_async",
                kwargs={"name": name, "version": self._version},
            )
        )
        return FakeSamplingClient(seed=self._version, version=self._version)

    async def save_state_async(self, name: str, ttl_seconds: int | None = None) -> FakeFuture:
        """Record the call and return a resolved :class:`FakeFuture`."""
        self.call_history.append(
            _TrainerCall(
                method="save_state_async",
                kwargs={"name": name, "ttl_seconds": ttl_seconds},
            )
        )
        if "save_state_async" in self.raise_on:
            raise self.raise_on["save_state_async"]
        return FakeFuture(_value={"path": name})

    # ------------------------------------------------------------------
    # Load / resume — mirrors tinker.LoRATrainingClient.load_state_async +
    # load_state_with_optimizer_async. Both accept a path string and return
    # an APIFuture; we duck-type with :class:`FakeFuture` and stash the
    # restore call in :attr:`call_history` so tests can assert it ran.
    # ------------------------------------------------------------------

    async def load_state_async(
        self, path: str, weights_access_token: str | None = None
    ) -> FakeFuture:
        """Record the call and return a resolved :class:`FakeFuture`.

        Mirrors tinker's ``load_state_async(path, weights_access_token)``
        signature. We track the requested path on ``self._loaded_state``
        so follow-up tests can verify restore actually happened before
        subsequent saves occurred.
        """
        self.call_history.append(
            _TrainerCall(
                method="load_state_async",
                kwargs={"path": path, "weights_access_token": weights_access_token},
            )
        )
        self._loaded_state = path
        return FakeFuture(_value={"path": path})

    async def load_state_with_optimizer_async(
        self, path: str, weights_access_token: str | None = None
    ) -> FakeFuture:
        """Record the call and return a resolved :class:`FakeFuture`.

        Mirrors tinker's ``load_state_with_optimizer_async(path,
        weights_access_token)``. Variant that also restores optimizer
        state; fake behavior is identical to :meth:`load_state_async`.
        """
        self.call_history.append(
            _TrainerCall(
                method="load_state_with_optimizer_async",
                kwargs={"path": path, "weights_access_token": weights_access_token},
            )
        )
        self._loaded_state = path
        return FakeFuture(_value={"path": path})


# ---------------------------------------------------------------------------
# Service client + helper
# ---------------------------------------------------------------------------


class FakeServiceClient:
    """Offline stand-in for :class:`tinker.ServiceClient`.

    The trainer only calls :meth:`create_lora_training_client_async`; we
    return a fresh :class:`FakeLoRATrainingClient` per invocation.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self._args = args
        self._kwargs = kwargs
        self.created_clients: list[FakeLoRATrainingClient] = []

    async def create_lora_training_client_async(
        self,
        base_model: str,
        rank: int = 32,
        seed: int | None = None,
        train_mlp: bool = True,
        train_attn: bool = True,
        train_unembed: bool = True,
        user_metadata: dict[str, str] | None = None,
    ) -> FakeLoRATrainingClient:
        """Return a fresh :class:`FakeLoRATrainingClient`."""
        client = FakeLoRATrainingClient(base_model=base_model, rank=rank)
        self.created_clients.append(client)
        return client

    async def get_server_capabilities_async(self) -> Any:
        """Duck-typed probe used by :meth:`Trainer._preflight_tinker`.

        Returns an object with ``supported_models`` that's a list of
        dict-like entries exposing ``model_name``. None means "don't
        validate" — the trainer accepts that as a no-op.
        """

        class _Cap:
            supported_models = None

        return _Cap()

    def create_lora_training_client(self, *args: Any, **kwargs: Any) -> FakeLoRATrainingClient:
        """Sync variant — kept for API symmetry with the real SDK."""
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self.create_lora_training_client_async(*args, **kwargs)
        )


@contextlib.contextmanager
def make_fake_tinker_module() -> Iterator[type[FakeServiceClient]]:
    """Monkey-patch ``tinker.ServiceClient`` with :class:`FakeServiceClient`.

    Usage::

        with make_fake_tinker_module():
            await trainer.setup(start_model_server=False)

    Yields the :class:`FakeServiceClient` class itself so callers can
    inspect or subclass if needed. Restores the original
    ``tinker.ServiceClient`` on exit even if an exception is raised.

    For fresh code the DI seam is preferred — pass
    :func:`fake_service_client_factory` to the trainer constructor::

        trainer = TinkerNeMoGymTrainer(
            cfg, service_client_factory=fake_service_client_factory()
        )

    which avoids monkey-patching at all.
    """
    original = tinker.ServiceClient
    tinker.ServiceClient = FakeServiceClient  # type: ignore[misc,assignment]
    try:
        yield FakeServiceClient
    finally:
        tinker.ServiceClient = original  # type: ignore[misc]


def fake_service_client_factory() -> type[FakeServiceClient]:
    """Return a zero-arg factory that yields fresh :class:`FakeServiceClient`.

    Use with the trainer's DI seam to avoid monkey-patching::

        trainer = TinkerNeMoGymTrainer(
            cfg, service_client_factory=fake_service_client_factory()
        )

    The factory is the class itself — calling it returns a new instance.
    """
    return FakeServiceClient


# ---------------------------------------------------------------------------
# Wandb fake — keeps tests offline without requiring ``wandb`` on PYTHONPATH
# (the trainer imports wandb lazily inside ``_maybe_init_wandb``).
# ---------------------------------------------------------------------------


class FakeWandb:
    """Minimal stand-in for the ``wandb`` module used by the trainer.

    Records every ``init``, ``log``, and ``finish`` call so tests can assert
    exact lifecycle semantics (e.g. ``finish`` called exactly once, even on
    exception; ``log`` called once per step with the expected key set).

    Install via :func:`patch_wandb` (context manager) or by stashing in
    ``sys.modules["wandb"]`` directly.
    """

    def __init__(self) -> None:
        self.init_calls: list[dict[str, Any]] = []
        self.log_calls: list[dict[str, Any]] = []
        self.finish_calls: int = 0
        self.run: Any = None

    def init(self, **kwargs: Any) -> Any:
        self.init_calls.append(dict(kwargs))
        self.run = object()
        return self.run

    def log(self, payload: dict[str, Any], step: int | None = None) -> None:
        entry = dict(payload)
        if step is not None:
            entry["_step"] = step
        self.log_calls.append(entry)

    def finish(self) -> None:
        self.finish_calls += 1
        self.run = None


@contextlib.contextmanager
def patch_wandb(fake: FakeWandb | None = None) -> Iterator[FakeWandb]:
    """Monkey-patch ``sys.modules["wandb"]`` with a :class:`FakeWandb` for the
    duration of the block. Yields the installed fake so tests can assert on it.
    """
    import sys

    fake = fake or FakeWandb()
    saved = sys.modules.get("wandb")
    sys.modules["wandb"] = fake  # type: ignore[assignment]
    try:
        yield fake
    finally:
        if saved is not None:
            sys.modules["wandb"] = saved
        else:
            sys.modules.pop("wandb", None)

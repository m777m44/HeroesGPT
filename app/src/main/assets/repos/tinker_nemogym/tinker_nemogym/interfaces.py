"""Structural-typing protocols for the subset of the Tinker SDK we use.

Why :class:`typing.Protocol` rather than ABCs? Tinker's real types are
pydantic models we don't want to subclass — we want to duck-type, and the
fakes in :mod:`tinker_nemogym.testing` are plain classes. Protocols give
us static type-checking at call sites plus ``isinstance`` checks at
runtime (via ``@runtime_checkable``) without coupling to a specific
superclass chain.

These protocols describe the **minimal** surface we actually call — they
are intentionally narrow, not exhaustive. Expand only when we add a
genuinely new dependency on a method.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SamplingClientProtocol(Protocol):
    """The minimal subset of :class:`tinker.SamplingClient` we rely on.

    Consumers: :mod:`tinker_responses_model`, the trainer.
    """

    async def sample_async(
        self,
        prompt: Any,
        num_samples: int,
        sampling_params: Any,
    ) -> Any:
        """Return an object whose ``.sequences`` is a list of items with
        ``tokens``, ``logprobs``, and ``stop_reason`` attributes."""
        ...


@runtime_checkable
class TrainingClientProtocol(Protocol):
    """The minimal subset of :class:`tinker.LoRATrainingClient` we rely on.

    Consumers: :class:`tinker_nemogym.trainer.TinkerNeMoGymTrainer`.
    """

    async def forward_backward_async(self, data: list[Any], loss_fn: str) -> Any:
        """Return a future-like object whose ``.result_async()`` yields the
        metrics dict (or a duck-typed equivalent carrying ``.metrics``)."""
        ...

    async def optim_step_async(self, adam_params: Any) -> Any:
        """Return a future-like object (``.result_async()`` awaitable)."""
        ...

    async def save_weights_and_get_sampling_client_async(self) -> Any:
        """Return a fresh :class:`SamplingClientProtocol`-compatible client."""
        ...

    async def save_state_async(self, name: str) -> Any:
        """Return a future-like object (``.result_async()`` awaitable)."""
        ...


@runtime_checkable
class ServiceClientProtocol(Protocol):
    """The minimal subset of :class:`tinker.ServiceClient` we rely on.

    Consumers: :class:`tinker_nemogym.trainer.TinkerNeMoGymTrainer` preflight
    + training-client creation.
    """

    async def create_lora_training_client_async(
        self,
        base_model: str,
        rank: int,
    ) -> TrainingClientProtocol:
        """Create + return a LoRA training client."""
        ...


__all__ = [
    "SamplingClientProtocol",
    "ServiceClientProtocol",
    "TrainingClientProtocol",
]

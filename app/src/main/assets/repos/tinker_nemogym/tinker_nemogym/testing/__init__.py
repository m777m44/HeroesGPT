"""Internal pytest test doubles for the Tinker SDK.

**Not a public extension point.** This module exists solely so that
``tinker-nemogym``'s own pytest suite can run without hitting the real
Tinker API. The canonical end-to-end path is the live-Tinker smoke
scripts (``scripts/smoke_mcqa.sh`` / ``scripts/smoke_diagnostics.sh`` /
``scripts/smoke_single_tool.sh``) — those exercise the full stack against
the real Tinker cloud and are the intended way to validate a change.

If you're reaching into ``tinker_nemogym.testing`` from your own code
you are almost certainly holding it wrong — talk to the maintainers
first.
"""

from __future__ import annotations

from .fakes import (
    FakeFuture,
    FakeLoRATrainingClient,
    FakeSampledSequence,
    FakeSampleResponse,
    FakeSamplingClient,
    FakeServiceClient,
    FakeWandb,
    fake_service_client_factory,
    make_fake_tinker_module,
    patch_wandb,
)

__all__ = [
    "FakeFuture",
    "FakeLoRATrainingClient",
    "FakeSampleResponse",
    "FakeSampledSequence",
    "FakeSamplingClient",
    "FakeServiceClient",
    "FakeWandb",
    "fake_service_client_factory",
    "make_fake_tinker_module",
    "patch_wandb",
]

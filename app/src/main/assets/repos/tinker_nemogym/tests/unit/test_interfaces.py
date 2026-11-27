"""Protocol conformance tests for :mod:`tinker_nemogym.interfaces`."""

from __future__ import annotations

from tinker_nemogym.interfaces import (
    SamplingClientProtocol,
    ServiceClientProtocol,
    TrainingClientProtocol,
)
from tinker_nemogym.testing import (
    FakeLoRATrainingClient,
    FakeSamplingClient,
    FakeServiceClient,
)


def test_fake_sampling_client_matches_protocol():
    """Our test fake implements the runtime-checkable SamplingClientProtocol."""
    client = FakeSamplingClient(seed=0)
    assert isinstance(client, SamplingClientProtocol)


def test_fake_training_client_matches_protocol():
    client = FakeLoRATrainingClient()
    assert isinstance(client, TrainingClientProtocol)


def test_fake_service_client_matches_protocol():
    client = FakeServiceClient()
    assert isinstance(client, ServiceClientProtocol)


def test_real_tinker_sampling_client_matches_protocol():
    """Sanity: the real Tinker SamplingClient also satisfies our protocol.

    We can't instantiate one without TINKER_API_KEY, so we check at the
    class level by confirming the methods we declared exist.
    """
    import tinker

    # isinstance on a type itself isn't meaningful — we just assert the
    # methods we rely on are present on the real class.
    for name in ("sample_async",):
        assert hasattr(tinker.SamplingClient, name), name


def test_real_tinker_training_client_matches_protocol_by_attribute():
    import tinker

    # Tinker >=0.18 exposes the base as ``tinker.TrainingClient``; older
    # releases used ``LoRATrainingClient``. Accept either so this test
    # stays forward/back-compatible.
    cls = getattr(tinker, "TrainingClient", None) or getattr(tinker, "LoRATrainingClient", None)
    assert cls is not None, "no Training/LoRATrainingClient on tinker module"
    for name in (
        "forward_backward_async",
        "optim_step_async",
        "save_weights_and_get_sampling_client_async",
        "save_state_async",
    ):
        assert hasattr(cls, name), name

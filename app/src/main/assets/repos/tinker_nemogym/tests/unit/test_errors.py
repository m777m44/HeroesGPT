"""Tests for :mod:`tinker_nemogym.errors`."""

from __future__ import annotations

import pytest

from tinker_nemogym.errors import (
    AgentDiscoveryError,
    CheckpointError,
    ConfigError,
    SamplerNotReadyError,
    ShimError,
    TinkerNeMoGymError,
    TrainingError,
)


def test_all_subclasses_inherit_from_base():
    for cls in (
        ConfigError,
        TrainingError,
        ShimError,
        SamplerNotReadyError,
        AgentDiscoveryError,
        CheckpointError,
    ):
        assert issubclass(cls, TinkerNeMoGymError)


def test_sampler_not_ready_is_a_shim_error():
    assert issubclass(SamplerNotReadyError, ShimError)
    assert issubclass(SamplerNotReadyError, TinkerNeMoGymError)


def test_base_catches_all_subclasses():
    """One ``except TinkerNeMoGymError`` catches every subclass."""
    for cls in (
        ConfigError,
        TrainingError,
        ShimError,
        SamplerNotReadyError,
        AgentDiscoveryError,
        CheckpointError,
    ):
        with pytest.raises(TinkerNeMoGymError):
            raise cls("boom")


def test_errors_preserve_cause_on_wrap():
    """``raise ... from e`` chain works as expected for wrapping SDK errors."""
    original = RuntimeError("tinker-sdk exploded")
    try:
        try:
            raise original
        except RuntimeError as e:
            raise TrainingError("step 5: forward_backward_async failed") from e
    except TrainingError as wrapped:
        assert wrapped.__cause__ is original
        assert "step 5" in str(wrapped)


def test_all_exported_names_resolve():
    """Module __all__ must not drift from the actual exports."""
    import tinker_nemogym.errors as errmod

    for name in errmod.__all__:
        assert hasattr(errmod, name), name

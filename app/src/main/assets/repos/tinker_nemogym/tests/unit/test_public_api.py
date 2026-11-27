"""Tests for the top-level :mod:`tinker_nemogym` public API.

Locks in the stable surface so accidental renames / removals break CI.
"""

from __future__ import annotations

import tinker_nemogym


def test_version_is_a_string():
    assert isinstance(tinker_nemogym.__version__, str)
    assert tinker_nemogym.__version__


def test_canonical_names_resolve():
    assert tinker_nemogym.TinkerNeMoGymConfig is not None
    assert tinker_nemogym.TinkerNeMoGymTrainer is not None
    assert tinker_nemogym.RawTrajectory is not None
    assert callable(tinker_nemogym.build_datum)
    assert callable(tinker_nemogym.build_batch)
    assert callable(tinker_nemogym.compute_advantages)


def test_backcompat_aliases_point_at_canonical_types():
    assert tinker_nemogym.Trainer is tinker_nemogym.TinkerNeMoGymTrainer
    assert tinker_nemogym.Config is tinker_nemogym.TinkerNeMoGymConfig
    assert tinker_nemogym.Trajectory is tinker_nemogym.RawTrajectory


def test_error_hierarchy_exposed():
    for name in (
        "TinkerNeMoGymError",
        "ConfigError",
        "TrainingError",
        "ShimError",
        "SamplerNotReadyError",
        "AgentDiscoveryError",
        "CheckpointError",
    ):
        assert hasattr(tinker_nemogym, name), name


def test_all_is_complete_and_consistent():
    """Every name in __all__ resolves; nothing public is missing from __all__."""
    for name in tinker_nemogym.__all__:
        assert hasattr(tinker_nemogym, name), name

    # Spot-check a few canonical names appear in __all__.
    for required in (
        "__version__",
        "TinkerNeMoGymConfig",
        "TinkerNeMoGymTrainer",
        "RawTrajectory",
        "build_datum",
        "build_batch",
        "compute_advantages",
        "Trainer",
        "Config",
        "Trajectory",
        "TinkerNeMoGymError",
    ):
        assert required in tinker_nemogym.__all__, required

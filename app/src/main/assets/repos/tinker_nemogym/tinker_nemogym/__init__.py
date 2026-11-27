"""tinker-nemogym: bridge NVIDIA NeMo-Gym RL environments to Thinking Machines Tinker.

Programmatic entry points (all re-exported here for convenience):

* :class:`TinkerNeMoGymConfig` — pydantic config (construct or load from YAML).
* :class:`TinkerNeMoGymTrainer` — async RL trainer.
* :class:`RawTrajectory`, :func:`build_datum`, :func:`build_batch`,
  :func:`compute_advantages` — pure datum helpers.
* Exception hierarchy: :class:`TinkerNeMoGymError` + subclasses.

Back-compat aliases ``Trainer``, ``Config``, ``Trajectory`` are kept because
early reviewers referenced those short names; they're soft-deprecated and
will remain indefinitely — the canonical names are the long-form ones.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:  # pragma: no cover - trivial metadata lookup
    __version__ = _pkg_version("tinker-nemogym")
except PackageNotFoundError:  # pragma: no cover - editable install outside poetry
    __version__ = "0.0.0+dev"


from tinker_nemogym._sync import train
from tinker_nemogym.config import TinkerNeMoGymConfig
from tinker_nemogym.datum_builder import (
    RawTrajectory,
    build_batch,
    build_datum,
    compute_advantages,
)
from tinker_nemogym.errors import (
    AgentDiscoveryError,
    CheckpointError,
    ConfigError,
    SamplerNotReadyError,
    ShimError,
    TinkerNeMoGymError,
    TrainingError,
)
from tinker_nemogym.trainer import TinkerNeMoGymTrainer

# Back-compat aliases (deprecated but kept indefinitely).
Trainer = TinkerNeMoGymTrainer
Config = TinkerNeMoGymConfig
Trajectory = RawTrajectory


__all__ = [
    "AgentDiscoveryError",
    "CheckpointError",
    "Config",
    "ConfigError",
    "RawTrajectory",
    "SamplerNotReadyError",
    "ShimError",
    "TinkerNeMoGymConfig",
    "TinkerNeMoGymError",
    "TinkerNeMoGymTrainer",
    "Trainer",
    "TrainingError",
    "Trajectory",
    "__version__",
    "build_batch",
    "build_datum",
    "compute_advantages",
    "train",
]

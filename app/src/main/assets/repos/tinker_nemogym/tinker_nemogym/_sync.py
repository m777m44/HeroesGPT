"""Synchronous one-liner wrapper around the async trainer.

Lets users who aren't writing an async entry-point call training with a
single function::

    import tinker_nemogym
    tinker_nemogym.train("configs/smoke_mcqa.yaml")

The async :class:`~tinker_nemogym.trainer.TinkerNeMoGymTrainer` remains the
canonical interface for power users who need to drive the loop themselves.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


def train(config: str | Path | Any) -> dict[str, Any]:
    """Run a full training session synchronously and return final metrics.

    Args:
        config: Either a :class:`TinkerNeMoGymConfig` instance or a path to a
            YAML file parseable by :meth:`TinkerNeMoGymConfig.from_yaml`.

    Returns:
        A dict with summary metrics from the run — currently
        ``{"steps": int, "final_metrics": dict}``. The schema may grow
        over time (new keys added only, never removed).

    Raises:
        :class:`tinker_nemogym.errors.ConfigError`: YAML / path issues.
        :class:`tinker_nemogym.errors.TinkerNeMoGymError`: any other
            library-originated failure (training, checkpoint, preflight).
    """
    # Lazy imports so ``import tinker_nemogym._sync`` doesn't drag the
    # whole trainer + tinker_cookbook stack into memory at module import.
    from .config import TinkerNeMoGymConfig
    from .trainer import TinkerNeMoGymTrainer

    cfg: TinkerNeMoGymConfig
    if isinstance(config, TinkerNeMoGymConfig):
        cfg = config
    else:
        cfg = TinkerNeMoGymConfig.from_yaml(config)

    trainer = TinkerNeMoGymTrainer(cfg)
    # ``trainer.run()`` currently returns None; we compose a minimal summary
    # dict from the trainer's internal counters so callers get *something*
    # useful without forcing a downstream change to the trainer API.
    asyncio.run(trainer.run())
    return {
        "steps": cfg.training.n_steps,
        "save_count": trainer._save_count,
    }


__all__ = ["train"]

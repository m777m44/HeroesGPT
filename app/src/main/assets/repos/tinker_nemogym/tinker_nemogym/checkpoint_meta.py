"""Checkpoint metadata — the JSON sidecar that rides alongside Tinker weights.

Tinker's :meth:`save_state_async` persists LoRA weights + optimizer state,
but nothing about the driver's view of the run (step counter, reward
history, dataset cursor, wandb run id). Persisting those next to the
weights lets ``resume_from_checkpoint`` pick up where it left off without
guesswork.

Format: one ``<label>.meta.json`` per save, living in
``cfg.tinker.checkpoint_dir``. Schema is forward-compatible — unknown keys
are preserved round-trip; removed keys default to ``None``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckpointMeta:
    """The portable sidecar format.

    Keys kept intentionally small + stable. Add new fields at the bottom
    and keep them optional (``None`` default) so old metadata files still
    deserialize cleanly.
    """

    step: int = 0
    save_count: int = 0
    mean_reward_history: list[float] = field(default_factory=list)
    wandb_run_id: str | None = None
    random_seed: int | None = None
    dataset_cursor: int = 0
    run_id: str | None = None
    # Unknown keys from a newer metadata file we couldn't recognise. Preserved
    # on round-trip so writing back doesn't drop them.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CheckpointMeta:
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: payload[k] for k in known if k in payload}
        extra = {k: v for k, v in payload.items() if k not in known}
        return cls(**kwargs, extra=extra)


def meta_path(checkpoint_dir: str | Path, label: str) -> Path:
    """Return the metadata path for ``<checkpoint_dir>/<label>.meta.json``."""
    return Path(checkpoint_dir).expanduser() / f"{label}.meta.json"


def save_meta(checkpoint_dir: str | Path, label: str, meta: CheckpointMeta) -> Path:
    """Write metadata atomically (write-then-rename) to the standard path."""
    target = meta_path(checkpoint_dir, label)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(meta.to_dict(), indent=2))
    tmp.replace(target)
    return target


def load_meta(checkpoint_dir: str | Path, label: str) -> CheckpointMeta | None:
    """Load metadata; return ``None`` when the file is absent or corrupt."""
    p = meta_path(checkpoint_dir, label)
    if not p.exists():
        return None
    try:
        return CheckpointMeta.from_dict(json.loads(p.read_text()))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - corrupt file
        return None


__all__ = ["CheckpointMeta", "load_meta", "meta_path", "save_meta"]

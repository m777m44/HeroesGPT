"""Structured logging helpers + run-scoped context vars.

Every training run gets a short ``run_id`` (first 8 hex chars of a UUID4) —
propagated through :class:`contextvars.ContextVar` so async tasks inherit
it without threading it manually. A small :class:`logging.Filter` injects
``run_id`` onto every log record, defaulting to ``"-"`` for records emitted
outside a run (CLI bootstrap, tests, etc.).

Two output modes:

* **Human** (default) — readable format for interactive runs and logs.
* **JSON** — one dict per record (for ingestion into log aggregators).

Usage::

    from tinker_nemogym.utils.logging import configure_logging, new_run_id, RUN_ID_VAR

    configure_logging(level="INFO", json=False)
    token = RUN_ID_VAR.set(new_run_id())
    try:
        ...
    finally:
        RUN_ID_VAR.reset(token)
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar

# ``run_id`` is a per-run short identifier. Default ``"-"`` so records
# emitted before/after a run start still format cleanly.
RUN_ID_VAR: ContextVar[str] = ContextVar("run_id", default="-")


def new_run_id() -> str:
    """Return a fresh 8-char run_id (first 8 hex chars of uuid4)."""
    return uuid.uuid4().hex[:8]


class RunIdFilter(logging.Filter):
    """Inject the current ``run_id`` onto every ``LogRecord``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = RUN_ID_VAR.get()
        return True


class _JsonFormatter(logging.Formatter):
    """Serialise each record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | int = "INFO", json: bool = False) -> None:
    """Configure the root logger for tinker-nemogym.

    Idempotent — repeated calls replace the existing handler rather than
    stacking them. Safe to call from tests and from the CLI.

    Args:
        level: Log level name (``"DEBUG"`` / ``"INFO"`` / ...) or numeric level.
        json: When True, emit JSON lines instead of human-readable strings.
    """
    root = logging.getLogger()
    # Remove any handlers we previously installed so repeated calls stay clean.
    for h in list(root.handlers):
        if getattr(h, "_tinker_nemogym", False):
            root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler._tinker_nemogym = True  # type: ignore[attr-defined]
    handler.addFilter(RunIdFilter())

    if json:
        handler.setFormatter(_JsonFormatter())
    else:
        # run_id first so multi-run log tails are easy to grep.
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(run_id)s] %(levelname)-7s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root.addHandler(handler)
    root.setLevel(level if isinstance(level, int) else level.upper())


__all__ = [
    "RUN_ID_VAR",
    "RunIdFilter",
    "configure_logging",
    "new_run_id",
]

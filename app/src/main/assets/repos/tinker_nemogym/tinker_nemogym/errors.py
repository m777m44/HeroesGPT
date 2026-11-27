"""Exception hierarchy for the tinker-nemogym library.

Single base class (:class:`TinkerNeMoGymError`) so callers can catch every
library-originating error with one ``except`` clause, plus narrow subclasses
keyed to the system layer that raised them:

* :class:`ConfigError` — invalid user config (YAML, CLI flags, env vars).
* :class:`TrainingError` — Tinker training call failed (fwd_bwd, optim,
  save_state). Wraps the underlying SDK error with context (step, op).
* :class:`ShimError` — the FastAPI completions shim failed; the most common
  variant is :class:`SamplerNotReadyError` raised when the trainer hasn't
  wired the initial sampling client yet.
* :class:`AgentDiscoveryError` — HeadServer couldn't be reached, or returned
  no agent URLs.
* :class:`CheckpointError` — save / load / resume failures.

None of these are ever raised by the public ``tinker.*`` SDK types; they are
strictly library-side. Downstream callers can still catch
:class:`tinker.AuthenticationError` / :class:`tinker.RateLimitError` etc.
directly when they need the full SDK taxonomy.
"""

from __future__ import annotations


class TinkerNeMoGymError(Exception):
    """Base for all library-raised errors."""


class ConfigError(TinkerNeMoGymError):
    """Raised when the user-supplied configuration is invalid.

    Typically wraps a :class:`pydantic.ValidationError` at the CLI / loader
    boundary so callers see a stable library-owned type.
    """


class TrainingError(TinkerNeMoGymError):
    """Raised when a Tinker training call fails.

    Wraps the underlying SDK exception with context (step, op) so error
    logs are self-describing. The original exception is attached as
    ``__cause__`` via ``raise ... from e``.
    """


class ShimError(TinkerNeMoGymError):
    """Raised by the FastAPI completions shim when a request can't be served."""


class SamplerNotReadyError(ShimError):
    """The sampler hasn't been wired yet — caller should retry shortly.

    Translated to HTTP 503 by the shim's request handlers. Typically seen
    during the brief window between ``trainer.setup()`` starting the server
    and ``set_sampling_client()`` being called for the first time.
    """


class AgentDiscoveryError(TinkerNeMoGymError):
    """Raised when the nemo-gym HeadServer can't be reached or has no agents.

    Surfaces as an actionable preflight error so operators know whether
    ``ng_run`` is running vs whether the URL itself is wrong.
    """


class CheckpointError(TinkerNeMoGymError):
    """Raised when a save/load/resume operation fails."""


__all__ = [
    "AgentDiscoveryError",
    "CheckpointError",
    "ConfigError",
    "SamplerNotReadyError",
    "ShimError",
    "TinkerNeMoGymError",
    "TrainingError",
]

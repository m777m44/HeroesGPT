"""Optional sampler↔trainer precision-gap diagnostics.

Implements the measurement instrument described in Amine Diro's HuggingFace
space *"Trainer-Generator BF16 Mismatch"*:
https://huggingface.co/spaces/aminediroHF/trainer-generator-bf16-mismatch.

For each trajectory we already have:

* ``response_logprobs[t]`` — per-token logprob stamped at **sample time** by the
  :class:`tinker.SamplingClient`. In Tinker terms this is ``log π_θ(a_t | s_t)``
  as computed by the inference kernel.

If we run a *trainer-side* forward pass on the same (prompt + response)
sequence with the ``cross_entropy`` loss, Tinker returns ``logprobs`` in the
``loss_fn_outputs`` — the training kernel's view of the same quantity. The
elementwise difference is the blog's :math:`\\beta_t`:

.. math::
    \\beta_t = f_{\\text{train}}(a_t; W_k) - f_{\\text{sampler}}(a_t; W_k)

We summarize it as ``beta_mean`` / ``beta_std`` / ``beta_abs_mean`` /
``beta_max`` (per-step scalars, emitted alongside regular training metrics).
If these values are large, the training ratio ``r = π_new / π_old`` is being
driven by precision noise rather than actual policy change, and PPO-style
clipping fires spuriously. The paper recommends either (a) use FP32 in the
generator or (b) — the cheap fix — substitute the trainer's recomputed
logprobs as the ``log π_old`` in the RL loss.

This module is small, side-effect-free, and used only by
:meth:`TinkerNeMoGymTrainer._maybe_measure_precision_gap`. Fakes in
:mod:`tinker_nemogym.testing.fakes` must also implement ``forward_async``
with a ``cross_entropy`` branch for this to exercise end-to-end in tests.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _per_token_trainer_logprobs_from_output(
    fwd_result: Any, n_datums: int
) -> list[list[float] | None]:
    """Pull per-datum trainer logprob arrays out of a ``forward`` result.

    Shape assumption: ``fwd_result.loss_fn_outputs`` is a list of
    :class:`tinker.types.LossFnOutput` (``dict[str, TensorData]``), one per
    datum, each with a ``"logprobs"`` entry. We call ``.data`` on the
    TensorData and reshape to the recorded shape when present.

    Returns a list (length ``n_datums``) where each element is either a
    list of per-token logprobs or ``None`` when the shape we got back
    didn't match expectations. We never raise — this is a diagnostic
    path, and a partial measurement is better than crashing the step.
    """
    out: list[list[float] | None] = []
    loss_outputs = getattr(fwd_result, "loss_fn_outputs", None)
    if not isinstance(loss_outputs, list):
        # Fakes / older SDKs may return a dict or None — treat as "no data".
        return [None] * n_datums
    for datum_idx in range(n_datums):
        try:
            entry = loss_outputs[datum_idx]
        except (IndexError, TypeError):
            out.append(None)
            continue
        lp_obj = entry.get("logprobs") if hasattr(entry, "get") else None
        if lp_obj is None:
            out.append(None)
            continue
        # TensorData.data is typically a sequence of floats; shape is optional.
        data = getattr(lp_obj, "data", None)
        if data is None and isinstance(lp_obj, dict):
            data = lp_obj.get("data")
        if data is None:
            out.append(None)
            continue
        try:
            arr = np.asarray(data, dtype=np.float64).reshape(-1)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(arr.tolist())
    return out


def compute_precision_gap_metrics(
    trainer_logprobs_per_datum: list[list[float] | None],
    trajectories: list[Any],  # list of RawTrajectory
) -> dict[str, float]:
    """Compute β-summary metrics given trainer-side + sampler-side logprobs.

    Both arrays are indexed by datum. For each datum the sampler provides
    ``response_logprobs`` (length == number of response tokens); the trainer
    provides an array over the full target window (length == prompt_len +
    response_len - 1). We slice off the prompt prefix before diffing.

    Returns a dict with scalar float metrics. Never raises — unusable
    entries are logged at DEBUG and skipped.
    """
    diffs: list[np.ndarray] = []
    n_skipped = 0
    for trainer_logprobs, traj in zip(trainer_logprobs_per_datum, trajectories, strict=False):
        if trainer_logprobs is None:
            n_skipped += 1
            continue
        sampler_logprobs = list(getattr(traj, "response_logprobs", []) or [])
        if not sampler_logprobs:
            n_skipped += 1
            continue
        prompt_len = len(getattr(traj, "prompt_tokens", []) or [])
        # Trainer returns logprobs over ``all_tokens[1:]`` — i.e.
        # (prompt_len - 1) prompt-prediction positions followed by
        # (response_len) response-prediction positions. We want the latter.
        response_slice_start = max(0, prompt_len - 1)
        trainer_resp = np.asarray(trainer_logprobs[response_slice_start:], dtype=np.float64)
        sampler_resp = np.asarray(sampler_logprobs, dtype=np.float64)
        # Length mismatches happen when the shim dropped a final stop token
        # or we mixed in a multi-turn rollout. Trim to shorter side.
        n = min(len(trainer_resp), len(sampler_resp))
        if n == 0:
            n_skipped += 1
            continue
        diffs.append(trainer_resp[:n] - sampler_resp[:n])
    if not diffs:
        logger.debug(
            "precision_gap: no valid (trainer, sampler) pairs "
            "(skipped=%d of %d)",
            n_skipped,
            len(trajectories),
        )
        return {}
    all_diffs = np.concatenate(diffs)
    return {
        "beta_mean": float(all_diffs.mean()),
        "beta_std": float(all_diffs.std()),
        "beta_abs_mean": float(np.abs(all_diffs).mean()),
        "beta_max": float(np.abs(all_diffs).max()),
        "beta_n_tokens": int(all_diffs.size),
        "beta_n_datums": int(len(diffs)),
        "beta_n_skipped_datums": int(n_skipped),
    }


__all__ = [
    "_per_token_trainer_logprobs_from_output",
    "compute_precision_gap_metrics",
]

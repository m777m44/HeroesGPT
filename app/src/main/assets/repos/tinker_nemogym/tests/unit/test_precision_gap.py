"""Unit tests for :mod:`tinker_nemogym.precision_gap`.

Validates both helpers in isolation with hand-crafted inputs so any
regression in β extraction logic surfaces with a precise failure rather
than buried inside a full trainer step.
"""

from __future__ import annotations

import numpy as np
import pytest

from tinker_nemogym.datum_builder import RawTrajectory
from tinker_nemogym.precision_gap import (
    _per_token_trainer_logprobs_from_output,
    compute_precision_gap_metrics,
)

# ---------------------------------------------------------------------------
# _per_token_trainer_logprobs_from_output
# ---------------------------------------------------------------------------


class _FakeTensor:
    def __init__(self, values: list[float], shape: list[int] | None = None) -> None:
        self.data = values
        self.shape = shape


class _FakeFwdOutput:
    def __init__(self, outputs: list[dict]) -> None:
        self.loss_fn_outputs = outputs
        self.metrics = {}


def test_per_token_extraction_happy_path() -> None:
    """Each datum contributes one ``logprobs`` TensorData — extract as a list."""
    fwd = _FakeFwdOutput(
        [
            {"logprobs": _FakeTensor([-0.1, -0.2, -0.3])},
            {"logprobs": _FakeTensor([-0.5, -0.6])},
        ]
    )
    out = _per_token_trainer_logprobs_from_output(fwd, n_datums=2)
    assert out == [[-0.1, -0.2, -0.3], [-0.5, -0.6]]


def test_per_token_extraction_missing_entry_returns_none() -> None:
    """Fewer entries than datums → pad with None, no raise."""
    fwd = _FakeFwdOutput([{"logprobs": _FakeTensor([-0.1])}])
    out = _per_token_trainer_logprobs_from_output(fwd, n_datums=3)
    assert out[0] == [-0.1]
    assert out[1] is None
    assert out[2] is None


def test_per_token_extraction_none_result() -> None:
    """A result object with no ``loss_fn_outputs`` attribute → all None."""

    class _Empty:
        loss_fn_outputs = None

    out = _per_token_trainer_logprobs_from_output(_Empty(), n_datums=2)
    assert out == [None, None]


# ---------------------------------------------------------------------------
# compute_precision_gap_metrics
# ---------------------------------------------------------------------------


def _traj(prompt_len: int, sampler_logprobs: list[float]) -> RawTrajectory:
    """Build a minimal RawTrajectory for β tests."""
    return RawTrajectory(
        prompt_tokens=list(range(100, 100 + prompt_len)),
        response_tokens=[0] * len(sampler_logprobs),
        response_logprobs=list(sampler_logprobs),
        reward=1.0,
    )


def test_precision_gap_basic_diff() -> None:
    """Trainer logprobs minus sampler logprobs → β stats."""
    # Trainer target window = prompt_len-1 prompt predictions + response predictions.
    # prompt_len=3 ⇒ first 2 logprobs are prompt-targets (ignored), next 2 are response.
    trainer = [[-0.5, -0.5, -0.1, -0.2]]
    trajs = [_traj(prompt_len=3, sampler_logprobs=[-0.05, -0.15])]
    beta = compute_precision_gap_metrics(trainer, trajs)
    # Elementwise diff: [-0.1 - -0.05, -0.2 - -0.15] = [-0.05, -0.05]
    assert beta["beta_n_tokens"] == 2
    assert beta["beta_mean"] == pytest.approx(-0.05)
    assert beta["beta_abs_mean"] == pytest.approx(0.05)
    assert beta["beta_max"] == pytest.approx(0.05)
    assert beta["beta_std"] == pytest.approx(0.0, abs=1e-9)


def test_precision_gap_skips_none() -> None:
    """Datums whose trainer logprobs are ``None`` are counted as skipped."""
    trajs = [
        _traj(prompt_len=2, sampler_logprobs=[-0.1, -0.2]),
        _traj(prompt_len=2, sampler_logprobs=[-0.3]),
    ]
    trainer = [
        None,  # skipped
        [-0.4, -0.5],  # prompt_len-1 = 1 prompt prediction, 1 response
    ]
    beta = compute_precision_gap_metrics(trainer, trajs)
    assert beta["beta_n_datums"] == 1
    assert beta["beta_n_skipped_datums"] == 1
    # Only datum 2 contributes: sampler [-0.3] vs trainer [-0.5] (slice index 1)
    assert beta["beta_mean"] == pytest.approx(-0.2)


def test_precision_gap_empty_returns_empty() -> None:
    """Zero valid pairs → empty dict (trainer emits no beta_* keys)."""
    assert compute_precision_gap_metrics([None], [_traj(2, [-0.1])]) == {}
    assert compute_precision_gap_metrics([], []) == {}


def test_precision_gap_trims_to_shorter() -> None:
    """Length mismatch (extra trainer logprobs or extra sampler) → trim
    to common length, no raise."""
    trainer = [[-0.1, -0.2, -0.3, -0.4, -0.5]]  # prompt_len=2 → prompt preds=1, resp=4
    trajs = [_traj(prompt_len=2, sampler_logprobs=[-0.05, -0.05])]  # only 2 sampler logprobs
    beta = compute_precision_gap_metrics(trainer, trajs)
    # Compare only the first min(4, 2) = 2 response-slot logprobs.
    # trainer response slice = [-0.2, -0.3, -0.4, -0.5][:2] = [-0.2, -0.3]
    # diff = [-0.15, -0.25]
    assert beta["beta_n_tokens"] == 2
    assert beta["beta_mean"] == pytest.approx(-0.2)


def test_precision_gap_determinism() -> None:
    """Pure function: same inputs → same outputs bit-for-bit."""
    trainer = [[-0.1, -0.2, -0.3]]
    trajs = [_traj(prompt_len=2, sampler_logprobs=[-0.05, -0.15])]
    a = compute_precision_gap_metrics(trainer, trajs)
    b = compute_precision_gap_metrics(trainer, trajs)
    assert a == b


def test_precision_gap_matches_numpy_reference() -> None:
    """Cross-check β stats against a direct numpy computation."""
    rng = np.random.default_rng(42)
    prompt_len = 5
    response_len = 20
    sampler = rng.standard_normal(response_len).tolist()
    trainer_prompt_preds = rng.standard_normal(prompt_len - 1).tolist()
    trainer_response_preds = rng.standard_normal(response_len).tolist()
    trainer = [trainer_prompt_preds + trainer_response_preds]
    trajs = [_traj(prompt_len=prompt_len, sampler_logprobs=sampler)]
    beta = compute_precision_gap_metrics(trainer, trajs)
    diffs = np.asarray(trainer_response_preds) - np.asarray(sampler)
    assert beta["beta_mean"] == pytest.approx(float(diffs.mean()))
    assert beta["beta_std"] == pytest.approx(float(diffs.std()))
    assert beta["beta_abs_mean"] == pytest.approx(float(np.abs(diffs).mean()))
    assert beta["beta_max"] == pytest.approx(float(np.abs(diffs).max()))

"""Tests for tinker_nemogym.datum_builder (extraction-only stage)."""

from __future__ import annotations

import numpy as np
import pytest
import tinker

from tinker_nemogym.datum_builder import (
    PROMPT_LOGPROB_SENTINEL,
    RawTrajectory,
    build_batch,
    build_datum,
    compute_advantages,
    extract_trajectory,
)

SAMPLE_RESPONSE = {
    "reward": 0.75,
    "response": {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}],
        "prompt_token_ids": [10, 20, 30],
        "generation_token_ids": [40, 50, 60, 70],
        "generation_log_probs": [-0.1, -0.2, -0.3, -0.4],
    },
    "trajectory_id": "abc",
    "steps": 3,
}


def test_extract_trajectory_basic():
    """Test 1: happy path — all fields parsed, correct types."""
    t = extract_trajectory(SAMPLE_RESPONSE)
    assert isinstance(t, RawTrajectory)
    assert t.reward == 0.75
    assert t.prompt_tokens == [10, 20, 30]
    assert t.response_tokens == [40, 50, 60, 70]
    assert len(t.response_logprobs) == 4
    assert t.response_logprobs == [-0.1, -0.2, -0.3, -0.4]


def test_extract_trajectory_metadata_captures_extra_keys():
    """Test 2: metadata picks up everything except reward/response."""
    t = extract_trajectory(SAMPLE_RESPONSE)
    assert t.metadata == {"trajectory_id": "abc", "steps": 3}


def test_extract_trajectory_missing_token_ids_raises():
    """Test 3: missing generation_token_ids → ValueError."""
    bad = {
        "reward": 0.1,
        "response": {
            "prompt_token_ids": [1, 2],
            # generation_token_ids missing
            "generation_log_probs": [-0.5],
        },
    }
    with pytest.raises(ValueError, match="token_ids/logprobs"):
        extract_trajectory(bad)


def test_extract_trajectory_length_mismatch_raises():
    """Test 4: generation_token_ids and generation_log_probs length mismatch → ValueError."""
    bad = {
        "reward": 0.1,
        "response": {
            "prompt_token_ids": [1, 2],
            "generation_token_ids": [3, 4, 5],
            "generation_log_probs": [-0.1, -0.2],  # only 2
        },
    }
    with pytest.raises(ValueError, match="length mismatch"):
        extract_trajectory(bad)


# ---------- compute_advantages (tests 5-7) ----------


def test_compute_advantages_zero_mean():
    """Test 5: GRPO centering → mean ≈ 0, rank-preserving."""
    rewards = [1.0, 0.5, 0.0, 0.5]
    adv = compute_advantages(rewards)
    assert abs(float(np.mean(adv))) < 1e-6
    assert adv[0] > adv[2]  # higher reward → higher advantage
    # Explicit values: mean = 0.5
    np.testing.assert_allclose(adv, [0.5, 0.0, -0.5, 0.0], atol=1e-6)


def test_compute_advantages_single_element_returns_zero():
    """Test 6: a single-element group returns [0.0]."""
    adv = compute_advantages([0.9])
    assert adv == [0.0]


def test_compute_advantages_empty_returns_empty():
    """Test 7: empty input returns empty list (defensive)."""
    assert compute_advantages([]) == []


# ---------- build_datum (tests 8-12) ----------


def _make_traj(
    prompt=(10, 20, 30),
    response=(40, 50, 60, 70),
    lps=(-0.1, -0.2, -0.3, -0.4),
    reward=0.5,
) -> RawTrajectory:
    return RawTrajectory(
        prompt_tokens=list(prompt),
        response_tokens=list(response),
        response_logprobs=list(lps),
        reward=reward,
        metadata={},
    )


def test_build_datum_shapes_and_dtypes():
    """Test 8: target/advantages/logprobs arrays have correct shape & dtype."""
    traj = _make_traj()
    datum = build_datum(traj, advantage=0.25)
    assert isinstance(datum, tinker.Datum)

    target = datum.loss_fn_inputs["target_tokens"].to_numpy()
    adv = datum.loss_fn_inputs["advantages"].to_numpy()
    lp = datum.loss_fn_inputs["logprobs"].to_numpy()

    # total tokens = 3 prompt + 4 response = 7; targets = 6
    assert target.shape == (6,)
    assert adv.shape == (6,)
    assert lp.shape == (6,)
    assert target.dtype == np.int64
    assert adv.dtype == np.float32
    assert lp.dtype == np.float32


def test_build_datum_shift_correctness():
    """Test 9: input = all_tokens[:-1]; target = all_tokens[1:]."""
    traj = _make_traj()
    datum = build_datum(traj, advantage=0.25)

    # input: tinker.ModelInput via from_ints supports .to_ints()
    input_ints = datum.model_input.to_ints()
    assert input_ints == [10, 20, 30, 40, 50, 60]

    target = datum.loss_fn_inputs["target_tokens"].to_numpy().tolist()
    assert target == [20, 30, 40, 50, 60, 70]


def test_build_datum_advantage_masking():
    """Test 10: advantages are 0.0 on prompt-shift positions, `adv` on response positions."""
    traj = _make_traj()
    datum = build_datum(traj, advantage=0.25)
    adv = datum.loss_fn_inputs["advantages"].to_numpy()

    # len(prompt) - 1 = 2 prompt-shift positions
    assert (adv[:2] == 0.0).all()
    # 4 response-token positions with advantage 0.25
    assert (adv[2:] == np.float32(0.25)).all()


def test_build_datum_logprob_sentinel_and_observed():
    """Test 11: logprobs are PROMPT_LOGPROB_SENTINEL on prompt, observed on response."""
    traj = _make_traj()
    datum = build_datum(traj, advantage=0.25)
    lp = datum.loss_fn_inputs["logprobs"].to_numpy()

    assert PROMPT_LOGPROB_SENTINEL == 1.0
    # prompt positions: sentinel
    assert (lp[:2] == np.float32(PROMPT_LOGPROB_SENTINEL)).all()
    # response positions: observed
    np.testing.assert_allclose(lp[2:], [-0.1, -0.2, -0.3, -0.4], atol=1e-6)


def test_build_datum_minimal_single_token_prompt():
    """Test 12: len(prompt)==1 → 0 prompt-shift positions (all targets are response tokens)."""
    traj = _make_traj(
        prompt=(99,),
        response=(40, 50, 60),
        lps=(-0.1, -0.2, -0.3),
    )
    datum = build_datum(traj, advantage=-0.5)

    input_ints = datum.model_input.to_ints()
    assert input_ints == [99, 40, 50]

    target = datum.loss_fn_inputs["target_tokens"].to_numpy().tolist()
    assert target == [40, 50, 60]

    adv = datum.loss_fn_inputs["advantages"].to_numpy()
    lp = datum.loss_fn_inputs["logprobs"].to_numpy()
    # 0 prompt-shift positions — everything is a response position
    assert adv.shape == (3,)
    assert (adv == np.float32(-0.5)).all()
    np.testing.assert_allclose(lp, [-0.1, -0.2, -0.3], atol=1e-6)


# ---------- build_batch (tests 13-16) ----------


def test_build_batch_two_varied_groups():
    """Test 13: two groups with varied rewards → 2*group_size datums, opposite advantages."""
    g1 = [_make_traj(reward=1.0), _make_traj(reward=0.0)]
    g2 = [_make_traj(reward=0.5), _make_traj(reward=0.1)]
    datums, meta = build_batch({"p1": g1, "p2": g2})

    assert len(datums) == 4
    assert meta["n_groups"] == 2
    assert meta["n_dropped_constant"] == 0
    assert meta["n_datums"] == 4
    # Mean of all 4 rewards
    assert abs(meta["mean_reward"] - ((1.0 + 0.0 + 0.5 + 0.1) / 4.0)) < 1e-6

    # Advantages on first group: g1 centered = [+0.5, -0.5]
    adv0 = datums[0].loss_fn_inputs["advantages"].to_numpy()
    adv1 = datums[1].loss_fn_inputs["advantages"].to_numpy()
    # Response positions carry the advantage
    assert adv0[-1] == pytest.approx(0.5, abs=1e-6)
    assert adv1[-1] == pytest.approx(-0.5, abs=1e-6)


def test_build_batch_drops_constant_reward_group():
    """Test 14: all-equal rewards → group dropped when drop_constant_reward=True."""
    g_const = [_make_traj(reward=1.0), _make_traj(reward=1.0)]
    g_varied = [_make_traj(reward=1.0), _make_traj(reward=0.0)]
    datums, meta = build_batch({"const": g_const, "varied": g_varied})

    assert meta["n_groups"] == 2
    assert meta["n_dropped_constant"] == 1
    assert len(datums) == 2  # only the varied group
    assert meta["n_datums"] == 2


def test_build_batch_keeps_constant_when_disabled():
    """Test 15: drop_constant_reward=False keeps the group; advantages are all zero there."""
    g_const = [_make_traj(reward=1.0), _make_traj(reward=1.0)]
    datums, meta = build_batch({"const": g_const}, drop_constant_reward=False)

    assert meta["n_dropped_constant"] == 0
    assert len(datums) == 2
    for d in datums:
        adv = d.loss_fn_inputs["advantages"].to_numpy()
        assert (adv == 0.0).all()


def test_build_batch_empty_input():
    """Test 16: empty dict → no datums, mean_reward=0.0, counts zero."""
    datums, meta = build_batch({})
    assert datums == []
    assert meta == {
        "mean_reward": 0.0,
        "n_groups": 0,
        "n_dropped_constant": 0,
        "n_dropped_oversize": 0,
        "n_datums": 0,
    }


def test_build_batch_skips_oversize_datums_with_warning(caplog):
    """Review 03 §2.2: oversize trajectories are skipped + logged, count surfaced."""

    def _traj(n_resp: int, reward: float) -> RawTrajectory:
        return RawTrajectory(
            prompt_tokens=[1, 2, 3],
            response_tokens=list(range(100, 100 + n_resp)),
            response_logprobs=[-0.1] * n_resp,
            reward=reward,
        )

    # Group with varied rewards — one trajectory is way too long, the other fits.
    group = [_traj(n_resp=2, reward=0.0), _traj(n_resp=200, reward=1.0)]
    with caplog.at_level("WARNING"):
        datums, meta = build_batch({"g": group}, max_trainer_tokens=100)

    assert meta["n_dropped_oversize"] == 1
    assert meta["n_datums"] == 1  # the smaller one survived
    assert len(datums) == 1
    assert any("Skipping oversize datum" in rec.message for rec in caplog.records)


def test_build_batch_no_cap_accepts_everything():
    """max_trainer_tokens=None (default) disables the cap."""

    def _traj(n_resp: int, reward: float) -> RawTrajectory:
        return RawTrajectory(
            prompt_tokens=[1, 2, 3],
            response_tokens=list(range(100, 100 + n_resp)),
            response_logprobs=[-0.1] * n_resp,
            reward=reward,
        )

    group = [_traj(n_resp=500, reward=0.0), _traj(n_resp=500, reward=1.0)]
    _datums, meta = build_batch({"g": group})  # no max_trainer_tokens
    assert meta["n_dropped_oversize"] == 0
    assert meta["n_datums"] == 2


def test_extract_trajectory_captures_usage_and_id_in_metadata():
    """Review 02 §4.2: extract_trajectory must stash response.id / usage / n_turns on metadata."""
    run_response = {
        "reward": 0.5,
        "response": {
            "id": "resp_abc123",
            "usage": {"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
            "n_turns": 3,
            "prompt_token_ids": [1, 2, 3],
            "generation_token_ids": [4, 5],
            "generation_log_probs": [-0.1, -0.2],
        },
    }
    traj = extract_trajectory(run_response)
    assert traj.metadata["response_id"] == "resp_abc123"
    assert traj.metadata["response_usage"] == {
        "prompt_tokens": 42,
        "completion_tokens": 17,
        "total_tokens": 59,
    }
    assert traj.metadata["response_n_turns"] == 3


def test_extract_trajectory_omits_absent_observability_fields():
    """If usage / id / n_turns are missing, metadata doesn't gain stub keys."""
    run_response = {
        "reward": 1.0,
        "response": {
            "prompt_token_ids": [1],
            "generation_token_ids": [2],
            "generation_log_probs": [-0.5],
        },
    }
    traj = extract_trajectory(run_response)
    assert "response_id" not in traj.metadata
    assert "response_usage" not in traj.metadata
    assert "response_n_turns" not in traj.metadata

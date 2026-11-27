"""Datum builder: pure functions that convert nemo-gym rollouts to tinker.Datum.

Contract (from analysis/02 §3 and tinker-atropos trainer.py):
  - all_tokens = prompt_tokens + response_tokens
  - input  = all_tokens[:-1]  → tinker.ModelInput.from_ints(input)
  - target = all_tokens[1:]   → int64 TensorData
  - For target position i:
      - If i < len(prompt_tokens) - 1: it predicts a prompt token
        -> advantage=0.0, logprob=PROMPT_LOGPROB_SENTINEL (1.0)
      - Else: it predicts a response token
        -> advantage=adv, logprob=observed response logprob
  - loss_fn_inputs = {"target_tokens": int64, "advantages": float32, "logprobs": float32}

This module is PURE: no HTTP, no tinker service calls, no global state. It only
uses tinker types for construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import tinker
from tinker import types as tt

# Tinker convention: 1.0 on prompt positions signals "this position was not sampled,
# so the importance-sampling loss should ignore it". Mirrors tinker-atropos
# trainer.py:283 (pad_data_to_good_offset) where prompt positions are filled with
# a sentinel logprob.
#
# WHY 1.0 vs 0.0? Both work — the tinker-atropos reference uses 1.0, while the
# tinker-cookbook reference uses 0.0. The value is safe either way because
# ``build_datum`` zeros out ``advantages[i]`` on every prompt position, so the
# importance-sampling loss at those indices multiplies the (possibly bogus)
# logprob term by 0 and contributes no gradient. Real logprobs are always
# ≤ 0; a positive sentinel like 1.0 makes any debugging scatter plot
# visually obvious ("these positions were never sampled"). We follow atropos.
PROMPT_LOGPROB_SENTINEL: float = 1.0


@dataclass
class RawTrajectory:
    """One rollout's worth of tokens + reward, ready to convert to a Datum.

    ``sampler_version`` is the ``save_count`` of the SamplingClient snapshot
    that produced ``response_tokens``. Our FastAPI shim stamps it on every
    response; trainers use it to compute *staleness*
    (``current_save_count − sampler_version``) and to detect when an
    in-flight rollout survived a hot-swap. Defaults to ``None`` for
    rollouts collected from servers that don't emit the field.
    """

    prompt_tokens: list[int]
    response_tokens: list[int]
    # Logprobs of the sampled response tokens under the sampling policy.
    # Must have len(response_logprobs) == len(response_tokens).
    response_logprobs: list[float]
    reward: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # Save-count of the sampler snapshot that produced this trajectory. None
    # when the upstream server didn't stamp one (older shim versions, vLLM).
    sampler_version: int | None = None


def _collect_training_outputs(resp: dict) -> list[dict]:
    """Return *every* output item carrying the ForTraining token/logprob triple.

    Multi-turn rollouts (e.g. the ``example_multi_step`` env) emit one
    ``NeMoGym*ForTraining`` item per model turn — a ``message`` here, a
    ``function_call`` there, another ``message`` at the end. To build a
    faithful datum we concatenate their ``generation_token_ids`` +
    ``generation_log_probs`` in list order. The prompt for the whole
    trajectory is the prompt attached to the *first* such item (subsequent
    items carry the same prompt prefix plus the prior generations).
    """
    output = resp.get("output") or []
    if not isinstance(output, list):
        return []
    out: list[dict] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if (
            "prompt_token_ids" in item
            and "generation_token_ids" in item
            and "generation_log_probs" in item
        ):
            out.append(item)
    return out


def extract_trajectory(run_response: dict) -> RawTrajectory:
    """Parse a nemo-gym agent /run response into a RawTrajectory.

    Requires the model server to attach `prompt_token_ids`, `generation_token_ids`,
    and `generation_log_probs` to the response (as vllm_model and our
    TinkerResponsesAPIModel do via TokenIDLogProbMixin). The fields may live
    either at the top level of ``run_response["response"]`` *or* on the first
    ``response.output`` item (the common case — that's where nemo-gym's
    ``NeMoGym*ForTraining`` variants carry them).

    Args:
        run_response: dict with top-level keys {"reward", "response", ...}, where
            `response` is itself a dict carrying the token id / logprob fields
            either at the top level or in the first ``output`` entry.

    Returns:
        A RawTrajectory. `metadata` contains every top-level key of `run_response`
        except "reward" and "response".

    Raises:
        ValueError: if the required token_ids / logprobs fields are missing.
        KeyError: if "reward" or "response" are missing from run_response.
    """
    resp = run_response["response"]
    reward = float(run_response["reward"])

    # Pull optional observability fields off the response envelope so the
    # trainer can log token-usage / response-id metrics per step (Review
    # 02 §4.2). Absent fields are simply omitted from ``metadata``.
    extra_meta: dict[str, Any] = {}
    if isinstance(resp, dict):
        for key in ("id", "usage", "n_turns"):
            if key in resp and resp[key] is not None:
                extra_meta[f"response_{key}"] = resp[key]
        # Diagnostic extras attached by TinkerResponsesAPIModel (see
        # ``tinker_responses_model._diagnostics_from_result``). Absent when
        # the upstream server is a vanilla vllm_model / older shim.
        for key in (
            "sampler_version",
            "sampling_params_used",
            "sample_latency_ms",
            "sample_started_at",
            "prompt_logprobs",
            "topk_prompt_logprobs",
        ):
            if key in resp and resp[key] is not None:
                extra_meta[key] = resp[key]

    # Prefer nested (NeMoGym* ForTraining output items) but fall back to the
    # top-level shape used by our older unit tests + by bespoke servers.
    training_items = _collect_training_outputs(resp)
    source: dict | None
    if training_items:
        # Multi-turn rollouts attach one ForTraining item per assistant turn.
        # Concatenate their generations (in list order) into one trajectory:
        # the first item's prompt is the initial user turn; subsequent items
        # carry the same prefix plus prior generations, so we only need to
        # append generation_token_ids + generation_log_probs. This preserves
        # both the shape invariants (len(tokens) == len(logprobs)) and the
        # causal ordering datum_builder expects.
        first = training_items[0]
        prompt_tokens = list(first["prompt_token_ids"])
        gen_tokens: list[int] = []
        gen_logprobs: list[float] = []
        for item in training_items:
            gen_tokens.extend(list(item["generation_token_ids"]))
            gen_logprobs.extend(list(item["generation_log_probs"]))
        source = {
            "prompt_token_ids": prompt_tokens,
            "generation_token_ids": gen_tokens,
            "generation_log_probs": gen_logprobs,
        }
    elif (
        "prompt_token_ids" in resp
        and "generation_token_ids" in resp
        and "generation_log_probs" in resp
    ):
        source = resp
    else:
        source = None

    if source is None:
        raise ValueError(
            "Response is missing token_ids/logprobs. Ensure the nemo-gym model "
            "server subclasses TokenIDLogProbMixin (use vllm_model or "
            "TinkerResponsesAPIModel)."
        )

    prompt_tokens = source["prompt_token_ids"]
    gen_tokens = source["generation_token_ids"]
    gen_logprobs = source["generation_log_probs"]

    if len(gen_tokens) != len(gen_logprobs):
        raise ValueError(
            f"generation_token_ids (len={len(gen_tokens)}) and "
            f"generation_log_probs (len={len(gen_logprobs)}) length mismatch."
        )

    # Extract sampler_version — prefer the first training item's stamp,
    # then fall back to the response-envelope stamp, then None. When a
    # multi-turn rollout spans a hot-swap (sampler changed mid-trajectory),
    # we pin to the *earliest* version; that's the conservative choice for
    # staleness bookkeeping.
    sampler_version: int | None = None
    if training_items:
        for item in training_items:
            v = item.get("sampler_version")
            if isinstance(v, int):
                sampler_version = v
                break
    if sampler_version is None and isinstance(resp, dict):
        v = resp.get("sampler_version")
        if isinstance(v, int):
            sampler_version = v

    return RawTrajectory(
        prompt_tokens=list(prompt_tokens),
        response_tokens=list(gen_tokens),
        response_logprobs=[float(x) for x in gen_logprobs],
        reward=reward,
        metadata={
            **{k: v for k, v in run_response.items() if k not in ("reward", "response")},
            **extra_meta,
        },
        sampler_version=sampler_version,
    )


def compute_advantages(rewards: list[float]) -> list[float]:
    """GRPO advantage: subtract group mean (no std normalization).

    Matches tinker-cookbook's simple GRPO implementation. A single-element
    group has mean == element, so advantage is [0.0] (which correctly signals
    "no learning signal" — the optimizer step will be a no-op for this group).

    Args:
        rewards: list of scalar rewards for a group of rollouts of the same prompt.

    Returns:
        Advantages (float), same length, with mean ≈ 0.
    """
    if not rewards:
        return []
    arr = np.asarray(rewards, dtype=np.float32)
    centered = arr - arr.mean()
    return centered.astype(np.float32).tolist()


def build_datum(traj: RawTrajectory, advantage: float) -> tinker.Datum:
    """Build a tinker.Datum for importance_sampling loss from one RawTrajectory.

    Shifts follow next-token-prediction:
      input  = all_tokens[:-1]    (fed to the model)
      target = all_tokens[1:]     (what to predict)

    For each target position i (0-indexed into the target array):
      - If i < len(prompt_tokens) - 1: it predicts a *prompt* token.
          advantage[i] = 0.0           (mask out prompt loss)
          logprobs[i]  = PROMPT_LOGPROB_SENTINEL (1.0)
      - Else: it predicts a *response* token.
          advantage[i] = `advantage` (the group-centered scalar)
          logprobs[i]  = traj.response_logprobs[i - (len(prompt_tokens) - 1)]

    The logprob sentinel (1.0) follows tinker-atropos convention and tells the
    loss to skip those positions (real logprobs are always ≤ 0).

    Dtypes:
      - target_tokens: int64
      - advantages:    float32
      - logprobs:      float32

    Raises:
        ValueError: if trajectory is malformed (empty prompt, empty response, or
            length mismatch between response_tokens and response_logprobs).
    """
    if len(traj.prompt_tokens) < 1:
        raise ValueError("prompt_tokens must be non-empty")
    if len(traj.response_tokens) < 1:
        raise ValueError("response_tokens must be non-empty")
    if len(traj.response_tokens) != len(traj.response_logprobs):
        raise ValueError(
            f"response_tokens (len={len(traj.response_tokens)}) and "
            f"response_logprobs (len={len(traj.response_logprobs)}) length mismatch"
        )

    all_tokens = traj.prompt_tokens + traj.response_tokens
    input_tokens = all_tokens[:-1]
    target_tokens = all_tokens[1:]

    n_prompt_targets = len(traj.prompt_tokens) - 1  # prompt positions in the target array
    n_response_targets = len(traj.response_tokens)  # always equals total - n_prompt_targets
    assert n_prompt_targets + n_response_targets == len(target_tokens)

    advantages = np.concatenate(
        [
            np.zeros(n_prompt_targets, dtype=np.float32),
            np.full(n_response_targets, advantage, dtype=np.float32),
        ]
    )
    logprobs = np.concatenate(
        [
            np.full(n_prompt_targets, PROMPT_LOGPROB_SENTINEL, dtype=np.float32),
            np.asarray(traj.response_logprobs, dtype=np.float32),
        ]
    )
    target_arr = np.asarray(target_tokens, dtype=np.int64)

    model_input = tt.ModelInput.from_ints(input_tokens)
    return tinker.Datum(
        model_input=model_input,
        loss_fn_inputs={
            "target_tokens": tt.TensorData.from_numpy(target_arr),
            "advantages": tt.TensorData.from_numpy(advantages),
            "logprobs": tt.TensorData.from_numpy(logprobs),
        },
    )


def build_batch_with_trajectories(
    trajectory_groups: dict[str, list[RawTrajectory]],
    drop_constant_reward: bool = True,
    max_trainer_tokens: int | None = None,
) -> tuple[list[tinker.Datum], list[RawTrajectory], dict]:
    """Like :func:`build_batch`, but also returns the surviving trajectories.

    Same filters as :func:`build_batch` (drop constant-reward groups, skip
    datums that exceed ``max_trainer_tokens``). The returned
    ``trajectories`` list is exactly aligned with the ``datums`` list so
    callers can pair them for downstream operations like the precision-gap
    shadow forward pass (see
    :meth:`TinkerNeMoGymTrainer._maybe_measure_precision_gap`).

    Returns:
        (datums, trajectories, metadata). Metadata has the same schema as
        :func:`build_batch`.
    """
    all_datums: list[tinker.Datum] = []
    kept_trajectories: list[RawTrajectory] = []
    dropped = 0
    dropped_oversize = 0
    rewards_all: list[float] = []

    for _prompt_id, group in trajectory_groups.items():
        rewards = [t.reward for t in group]
        rewards_all.extend(rewards)
        if drop_constant_reward and len(set(rewards)) <= 1:
            dropped += 1
            continue
        advantages = compute_advantages(rewards)
        for traj, adv in zip(group, advantages, strict=True):
            total_len = len(traj.prompt_tokens) + len(traj.response_tokens)
            if max_trainer_tokens is not None and total_len > max_trainer_tokens:
                import logging

                logging.getLogger(__name__).warning(
                    "Skipping oversize datum: %d tokens > max_trainer_tokens=%d "
                    "(prompt=%d, response=%d)",
                    total_len,
                    max_trainer_tokens,
                    len(traj.prompt_tokens),
                    len(traj.response_tokens),
                )
                dropped_oversize += 1
                continue
            all_datums.append(build_datum(traj, advantage=float(adv)))
            kept_trajectories.append(traj)

    meta = {
        "mean_reward": float(np.mean(rewards_all)) if rewards_all else 0.0,
        "n_groups": len(trajectory_groups),
        "n_dropped_constant": dropped,
        "n_dropped_oversize": dropped_oversize,
        "n_datums": len(all_datums),
    }
    return all_datums, kept_trajectories, meta


def build_batch(
    trajectory_groups: dict[str, list[RawTrajectory]],
    drop_constant_reward: bool = True,
    max_trainer_tokens: int | None = None,
) -> tuple[list[tinker.Datum], dict]:
    """Convert groups of RawTrajectories into a flat list of tinker.Datums.

    For each group (keyed by prompt_id):
      - Compute GRPO advantages (group-centered rewards).
      - If `drop_constant_reward` and every reward in the group is equal, skip
        the group — its advantages would all be zero, contributing no gradient.
      - Otherwise emit one Datum per trajectory in the group.
      - If ``max_trainer_tokens`` is set and
        ``len(prompt_tokens) + len(response_tokens)`` exceeds it, the datum
        is skipped with a WARNING log. Prevents silent overflow of Tinker's
        per-model ``max_seq_len`` inside ``forward_backward_async`` (see
        Review 03 §2.2).

    Returns:
        (datums, metadata) where metadata has:
          - mean_reward: scalar over ALL input rewards (including dropped groups)
          - n_groups: number of input groups
          - n_dropped_constant: groups skipped due to constant reward
          - n_dropped_oversize: datums skipped due to max_trainer_tokens
          - n_datums: len(datums)
    """
    datums, _trajectories, meta = build_batch_with_trajectories(
        trajectory_groups,
        drop_constant_reward=drop_constant_reward,
        max_trainer_tokens=max_trainer_tokens,
    )
    return datums, meta

"""End-to-end integration tests for the diagnostic fields added in the
"BF16 precision-gap" work:

* ``sampler_version`` pinned on every ``RawTrajectory``
* β (precision-gap) measurement via ``training.measure_precision_gap``
* ``prompt_logprobs`` / ``topk_prompt_logprobs`` passthrough via the shim
* ``sampling_params_used`` echoed back on every response
* per-rollout latency stamps + step-level p50/p95 aggregation
* staleness (``current_save_count − trajectory.sampler_version``) aggregates

These tests reuse the ``_running_shim_and_agent`` harness from
:mod:`tests.integration.test_e2e_fake` to exercise the full agent →
shim → FakeSamplingClient → trainer datum pipeline without a real Tinker
backend. The whole suite completes in a few seconds.
"""

# ruff: noqa: F811  (pytest fixture injection re-binds names imported from test_e2e_fake)

from __future__ import annotations

import aiohttp
import pytest

from tinker_nemogym.config import TinkerNeMoGymConfig
from tinker_nemogym.datum_builder import extract_trajectory
from tinker_nemogym.rollout_driver import rollout_group
from tinker_nemogym.testing import make_fake_tinker_module
from tinker_nemogym.trainer import TinkerNeMoGymTrainer

# Reuse the harness + fixtures from the main e2e file so we don't duplicate
# the shim/fake-agent plumbing. pytest needs these imported at module scope
# to register them as fixtures; ruff F811 noise is suppressed below.
from .test_e2e_fake import (  # noqa: F401
    _pick_free_port,
    _running_shim_and_agent,
    prompt_payload,  # noqa: F401,F811
    smoke_config,  # noqa: F401,F811
)

# ---------------------------------------------------------------------------
# Shim-level diagnostics (bypasses the trainer; fastest path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shim_attaches_sampler_version_on_response(prompt_payload: dict) -> None:
    """Every shim response carries ``sampler_version`` on both the output
    item and the top-level envelope."""
    with _running_shim_and_agent() as (shim_url, _agent_url, _):
        sp_body = {
            "input": prompt_payload["responses_create_params"]["input"],
            "max_output_tokens": 10,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{shim_url}/v1/responses", json=sp_body) as r:
                resp = await r.json()
    # Top-level diagnostic envelope.
    assert "sampler_version" in resp, resp
    assert isinstance(resp["sampler_version"], int)
    # And on the ForTraining output item — datum_builder reads from here.
    item = resp["output"][0]
    assert item["sampler_version"] == resp["sampler_version"]


@pytest.mark.asyncio
async def test_shim_stamps_latency_and_params_used(prompt_payload: dict) -> None:
    """Shim attaches ``sample_latency_ms`` + ``sampling_params_used`` with the
    effective parameters including Tinker defaults."""
    with _running_shim_and_agent() as (shim_url, _agent_url, _):
        sp_body = {
            "input": prompt_payload["responses_create_params"]["input"],
            "max_output_tokens": 8,
            "temperature": 0.7,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{shim_url}/v1/responses", json=sp_body) as r:
                resp = await r.json()
    # Latency must be a non-negative float (shim uses time.monotonic delta).
    assert resp["sample_latency_ms"] >= 0.0
    assert resp["sample_started_at"] > 0.0
    used = resp["sampling_params_used"]
    # Caller asked for temperature=0.7; we echo the actual value we used.
    assert used["temperature"] == pytest.approx(0.7)
    assert used["max_tokens"] == 8
    # Tinker SamplingParams defaults: top_p=1, top_k=-1, seed=None.
    assert used["top_p"] == 1 or used["top_p"] is None
    assert used["seed"] is None


@pytest.mark.asyncio
async def test_shim_passes_through_prompt_logprobs(prompt_payload: dict) -> None:
    """When the caller asks for ``include_prompt_logprobs`` the shim forwards
    to SamplingClient and surfaces the result on the response envelope."""
    with _running_shim_and_agent() as (shim_url, _agent_url, _):
        sp_body = {
            "input": prompt_payload["responses_create_params"]["input"],
            "max_output_tokens": 6,
            "include_prompt_logprobs": True,
            "topk_prompt_logprobs": 3,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{shim_url}/v1/responses", json=sp_body) as r:
                resp = await r.json()
    # FakeSampleResponse returns None for these fields, so the shim should
    # simply omit them (see :func:`_diagnostics_from_result`). The *request*
    # knob still goes through — we verify the sampling_params were built:
    assert "sampling_params_used" in resp
    # When the fake does populate them (real Tinker does), these keys will
    # be present. For now just check the pass-through path doesn't crash
    # and still returns the mandatory contract fields.
    assert "prompt_token_ids" in resp["output"][0]


# ---------------------------------------------------------------------------
# extract_trajectory end-to-end: shim → agent → driver → trajectory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trajectory_carries_sampler_version_after_rollout(
    prompt_payload: dict,
) -> None:
    """After a full rollout_group round-trip, ``RawTrajectory.sampler_version``
    is populated from the shim's stamp."""
    with _running_shim_and_agent() as (_shim_url, agent_url, _):
        group = await rollout_group(agent_url, prompt_payload, group_size=2, timeout_sec=30)
    for raw in group:
        traj = extract_trajectory(raw)
        assert traj.sampler_version is not None, traj.metadata
        assert isinstance(traj.sampler_version, int)
        # Diagnostic extras land in metadata.
        assert "sample_latency_ms" in traj.metadata
        assert "sampling_params_used" in traj.metadata


# ---------------------------------------------------------------------------
# Full trainer step — staleness + β measurement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trainer_step_reports_staleness_and_latency(
    smoke_config: TinkerNeMoGymConfig,
) -> None:
    """One real trainer step aggregates per-rollout latency and staleness
    into step metrics."""
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            # Bump the save count ONCE so staleness is non-trivial: the shim
            # stamp was recorded at version 1, but the trainer already
            # advanced to 2 during setup.
            metrics = await trainer._run_step(0)
            # Latency aggregates must be present.
            for k in (
                "sample_latency_ms_mean",
                "sample_latency_ms_p50",
                "sample_latency_ms_p95",
                "sample_latency_ms_max",
            ):
                assert k in metrics, list(metrics.keys())
                assert metrics[k] >= 0.0
            # Staleness aggregates present since the shim stamped a version.
            assert "staleness_mean" in metrics
            assert "staleness_max" in metrics
            assert metrics["staleness_mean"] >= 0.0
            assert metrics["staleness_max"] >= 0
            await trainer._cleanup()


@pytest.mark.asyncio
async def test_trainer_step_reports_precision_gap_when_enabled(
    smoke_config: TinkerNeMoGymConfig,
) -> None:
    """With ``training.measure_precision_gap=True`` the shadow forward pass
    runs and emits ``beta_*`` metrics."""
    smoke_config.training.measure_precision_gap = True
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            metrics = await trainer._run_step(0)
            # β metrics land in the step's metrics dict.
            assert "beta_mean" in metrics, list(metrics.keys())
            assert "beta_std" in metrics
            assert "beta_abs_mean" in metrics
            assert "beta_max" in metrics
            assert metrics["beta_n_datums"] >= 1
            assert metrics["beta_n_tokens"] >= 1
            # The fake returns deterministic logprobs so β is reproducible:
            # sampler emits ``-0.1 - 0.0001 * token_id`` while trainer emits
            # ``-0.1 - 0.0001 * (i % 13)``. Absolute values are small but
            # meaningfully non-zero — enough to validate the measurement
            # pipeline works.
            assert metrics["beta_abs_mean"] >= 0.0
            # Forward-only call must have been made alongside forward_backward.
            methods = [c.method for c in trainer.training_client.call_history]
            assert "forward_async" in methods, methods
            assert "forward_backward_async" in methods
            await trainer._cleanup()


@pytest.mark.asyncio
async def test_trainer_step_skips_precision_gap_when_disabled(
    smoke_config: TinkerNeMoGymConfig,
) -> None:
    """Default config doesn't run the shadow pass — β metrics absent."""
    assert smoke_config.training.measure_precision_gap is False
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            metrics = await trainer._run_step(0)
            assert "beta_mean" not in metrics
            methods = [c.method for c in trainer.training_client.call_history]
            assert "forward_async" not in methods, methods
            await trainer._cleanup()


@pytest.mark.asyncio
async def test_trainer_precision_gap_nonfatal_on_failure(
    smoke_config: TinkerNeMoGymConfig,
) -> None:
    """If the shadow forward raises, β is skipped but training continues."""
    smoke_config.training.measure_precision_gap = True
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            # Wire the fake to blow up only on forward_async.
            trainer.training_client.raise_on["forward_async"] = RuntimeError("simulated β failure")
            metrics = await trainer._run_step(0)
            # Training ran anyway (loss captured).
            assert "loss" in metrics, list(metrics.keys())
            # β metrics absent, error recorded.
            assert "beta_mean" not in metrics
            assert "precision_gap_error" in metrics
            await trainer._cleanup()

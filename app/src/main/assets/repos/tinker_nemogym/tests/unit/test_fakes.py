"""Unit tests for the Tinker SDK fakes.

These tests verify the fakes match the shape of the real SDK in the ways
our trainer and FastAPI shim consume them.
"""

from __future__ import annotations

import pytest
import tinker
from tinker import types as tt

from tinker_nemogym.testing import (
    FakeFuture,
    FakeLoRATrainingClient,
    FakeSampledSequence,
    FakeSampleResponse,
    FakeSamplingClient,
    FakeServiceClient,
    make_fake_tinker_module,
)


@pytest.mark.asyncio
async def test_fake_sampling_client_matches_real_shape() -> None:
    client = FakeSamplingClient(seed=42)
    prompt = tt.ModelInput.from_ints([1, 2, 3, 4, 5])
    params = tt.SamplingParams(max_tokens=30, temperature=1.0)
    resp = await client.sample_async(prompt=prompt, num_samples=3, sampling_params=params)

    # Mirrors tinker.SampleResponse fields.
    assert isinstance(resp, FakeSampleResponse)
    assert resp.type == "sample"
    assert len(resp.sequences) == 3
    for seq in resp.sequences:
        assert isinstance(seq, FakeSampledSequence)
        assert isinstance(seq.tokens, list)
        assert all(isinstance(t, int) for t in seq.tokens)
        assert seq.logprobs is not None
        assert len(seq.logprobs) == len(seq.tokens)
        assert all(lp <= 0 for lp in seq.logprobs)
        assert seq.stop_reason in ("length", "stop")
        # Within the configured bounds.
        assert client.min_tokens <= len(seq.tokens) <= client.max_tokens_cap


@pytest.mark.asyncio
async def test_fake_sampling_client_is_deterministic() -> None:
    prompt = tt.ModelInput.from_ints([1, 2, 3])
    params = tt.SamplingParams(max_tokens=20, seed=7)
    a = await FakeSamplingClient(seed=0).sample_async(prompt, 2, params)
    b = await FakeSamplingClient(seed=0).sample_async(prompt, 2, params)
    assert [s.tokens for s in a.sequences] == [s.tokens for s in b.sequences]


@pytest.mark.asyncio
async def test_fake_sampling_client_version_changes_output() -> None:
    prompt = tt.ModelInput.from_ints([1, 2, 3])
    params = tt.SamplingParams(max_tokens=20)
    a = await FakeSamplingClient(seed=1, version=1).sample_async(prompt, 1, params)
    b = await FakeSamplingClient(seed=1, version=2).sample_async(prompt, 1, params)
    # Different versions should give different outputs (hot-swap invariant).
    assert a.sequences[0].tokens != b.sequences[0].tokens


@pytest.mark.asyncio
async def test_fake_training_client_full_flow_records_history() -> None:
    client = FakeLoRATrainingClient(base_model="test", rank=8)

    fb = await client.forward_backward_async(data=[1, 2, 3], loss_fn="importance_sampling")
    assert isinstance(fb, FakeFuture)
    res = await fb.result_async()
    # Duck-typed to tinker.ForwardBackwardOutput: must have ``metrics``.
    assert hasattr(res, "metrics")
    assert "loss" in res.metrics

    op = await client.optim_step_async(object())
    assert isinstance(op, FakeFuture)
    assert "metrics" in await op.result_async()

    sampler = await client.save_weights_and_get_sampling_client_async(name="step_1")
    assert isinstance(sampler, FakeSamplingClient)
    assert sampler.version == 1

    sampler2 = await client.save_weights_and_get_sampling_client_async(name="step_2")
    assert sampler2.version == 2
    # Each call returns a NEW object — trainer uses identity to verify hot-swap.
    assert sampler is not sampler2

    save = await client.save_state_async(name="ckpt/step_2")
    assert (await save.result_async())["path"] == "ckpt/step_2"

    methods = [c.method for c in client.call_history]
    assert methods == [
        "forward_backward_async",
        "optim_step_async",
        "save_weights_and_get_sampling_client_async",
        "save_weights_and_get_sampling_client_async",
        "save_state_async",
    ]


@pytest.mark.asyncio
async def test_fake_service_client_creates_training_clients() -> None:
    svc = FakeServiceClient()
    tc = await svc.create_lora_training_client_async(base_model="m", rank=16)
    assert isinstance(tc, FakeLoRATrainingClient)
    assert tc.base_model == "m"
    assert tc.rank == 16
    assert len(svc.created_clients) == 1


def test_make_fake_tinker_module_patches_and_restores() -> None:
    original = tinker.ServiceClient
    with make_fake_tinker_module():
        assert tinker.ServiceClient is FakeServiceClient
    assert tinker.ServiceClient is original


def test_make_fake_tinker_module_restores_on_exception() -> None:
    original = tinker.ServiceClient
    with pytest.raises(RuntimeError, match="boom"):
        with make_fake_tinker_module():
            assert tinker.ServiceClient is FakeServiceClient
            raise RuntimeError("boom")
    assert tinker.ServiceClient is original


@pytest.mark.asyncio
async def test_fake_sampling_client_records_call() -> None:
    client = FakeSamplingClient()
    prompt = tt.ModelInput.from_ints([10, 20, 30])
    params = tt.SamplingParams(max_tokens=15)
    await client.sample_async(prompt, 2, params)
    assert len(client.call_history) == 1
    assert client.call_history[0]["method"] == "sample_async"
    assert client.call_history[0]["num_samples"] == 2

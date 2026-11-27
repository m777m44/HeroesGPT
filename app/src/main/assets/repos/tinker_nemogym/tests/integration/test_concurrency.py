"""Concurrent-rollout scale tests.

The rollout driver is asyncio-based, so wall-clock time should be bounded by
the slowest call — not sum of all calls. These tests encode that invariant
for practical sizes.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI

from tinker_nemogym import tinker_responses_model as tmodel
from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
from tinker_nemogym.rollout_driver import rollout_batch
from tinker_nemogym.testing import FakeSamplingClient, make_fake_tinker_module
from tinker_nemogym.trainer import TinkerNeMoGymTrainer
from tinker_nemogym.utils.process import pick_free_port


class _BG:
    def __init__(self, app: FastAPI):
        self.port = pick_free_port()
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._server.serve()), daemon=True
        )

    def start(self, timeout: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not getattr(self._server, "started", False):
            time.sleep(0.02)
        if not getattr(self._server, "started", False):
            raise RuntimeError("uvicorn did not start")

    def stop(self, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _make_latency_agent(latency_sec: float) -> FastAPI:
    """Returns a tiny 200-with-reward agent that sleeps ``latency_sec`` per call."""
    app = FastAPI()
    counter = {"n": 0}

    @app.post("/run")
    async def _run(body: dict) -> dict:  # noqa: ARG001
        await asyncio.sleep(latency_sec)
        counter["n"] += 1
        # Minimal payload matching extract_trajectory's contract so downstream
        # could consume it — not strictly required for these tests.
        return {
            "reward": 1.0,
            "response": {
                "output": [
                    {
                        "id": "m",
                        "type": "message",
                        "role": "assistant",
                        "prompt_token_ids": [1, 2, 3],
                        "generation_token_ids": [4, 5],
                        "generation_log_probs": [-0.1, -0.2],
                    }
                ],
            },
        }

    app.state.counter = counter  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# Concurrency scale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollout_batch_handles_group_size_16() -> None:
    """4 prompts × group_size=16 = 64 concurrent calls, 50ms latency each.

    If rollout_batch runs them concurrently, wall-clock should be ~50ms plus
    overhead, not 64 × 50ms. We give a generous budget (1s) to absorb
    uvicorn startup and network overhead on slow CI.
    """
    app = _make_latency_agent(0.05)
    srv = _BG(app)
    srv.start()
    try:
        prompts = [{"responses_create_params": {}} for _ in range(4)]
        started = time.monotonic()
        result = await rollout_batch(srv.url, prompts, group_size=16, timeout_sec=30)
        elapsed = time.monotonic() - started
    finally:
        srv.stop()

    assert len(result) == 4
    assert sum(len(g) for g in result) == 64
    # Must be FAR less than the sequential bound of 64 × 50ms = 3.2s. Generous
    # threshold accommodates slow CI boxes; the sequential-vs-parallel gap is
    # so large (10×+) that a 1.5s cap still catches regressions.
    assert elapsed < 1.5, f"64 concurrent calls took {elapsed:.2f}s (sequential would be ~3.2s)"


@pytest.mark.asyncio
async def test_rollout_batch_handles_prompts_50() -> None:
    """50 prompts × group_size=4 = 200 concurrent calls; 10ms latency each."""
    app = _make_latency_agent(0.01)
    srv = _BG(app)
    srv.start()
    try:
        prompts = [{"responses_create_params": {}} for _ in range(50)]
        started = time.monotonic()
        result = await rollout_batch(srv.url, prompts, group_size=4, timeout_sec=30)
        elapsed = time.monotonic() - started
    finally:
        srv.stop()

    assert len(result) == 50
    total = sum(len(g) for g in result)
    assert total == 200, f"expected 200 responses, got {total}"
    # Sequential bound ≈ 2.0s; concurrent bound should be much lower.
    assert elapsed < 5.0


# ---------------------------------------------------------------------------
# Trainer at scale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trainer_scale_group_size_8(tmp_path) -> None:
    """Trainer with group_size=8, 2 steps, fake agent → every step runs cleanly."""
    # Set up the shim + a zero-latency fake agent.
    tmodel._reset_for_tests()
    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(FakeSamplingClient(seed=99))

    shim = _BG(tmodel.app)
    shim.start()

    state = {"i": 0}
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:
        import aiohttp

        params = body.get("responses_create_params", {})
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{shim.url}/v1/responses",
                json=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                r.raise_for_status()
                response = await r.json()
        i = state["i"]
        state["i"] += 1
        # Alternating reward dodges the drop_constant_reward gate.
        return {"responses_create_params": params, "response": response, "reward": float(i % 2)}

    agent = _BG(app)
    agent.start()

    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        json.dumps({"responses_create_params": {"input": [{"role": "user", "content": "x"}]}})
        + "\n"
    )
    cfg = TinkerNeMoGymConfig(
        tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct", lora_rank=4),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(dataset_jsonl=str(dataset), group_size=8, agent_url=agent.url),
        training=TrainingConfig(n_steps=2, batch_size=1, save_every=0),
    )

    try:
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            tmodel.set_sampling_client(trainer.current_sampling_client)

            for step in range(cfg.training.n_steps):
                await trainer._run_step(step)

            methods = [c.method for c in trainer.training_client.call_history]
            # Each step ran fwd_bwd and a hot-swap.
            assert methods.count("forward_backward_async") == 2
            # +1 for the initial sampler snapshot from setup().
            assert methods.count("save_weights_and_get_sampling_client_async") >= 3
            await trainer._cleanup()
    finally:
        agent.stop()
        shim.stop()
        tmodel._reset_for_tests()

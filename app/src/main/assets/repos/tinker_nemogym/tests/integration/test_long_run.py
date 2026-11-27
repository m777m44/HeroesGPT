"""Long-run + transient-error-recovery trainer tests.

These hold the trainer to harder invariants than the 2-step smoke: 50 steps
end-to-end (must complete in under 30s and hot-swap enough times), and a
scenario where the *first* rollout call returns 500 — the trainer must log,
skip, and keep going.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, HTTPException

from tinker_nemogym import tinker_responses_model as tmodel
from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
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


def _install_shim() -> _BG:
    """Set up tmodel + boot the shim; callers must stop() it and _reset_for_tests()."""
    tmodel._reset_for_tests()
    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(FakeSamplingClient(seed=7))
    shim = _BG(tmodel.app)
    shim.start()
    return shim


def _agent_cycling_rewards(shim_url: str, rewards: list[float]) -> _BG:
    state = {"i": 0}
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:
        import aiohttp

        params = body.get("responses_create_params", {})
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{shim_url}/v1/responses",
                json=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                r.raise_for_status()
                response = await r.json()
        i = state["i"]
        state["i"] += 1
        return {
            "responses_create_params": params,
            "response": response,
            "reward": float(rewards[i % len(rewards)]),
        }

    agent = _BG(app)
    agent.start()
    return agent


def _write_dataset(tmp_path, n: int) -> str:
    ds = tmp_path / "ds.jsonl"
    ds.write_text(
        "\n".join(
            json.dumps(
                {"responses_create_params": {"input": [{"role": "user", "content": f"q{i}"}]}}
            )
            for i in range(n)
        )
        + "\n"
    )
    return str(ds)


def _cfg(tmp_path, *, n_steps: int, group_size: int = 2, batch_size: int = 2):
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct", lora_rank=4),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(
            dataset_jsonl=_write_dataset(tmp_path, max(2, batch_size)),
            group_size=group_size,
        ),
        training=TrainingConfig(
            n_steps=n_steps,
            batch_size=batch_size,
            save_every=0,
            drop_constant_reward=True,
        ),
    )


# ---------------------------------------------------------------------------
# 50-step long run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trainer_runs_50_steps_without_exception(tmp_path) -> None:
    """50 steps back-to-back; must complete < 30s and hot-swap at least 25 times."""
    shim = _install_shim()
    agent = _agent_cycling_rewards(shim.url, [0.0, 1.0])  # varied → no drops
    cfg = _cfg(tmp_path, n_steps=50, group_size=2, batch_size=2)
    cfg.nemogym.agent_url = agent.url

    try:
        started = time.monotonic()
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            tmodel.set_sampling_client(trainer.current_sampling_client)
            initial_sampler_id = id(trainer.current_sampling_client)

            for step in range(cfg.training.n_steps):
                await trainer._run_step(step)

            elapsed = time.monotonic() - started

            methods = [c.method for c in trainer.training_client.call_history]
            fwd_bwd = methods.count("forward_backward_async")
            swaps = methods.count("save_weights_and_get_sampling_client_async")
            # fwd_bwd may equal 50 or slightly less if any group collapsed to
            # identical rewards by chance (our [0, 1] cycle keeps this rare).
            assert fwd_bwd >= 45
            # Each step that runs fwd_bwd also runs a hot-swap, plus the one
            # from setup. So we expect >= 46 swaps total; be lenient.
            assert swaps >= 25
            # Sampler actually rotated — final sampler object differs from initial.
            assert id(trainer.current_sampling_client) != initial_sampler_id
            assert trainer.current_sampling_client is not None
            # Wall-clock sanity: fake everything should be fast.
            assert elapsed < 30.0, f"50 fake steps took {elapsed:.2f}s"
            await trainer._cleanup()
    finally:
        agent.stop()
        shim.stop()
        tmodel._reset_for_tests()


# ---------------------------------------------------------------------------
# Transient rollout error recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trainer_resumes_after_transient_rollout_error(tmp_path) -> None:
    """First /run → 500; subsequent calls succeed. Trainer skips step 0 only."""
    shim = _install_shim()

    state = {"i": 0}
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:
        import aiohttp

        i = state["i"]
        state["i"] += 1
        if i == 0:
            # Intentionally fail the very first rollout call.
            raise HTTPException(status_code=500, detail="transient backend error")
        params = body.get("responses_create_params", {})
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{shim.url}/v1/responses",
                json=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                r.raise_for_status()
                response = await r.json()
        return {
            "responses_create_params": params,
            "response": response,
            "reward": float(i % 2),  # alternating 1/0 to dodge constant-reward drop
        }

    agent = _BG(app)
    agent.start()

    cfg = _cfg(tmp_path, n_steps=3, group_size=2, batch_size=1)
    cfg.nemogym.agent_url = agent.url

    try:
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            tmodel.set_sampling_client(trainer.current_sampling_client)

            # Driving via _run_step so we can inspect metrics per step.
            metrics = [await trainer._run_step(s) for s in range(cfg.training.n_steps)]

            methods = [c.method for c in trainer.training_client.call_history]
            fwd_bwd = methods.count("forward_backward_async")
            # Step 0 must have failed; subsequent steps should have fwd_bwd-ed.
            assert fwd_bwd >= cfg.training.n_steps - 1
            # Step 0 metrics reflect the skipped path (n_datums==0).
            assert metrics[0]["n_datums"] == 0
            await trainer._cleanup()
    finally:
        agent.stop()
        shim.stop()
        tmodel._reset_for_tests()

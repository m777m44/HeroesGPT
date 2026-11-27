"""Targeted error-recovery tests across rollout driver, trainer, and shim.

These exercise the defensive error handling added in this PR: try/except
around ``forward_backward_async``, try/except around ``save_state_async``,
and the shim's catch-all that converts sampling-client exceptions into
HTTP 500 responses instead of taking the whole process down.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import aiohttp
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
from tinker_nemogym.rollout_driver import rollout_group, rollout_group_with_retry
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


# ---------------------------------------------------------------------------
# rollout_group_with_retry contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollout_group_handles_agent_500() -> None:
    """Every slot 500s → rollout_group_with_retry returns empty (no exception)."""
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:  # noqa: ARG001
        raise HTTPException(status_code=500, detail="boom")

    srv = _BG(app)
    srv.start()
    try:
        results = await rollout_group_with_retry(
            srv.url, {"responses_create_params": {}}, group_size=2, max_retries=1,
            timeout_sec=5,
        )
    finally:
        srv.stop()
    assert results == []  # all retries gave up; no crash.


@pytest.mark.asyncio
async def test_rollout_group_with_retry_partial_success() -> None:
    """First attempt of each slot 500s; second attempt succeeds."""
    state = {"n": 0}
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:  # noqa: ARG001
        state["n"] += 1
        if state["n"] <= 2:
            raise HTTPException(status_code=500, detail="boom")
        return {"reward": 1.0, "response": {"output": []}}

    srv = _BG(app)
    srv.start()
    try:
        results = await rollout_group_with_retry(
            srv.url, {"responses_create_params": {}}, group_size=2, max_retries=3,
            timeout_sec=5,
        )
    finally:
        srv.stop()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_rollout_group_handles_agent_timeout() -> None:
    """Simulated slow agent → caller sees TimeoutError (caught by outer loop)."""
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:  # noqa: ARG001
        await asyncio.sleep(5)
        return {}

    srv = _BG(app)
    srv.start()
    try:
        with pytest.raises((TimeoutError, asyncio.TimeoutError, aiohttp.ClientError)):
            await rollout_group(
                srv.url, {"responses_create_params": {}}, group_size=1, timeout_sec=1
            )
    finally:
        srv.stop()


@pytest.mark.asyncio
async def test_rollout_group_handles_agent_returning_malformed_json() -> None:
    """Non-JSON body → aiohttp raises; caller gets a ContentTypeError."""
    from fastapi.responses import PlainTextResponse

    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> PlainTextResponse:  # noqa: ARG001
        return PlainTextResponse("not json at all", status_code=200)

    srv = _BG(app)
    srv.start()
    try:
        with pytest.raises((aiohttp.ContentTypeError, ValueError, json.JSONDecodeError)):
            await rollout_group(
                srv.url, {"responses_create_params": {}}, group_size=1, timeout_sec=5
            )
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# Trainer resilience
# ---------------------------------------------------------------------------


def _minimal_cfg(tmp_path):
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        json.dumps({"responses_create_params": {"input": [{"role": "user", "content": "x"}]}})
        + "\n"
    )
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct", lora_rank=4),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(dataset_jsonl=str(dataset), group_size=2),
        training=TrainingConfig(
            n_steps=1, batch_size=1, save_every=1, drop_constant_reward=False
        ),
    )


@pytest.mark.asyncio
async def test_trainer_handles_fwd_bwd_exception(tmp_path, caplog) -> None:
    """forward_backward_async raises → trainer logs + returns metrics (no crash)."""
    cfg = _minimal_cfg(tmp_path)
    trainer = TinkerNeMoGymTrainer(cfg)

    # Mock the datum-producing path entirely so we can inject the exception
    # without spinning up an agent.
    groups_raw = [[{"reward": 1.0}, {"reward": 0.5}]]
    fake_traj = MagicMock(reward=1.0)
    fake_datums = [MagicMock(), MagicMock()]
    fake_meta = {"mean_reward": 0.75, "n_datums": 2, "n_dropped_constant": 0}

    trainer.training_client = MagicMock()
    trainer.training_client.forward_backward_async = AsyncMock(
        side_effect=RuntimeError("tinker backend 503")
    )
    trainer.training_client.optim_step_async = AsyncMock()
    trainer.training_client.save_weights_and_get_sampling_client_async = AsyncMock()
    trainer.dataset = [{"responses_create_params": {}}]

    from unittest.mock import patch

    with (
        patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=groups_raw)),
        patch("tinker_nemogym.trainer.extract_trajectory", return_value=fake_traj),
        patch(
            "tinker_nemogym.trainer.build_batch_with_trajectories",
            return_value=(fake_datums, [object()] * len(fake_datums), fake_meta),
        ),
    ):
        with caplog.at_level("ERROR"):
            metrics = await trainer._run_step(0)

    # Didn't raise; metrics carry the error marker.
    assert "fwd_bwd_error" in metrics
    # Hot-swap did NOT run (we never got past fwd_bwd).
    trainer.training_client.save_weights_and_get_sampling_client_async.assert_not_called()
    assert any("forward_backward" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_trainer_handles_save_state_exception(tmp_path, caplog) -> None:
    """save_state_async raises → _maybe_save_checkpoint logs WARNING, no raise."""
    cfg = _minimal_cfg(tmp_path)
    cfg.training.save_every = 1
    trainer = TinkerNeMoGymTrainer(cfg)
    trainer.training_client = MagicMock()
    trainer.training_client.save_state_async = AsyncMock(side_effect=RuntimeError("disk full"))

    with caplog.at_level("WARNING"):
        # Must not raise.
        await trainer._maybe_save_checkpoint(0)

    assert any("save_state_async" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Shim resilience
# ---------------------------------------------------------------------------


class _ExplodingSamplingClient:
    """Sampling client that always raises. Mirrors the tinker.SamplingClient
    contract shape: ``sample_async`` is the only method we call here."""

    version = 999

    async def sample_async(self, *args, **kwargs) -> None:  # noqa: D401
        raise RuntimeError("simulated tinker backend error")


@pytest.mark.asyncio
async def test_shim_handles_sampling_client_exception() -> None:
    """Sampling client raises → shim returns 500 with detail, stays alive."""
    tmodel._reset_for_tests()
    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(_ExplodingSamplingClient())

    shim = _BG(tmodel.app)
    shim.start()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{shim.url}/v1/responses",
                json={"input": [{"role": "user", "content": "hi"}], "max_output_tokens": 8},
            ) as r:
                # Must not crash the shim — we get a 500 with an actionable message.
                assert r.status == 500
                body = await r.json()
                assert "sampling_client error" in body.get("detail", "")

            # And the shim is still responsive after the failure.
            async with s.get(f"{shim.url}/health") as r2:
                assert r2.status == 200

            # Now swap in a real fake sampler and verify a follow-up succeeds.
            tmodel.set_sampling_client(FakeSamplingClient(seed=0))
            async with s.post(
                f"{shim.url}/v1/responses",
                json={"input": [{"role": "user", "content": "hi"}], "max_output_tokens": 8},
            ) as r3:
                assert r3.status == 200
    finally:
        shim.stop()
        tmodel._reset_for_tests()


@pytest.mark.asyncio
async def test_shim_chat_completions_handles_sampling_exception() -> None:
    """Same contract for /v1/chat/completions."""
    tmodel._reset_for_tests()
    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(_ExplodingSamplingClient())

    shim = _BG(tmodel.app)
    shim.start()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{shim.url}/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8},
            ) as r:
                assert r.status == 500
                body = await r.json()
                assert "sampling_client error" in body.get("detail", "")
    finally:
        shim.stop()
        tmodel._reset_for_tests()


@pytest.mark.asyncio
async def test_trainer_continues_after_transient_fwd_bwd_failure(tmp_path) -> None:
    """Across 3 steps, alternating fwd_bwd success/failure → trainer never crashes."""
    cfg = _minimal_cfg(tmp_path)
    cfg.training.n_steps = 3

    with make_fake_tinker_module():
        trainer = TinkerNeMoGymTrainer(cfg)
        await trainer.setup(start_model_server=False)

        # Inject intermittent failure via the raise_on hook.
        tc = trainer.training_client
        call_counter = {"n": 0}

        original_fwd = tc.forward_backward_async

        async def _flaky_fwd(*a, **kw):
            call_counter["n"] += 1
            if call_counter["n"] == 2:
                raise RuntimeError("transient")
            return await original_fwd(*a, **kw)

        tc.forward_backward_async = _flaky_fwd  # type: ignore[assignment]

        groups_raw = [[{"reward": 1.0}, {"reward": 0.5}]]
        fake_traj = MagicMock(reward=1.0)
        fake_datums = [MagicMock(), MagicMock()]
        fake_meta = {"mean_reward": 0.75, "n_datums": 2, "n_dropped_constant": 0}

        from unittest.mock import patch

        with (
            patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=groups_raw)),
            patch("tinker_nemogym.trainer.extract_trajectory", return_value=fake_traj),
            patch(
                "tinker_nemogym.trainer.build_batch_with_trajectories",
                return_value=(fake_datums, [object()] * len(fake_datums), fake_meta),
            ),
        ):
            results = [await trainer._run_step(s) for s in range(3)]

        # Step 1 hit the RuntimeError — recorded in metrics, no raise.
        assert "fwd_bwd_error" in results[1]
        # Steps 0 and 2 ran fwd_bwd + hot-swap.
        assert "fwd_bwd_error" not in results[0]
        assert "fwd_bwd_error" not in results[2]
        await trainer._cleanup()

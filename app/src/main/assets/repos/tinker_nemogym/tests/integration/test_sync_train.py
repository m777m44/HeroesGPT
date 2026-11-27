"""Integration test for :func:`tinker_nemogym.train` (sync wrapper).

Exercises the full one-liner path end-to-end against a fake Tinker module
and a minimal in-process fake agent. Not marked slow — runs in <5s.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import aiohttp
import pytest
import uvicorn
from fastapi import FastAPI

import tinker_nemogym
from tinker_nemogym import tinker_responses_model as tmodel
from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
from tinker_nemogym.testing import FakeSamplingClient, make_fake_tinker_module
from tinker_nemogym.utils.process import pick_free_port


class _Server:
    def __init__(self, app: FastAPI, port: int):
        self.port = port
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self._t = threading.Thread(target=lambda: asyncio.run(self._server.serve()), daemon=True)

    def start(self) -> None:
        self._t.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not getattr(self._server, "started", False):
            time.sleep(0.02)

    def stop(self) -> None:
        self._server.should_exit = True
        self._t.join(timeout=3)


def _fake_agent_app(shim_url: str, reward: float = 0.5) -> FastAPI:
    app = FastAPI()

    state = {"i": 0}

    @app.post("/run")
    async def _run(body: dict) -> dict:
        params = body.get("responses_create_params", {})
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{shim_url}/v1/responses", json=params, timeout=30) as r:
                r.raise_for_status()
                resp = await r.json()
        # alternate rewards so GRPO doesn't drop the group
        rew = [0.0, 1.0][state["i"] % 2]
        state["i"] += 1
        return {"responses_create_params": params, "response": resp, "reward": float(rew)}

    return app


@pytest.mark.asyncio
async def test_sync_train_runs_end_to_end(tmp_path):
    """tinker_nemogym.train(cfg) returns a summary dict after one step."""
    # 1) Dataset
    ds = tmp_path / "d.jsonl"
    ds.write_text(
        json.dumps(
            {
                "responses_create_params": {
                    "input": [{"role": "user", "content": "hi"}]
                }
            }
        )
        + "\n"
    )

    # 2) Shim tokenizer / renderer
    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)

    tmodel._reset_for_tests()
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(FakeSamplingClient(seed=7))

    shim_port = pick_free_port()
    shim = _Server(tmodel.app, shim_port)
    shim.start()

    agent_port = pick_free_port()
    agent = _Server(_fake_agent_app(f"http://127.0.0.1:{shim_port}"), agent_port)
    agent.start()

    ckpt = tmp_path / "ckpts"
    ckpt.mkdir()

    cfg = TinkerNeMoGymConfig(
        tinker=TinkerConfig(
            base_model=base_model,
            lora_rank=4,
            checkpoint_dir=str(ckpt),
        ),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(
            dataset_jsonl=str(ds),
            agent_url=f"http://127.0.0.1:{agent_port}",
            group_size=2,
        ),
        training=TrainingConfig(
            n_steps=1,
            batch_size=1,
            save_every=0,
            drop_constant_reward=False,
        ),
    )

    try:
        with make_fake_tinker_module():
            summary = await asyncio.to_thread(tinker_nemogym.train, cfg)
    finally:
        agent.stop()
        shim.stop()
        tmodel._reset_for_tests()

    assert isinstance(summary, dict)
    assert summary["steps"] == 1
    # save_count >= 1 because setup() snapshots the initial sampler.
    assert summary["save_count"] >= 1

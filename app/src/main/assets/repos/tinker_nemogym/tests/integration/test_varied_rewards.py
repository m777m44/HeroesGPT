"""Integration tests for reward-signal variation + drop_constant_reward matrix.

These tests drive the rollout → datum → forward_backward path with a mock
agent that returns *varied* per-rollout rewards (round-robin through
``{0.0, 0.25, 0.5, 0.75, 1.0}``). We then verify:

* GRPO advantages are non-trivial (at least one non-zero entry in the batch).
* ``build_batch`` emits datums in the varied case; skips in the constant case.
* The ``drop_constant_reward=False`` escape hatch still hits forward_backward
  even when every reward is identical.

The fake agent never invokes a real subprocess — it's an in-process FastAPI
whose ``/run`` cycles through a reward table. The shim + fake sampling client
handle the actual token generation.
"""

from __future__ import annotations

import asyncio
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
from tinker_nemogym.datum_builder import (
    build_batch,
    compute_advantages,
    extract_trajectory,
)
from tinker_nemogym.rollout_driver import rollout_group
from tinker_nemogym.testing import FakeSamplingClient, make_fake_tinker_module
from tinker_nemogym.trainer import TinkerNeMoGymTrainer
from tinker_nemogym.utils.process import pick_free_port

VARIED_REWARDS = [0.0, 0.25, 0.5, 0.75, 1.0]


# ---------------------------------------------------------------------------
# Shared fake-agent / shim fixtures
# ---------------------------------------------------------------------------


class _BGServer:
    def __init__(self, app: FastAPI):
        self.host = "127.0.0.1"
        self.port = pick_free_port()
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
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
            raise RuntimeError(f"uvicorn on :{self.port} did not start")

    def stop(self, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _make_shim_and_agent(
    rewards: list[float],
) -> tuple[_BGServer, _BGServer, list[float]]:
    """Spin up the real shim + a fake agent that round-robins ``rewards``."""
    tmodel._reset_for_tests()

    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(FakeSamplingClient(seed=42))

    shim = _BGServer(tmodel.app)
    shim.start()

    state = {"i": 0}
    used: list[float] = []

    fake_agent_app = FastAPI()

    @fake_agent_app.post("/run")
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
        rew = rewards[i % len(rewards)]
        used.append(rew)
        return {
            "responses_create_params": params,
            "response": response,
            "reward": float(rew),
        }

    agent = _BGServer(fake_agent_app)
    agent.start()
    return shim, agent, used


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_compute_advantages_nonzero_for_varied_rewards() -> None:
    """Pure-function sanity: varied rewards → at least one non-zero advantage."""
    advs = compute_advantages([0.0, 0.25, 0.5, 0.75, 1.0])
    assert any(abs(a) > 1e-6 for a in advs)
    assert abs(sum(advs)) < 1e-5  # centered on zero


def test_compute_advantages_zero_for_constant_rewards() -> None:
    """All-identical rewards → all-zero advantages (GRPO would drop)."""
    advs = compute_advantages([0.5, 0.5, 0.5, 0.5])
    assert all(abs(a) < 1e-6 for a in advs)


@pytest.mark.asyncio
async def test_rollout_with_varied_rewards_produces_nonzero_advantages() -> None:
    """End-to-end: 4 rollouts, varied rewards → build_batch emits datums."""
    shim, agent, used = _make_shim_and_agent(VARIED_REWARDS)
    try:
        group = await rollout_group(
            agent.url,
            {"responses_create_params": {"input": [{"role": "user", "content": "x"}]}},
            group_size=4,
            timeout_sec=30,
        )
    finally:
        agent.stop()
        shim.stop()
        tmodel._reset_for_tests()

    trajs = [extract_trajectory(r) for r in group]
    # At least 2 distinct rewards — otherwise drop_constant_reward would kick in.
    distinct = {t.reward for t in trajs}
    assert len(distinct) >= 2, f"expected varied rewards, got {distinct}"

    datums, meta = build_batch(
        {"prompt_0": trajs}, drop_constant_reward=True
    )
    assert meta["n_dropped_constant"] == 0
    assert len(datums) == len(trajs)
    # At least one advantage must be non-zero (that's the whole point).
    advantages = compute_advantages([t.reward for t in trajs])
    assert any(abs(a) > 1e-6 for a in advantages)
    assert list(used) == VARIED_REWARDS[: len(group)]


def _cfg_for_matrix(tmp_path, dataset_rows: int = 2, drop: bool = True):
    dataset = tmp_path / "ds.jsonl"
    import json

    dataset.write_text(
        "\n".join(
            json.dumps(
                {
                    "responses_create_params": {
                        "input": [{"role": "user", "content": f"q{i}"}]
                    }
                }
            )
            for i in range(dataset_rows)
        )
        + "\n"
    )
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct", lora_rank=4),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(dataset_jsonl=str(dataset), group_size=2),
        training=TrainingConfig(
            n_steps=1, batch_size=1, save_every=0, drop_constant_reward=drop
        ),
    )


@pytest.mark.asyncio
async def test_drop_constant_reward_matrix(tmp_path) -> None:
    """Matrix over (drop_constant_reward, rewards) — forward_backward gating.

    * drop=True + constant → skip.
    * drop=True + varied   → run.
    * drop=False + constant → run (even though gradient would be zero).
    """
    cases = [
        ("drop_constant", [1.0, 1.0], True, False),
        ("keep_varied", [0.0, 1.0], True, True),
        ("force_constant", [1.0, 1.0], False, True),
    ]
    for name, rewards_cycle, drop, expect_fwd_bwd in cases:
        shim, agent, _ = _make_shim_and_agent(rewards_cycle)
        cfg = _cfg_for_matrix(tmp_path, dataset_rows=1, drop=drop)
        cfg.nemogym.agent_url = agent.url
        try:
            with make_fake_tinker_module():
                trainer = TinkerNeMoGymTrainer(cfg)
                await trainer.setup(start_model_server=False)
                tmodel.set_sampling_client(trainer.current_sampling_client)
                await trainer._run_step(0)
                methods = [c.method for c in trainer.training_client.call_history]
                got_fwd_bwd = "forward_backward_async" in methods
                assert got_fwd_bwd == expect_fwd_bwd, (
                    f"case={name}: expected fwd_bwd={expect_fwd_bwd}, "
                    f"got methods={methods}"
                )
                await trainer._cleanup()
        finally:
            agent.stop()
            shim.stop()
            tmodel._reset_for_tests()

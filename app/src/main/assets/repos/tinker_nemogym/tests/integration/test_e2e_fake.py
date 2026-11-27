"""Permanent integration tests that exercise the full tinker-nemogym
pipeline **without** a real ``TINKER_API_KEY`` and **without** launching
the slow nemo-gym subprocess stack.

Strategy: a tiny in-process FastAPI "fake agent" mimics nemo-gym's
``SimpleResponsesAPIAgent`` well enough for our trainer to:

  1. POST to ``{agent_url}/run`` with a ``responses_create_params`` payload,
  2. have the fake agent forward ``/v1/responses`` to our shim
     (``tinker_nemogym.tinker_responses_model.app``) which samples through
     the patched ``FakeSamplingClient``,
  3. and return a ``{"reward", "response"}`` dict whose ``response.output``
     carries the same ``NeMoGym*ForTraining`` field triple the real agent
     emits.

This keeps CI fast (<5s) while still covering every seam our real
integration exposed during the manual e2e.

The opt-in "slow" suite (``-m slow``) launches real ng_run subprocesses;
those tests are marked ``@pytest.mark.slow`` so they don't run by default.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import Iterator
from typing import Any

import aiohttp
import pytest
import tinker
import uvicorn
from fastapi import FastAPI

from tinker_nemogym import tinker_responses_model as tmodel
from tinker_nemogym.config import TinkerNeMoGymConfig
from tinker_nemogym.datum_builder import build_datum, extract_trajectory
from tinker_nemogym.rollout_driver import rollout_group
from tinker_nemogym.testing import (
    FakeSamplingClient,
    make_fake_tinker_module,
)
from tinker_nemogym.trainer import TinkerNeMoGymTrainer
from tinker_nemogym.utils.process import pick_free_port

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_free_port() -> int:
    """Deprecated in-module shim; kept for backward-compat.

    Prefer :func:`tinker_nemogym.utils.process.pick_free_port` in new code.
    """
    return pick_free_port()


class _BackgroundServer:
    """uvicorn server running a FastAPI app in a daemon thread.

    Offers ``start()`` / ``stop()``. Blocks in ``start()`` until the
    socket is bound so tests don't race the listener.
    """

    def __init__(self, app: FastAPI, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port or _pick_free_port()
        self._config = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._server.serve()), daemon=True
        )

    def start(self, timeout: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not getattr(self._server, "started", False):
            time.sleep(0.02)
        if not getattr(self._server, "started", False):
            raise RuntimeError(f"uvicorn on :{self.port} did not start in {timeout}s")

    def stop(self, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _make_fake_agent_app(model_base_url: str, reward: float = 1.0) -> FastAPI:
    """Build an in-process FastAPI that impersonates nemo-gym's simple_agent.

    Kept as a standalone helper (also re-used below) for clarity. Accepts
    ``POST /run`` and returns ``{"reward", "response",
    "responses_create_params"}``. Internally forwards ``/v1/responses`` to
    ``model_base_url`` (our shim) so every rollout still goes through the
    real FastAPI shim + (patched) Tinker sampling client.
    """
    app = FastAPI(title="fake-nemo-gym-agent")

    @app.get("/")
    async def _root() -> dict:
        return {"ok": True}

    @app.post("/run")
    async def _run(body: dict) -> dict:
        params = body.get("responses_create_params", {})
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{model_base_url.rstrip('/')}/responses",
                json=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                r.raise_for_status()
                response = await r.json()
        return {
            "responses_create_params": params,
            "response": response,
            "reward": float(reward),
        }

    return app


@contextlib.contextmanager
def _running_shim_and_agent(
    reward: float = 1.0, varied_reward: bool = False
) -> Iterator[tuple[str, str, list[float]]]:
    """Context manager that spins up the trainer's shim + a fake agent.

    Yields ``(shim_url, agent_url, rewards_used)``. ``rewards_used`` is a
    mutable list the caller can peek at — each slot of a rollout takes one
    reward from it (default [1.0] * group_size). When ``varied_reward`` is
    True the helper cycles between 0.0 and 1.0 so GRPO doesn't drop the
    group.
    """
    tmodel._reset_for_tests()  # clean slate
    # 1) Set up tokenizer + renderer on the shim.
    from tinker_cookbook import model_info
    from tinker_cookbook.renderers import get_renderer
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    # Llama-3.2-1B-Instruct is cached in our dev env; if a CI box doesn't have it,
    # swap the config for an ungated model (see docs/E2E_FIXES.md §6).
    base_model = "meta-llama/Llama-3.2-1B-Instruct"
    tokenizer = get_tokenizer(base_model)
    renderer = get_renderer(model_info.get_recommended_renderer_name(base_model), tokenizer)
    tmodel.init(base_model=base_model, tokenizer=tokenizer, renderer=renderer)
    tmodel.set_sampling_client(FakeSamplingClient(seed=1234))

    # 2) Boot the shim.
    shim = _BackgroundServer(tmodel.app)
    shim.start()

    # 3) Configurable-reward fake agent.
    rewards_cycle: list[float] = (
        [0.0, 1.0, 0.0, 1.0] if varied_reward else [reward, reward, reward, reward]
    )
    state = {"i": 0}
    rewards_used: list[float] = []

    fake_app = FastAPI(title="fake-nemo-gym-agent")

    @fake_app.post("/run")
    async def _run(body: dict) -> dict:
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
        rew = rewards_cycle[i % len(rewards_cycle)]
        rewards_used.append(rew)
        return {
            "responses_create_params": params,
            "response": response,
            "reward": float(rew),
        }

    agent = _BackgroundServer(fake_app)
    agent.start()

    try:
        yield shim.url, agent.url, rewards_used
    finally:
        agent.stop()
        shim.stop()
        tmodel._reset_for_tests()


# ---------------------------------------------------------------------------
# Fixtures (session-scoped where possible)
# ---------------------------------------------------------------------------


@pytest.fixture
def prompt_payload() -> dict:
    """One-shot agent-style prompt matching nemo-gym's jsonl schema."""
    return {
        "responses_create_params": {
            "input": [{"role": "user", "content": "Hello from tinker-nemogym test."}]
        }
    }


@pytest.fixture
def smoke_config() -> TinkerNeMoGymConfig:
    """Load the smoke-test config and bump a few knobs for test speed."""
    cfg = TinkerNeMoGymConfig.from_yaml("configs/smoke_single_tool.yaml")
    cfg.training.drop_constant_reward = False
    cfg.training.n_steps = 2
    cfg.training.batch_size = 2
    cfg.training.save_every = 1  # save every step → test_checkpoint_saved
    cfg.nemogym.group_size = 2
    # Allocate a fresh port per test run so tests can parallelize.
    cfg.model_server.port = _pick_free_port()
    return cfg


# ---------------------------------------------------------------------------
# Tests — fake-agent path (default, CI-friendly)
# ---------------------------------------------------------------------------


def test_our_shim_starts(smoke_config: TinkerNeMoGymConfig) -> None:
    """uvicorn starts our FastAPI on a free port; /health returns 200."""
    with _running_shim_and_agent() as (shim_url, _agent_url, _):
        import urllib.request

        with urllib.request.urlopen(f"{shim_url}/health", timeout=5) as r:
            assert r.status == 200
            body = r.read().decode()
            assert '"status":"ok"' in body
            assert '"sampling_client_ready":true' in body


@pytest.mark.asyncio
async def test_agent_can_call_our_shim(prompt_payload: dict) -> None:
    """fake agent → shim → fake sampling client → training fields attached."""
    with _running_shim_and_agent() as (_shim_url, agent_url, _):
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{agent_url}/run", json=prompt_payload) as r:
                assert r.status == 200
                body = await r.json()
        # Nemo-gym contract: {"reward": float, "response": {...}}
        assert "reward" in body
        assert "response" in body
        output = body["response"]["output"]
        assert len(output) >= 1
        item = output[0]
        # TokenIDLogProbMixin triple must be attached by our shim.
        assert "prompt_token_ids" in item
        assert "generation_token_ids" in item
        assert "generation_log_probs" in item
        assert len(item["generation_token_ids"]) == len(item["generation_log_probs"])
        assert len(item["generation_token_ids"]) >= 1


@pytest.mark.asyncio
async def test_rollout_driver_hits_agent(prompt_payload: dict) -> None:
    """``rollout_group(agent_url, prompt, 2)`` returns 2 shaped responses."""
    with _running_shim_and_agent() as (_shim_url, agent_url, _):
        group = await rollout_group(agent_url, prompt_payload, group_size=2, timeout_sec=30)
    assert len(group) == 2
    for r in group:
        assert "reward" in r
        assert "response" in r


@pytest.mark.asyncio
async def test_build_datum_from_real_agent_response(prompt_payload: dict) -> None:
    """rollout_group → extract_trajectory → build_datum round-trips cleanly."""
    with _running_shim_and_agent() as (_shim_url, agent_url, _):
        group = await rollout_group(agent_url, prompt_payload, group_size=2, timeout_sec=30)
    for raw in group:
        traj = extract_trajectory(raw)
        assert len(traj.prompt_tokens) > 0
        assert len(traj.response_tokens) > 0
        assert len(traj.response_tokens) == len(traj.response_logprobs)
        datum = build_datum(traj, advantage=0.5)
        assert isinstance(datum, tinker.Datum)


@pytest.mark.asyncio
async def test_trainer_single_step(smoke_config: TinkerNeMoGymConfig) -> None:
    """trainer.setup() + _run_step() returns a metrics dict with expected keys."""
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        # Our shim is already running — tell the trainer to skip starting one.
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            # The shim fixture already set a sampling client; re-inject the
            # trainer's so hot-swap assertions downstream hold.
            tmodel.set_sampling_client(trainer.current_sampling_client)
            metrics = await trainer._run_step(0)
            assert metrics["step"] == 0
            assert "mean_reward" in metrics
            assert "n_datums" in metrics
            assert metrics["n_datums"] >= 1
            await trainer._cleanup()


@pytest.mark.asyncio
async def test_trainer_two_steps_hot_swap(
    smoke_config: TinkerNeMoGymConfig,
) -> None:
    """Two steps back-to-back; sampling_client object should change between them."""
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            tmodel.set_sampling_client(trainer.current_sampling_client)

            ids: list[int] = [id(trainer.current_sampling_client)]
            versions: list[Any] = [getattr(trainer.current_sampling_client, "version", None)]

            await trainer._run_step(0)
            ids.append(id(trainer.current_sampling_client))
            versions.append(getattr(trainer.current_sampling_client, "version", None))

            await trainer._run_step(1)
            ids.append(id(trainer.current_sampling_client))
            versions.append(getattr(trainer.current_sampling_client, "version", None))

            # Identity must change at least once → hot-swap happened.
            assert len(set(ids)) >= 2
            # And the FakeLoRATrainingClient records every swap call.
            methods = [c.method for c in trainer.training_client.call_history]
            assert methods.count("save_weights_and_get_sampling_client_async") >= 2
            assert methods.count("forward_backward_async") >= 2
            assert versions[-1] != versions[0]
            await trainer._cleanup()


@pytest.mark.asyncio
async def test_checkpoint_saved(smoke_config: TinkerNeMoGymConfig) -> None:
    """``save_every=1`` means each step triggers ``save_state_async``."""
    smoke_config.training.save_every = 1
    with _running_shim_and_agent(varied_reward=True) as (_shim_url, agent_url, _):
        smoke_config.nemogym.agent_url = agent_url
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(smoke_config)
            await trainer.setup(start_model_server=False)
            tmodel.set_sampling_client(trainer.current_sampling_client)

            await trainer._run_step(0)
            await trainer._maybe_save_checkpoint(0)
            methods = [c.method for c in trainer.training_client.call_history]
            assert "save_state_async" in methods, f"no save_state_async in {methods}"
            await trainer._cleanup()


@pytest.mark.asyncio
async def test_shim_hot_swap_routes_to_new_client(prompt_payload: dict) -> None:
    """Swapping the sampling client mid-flight changes the produced tokens."""
    with _running_shim_and_agent() as (shim_url, _agent_url, _):
        sp_body = {
            "input": prompt_payload["responses_create_params"]["input"],
            "max_output_tokens": 20,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{shim_url}/v1/responses", json=sp_body) as r1:
                resp1 = await r1.json()
            # Hot-swap to a new version-2 fake sampler.
            tmodel.set_sampling_client(FakeSamplingClient(seed=1234, version=2))
            async with s.post(f"{shim_url}/v1/responses", json=sp_body) as r2:
                resp2 = await r2.json()
        tokens1 = resp1["output"][0]["generation_token_ids"]
        tokens2 = resp2["output"][0]["generation_token_ids"]
        # Different versions of the fake sampler produce different outputs.
        assert tokens1 != tokens2


# ---------------------------------------------------------------------------
# Slow suite — opt-in (runs real ng_run). Skipped by default.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_stack_comes_up_real_ng_run() -> None:  # pragma: no cover - slow/opt-in
    """Sanity: ng_run boots HeadServer + sub-servers within 120s.

    Excluded from the default test run. Enable with ``pytest -m slow``.
    Requires ``NG_RUN`` env or a sibling ``../nemo-gym/.venv/bin/ng_run``
    binary (the default path).
    """
    import os
    import subprocess
    import urllib.request

    # Default: look for ng_run in the sibling nemo-gym repo's venv. Override
    # with the ``NG_RUN`` env var if you install nemo-gym elsewhere.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_ng_run = os.path.abspath(
        os.path.join(repo_root, "..", ".venv", "bin", "ng_run")
    )
    ng_run = os.environ.get("NG_RUN", default_ng_run)
    if not os.path.exists(ng_run):
        pytest.skip(f"ng_run not found at {ng_run}")

    nemo_gym = os.path.abspath(os.path.join(repo_root, "..", "nemo-gym"))
    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            ng_run,
            f"+config_paths=[{repo_root}/configs/nemogym_resources.yaml,"
            f"{repo_root}/configs/nemogym_agent.yaml]",
            "+skip_venv_if_present=true",
        ],
        cwd=nemo_gym,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:11000/server_instances", timeout=3
                ) as r:
                    if r.status == 200:
                        return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
        raise AssertionError("HeadServer did not come up within 120s")
    finally:
        proc.send_signal(2)  # SIGINT
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

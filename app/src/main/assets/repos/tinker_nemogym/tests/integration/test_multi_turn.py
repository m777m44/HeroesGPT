"""Integration tests for multi-turn (interleaved) tool-use rollouts.

The fake agent here mirrors nemo-gym's ``example_multi_step`` wire format: it
emits a response with *multiple* ``NeMoGym*ForTraining`` items interleaved
with function-call + function-call-output items, so the downstream
``datum_builder`` is forced through its multi-turn concatenation path.

These tests don't touch real nemo-gym; they exercise only the tinker-nemogym
code paths that have to handle the multi-turn response shape.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest
import tinker
import uvicorn
from fastapi import FastAPI

from tinker_nemogym.datum_builder import (
    _collect_training_outputs,
    build_datum,
    extract_trajectory,
)
from tinker_nemogym.rollout_driver import rollout_group
from tinker_nemogym.utils.process import pick_free_port


def _multi_turn_response(*, reward: float = 1.0) -> dict:
    """Shape-accurate multi-turn /run response.

    Three assistant turns:

    1. ``function_call`` to ``get_synonym_value`` (with ForTraining fields)
    2. ``function_call_output`` (tool result — no ForTraining block)
    3. Final ``message`` committing ``extract_synonym_values`` (ForTraining fields)

    Each ForTraining item has matched token/logprob lengths. The prompt
    attached to the first item is the canonical prompt; subsequent items
    carry the same prefix + prior generations, so ``extract_trajectory``
    only needs to concatenate ``generation_token_ids``/``generation_log_probs``.
    """
    prompt_ids = [100, 101, 102, 103, 104]
    turn1_gen = [200, 201, 202]
    turn1_lp = [-0.1, -0.2, -0.15]
    turn2_gen = [300, 301, 302, 303]
    turn2_lp = [-0.11, -0.12, -0.13, -0.14]
    turn3_gen = [400, 401]
    turn3_lp = [-0.2, -0.25]
    return {
        "reward": float(reward),
        "response": {
            "id": "resp_test",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "item_1",
                    "type": "function_call",
                    "name": "get_synonym_value",
                    "arguments": '{"synonym": "Outperform"}',
                    "prompt_token_ids": prompt_ids,
                    "generation_token_ids": turn1_gen,
                    "generation_log_probs": turn1_lp,
                },
                {
                    "id": "tool_1",
                    "type": "function_call_output",
                    "output": '{"synonym_value": 1234}',
                },
                {
                    "id": "item_2",
                    "type": "function_call",
                    "name": "get_synonym_value",
                    "arguments": '{"synonym": "Desolate"}',
                    "prompt_token_ids": prompt_ids + turn1_gen,
                    "generation_token_ids": turn2_gen,
                    "generation_log_probs": turn2_lp,
                },
                {
                    "id": "tool_2",
                    "type": "function_call_output",
                    "output": '{"synonym_value": 5678}',
                },
                {
                    "id": "item_3",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "done"}],
                    "prompt_token_ids": prompt_ids + turn1_gen + turn2_gen,
                    "generation_token_ids": turn3_gen,
                    "generation_log_probs": turn3_lp,
                },
            ],
        },
    }


class _BGServer:
    """Tiny uvicorn-in-thread helper (duplicated from test_e2e_fake to keep
    this module import-independent)."""

    def __init__(self, app: FastAPI, host: str = "127.0.0.1", port: int | None = None):
        self.host = host
        self.port = port or pick_free_port()
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


def _make_multi_turn_agent() -> FastAPI:
    """Fake agent whose /run returns a multi-turn /v1/responses body."""
    app = FastAPI()

    @app.post("/run")
    async def _run(body: dict) -> dict:  # noqa: ARG001 - mirrors nemo-gym shape
        return _multi_turn_response(reward=1.0)

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_collect_training_outputs_finds_every_for_training_item() -> None:
    """_collect_training_outputs must return every ForTraining item in order."""
    resp = _multi_turn_response()["response"]
    items = _collect_training_outputs(resp)
    assert len(items) == 3
    # Order preserved (first function_call, then final message).
    assert items[0]["generation_token_ids"] == [200, 201, 202]
    assert items[-1]["generation_token_ids"] == [400, 401]


def test_extract_trajectory_concatenates_interleaved_chunks() -> None:
    """Multi-turn response → single RawTrajectory with concatenated generations."""
    run_resp = _multi_turn_response(reward=0.75)
    traj = extract_trajectory(run_resp)
    assert traj.reward == 0.75
    # prompt from the FIRST ForTraining item.
    assert traj.prompt_tokens == [100, 101, 102, 103, 104]
    # generations concatenated across all three turns.
    assert traj.response_tokens == [200, 201, 202, 300, 301, 302, 303, 400, 401]
    assert len(traj.response_logprobs) == len(traj.response_tokens) == 9


def test_multi_turn_datum_handles_interleaved_chunks() -> None:
    """extract_trajectory + build_datum on a multi-turn response round-trip."""
    traj = extract_trajectory(_multi_turn_response(reward=0.5))
    datum = build_datum(traj, advantage=0.25)
    assert isinstance(datum, tinker.Datum)
    # loss_fn_inputs shapes must all line up: target has len(all_tokens) - 1.
    n_total = len(traj.prompt_tokens) + len(traj.response_tokens)
    target = datum.loss_fn_inputs["target_tokens"].to_numpy()
    advantages = datum.loss_fn_inputs["advantages"].to_numpy()
    logprobs = datum.loss_fn_inputs["logprobs"].to_numpy()
    assert len(target) == n_total - 1
    assert len(advantages) == n_total - 1
    assert len(logprobs) == n_total - 1


@pytest.mark.asyncio
async def test_multi_turn_rollout_produces_multiple_tool_calls() -> None:
    """rollout_group against a multi-turn agent returns a response with >1 function_call."""
    srv = _BGServer(_make_multi_turn_agent())
    srv.start()
    try:
        group = await rollout_group(
            srv.url,
            {"responses_create_params": {"input": [{"role": "user", "content": "hi"}]}},
            group_size=2,
            timeout_sec=30,
        )
    finally:
        srv.stop()
    assert len(group) == 2
    for item in group:
        output = item["response"]["output"]
        fcs = [o for o in output if o.get("type") == "function_call"]
        msgs = [o for o in output if o.get("type") == "message"]
        # >1 function_call OR multiple message items — we have both.
        assert len(fcs) >= 2, f"expected >= 2 function_call items, got {len(fcs)}"
        assert len(msgs) >= 1


def test_extract_trajectory_still_handles_single_turn() -> None:
    """Regression: single-turn responses (one ForTraining item) still work."""
    resp = {
        "reward": 1.0,
        "response": {
            "output": [
                {
                    "id": "only",
                    "type": "message",
                    "role": "assistant",
                    "prompt_token_ids": [1, 2, 3],
                    "generation_token_ids": [4, 5, 6],
                    "generation_log_probs": [-0.1, -0.2, -0.3],
                }
            ],
        },
    }
    traj = extract_trajectory(resp)
    assert traj.prompt_tokens == [1, 2, 3]
    assert traj.response_tokens == [4, 5, 6]
    assert traj.response_logprobs == pytest.approx([-0.1, -0.2, -0.3])


def test_extract_trajectory_top_level_fallback() -> None:
    """Older synthetic fixtures attach fields at ``response`` top level."""
    resp = {
        "reward": 0.25,
        "response": {
            "prompt_token_ids": [7, 8],
            "generation_token_ids": [9, 10],
            "generation_log_probs": [-0.5, -0.6],
            "output": [],
        },
    }
    traj = extract_trajectory(resp)
    assert traj.prompt_tokens == [7, 8]
    assert traj.response_tokens == [9, 10]


def test_extract_trajectory_missing_fields_raises() -> None:
    """No ForTraining output and no top-level fields → ValueError."""
    resp: dict[str, Any] = {"reward": 0.0, "response": {"output": [{"type": "message"}]}}
    with pytest.raises(ValueError, match="token_ids/logprobs"):
        extract_trajectory(resp)

"""Unit tests for ``tinker_nemogym.rollout_driver``.

We mock the nemo-gym ``/run`` endpoint with an in-process aiohttp test
server (pytest-httpx only intercepts httpx, not aiohttp, so we need a
real TCP server — it's cheap).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from tinker_nemogym import rollout_driver
from tinker_nemogym.rollout_driver import (
    _call_once,
    load_jsonl,
    rollout_batch,
    rollout_group,
)

# ---------------------------------------------------------------------------
# Fixtures: spin up a local aiohttp server with a pluggable handler.
# ---------------------------------------------------------------------------


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class MockAgent:
    """Wraps a running aiohttp ``/run`` server exposed at ``self.url``."""

    def __init__(self, runner: web.AppRunner, site: web.TCPSite, url: str, calls: list[dict]):
        self.runner = runner
        self.site = site
        self.url = url  # e.g. "http://127.0.0.1:12345"
        self.calls = calls

    @property
    def num_calls(self) -> int:
        return len(self.calls)


@pytest.fixture
async def make_mock_agent() -> Any:
    """Factory fixture that starts a mock ``/run`` server on an ephemeral port.

    Usage:
        agent = await make_mock_agent(handler=my_handler)
    """
    started: list[MockAgent] = []

    async def _factory(handler: Handler) -> MockAgent:
        app = web.Application()
        calls: list[dict] = []

        async def _wrapper(request: web.Request) -> web.StreamResponse:
            try:
                body = await request.json()
            except Exception:
                body = None
            calls.append({"path": request.path, "body": body})
            return await handler(request)

        app.router.add_post("/run", _wrapper)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        # Resolve the ephemeral port.
        server = site._server  # type: ignore[attr-defined]
        assert server is not None and server.sockets
        port = server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"

        agent = MockAgent(runner=runner, site=site, url=url, calls=calls)
        started.append(agent)
        return agent

    try:
        yield _factory
    finally:
        for agent in started:
            await agent.runner.cleanup()


def _ok_handler(
    reward: float = 0.5,
    response_body: dict | None = None,
) -> Handler:
    if response_body is None:
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "hello"}],
                }
            ],
            "prompt_token_ids": [1, 2, 3],
            "generation_token_ids": [4, 5, 6],
            "generation_log_probs": [-0.1, -0.2, -0.3],
        }

    async def _handler(_request: web.Request) -> web.Response:
        return web.json_response({"reward": reward, "response": response_body})

    return _handler


def _sleep_handler(sleep_sec: float, reward: float = 1.0) -> Handler:
    async def _handler(_request: web.Request) -> web.Response:
        await asyncio.sleep(sleep_sec)
        return web.json_response(
            {
                "reward": reward,
                "response": {
                    "output": [],
                    "prompt_token_ids": [1],
                    "generation_token_ids": [2],
                    "generation_log_probs": [-0.5],
                },
            }
        )

    return _handler


def _status_handler(status: int, body: str = "kaboom") -> Handler:
    async def _handler(_request: web.Request) -> web.Response:
        return web.Response(status=status, text=body)

    return _handler


# ---------------------------------------------------------------------------
# load_jsonl
# ---------------------------------------------------------------------------


def test_load_jsonl_reads_three_lines(tmp_path):
    p = tmp_path / "data.jsonl"
    rows = [{"a": 1}, {"b": 2, "c": [1, 2]}, {"nested": {"x": True}}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert load_jsonl(str(p)) == rows


def test_load_jsonl_skips_empty_lines(tmp_path):
    p = tmp_path / "data.jsonl"
    p.write_text("\n" + json.dumps({"a": 1}) + "\n" + "   \n" + json.dumps({"b": 2}) + "\n" + "\n")
    assert load_jsonl(str(p)) == [{"a": 1}, {"b": 2}]


def test_load_jsonl_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_jsonl(str(tmp_path / "does_not_exist.jsonl"))


def test_load_jsonl_malformed_line_raises(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"a": 1}\n{not valid json}\n{"c": 3}\n')
    with pytest.raises(ValueError) as exc_info:
        load_jsonl(str(p))
    msg = str(exc_info.value)
    assert "line 2" in msg
    assert str(p) in msg


# ---------------------------------------------------------------------------
# rollout_group
# ---------------------------------------------------------------------------


async def test_rollout_group_returns_group_size_results(make_mock_agent):
    agent = await make_mock_agent(_ok_handler(reward=0.5))
    result = await rollout_group(agent.url, {"prompt": "hi"}, group_size=4)

    assert len(result) == 4
    assert agent.num_calls == 4
    for r in result:
        assert r["reward"] == 0.5
        assert "response" in r
        assert "prompt_token_ids" in r["response"]


async def test_rollout_group_deterministic_shape(make_mock_agent):
    agent = await make_mock_agent(_ok_handler(reward=0.9))
    result = await rollout_group(agent.url, {"p": 1}, group_size=4)

    assert len(result) == 4
    # All four responses have the same shape & reward value.
    for r in result:
        assert set(r.keys()) == {"reward", "response"}
        assert r["reward"] == 0.9
        assert set(r["response"].keys()) >= {
            "prompt_token_ids",
            "generation_token_ids",
            "generation_log_probs",
        }


async def test_rollout_group_agent_url_trailing_slash(make_mock_agent):
    """agent_url with trailing slash still hits /run (not //run)."""
    agent = await make_mock_agent(_ok_handler())
    await rollout_group(agent.url + "/", {"p": 1}, group_size=1)
    assert agent.num_calls == 1
    assert agent.calls[0]["path"] == "/run"


async def test_rollout_group_forwards_payload(make_mock_agent):
    agent = await make_mock_agent(_ok_handler())
    payload = {"responses_create_params": {"input": [{"role": "user", "content": "hi"}]}}
    await rollout_group(agent.url, payload, group_size=2)
    assert agent.num_calls == 2
    for call in agent.calls:
        assert call["body"] == payload


async def test_rollout_group_is_concurrent(make_mock_agent):
    """4 concurrent calls × ~100ms each should take well under 400ms."""
    agent = await make_mock_agent(_sleep_handler(0.1))
    t0 = time.perf_counter()
    result = await rollout_group(agent.url, {"p": 1}, group_size=4)
    elapsed = time.perf_counter() - t0
    assert len(result) == 4
    # Sequential would be ~400ms; concurrent should be ~100ms + overhead.
    assert elapsed < 0.3, f"expected concurrency, but took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# rollout_batch
# ---------------------------------------------------------------------------


async def test_rollout_batch_returns_nested_shape(make_mock_agent):
    agent = await make_mock_agent(_ok_handler(reward=0.25))
    prompts = [{"q": "a"}, {"q": "b"}, {"q": "c"}]
    batch = await rollout_batch(agent.url, prompts, group_size=2)

    assert len(batch) == 3
    for group in batch:
        assert len(group) == 2
        for r in group:
            assert r["reward"] == 0.25
    assert agent.num_calls == 3 * 2


# ---------------------------------------------------------------------------
# _call_once
# ---------------------------------------------------------------------------


async def test_call_once_raises_on_500(make_mock_agent):
    agent = await make_mock_agent(_status_handler(500, "internal boom"))
    url = agent.url + "/run"
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientResponseError) as exc_info:
            await _call_once(session, url, {"p": 1})
    assert exc_info.value.status == 500


async def test_call_once_timeout(make_mock_agent):
    """Server sleeps 2s but timeout_sec=0.1 → aiohttp raises a timeout."""
    agent = await make_mock_agent(_sleep_handler(2.0))
    url = agent.url + "/run"
    async with aiohttp.ClientSession() as session:
        with pytest.raises((asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
            await _call_once(session, url, {"p": 1}, timeout_sec=0.1)


# ---------------------------------------------------------------------------
# Logging sanity — make sure we actually use our named logger.
# ---------------------------------------------------------------------------


def test_logger_name_is_module():
    assert rollout_driver.logger.name == "tinker_nemogym.rollout_driver"


# ---------------------------------------------------------------------------
# Session pooling (Review 04 §2.3)
# ---------------------------------------------------------------------------


async def test_rollout_batch_reuses_session_when_provided(make_mock_agent):
    """When caller passes a session, rollout_batch must not close it.

    We assert the session is still usable after rollout_batch returns
    (closed sessions raise on subsequent requests).
    """
    agent = await make_mock_agent(_ok_handler(reward=0.5))

    session = aiohttp.ClientSession()
    try:
        batch = await rollout_batch(
            agent.url, [{"p": 1}, {"p": 2}], group_size=2, session=session
        )
        assert len(batch) == 2
        assert not session.closed, "rollout_batch must not close caller-owned session"
        # Still usable for another call:
        batch2 = await rollout_batch(
            agent.url, [{"p": 3}], group_size=2, session=session
        )
        assert len(batch2) == 1
    finally:
        await session.close()


async def test_rollout_batch_creates_own_session_when_none(make_mock_agent):
    """Regression: rollout_batch(session=None) still creates+closes a session itself."""
    agent = await make_mock_agent(_ok_handler(reward=0.5))
    batch = await rollout_batch(agent.url, [{"p": 1}], group_size=1)
    assert len(batch) == 1

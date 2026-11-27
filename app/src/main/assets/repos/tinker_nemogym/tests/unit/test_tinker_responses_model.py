"""Unit tests for ``tinker_nemogym.tinker_responses_model``.

Covers:
- hot-swap primitives (set/get + locking)
- init + runtime error when not initialized
- ``_route_to_tinker`` happy path with a mock ``SamplingClient`` + renderer
- hot-swap: second call uses the newly installed client
- FastAPI ``/v1/chat/completions`` end-to-end with a starlette ``TestClient``
- concurrent safety (two threads: writer + reader)
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tinker_nemogym import tinker_responses_model as m

# ---------------------------------------------------------------------------
# Helpers — stub SamplingClient / renderer / tokenizer
# ---------------------------------------------------------------------------


class _StubModelInput:
    """Minimal ModelInput stand-in with to_ints()."""

    def __init__(self, tokens: list[int]) -> None:
        self._tokens = list(tokens)

    def to_ints(self) -> list[int]:
        return list(self._tokens)


def _make_renderer(
    prompt_tokens: list[int] | None = None,
    parsed_text: str = "hello world",
    stop_sequences: list[str] | None = None,
):
    """Build a mock renderer satisfying the interface that _route_to_tinker uses."""
    renderer = MagicMock(name="renderer")
    renderer.build_generation_prompt.return_value = _StubModelInput(
        prompt_tokens or [100, 101, 102]
    )
    renderer.parse_response.return_value = ({"role": "assistant", "content": parsed_text}, True)
    renderer.get_stop_sequences.return_value = stop_sequences or ["<|eot|>"]
    return renderer


def _make_sampling_client(
    gen_tokens: list[int] | None = None,
    gen_logprobs: list[float] | None = None,
    stop_reason: str = "stop",
):
    """Build a mock SamplingClient.sample_async returning a canned SampleResponse-shaped object."""
    gen_tokens = gen_tokens if gen_tokens is not None else [1, 2, 3]
    gen_logprobs = gen_logprobs if gen_logprobs is not None else [-0.1, -0.2, -0.3]
    seq = SimpleNamespace(
        tokens=list(gen_tokens),
        logprobs=list(gen_logprobs),
        stop_reason=stop_reason,
    )
    response = SimpleNamespace(sequences=[seq])

    client = MagicMock(name="SamplingClient")
    client.sample_async = AsyncMock(return_value=response)
    return client


@pytest.fixture(autouse=True)
def _reset_module():
    m._reset_for_tests()
    yield
    m._reset_for_tests()


# ---------------------------------------------------------------------------
# Test 1: set_sampling_client updates global under lock
# ---------------------------------------------------------------------------


def test_set_sampling_client_swaps_global_under_lock():
    assert m.get_sampling_client() is None
    client_a = object()
    m.set_sampling_client(client_a)  # type: ignore[arg-type]
    assert m.get_sampling_client() is client_a
    client_b = object()
    m.set_sampling_client(client_b)  # type: ignore[arg-type]
    assert m.get_sampling_client() is client_b

    # The module-level lock should be the same object used for writes + reads.
    assert isinstance(m._sampling_client_lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# Test 2: init stashes tokenizer + renderer; route without init raises
# ---------------------------------------------------------------------------


def test_init_stashes_state():
    tok = object()
    ren = object()
    m.init("meta-llama/Llama-3.2-1B-Instruct", tok, ren)
    assert m._tokenizer is tok
    assert m._renderer is ren
    assert m._model_config == {"base_model": "meta-llama/Llama-3.2-1B-Instruct"}


def test_route_without_init_raises():
    # No init, no sampling client.
    from tinker_nemogym.errors import SamplerNotReadyError

    with pytest.raises(SamplerNotReadyError, match="init"):
        asyncio.run(
            m._route_to_tinker(
                prompt_messages=[{"role": "user", "content": "hi"}],
                max_tokens=8,
                temperature=1.0,
                stop=None,
            )
        )


def test_route_without_sampling_client_raises():
    from tinker_nemogym.errors import SamplerNotReadyError

    m.init("m", tokenizer=object(), renderer=_make_renderer())
    with pytest.raises(SamplerNotReadyError, match="sampling client"):
        asyncio.run(
            m._route_to_tinker(
                prompt_messages=[{"role": "user", "content": "hi"}],
                max_tokens=8,
                temperature=1.0,
                stop=None,
            )
        )


# ---------------------------------------------------------------------------
# Test 3: _route_to_tinker happy path
# ---------------------------------------------------------------------------


def test_route_to_tinker_returns_token_fields():
    renderer = _make_renderer(prompt_tokens=[10, 20, 30], parsed_text="hi")
    m.init("m", tokenizer=object(), renderer=renderer)
    client = _make_sampling_client(
        gen_tokens=[1, 2, 3], gen_logprobs=[-0.1, -0.2, -0.3], stop_reason="stop"
    )
    m.set_sampling_client(client)

    out = asyncio.run(
        m._route_to_tinker(
            prompt_messages=[{"role": "user", "content": "hi"}],
            max_tokens=16,
            temperature=0.7,
            stop=None,
        )
    )

    assert out["text"] == "hi"
    assert out["prompt_token_ids"] == [10, 20, 30]
    assert out["generation_token_ids"] == [1, 2, 3]
    assert out["generation_log_probs"] == [-0.1, -0.2, -0.3]
    assert out["stop_reason"] == "stop"

    # The renderer should have been asked for stop sequences since caller
    # passed stop=None.
    assert renderer.get_stop_sequences.called
    # The sampling client should have been called with our ModelInput + params.
    assert client.sample_async.await_count == 1
    call = client.sample_async.await_args
    assert call.kwargs["num_samples"] == 1
    assert call.kwargs["sampling_params"].max_tokens == 16
    assert call.kwargs["sampling_params"].temperature == 0.7


def test_route_to_tinker_respects_caller_stop():
    renderer = _make_renderer()
    m.init("m", tokenizer=object(), renderer=renderer)
    m.set_sampling_client(_make_sampling_client())

    asyncio.run(
        m._route_to_tinker(
            prompt_messages=[{"role": "user", "content": "x"}],
            max_tokens=4,
            temperature=1.0,
            stop=["STOP"],
        )
    )
    # Explicit stop wins over renderer default.
    assert not renderer.get_stop_sequences.called


# ---------------------------------------------------------------------------
# Test 4: hot-swap — second call goes to the replacement client
# ---------------------------------------------------------------------------


def test_hot_swap_routes_to_latest_client():
    m.init("m", tokenizer=object(), renderer=_make_renderer())
    client_a = _make_sampling_client(gen_tokens=[1], gen_logprobs=[-0.5])
    client_b = _make_sampling_client(gen_tokens=[9], gen_logprobs=[-0.05])

    m.set_sampling_client(client_a)
    asyncio.run(
        m._route_to_tinker(
            prompt_messages=[{"role": "user", "content": "q1"}],
            max_tokens=4,
            temperature=1.0,
            stop=None,
        )
    )
    assert client_a.sample_async.await_count == 1
    assert client_b.sample_async.await_count == 0

    m.set_sampling_client(client_b)
    asyncio.run(
        m._route_to_tinker(
            prompt_messages=[{"role": "user", "content": "q2"}],
            max_tokens=4,
            temperature=1.0,
            stop=None,
        )
    )
    # client_a was NOT called a second time; client_b was.
    assert client_a.sample_async.await_count == 1
    assert client_b.sample_async.await_count == 1


# ---------------------------------------------------------------------------
# Test 5: end-to-end /v1/chat/completions via TestClient
# ---------------------------------------------------------------------------


def test_chat_completions_endpoint_attaches_token_fields():
    renderer = _make_renderer(prompt_tokens=[5, 6, 7], parsed_text="hey there")
    m.init("base", tokenizer=object(), renderer=renderer)
    m.set_sampling_client(_make_sampling_client(gen_tokens=[42, 43], gen_logprobs=[-0.01, -0.02]))

    with TestClient(m.app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "base",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 16,
                "temperature": 1.0,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object"] == "chat.completion"
    msg = body["choices"][0]["message"]
    assert msg["role"] == "assistant"
    assert msg["content"] == "hey there"
    # TokenIDLogProbMixin contract:
    assert msg["prompt_token_ids"] == [5, 6, 7]
    assert msg["generation_token_ids"] == [42, 43]
    assert msg["generation_log_probs"] == [-0.01, -0.02]


def test_responses_endpoint_attaches_token_fields():
    renderer = _make_renderer(prompt_tokens=[5, 6], parsed_text="ok")
    m.init("base", tokenizer=object(), renderer=renderer)
    m.set_sampling_client(_make_sampling_client(gen_tokens=[77], gen_logprobs=[-0.1]))

    with TestClient(m.app) as client:
        resp = client.post(
            "/v1/responses",
            json={
                "model": "base",
                "input": [{"role": "user", "content": "hi"}],
                "max_output_tokens": 8,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object"] == "response"
    item = body["output"][0]
    assert item["type"] == "message"
    assert item["role"] == "assistant"
    assert item["prompt_token_ids"] == [5, 6]
    assert item["generation_token_ids"] == [77]
    assert item["generation_log_probs"] == [-0.1]


# ---------------------------------------------------------------------------
# Test 6: concurrent hot-swap safety
# ---------------------------------------------------------------------------


def test_concurrent_hot_swap_never_returns_none_after_first_set():
    # One writer thread toggling between two clients; one reader thread
    # polling get_sampling_client(). After the first write, the reader must
    # always see one of the two clients — never None, never a partially
    # constructed object.
    client_a = object()
    client_b = object()

    m.set_sampling_client(client_a)  # type: ignore[arg-type]

    stop_flag = threading.Event()
    bad_reads: list[object] = []
    read_count = [0]

    def writer() -> None:
        for _ in range(5000):
            if stop_flag.is_set():
                return
            m.set_sampling_client(client_a)  # type: ignore[arg-type]
            m.set_sampling_client(client_b)  # type: ignore[arg-type]

    def reader() -> None:
        while not stop_flag.is_set():
            v = m.get_sampling_client()
            read_count[0] += 1
            if v is None or (v is not client_a and v is not client_b):
                bad_reads.append(v)
            # avoid pegging a single core
            if read_count[0] % 500 == 0:
                time.sleep(0)

    t_writer = threading.Thread(target=writer)
    t_reader = threading.Thread(target=reader)
    t_writer.start()
    t_reader.start()
    t_writer.join(timeout=10)
    stop_flag.set()
    t_reader.join(timeout=5)

    assert not bad_reads, f"Reader saw invalid values: {bad_reads[:5]}"
    assert read_count[0] > 100, "Reader thread did not run enough iterations"

"""Integration tests: FastAPI shim propagates session cookies for stateful envs.

nemo-gym's ``SimpleServer`` registers a Starlette ``SessionMiddleware`` whose
cookie name is derived from the server class + instance name. Multi-turn
agents rely on that middleware to keep per-session state across calls.

When our shim is wrapped by ``TinkerResponsesAPIModel`` (the nemo-gym
subclass), the middleware handles Set-Cookie automatically. These tests
cover the *other* path: the bare ``app`` served by uvicorn (tests, the
``tinker-nemogym serve`` subcommand). There is no middleware then — but
we still want inbound ``session=...`` cookies echoed so callers can chain
requests. See Review 02 §1.3.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from tinker_nemogym import tinker_responses_model as m


def _make_renderer(*, prompt_tokens: list[int], parsed_text: str = "ok"):
    renderer = MagicMock()
    model_input = MagicMock()
    model_input.to_ints.return_value = prompt_tokens
    renderer.build_generation_prompt.return_value = model_input
    renderer.get_stop_sequences.return_value = []
    renderer.parse_response.return_value = ({"role": "assistant", "content": parsed_text}, True)
    return renderer


def _make_sampling_client(*, gen_tokens: list[int], gen_logprobs: list[float]):
    sampler = MagicMock()
    seq = MagicMock()
    seq.tokens = gen_tokens
    seq.logprobs = gen_logprobs
    seq.stop_reason = "stop"
    result = MagicMock()
    result.sequences = [seq]

    async def _sample_async(**_kwargs):
        return result

    sampler.sample_async = _sample_async
    return sampler


def _wire_shim() -> None:
    m.init("base", tokenizer=object(), renderer=_make_renderer(prompt_tokens=[1, 2]))
    m.set_sampling_client(_make_sampling_client(gen_tokens=[11, 12], gen_logprobs=[-0.1, -0.2]))


def test_shim_echoes_session_cookie_on_responses() -> None:
    """POST /v1/responses with Cookie: session=abc123 → Set-Cookie: session=abc123."""
    _wire_shim()
    with TestClient(m.app) as client:
        resp = client.post(
            "/v1/responses",
            json={"input": [{"role": "user", "content": "hi"}]},
            cookies={"session": "abc123"},
        )
    assert resp.status_code == 200, resp.text
    # httpx's cookie jar exposes the response's Set-Cookie entries.
    assert resp.cookies.get("session") == "abc123"


def test_shim_echoes_session_cookie_on_chat_completions() -> None:
    """Same contract for the OpenAI chat-completions endpoint."""
    _wire_shim()
    with TestClient(m.app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            cookies={"session": "xyz789"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.cookies.get("session") == "xyz789"


def test_multi_turn_preserves_session_cookie() -> None:
    """Two sequential POSTs with the same session cookie both succeed and
    round-trip the same cookie value back to the caller."""
    _wire_shim()
    with TestClient(m.app) as client:
        r1 = client.post(
            "/v1/responses",
            json={"input": [{"role": "user", "content": "turn 1"}]},
            cookies={"session": "turn-sid"},
        )
        r2 = client.post(
            "/v1/responses",
            json={"input": [{"role": "user", "content": "turn 2"}]},
            cookies={"session": "turn-sid"},
        )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.cookies.get("session") == "turn-sid"
    assert r2.cookies.get("session") == "turn-sid"


def test_shim_without_session_cookie_leaves_response_clean() -> None:
    """No inbound session cookie → no Set-Cookie in the response."""
    _wire_shim()
    with TestClient(m.app) as client:
        resp = client.post(
            "/v1/responses",
            json={"input": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    # httpx normalizes missing cookies to None.
    assert resp.cookies.get("session") is None

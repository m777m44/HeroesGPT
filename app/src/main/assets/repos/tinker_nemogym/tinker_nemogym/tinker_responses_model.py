"""FastAPI app that masquerades as a nemo-gym ResponsesAPIModel and routes every
completion through a hot-swappable :class:`tinker.SamplingClient`.

Two layers:

1. Module-global state (``_current_sampling_client``, ``_current_sampler_version``,
   ``_tokenizer``, ``_renderer``) + thread-safe accessors
   (:func:`set_sampling_client`, :func:`get_sampling_client`,
   :func:`get_sampler_version`, :func:`init`). The trainer swaps the sampling
   client between RL steps via :func:`set_sampling_client` and passes the
   ``save_count`` as the version so every response can be pinned to the
   exact sampler snapshot it came from.

2. A module-level :data:`app` — a FastAPI instance exposing
   ``POST /v1/chat/completions`` and ``POST /v1/responses`` that route every
   request through :func:`_route_to_tinker`. Uvicorn can serve this app
   directly (``tinker_nemogym.tinker_responses_model:app``).

Optionally we also define :class:`TinkerResponsesAPIModel`, a subclass of
nemo-gym's ``SimpleResponsesAPIModel`` whose ``setup_webserver`` returns the
same module-level app so that the trainer can still go through nemo-gym's
``run_webserver()`` lifecycle while the hot-swap primitives live here. The
subclass is only defined when nemo-gym is importable (it's an optional import
so that unit tests don't require the full nemo-gym stack).

The subclass attaches the TokenIDLogProbMixin contract
(``prompt_token_ids``, ``generation_token_ids``, ``generation_log_probs``) on
every response message -- this is what lets downstream
``datum_builder.extract_trajectory`` recover tokens + logprobs for RL.

Extended diagnostic fields (attached on every response alongside the mandatory
TokenIDLogProbMixin triple) — these are *optional* for the trainer but let us
measure the things the HuggingFace BF16-mismatch paper measures:

* ``sampler_version`` — save-count of the sampler snapshot that produced
  this rollout. Lets the trainer detect sampler drift (a.k.a. ``k − j`` in
  the blog's notation) on every datum.
* ``prompt_logprobs`` / ``topk_prompt_logprobs`` — optional per-prompt-token
  logprob distributions (opt in via the caller's request body). Enables
  KL-divergence / distillation diagnostics.
* ``sampling_params_used`` — the SamplingParams we *actually* fed to Tinker,
  including defaults. Pure reproducibility.
* ``sample_latency_ms`` / ``sample_started_at`` — per-rollout timing.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from uuid import uuid4

import tinker
from fastapi import Body, FastAPI, HTTPException, Request, Response
from tinker import types as tt

from .errors import SamplerNotReadyError

# ---------------------------------------------------------------------------
# Module-global state. These are shared across every uvicorn worker / FastAPI
# route handler in the process. Mutation of _current_sampling_client is
# serialized with _sampling_client_lock.
# ---------------------------------------------------------------------------

_sampling_client_lock: threading.Lock = threading.Lock()
_current_sampling_client: tinker.SamplingClient | None = None
# Save-count of the sampler currently wired in. Stamped onto every response
# so downstream trainers can compute staleness (rollouts from in-flight
# requests may finish after a hot-swap).
_current_sampler_version: int = 0

_tokenizer: Any = None
_renderer: Any = None
_model_config: dict[str, Any] | None = None


def set_sampling_client(
    client: tinker.SamplingClient, version: int | None = None
) -> None:
    """Atomically swap the active sampling client.

    Called by the trainer after ``save_weights_and_get_sampling_client_async``
    so subsequent inbound completions sample from the freshly updated weights.

    Args:
        client: The new sampling client.
        version: Save-count of the snapshot this client wraps. ``None``
            preserves the previous value (legacy callers that don't track
            versions); otherwise we stamp this number onto every response
            so the trainer can pin each datum to an exact snapshot.
    """
    global _current_sampling_client, _current_sampler_version
    with _sampling_client_lock:
        _current_sampling_client = client
        if version is not None:
            _current_sampler_version = int(version)


def get_sampling_client() -> tinker.SamplingClient | None:
    """Atomic read of the active sampling client."""
    with _sampling_client_lock:
        return _current_sampling_client


def get_sampler_version() -> int:
    """Atomic read of the current sampler version (save_count)."""
    with _sampling_client_lock:
        return _current_sampler_version


def init(base_model: str, tokenizer: Any, renderer: Any) -> None:
    """One-time init — stash the tokenizer + renderer + base_model metadata.

    The renderer is used to build a token-level generation prompt from chat
    messages and to parse the sampled tokens back into a text response.
    """
    global _tokenizer, _renderer, _model_config
    _tokenizer = tokenizer
    _renderer = renderer
    _model_config = {"base_model": base_model}


def _reset_for_tests() -> None:
    """Reset module globals — intended for unit tests only."""
    global _current_sampling_client, _current_sampler_version
    global _tokenizer, _renderer, _model_config
    with _sampling_client_lock:
        _current_sampling_client = None
        _current_sampler_version = 0
    _tokenizer = None
    _renderer = None
    _model_config = None


# ---------------------------------------------------------------------------
# Core routing helper — this is where every request ultimately lands.
# ---------------------------------------------------------------------------


async def _route_to_tinker(
    prompt_messages: list[dict],
    max_tokens: int,
    temperature: float,
    stop: list[str] | list[int] | None,
    *,
    top_p: float | None = None,
    top_k: int | None = None,
    seed: int | None = None,
    include_prompt_logprobs: bool = False,
    topk_prompt_logprobs: int = 0,
) -> dict:
    """Run one completion through the current ``SamplingClient``.

    Returns a dict with:

    - ``text``: decoded assistant text
    - ``prompt_token_ids``: list[int] — the prompt we fed to the sampler
    - ``generation_token_ids``: list[int] — sampled tokens
    - ``generation_log_probs``: list[float] — per-token logprobs under the sampler
    - ``stop_reason``: str
    - ``sampler_version``: int — save_count of the sampler that served this call
    - ``prompt_logprobs``: list[float | None] | None — optional, when requested
    - ``topk_prompt_logprobs``: Any | None — optional, when requested
    - ``sampling_params_used``: dict — the params we actually sent to Tinker
    - ``sample_latency_ms``: float — wall-clock time spent in ``sample_async``
    - ``sample_started_at``: float — ``time.time()`` when sampling began
    """
    if _renderer is None or _tokenizer is None:
        raise SamplerNotReadyError(
            "tinker_responses_model.init(base_model, tokenizer, renderer) has not been called"
        )
    client = get_sampling_client()
    if client is None:
        raise SamplerNotReadyError(
            "No active sampling client; trainer must call set_sampling_client() first"
        )

    # 1) Render prompt into a ModelInput (sequence of token chunks).
    model_input = _renderer.build_generation_prompt(prompt_messages)
    try:
        prompt_token_ids = list(model_input.to_ints())
    except Exception:
        # Non-token chunks (e.g. images); fall back to empty so we don't crash
        # the RL loop — datum_builder will flag it as a missing field.
        prompt_token_ids = []

    # 2) Compose SamplingParams. A ``None``/empty ``stop`` falls back to the
    # renderer's default stop sequences so generation terminates on the
    # model's EOT token rather than running to max_tokens.
    effective_stop: list[str] | list[int] | None
    if stop is None or stop == []:
        renderer_stop = _renderer.get_stop_sequences()
        effective_stop = renderer_stop if renderer_stop else None
    else:
        effective_stop = stop

    # Build SamplingParams with only the fields the caller cared about so
    # Tinker's own defaults (``top_p=1``, ``top_k=-1``, ``seed=None``) stay
    # authoritative when the caller didn't ask.
    sp_kwargs: dict[str, Any] = {
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stop": effective_stop,
    }
    if top_p is not None:
        sp_kwargs["top_p"] = top_p
    if top_k is not None:
        sp_kwargs["top_k"] = top_k
    if seed is not None:
        sp_kwargs["seed"] = seed
    sampling_params = tt.SamplingParams(**sp_kwargs)

    # Capture the effective params so the response can echo them back for
    # reproducibility (values here include Tinker defaults like top_p=1).
    params_used: dict[str, Any] = {
        "max_tokens": sampling_params.max_tokens,
        "temperature": sampling_params.temperature,
        "stop": list(effective_stop) if effective_stop is not None else None,
        "top_p": getattr(sampling_params, "top_p", None),
        "top_k": getattr(sampling_params, "top_k", None),
        "seed": getattr(sampling_params, "seed", None),
    }

    # 3) Sample. Use the snapshot from above (not _current_sampling_client) so
    # a concurrent hot-swap mid-flight still gets a stable reference. We
    # record the sampler_version BEFORE the sample call so downstream
    # callers can tell "what weights produced these tokens".
    sampler_version_at_call = get_sampler_version()
    started_at = time.time()
    t0 = time.monotonic()
    result = await client.sample_async(
        prompt=model_input,
        num_samples=1,
        sampling_params=sampling_params,
        include_prompt_logprobs=include_prompt_logprobs,
        topk_prompt_logprobs=int(topk_prompt_logprobs or 0),
    )
    latency_ms = (time.monotonic() - t0) * 1000.0
    if not result.sequences:
        raise RuntimeError("SamplingClient returned no sequences")
    seq = result.sequences[0]

    gen_tokens = list(seq.tokens)
    gen_logprobs = list(seq.logprobs) if seq.logprobs is not None else []

    # 4) Parse response tokens back into a text message.
    try:
        parsed_message, _ok = _renderer.parse_response(gen_tokens)
        content = parsed_message.get("content", "") if isinstance(parsed_message, dict) else ""
        if isinstance(content, list):
            # renderer may return structured content parts
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    text_parts.append(part.get("text", ""))
                else:
                    text_parts.append(str(part))
            text = "".join(text_parts)
        else:
            text = content or ""
    except Exception:
        # Best effort — if the renderer can't parse the tokens (e.g. missing
        # stop token), still return the raw tokens/logprobs upstream.
        text = ""

    # Optional prompt logprob extras — best-effort: older SDKs / some
    # sampling paths may not populate these even when requested.
    prompt_logprobs = getattr(result, "prompt_logprobs", None) if include_prompt_logprobs else None
    topk_prompt_logprobs_out: Any = (
        getattr(result, "topk_prompt_logprobs", None) if topk_prompt_logprobs else None
    )

    return {
        "text": text,
        "prompt_token_ids": prompt_token_ids,
        "generation_token_ids": gen_tokens,
        "generation_log_probs": gen_logprobs,
        "stop_reason": seq.stop_reason,
        "sampler_version": sampler_version_at_call,
        "prompt_logprobs": prompt_logprobs,
        "topk_prompt_logprobs": topk_prompt_logprobs_out,
        "sampling_params_used": params_used,
        "sample_latency_ms": latency_ms,
        "sample_started_at": started_at,
    }


# ---------------------------------------------------------------------------
# FastAPI app — the thing that uvicorn serves.
# ---------------------------------------------------------------------------

app = FastAPI(title="tinker-nemogym TinkerResponsesAPIModel")


@app.get("/health")
async def _health() -> dict:
    return {
        "status": "ok",
        "sampling_client_ready": get_sampling_client() is not None,
        "sampler_version": get_sampler_version(),
        "renderer_ready": _renderer is not None,
    }


def _extract_messages_chat(body: dict) -> list[dict]:
    """Normalize OpenAI ``/v1/chat/completions`` ``messages`` into the
    ``{role, content: str}`` TypedDicts that the renderer expects."""
    msgs = body.get("messages", [])
    out: list[dict] = []
    for m in msgs:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for c in content:
                if isinstance(c, dict):
                    parts.append(c.get("text", "") or c.get("content", "") or "")
                else:
                    parts.append(str(c))
            content = "".join(parts)
        out.append({"role": role, "content": content or ""})
    return out


def _extract_messages_responses(body: dict) -> list[dict]:
    """Normalize OpenAI Responses API ``input`` into ``{role, content: str}``."""
    inp = body.get("input", [])
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]
    out: list[dict] = []
    for item in inp:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "user")
        content = item.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for c in content:
                if isinstance(c, dict):
                    parts.append(c.get("text", "") or c.get("content", "") or "")
                else:
                    parts.append(str(c))
            content = "".join(parts)
        out.append({"role": role, "content": content or ""})
    return out


def _model_name() -> str:
    if _model_config is None:
        return "tinker"
    return _model_config.get("base_model", "tinker")


def _extract_advanced_sampling(body: dict) -> dict:
    """Pull optional top_p / top_k / seed / prompt_logprob knobs off a request.

    Returns a kwargs dict suitable for ``_route_to_tinker``. Only includes
    keys the caller actually set (so Tinker's defaults stay authoritative).
    """
    out: dict[str, Any] = {}
    if "top_p" in body and body["top_p"] is not None:
        out["top_p"] = float(body["top_p"])
    if "top_k" in body and body["top_k"] is not None:
        out["top_k"] = int(body["top_k"])
    if "seed" in body and body["seed"] is not None:
        out["seed"] = int(body["seed"])
    # Prompt-logprob passthrough: accept both the Tinker-style kwargs and
    # OpenAI's ``logprobs`` boolean for ergonomic tests.
    include = body.get("include_prompt_logprobs", body.get("logprobs"))
    if include:
        out["include_prompt_logprobs"] = True
    topk = body.get("topk_prompt_logprobs")
    if topk is not None:
        out["topk_prompt_logprobs"] = int(topk)
    return out


_BODY_DICT = Body(...)


# ---------------------------------------------------------------------------
# Session-cookie propagation. nemo-gym's base SimpleServer registers a
# Starlette SessionMiddleware whose cookie is named after the server
# class+instance (see ``server_utils.SimpleServer.setup_session_middleware``).
# When our shim is wrapped by a SimpleResponsesAPIModel subclass, that
# middleware runs and handles Set-Cookie automatically. When the bare
# module-level ``app`` is uvicorn'd (tests, ``tinker-nemogym serve``),
# there is no middleware — but multi-turn agents may still attach a
# ``session=...`` cookie. We echo it back unmodified so callers can chain
# requests without losing state.
# ---------------------------------------------------------------------------

_SESSION_COOKIE_NAMES: tuple[str, ...] = ("session",)


def _propagate_session_cookie(request: Request, response: Response) -> None:
    """Read any ``session`` cookie off the request, echo on the response.

    Cheap and safe: we only touch cookies whose name appears in
    :data:`_SESSION_COOKIE_NAMES`. SessionMiddleware (when installed by the
    nemo-gym base class) will overwrite these with its own Set-Cookie on the
    way out, so we never stomp the production path.
    """
    for name in _SESSION_COOKIE_NAMES:
        value = request.cookies.get(name)
        if value is not None:
            # httponly=False so test clients (httpx / requests) can see it.
            response.set_cookie(key=name, value=value, httponly=False, samesite="lax")


def _diagnostics_from_result(result: dict) -> dict[str, Any]:
    """Carve out the non-mandatory diagnostic fields we attach on every
    response alongside the TokenIDLogProbMixin triple.

    Returns a dict of ``{key: value}`` where every ``value is not None``.
    """
    diag: dict[str, Any] = {
        "sampler_version": result.get("sampler_version"),
        "sampling_params_used": result.get("sampling_params_used"),
        "sample_latency_ms": result.get("sample_latency_ms"),
        "sample_started_at": result.get("sample_started_at"),
    }
    if result.get("prompt_logprobs") is not None:
        diag["prompt_logprobs"] = result["prompt_logprobs"]
    if result.get("topk_prompt_logprobs") is not None:
        diag["topk_prompt_logprobs"] = result["topk_prompt_logprobs"]
    # Never emit None — keeps wire format tidy.
    return {k: v for k, v in diag.items() if v is not None}


@app.post("/v1/chat/completions")
async def chat_completions_endpoint(
    request: Request, response: Response, body: dict = _BODY_DICT
) -> dict:
    """OpenAI-style chat completions. Attaches the TokenIDLogProbMixin triple
    (``prompt_token_ids``, ``generation_token_ids``, ``generation_log_probs``)
    on the choice's message so downstream RL trainers can recover per-token
    logprobs.

    Also attaches diagnostic fields (``sampler_version``,
    ``sampling_params_used``, ``sample_latency_ms``, and optionally
    ``prompt_logprobs``/``topk_prompt_logprobs``) on both the choice message
    and the top-level response envelope so callers can grab them without
    digging into ``choices[0]``.

    Propagates inbound ``session=...`` cookies on the response so nemo-gym
    agents can maintain stateful sessions across calls (see Review 02 §1.3).
    """
    _propagate_session_cookie(request, response)
    try:
        messages = _extract_messages_chat(body)
        max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or 512)
        temperature = float(body.get("temperature", 1.0))
        stop = body.get("stop")
        if isinstance(stop, str):
            stop = [stop]
        extra = _extract_advanced_sampling(body)
        result = await _route_to_tinker(messages, max_tokens, temperature, stop, **extra)
    except SamplerNotReadyError as e:
        # Sampler not wired yet (trainer hasn't created the first sampling
        # client, or init() hasn't run). Translate to 503 so the caller can
        # retry after a short backoff.
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        # Anything else (a RuntimeError raised from inside the sampling
        # client itself) is a genuine sampling failure → 500.
        raise HTTPException(
            status_code=500, detail=f"sampling_client error: {e!r}"
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        # Sampling client exploded (upstream Tinker error, malformed prompt,
        # etc.). Return a 500 with the error message so the caller can log
        # and retry — crashing the shim process would drop every concurrent
        # request in flight.
        raise HTTPException(
            status_code=500, detail=f"sampling_client error: {e!r}"
        ) from e

    diagnostics = _diagnostics_from_result(result)
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": _model_name(),
        "choices": [
            {
                "index": 0,
                "finish_reason": ("length" if result["stop_reason"] == "length" else "stop"),
                "message": {
                    "role": "assistant",
                    "content": result["text"],
                    # TokenIDLogProbMixin contract:
                    "prompt_token_ids": result["prompt_token_ids"],
                    "generation_token_ids": result["generation_token_ids"],
                    "generation_log_probs": result["generation_log_probs"],
                    # Diagnostic extras (see module docstring).
                    **diagnostics,
                },
            }
        ],
        # Top-level duplicate so callers that don't drill into choices[0]
        # (e.g. load tests, health probes) can still observe latency/version.
        **diagnostics,
    }


@app.post("/v1/responses")
async def responses_endpoint(
    request: Request, response: Response, body: dict = _BODY_DICT
) -> dict:
    """OpenAI-Responses-style endpoint. Same TokenIDLogProbMixin contract — we
    attach the three token-id/logprob fields on the assistant message item.

    The returned shape matches :class:`nemo_gym.openai_utils.NeMoGymResponse`,
    including the ``parallel_tool_calls`` / ``tool_choice`` / ``tools`` fields
    that nemo-gym's pydantic validator requires even for tool-free responses.

    Propagates inbound ``session=...`` cookies on the response so nemo-gym
    agents can maintain stateful sessions across calls (see Review 02 §1.3).
    """
    _propagate_session_cookie(request, response)
    try:
        messages = _extract_messages_responses(body)
        max_tokens = int(body.get("max_output_tokens") or body.get("max_tokens") or 512)
        temperature = float(body.get("temperature", 1.0))
        stop = body.get("stop")
        if isinstance(stop, str):
            stop = [stop]
        extra = _extract_advanced_sampling(body)
        result = await _route_to_tinker(messages, max_tokens, temperature, stop, **extra)
    except SamplerNotReadyError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=500, detail=f"sampling_client error: {e!r}"
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        # Same rationale as the chat-completions handler: surface as 500
        # with an actionable detail rather than letting the shim die.
        raise HTTPException(
            status_code=500, detail=f"sampling_client error: {e!r}"
        ) from e

    # Pass tool-related fields back through so NeMoGymResponse validates.
    tools = body.get("tools") or []
    tool_choice = body.get("tool_choice", "auto")
    parallel_tool_calls = body.get("parallel_tool_calls", True)

    diagnostics = _diagnostics_from_result(result)
    return {
        "id": f"resp_{uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "model": _model_name(),
        "status": "completed",
        "parallel_tool_calls": parallel_tool_calls,
        "tool_choice": tool_choice,
        "tools": tools,
        "output": [
            {
                "id": f"msg_{uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": result["text"],
                        "annotations": [],
                    }
                ],
                # TokenIDLogProbMixin contract:
                "prompt_token_ids": result["prompt_token_ids"],
                "generation_token_ids": result["generation_token_ids"],
                "generation_log_probs": result["generation_log_probs"],
                # Diagnostic extras (see module docstring).
                **diagnostics,
            }
        ],
        # Top-level duplicate — see chat_completions docstring.
        **diagnostics,
    }


# ---------------------------------------------------------------------------
# Optional nemo-gym subclass. Only imports if nemo-gym is installed. Exposing
# this lets the trainer spin up the server via nemo-gym's ``run_webserver``
# lifecycle (session middleware, exception middleware, uvicorn multi-worker
# app string, etc.) while still reusing our module-level hot-swap state.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - imports only available when nemo-gym is installed
    from fastapi import Request  # noqa: F401  (used by nemo-gym base class)
    from nemo_gym.base_responses_api_model import (
        BaseResponsesAPIModelConfig,
        SimpleResponsesAPIModel,
    )

    class TinkerResponsesAPIModelConfig(BaseResponsesAPIModelConfig):
        base_model: str = "meta-llama/Llama-3.1-8B-Instruct"

    _BODY_ANY = Body()

    class TinkerResponsesAPIModel(SimpleResponsesAPIModel):
        """nemo-gym SimpleResponsesAPIModel whose webserver is our module-level
        hot-swap FastAPI app.

        The TokenIDLogProbMixin contract is satisfied by the route handlers
        above, which attach the three token-id/logprob fields on every
        response.
        """

        config: TinkerResponsesAPIModelConfig

        def setup_webserver(self) -> FastAPI:
            # Return the module-level app (with hot-swap routes already wired)
            # rather than creating a fresh one in the parent class. This keeps
            # uvicorn workers sharing our module-global state.
            self.setup_session_middleware(app)
            return app

        async def chat_completions(
            self, request: Request, response: Response, body: Any = _BODY_ANY
        ) -> Any:
            if hasattr(body, "model_dump"):
                body = body.model_dump(exclude_unset=True)
            return await chat_completions_endpoint(request, response, body)

        async def responses(
            self, request: Request, response: Response, body: Any = _BODY_ANY
        ) -> Any:
            if hasattr(body, "model_dump"):
                body = body.model_dump(exclude_unset=True)
            return await responses_endpoint(request, response, body)

except ImportError:  # pragma: no cover
    # nemo-gym isn't installed — expose sentinels so ``from tinker_responses_model
    # import TinkerResponsesAPIModel`` still works (callers can None-check).
    # We use separate names at the module level so the import path keeps
    # working; no reassignment to a type alias (mypy can't track that).
    TinkerResponsesAPIModel = None  # type: ignore[misc,assignment]
    TinkerResponsesAPIModelConfig = None  # type: ignore[misc,assignment]


__all__ = [
    "app",
    "set_sampling_client",
    "get_sampling_client",
    "get_sampler_version",
    "init",
    "_route_to_tinker",
    "TinkerResponsesAPIModel",
    "TinkerResponsesAPIModelConfig",
]

"""Async HTTP driver for nemo-gym agent ``/run`` endpoint.

This module knows nothing about Tinker. It POSTs prompt payloads (one per
dataset row) to a running nemo-gym ``SimpleResponsesAPIAgent`` and collects
the raw ``{"reward": float, "response": {...}}`` dicts.

Design:

* ``_call_once`` fires a single POST with a configurable timeout and raises
  on non-2xx responses.
* ``rollout_group`` launches ``group_size`` parallel copies of the same
  prompt (for GRPO-style group sampling).
* ``rollout_batch`` runs ``rollout_group`` concurrently across a list of
  distinct prompts.
* ``load_jsonl`` reads a one-JSON-per-line file (agent-style rows).
* ``rollout_group_with_retry`` is a best-effort retrying wrapper — it
  swallows per-call failures and retries each slot up to ``max_retries``
  times, returning only the successful responses.

Logging (stdlib ``logging``, logger name = ``__name__``):

* ``DEBUG`` on each POST fired.
* ``WARNING`` on non-200 responses.
* ``ERROR`` on timeouts / exceptions.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

import aiohttp

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def get_or_create_session(
    session: aiohttp.ClientSession | None = None,
) -> AsyncIterator[aiohttp.ClientSession]:
    """Yield ``session`` if provided (caller owns lifecycle), else a fresh one.

    Lets rollout functions accept an externally-managed shared session for
    pooling (trainer lifetime) while still being usable standalone in tests
    that create a throwaway session per call.
    """
    if session is not None:
        yield session
        return
    owned = aiohttp.ClientSession()
    try:
        yield owned
    finally:
        await owned.close()


async def _call_once(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    timeout_sec: float = 600,
) -> dict:
    """Fire one POST to ``url`` with ``payload``. Returns parsed JSON.

    Raises:
        aiohttp.ClientResponseError: on non-2xx HTTP status.
        asyncio.TimeoutError: on timeout.
        aiohttp.ClientError: on transport errors.
    """
    logger.debug("POST %s (timeout=%ss)", url, timeout_sec)
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    try:
        async with session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                body_preview = ""
                try:
                    body_preview = (await resp.text())[:200]
                except Exception:  # pragma: no cover - best-effort logging
                    pass
                logger.warning(
                    "Non-200 response from %s: status=%s body=%r",
                    url,
                    resp.status,
                    body_preview,
                )
            resp.raise_for_status()
            return await resp.json()
    except TimeoutError:
        logger.error("Timeout (%ss) POSTing to %s", timeout_sec, url)
        raise
    except aiohttp.ClientResponseError:
        # Already logged via WARNING above.
        raise
    except aiohttp.ClientError as e:
        logger.error("Client error POSTing to %s: %r", url, e)
        raise


def _agent_run_url(agent_url: str) -> str:
    return agent_url.rstrip("/") + "/run"


async def rollout_group(
    agent_url: str,
    prompt_payload: dict,
    group_size: int,
    timeout_sec: int = 600,
    session: aiohttp.ClientSession | None = None,
) -> list[dict]:
    """POST ``prompt_payload`` to ``agent_url + /run`` ``group_size`` times in parallel.

    Returns a list of parsed ``/run`` responses (one per call). Raises the
    first exception encountered if any call fails (use
    :func:`rollout_group_with_retry` for fault-tolerant collection).

    When ``session`` is provided, it is used for all POSTs (caller owns
    lifecycle). Otherwise a throwaway :class:`aiohttp.ClientSession` is
    created and closed.
    """
    if group_size <= 0:
        raise ValueError(f"group_size must be positive, got {group_size}")

    url = _agent_run_url(agent_url)
    async with get_or_create_session(session) as sess:
        coros = [
            _call_once(sess, url, prompt_payload, timeout_sec=timeout_sec)
            for _ in range(group_size)
        ]
        return await asyncio.gather(*coros)


async def rollout_batch(
    agent_url: str,
    prompts: list[dict],
    group_size: int,
    timeout_sec: int = 600,
    session: aiohttp.ClientSession | None = None,
) -> list[list[dict]]:
    """For each prompt in ``prompts``, do a group rollout of size ``group_size``.

    All (``len(prompts) * group_size``) requests run concurrently under a
    single shared ClientSession. Returns a nested list shape
    ``[len(prompts)][group_size]``.

    When ``session`` is provided, it is reused for all POSTs. Otherwise a
    throwaway session is created for this call.
    """
    if group_size <= 0:
        raise ValueError(f"group_size must be positive, got {group_size}")

    url = _agent_run_url(agent_url)
    async with get_or_create_session(session) as sess:
        # Flatten: one coro per (prompt_idx, slot) pair, then reshape.
        flat_coros = [
            _call_once(sess, url, prompt, timeout_sec=timeout_sec)
            for prompt in prompts
            for _ in range(group_size)
        ]
        flat_results = await asyncio.gather(*flat_coros)

    grouped: list[list[dict]] = []
    for i in range(len(prompts)):
        grouped.append(flat_results[i * group_size : (i + 1) * group_size])
    return grouped


async def rollout_group_with_retry(
    agent_url: str,
    prompt_payload: dict,
    group_size: int,
    timeout_sec: int = 600,
    max_retries: int = 2,
    session: aiohttp.ClientSession | None = None,
) -> list[dict]:
    """Best-effort variant of :func:`rollout_group`.

    Each slot is retried up to ``max_retries`` times on HTTP / transport /
    timeout errors. Slots that still fail after retries are silently
    dropped; a WARNING is logged. Returns the list of successful responses
    (may be shorter than ``group_size``).
    """
    if group_size <= 0:
        raise ValueError(f"group_size must be positive, got {group_size}")

    url = _agent_run_url(agent_url)

    async def _one_slot(session: aiohttp.ClientSession, slot: int) -> dict | None:
        for attempt in range(max_retries + 1):
            try:
                return await _call_once(session, url, prompt_payload, timeout_sec=timeout_sec)
            except (TimeoutError, aiohttp.ClientError) as e:
                logger.warning(
                    "Slot %d attempt %d/%d failed: %r",
                    slot,
                    attempt + 1,
                    max_retries + 1,
                    e,
                )
        logger.warning("Slot %d: giving up after %d attempts", slot, max_retries + 1)
        return None

    async with get_or_create_session(session) as sess:
        results = await asyncio.gather(*[_one_slot(sess, i) for i in range(group_size)])

    return [r for r in results if r is not None]


def load_jsonl(path: str) -> list[dict]:
    """Read a one-JSON-per-line file. Skips blank lines.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        ValueError: if a non-blank line fails to parse, with the offending
            line number.
    """
    out: list[dict] = []
    with open(path) as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed JSON on line {lineno} of {path}: {e.msg}") from e
    return out


__all__ = [
    "get_or_create_session",
    "load_jsonl",
    "rollout_batch",
    "rollout_group",
    "rollout_group_with_retry",
    "_call_once",
]

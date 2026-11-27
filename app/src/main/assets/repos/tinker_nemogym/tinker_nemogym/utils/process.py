"""Subprocess and port utilities for tinker-nemogym.

Small, dependency-light helpers shared across the internal pytest suite
and the trainer's agent-discovery path. Used to probe an HTTP service
(typically the nemo-gym HeadServer) before proceeding.

Nothing here imports Tinker or nemo-gym — it's purely stdlib utilities
for port allocation and HTTP readiness polling.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request


def pick_free_port(host: str = "127.0.0.1") -> int:
    """Ask the kernel for a free TCP port on ``host`` and return it.

    There's an unavoidable TOCTOU race between the call returning a port
    and a caller binding it — caller should bind immediately. Works well
    for tests that allocate a port just before spawning their own server.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def wait_for_http_200(url: str, timeout_sec: float = 20.0, poll_sec: float = 0.5) -> None:
    """Poll ``url`` until it responds 2xx or ``timeout_sec`` elapses.

    Raises:
        TimeoutError: if the URL never returns a 2xx response in the window.
    """
    deadline = time.monotonic() + timeout_sec
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    return
        except (urllib.error.URLError, OSError) as e:  # noqa: PERF203
            last_err = e
        time.sleep(poll_sec)
    raise TimeoutError(f"Timed out waiting for {url} (last error: {last_err!r})")


def discover_agent_url(head_url: str, timeout_sec: float = 60.0) -> str:
    """Poll nemo-gym ``HeadServer`` for the first ``responses_api_agents`` URL.

    nemo-gym allocates random ports in 10001-20000 for sub-servers, so
    hard-coding the agent URL isn't portable. ``GET {head_url}/server_instances``
    returns a list of dicts including the agent's live ``http://host:port``.

    Args:
        head_url: base URL for nemo-gym's HeadServer, e.g. ``http://127.0.0.1:11000``.
        timeout_sec: total budget for the poll loop.

    Returns:
        The first agent's URL string.

    Raises:
        TimeoutError: if no ``responses_api_agents`` entry appears in time.
    """
    deadline = time.monotonic() + timeout_sec
    url = f"{head_url.rstrip('/')}/server_instances"
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            for inst in data:
                if inst.get("server_type") == "responses_api_agents" and inst.get("url"):
                    return inst["url"]
        except (urllib.error.URLError, OSError) as e:  # noqa: PERF203
            last_err = e
        time.sleep(1.0)
    raise TimeoutError(
        f"Timed out after {timeout_sec:.0f}s waiting for agent on {head_url} "
        f"(last error: {last_err!r})"
    )


__all__ = ["discover_agent_url", "pick_free_port", "wait_for_http_200"]

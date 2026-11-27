# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# tng_json_format — JSON-output compliance resources server.
#
# Grades a model's structured-output behaviour against a per-row
# ``required_keys`` contract. Partial credit (0.5) for "parses as JSON but
# keys missing/wrong" rewards the first step of the learning curve (the
# model learns *to emit JSON* before it learns *the schema*).
#
# This file is the SINGLE source of truth for the tng_json_format resources
# server. It lives inside tinker-nemogym and is symlinked into the nemo-gym
# sibling repo's ``resources_servers/`` tree at smoke-run time so ``ng_run``
# can discover it.
import json
import re
from typing import Any

from fastapi import FastAPI
from nemo_gym.base_resources_server import (
    BaseResourcesServerConfig,
    BaseRunRequest,
    BaseVerifyRequest,
    BaseVerifyResponse,
    SimpleResourcesServer,
)

# Strip a single outer ```json ... ``` or ``` ... ``` markdown fence if present,
# since many base models wrap JSON in one by default.
_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class JSONFormatResourcesServerConfig(BaseResourcesServerConfig):
    pass


class JSONFormatRunRequest(BaseRunRequest):
    uuid: str | None = None
    required_keys: list[str] | None = None
    expected_count: int | None = None
    metadata: dict[str, Any] | None = None


class JSONFormatVerifyRequest(JSONFormatRunRequest, BaseVerifyRequest):
    pass


class JSONFormatVerifyResponse(BaseVerifyResponse):
    parsed_ok: bool
    keys_ok: bool
    required_keys: list[str] | None
    expected_count: int | None


def _strip_fence(text: str) -> str:
    m = _FENCE_PATTERN.match(text)
    return m.group(1) if m else text


def _keys_match(parsed: Any, required: list[str], expected_count: int | None) -> bool:
    """True if ``parsed`` satisfies the ``required_keys`` contract.

    * If ``parsed`` is a list, every element must be a dict containing all
      ``required_keys``. If ``expected_count`` is set, ``len(parsed)`` must match.
    * If ``parsed`` is a dict, it must contain all ``required_keys``.
    """
    req = set(required)
    if isinstance(parsed, list):
        if expected_count is not None and len(parsed) != expected_count:
            return False
        if not parsed:
            return False
        for item in parsed:
            if not isinstance(item, dict):
                return False
            if not req.issubset(item.keys()):
                return False
        return True
    if isinstance(parsed, dict):
        return req.issubset(parsed.keys())
    return False


class JSONFormatResourcesServer(SimpleResourcesServer):
    config: JSONFormatResourcesServerConfig

    def setup_webserver(self) -> FastAPI:
        return super().setup_webserver()

    async def verify(self, body: JSONFormatVerifyRequest) -> JSONFormatVerifyResponse:
        text = (body.response.output_text or "").strip()
        text = _strip_fence(text)

        parsed: Any = None
        parsed_ok = False
        try:
            parsed = json.loads(text)
            parsed_ok = True
        except (json.JSONDecodeError, ValueError):
            parsed_ok = False

        required = body.required_keys or []
        keys_ok = (
            parsed_ok
            and bool(required)
            and _keys_match(parsed, required, body.expected_count)
        )

        if parsed_ok and keys_ok:
            reward = 1.0
        elif parsed_ok:
            reward = 0.5
        else:
            reward = 0.0

        return JSONFormatVerifyResponse(
            **body.model_dump(),
            reward=reward,
            parsed_ok=parsed_ok,
            keys_ok=keys_ok,
        )


if __name__ == "__main__":
    JSONFormatResourcesServer.run_webserver()

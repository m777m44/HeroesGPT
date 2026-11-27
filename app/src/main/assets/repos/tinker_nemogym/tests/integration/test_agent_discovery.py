"""Integration test: trainer discovers nemo-gym agent URL from HeadServer.

When ``cfg.nemogym.agent_url`` is None, :meth:`TinkerNeMoGymTrainer.setup`
calls :func:`tinker_nemogym.utils.process.discover_agent_url` which GETs
``head_url + /server_instances`` and picks the first
``responses_api_agents`` entry. We spin up a tiny FastAPI server that
impersonates the HeadServer endpoint and verify setup() resolves
``trainer.agent_url`` to the URL it returned.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn
from fastapi import FastAPI

from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
from tinker_nemogym.trainer import TinkerNeMoGymTrainer
from tinker_nemogym.utils.process import pick_free_port


def _make_head_app(agent_url: str) -> FastAPI:
    app = FastAPI()

    @app.get("/server_instances")
    async def _list() -> list[dict]:
        return [
            {"server_type": "resources_servers", "url": "http://ignore:1"},
            {"server_type": "responses_api_agents", "url": agent_url},
        ]

    return app


class _BGServer:
    def __init__(self, app: FastAPI) -> None:
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
            raise RuntimeError("head-server fake never started")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _make_cfg(tmp_path, head_url: str) -> TinkerNeMoGymConfig:
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(json.dumps({"user_messages": ["hi"], "metadata": {}}) + "\n")
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct", lora_rank=4),
        model_server=ModelServerConfig(host="127.0.0.1", port=pick_free_port()),
        nemogym=NeMoGymConfig(
            dataset_jsonl=str(dataset),
            agent_url=None,
            head_url=head_url,
            group_size=2,
        ),
        training=TrainingConfig(n_steps=0, batch_size=1, save_every=0),
    )


@pytest.mark.asyncio
async def test_trainer_discovers_agent_url_from_head_server(tmp_path) -> None:
    """cfg.nemogym.agent_url=None → setup() populates trainer.agent_url from HeadServer."""
    discovered = "http://127.0.0.1:19999"
    head = _BGServer(_make_head_app(discovered))
    head.start()
    try:
        cfg = _make_cfg(tmp_path, head_url=head.url)
        trainer = TinkerNeMoGymTrainer(cfg)

        mock_training_client = MagicMock()
        mock_training_client.save_weights_and_get_sampling_client_async = AsyncMock(
            return_value="sc"
        )
        mock_service_client = MagicMock()
        mock_service_client.create_lora_training_client_async = AsyncMock(
            return_value=mock_training_client
        )
        mock_service_client.get_server_capabilities_async = AsyncMock(
            return_value=MagicMock(supported_models=None)
        )
        with (
            patch(
                "tinker_nemogym.trainer.tinker.ServiceClient", return_value=mock_service_client
            ),
            patch("tinker_nemogym.trainer.tmodel.init"),
            patch("tinker_nemogym.trainer.tmodel.set_sampling_client"),
            patch(
                "tinker_cookbook.model_info.get_recommended_renderer_name",
                return_value="llama3",
            ),
            patch(
                "tinker_cookbook.renderers.get_renderer", return_value=MagicMock(name="renderer")
            ),
            patch(
                "tinker_cookbook.tokenizer_utils.get_tokenizer",
                return_value=MagicMock(name="tokenizer"),
            ),
        ):
            await trainer.setup(start_model_server=False)

        assert trainer.agent_url == discovered
    finally:
        head.stop()

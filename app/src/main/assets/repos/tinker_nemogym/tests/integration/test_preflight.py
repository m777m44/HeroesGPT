"""Preflight checks fire before the expensive LoRA training client creation.

All network access mocked — no real Tinker, no real nemo-gym.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
from tinker_nemogym.errors import AgentDiscoveryError, TinkerNeMoGymError
from tinker_nemogym.trainer import TinkerNeMoGymTrainer


def _make_cfg(
    tmp_path,
    *,
    agent_url: str | None = "http://127.0.0.1:11001",
    head_url: str = "http://127.0.0.1:11000",
) -> TinkerNeMoGymConfig:
    dataset = tmp_path / "d.jsonl"
    dataset.write_text(json.dumps({"user_messages": ["hi"]}) + "\n")
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct", lora_rank=4),
        model_server=ModelServerConfig(port=19001),
        nemogym=NeMoGymConfig(
            dataset_jsonl=str(dataset),
            agent_url=agent_url,
            head_url=head_url,
            group_size=2,
        ),
        training=TrainingConfig(n_steps=0, batch_size=1, save_every=0),
    )


def _inject_service_client(trainer: TinkerNeMoGymTrainer, sc) -> None:
    """Install a zero-arg factory returning sc."""
    trainer._service_client_factory_override = lambda: sc


@pytest.mark.asyncio
async def test_preflight_raises_on_missing_dataset(tmp_path):
    cfg = _make_cfg(tmp_path)
    # Subvert validation by toggling strict=False at construction, then
    # nuking the dataset file so the preflight re-check fires.
    from pathlib import Path

    Path(cfg.nemogym.dataset_jsonl).unlink()

    sc = MagicMock()
    sc.get_server_capabilities_async = AsyncMock(return_value=MagicMock(supported_models=None))

    trainer = TinkerNeMoGymTrainer(cfg)
    _inject_service_client(trainer, sc)

    with pytest.raises(TinkerNeMoGymError, match="dataset_jsonl"):
        await trainer._preflight_checks()


@pytest.mark.asyncio
async def test_preflight_raises_with_auth_hint_on_401(tmp_path):
    cfg = _make_cfg(tmp_path)

    sc = MagicMock()
    sc.get_server_capabilities_async = AsyncMock(
        side_effect=RuntimeError("401 Unauthorized: bad api_key")
    )

    trainer = TinkerNeMoGymTrainer(cfg)
    _inject_service_client(trainer, sc)

    with pytest.raises(TinkerNeMoGymError, match="TINKER_API_KEY"):
        await trainer._preflight_checks()


@pytest.mark.asyncio
async def test_preflight_warns_on_unsupported_base_model(tmp_path, caplog):
    cfg = _make_cfg(tmp_path)

    other = MagicMock()
    other.model_name = "other-model"
    caps = MagicMock()
    caps.supported_models = [other]

    sc = MagicMock()
    sc.get_server_capabilities_async = AsyncMock(return_value=caps)

    trainer = TinkerNeMoGymTrainer(cfg)
    _inject_service_client(trainer, sc)

    with caplog.at_level("WARNING"):
        await trainer._preflight_checks()

    msgs = [r.message for r in caplog.records]
    assert any("NOT in Tinker's supported_models list" in m for m in msgs), msgs


@pytest.mark.asyncio
async def test_preflight_head_server_unreachable_raises_discovery_error(tmp_path):
    # agent_url=None → trigger HeadServer probe. Use a port that's definitely
    # nothing (picked by OS then closed).
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    cfg = _make_cfg(tmp_path, agent_url=None, head_url=f"http://127.0.0.1:{port}")

    sc = MagicMock()
    sc.get_server_capabilities_async = AsyncMock(return_value=MagicMock(supported_models=None))

    trainer = TinkerNeMoGymTrainer(cfg)
    _inject_service_client(trainer, sc)

    with pytest.raises(AgentDiscoveryError, match="nemo-gym"):
        await trainer._preflight_checks()


@pytest.mark.asyncio
async def test_preflight_skips_head_check_when_agent_url_set(tmp_path):
    cfg = _make_cfg(tmp_path, agent_url="http://127.0.0.1:11001")

    sc = MagicMock()
    sc.get_server_capabilities_async = AsyncMock(return_value=MagicMock(supported_models=None))

    trainer = TinkerNeMoGymTrainer(cfg)
    _inject_service_client(trainer, sc)

    with patch.object(trainer, "_preflight_head_server", AsyncMock()) as head_probe:
        await trainer._preflight_checks()
        head_probe.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_service_client_construction_error(tmp_path):
    cfg = _make_cfg(tmp_path)
    trainer = TinkerNeMoGymTrainer(cfg)

    def _broken() -> None:
        raise RuntimeError("no key")

    trainer._service_client_factory_override = _broken

    with pytest.raises(TinkerNeMoGymError, match="TINKER_API_KEY"):
        await trainer._preflight_checks()


@pytest.mark.asyncio
async def test_service_client_factory_di_seam(tmp_path):
    """Passing ``service_client_factory=...`` to the ctor wins over monkey-patch."""
    cfg = _make_cfg(tmp_path)
    sentinel = object()

    def factory() -> object:
        return sentinel

    trainer = TinkerNeMoGymTrainer(cfg, service_client_factory=factory)
    assert trainer._service_client_factory is factory
    # ``service_client_factory()`` is what setup() calls — verify it yields sentinel.
    assert trainer._service_client_factory() is sentinel

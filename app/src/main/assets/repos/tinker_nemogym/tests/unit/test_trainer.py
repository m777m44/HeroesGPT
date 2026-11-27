"""Unit tests for :class:`tinker_nemogym.trainer.TinkerNeMoGymTrainer`.

All external services (tinker clients, tinker_cookbook, the FastAPI shim, wandb,
rollout_driver, and datum_builder helpers) are mocked. These tests exercise the
pure Python glue in the trainer module — constructor, setup(), _run_step(),
_maybe_save_checkpoint(), and wandb gating — without touching the network.
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
from tinker_nemogym.trainer import TinkerNeMoGymTrainer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cfg(tmp_path, **overrides):
    """Build a fully-specified TinkerNeMoGymConfig for tests.

    ``overrides`` keys may be: ``tinker``, ``model_server``, ``nemogym``,
    ``training`` — each a dict merged into the defaults.
    """
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({"user_messages": ["hello"], "metadata": {}}) + "\n")

    tinker_kwargs = {"base_model": "meta-llama/Llama-3.2-1B-Instruct", "lora_rank": 4}
    tinker_kwargs.update(overrides.get("tinker", {}))

    nemogym_kwargs = {"dataset_jsonl": str(dataset), "group_size": 2}
    nemogym_kwargs.update(overrides.get("nemogym", {}))

    training_kwargs = {"n_steps": 1, "batch_size": 1, "save_every": 10}
    training_kwargs.update(overrides.get("training", {}))

    model_server_kwargs = {"host": "127.0.0.1", "port": 18001}
    model_server_kwargs.update(overrides.get("model_server", {}))

    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(**tinker_kwargs),
        model_server=ModelServerConfig(**model_server_kwargs),
        nemogym=NeMoGymConfig(**nemogym_kwargs),
        training=TrainingConfig(**training_kwargs),
    )


@pytest.fixture
def cfg(tmp_path):
    return _make_cfg(tmp_path)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_constructor_stores_config_and_initializes_attrs(cfg):
    trainer = TinkerNeMoGymTrainer(cfg)
    assert trainer.cfg is cfg
    assert trainer.service_client is None
    assert trainer.training_client is None
    assert trainer.current_sampling_client is None
    assert trainer.tokenizer is None
    assert trainer.renderer is None
    assert trainer.dataset == []
    assert trainer._wandb_enabled is False
    assert trainer._server_thread is None
    assert trainer._server is None


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_populates_clients_and_dataset(cfg):
    """setup() creates service/training/sampling clients and loads dataset."""
    trainer = TinkerNeMoGymTrainer(cfg)

    mock_training_client = MagicMock()
    mock_training_client.save_weights_and_get_sampling_client_async = AsyncMock(
        return_value="sampling-client-0"
    )
    mock_service_client = MagicMock()
    mock_service_client.create_lora_training_client_async = AsyncMock(
        return_value=mock_training_client
    )
    # Preflight probe — async, returns an object with ``supported_models``.
    mock_service_client.get_server_capabilities_async = AsyncMock(
        return_value=MagicMock(supported_models=[MagicMock(model_name="meta-llama/Llama-3.2-1B-Instruct")])
    )

    with (
        patch("tinker_nemogym.trainer.tinker.ServiceClient", return_value=mock_service_client),
        patch("tinker_nemogym.trainer.tmodel.init") as mock_init,
        patch("tinker_nemogym.trainer.tmodel.set_sampling_client") as mock_set,
        patch("tinker_cookbook.model_info.get_recommended_renderer_name", return_value="llama3"),
        patch("tinker_cookbook.renderers.get_renderer", return_value=MagicMock(name="renderer")),
        patch(
            "tinker_cookbook.tokenizer_utils.get_tokenizer",
            return_value=MagicMock(name="tokenizer"),
        ),
    ):
        await trainer.setup(start_model_server=False)

    assert trainer.service_client is mock_service_client
    assert trainer.training_client is mock_training_client
    assert trainer.current_sampling_client == "sampling-client-0"
    assert trainer.tokenizer is not None
    assert trainer.renderer is not None
    mock_service_client.create_lora_training_client_async.assert_awaited_once()
    # Tinker SDK dropped ``name=`` in 0.18+; trainer must not pass it anymore.
    mock_training_client.save_weights_and_get_sampling_client_async.assert_awaited_once_with()
    mock_init.assert_called_once()
    mock_set.assert_called_once_with("sampling-client-0", version=1)


@pytest.mark.asyncio
async def test_setup_loads_dataset_from_jsonl(tmp_path):
    """setup() loads dataset rows from cfg.nemogym.dataset_jsonl."""
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        json.dumps({"user_messages": ["a"], "metadata": {}})
        + "\n"
        + json.dumps({"user_messages": ["b"], "metadata": {}})
        + "\n"
        + json.dumps({"user_messages": ["c"], "metadata": {}})
        + "\n"
    )
    cfg = _make_cfg(tmp_path, nemogym={"dataset_jsonl": str(dataset)})
    trainer = TinkerNeMoGymTrainer(cfg)

    mock_training_client = MagicMock()
    mock_training_client.save_weights_and_get_sampling_client_async = AsyncMock(return_value="sc")
    mock_service_client = MagicMock()
    mock_service_client.create_lora_training_client_async = AsyncMock(
        return_value=mock_training_client
    )
    mock_service_client.get_server_capabilities_async = AsyncMock(
        return_value=MagicMock(supported_models=None)
    )

    with (
        patch("tinker_nemogym.trainer.tinker.ServiceClient", return_value=mock_service_client),
        patch("tinker_nemogym.trainer.tmodel.init"),
        patch("tinker_nemogym.trainer.tmodel.set_sampling_client"),
        patch("tinker_cookbook.model_info.get_recommended_renderer_name", return_value="r"),
        patch("tinker_cookbook.renderers.get_renderer", return_value=MagicMock()),
        patch("tinker_cookbook.tokenizer_utils.get_tokenizer", return_value=MagicMock()),
    ):
        await trainer.setup(start_model_server=False)

    assert len(trainer.dataset) == 3
    assert trainer.dataset[0]["user_messages"] == ["a"]


# ---------------------------------------------------------------------------
# wandb gating
# ---------------------------------------------------------------------------


def test_maybe_init_wandb_disabled_when_project_none(cfg):
    trainer = TinkerNeMoGymTrainer(cfg)
    fake_wandb = MagicMock()
    with patch.dict("sys.modules", {"wandb": fake_wandb}):
        trainer._maybe_init_wandb()
    fake_wandb.init.assert_not_called()
    assert trainer._wandb_enabled is False


def test_maybe_init_wandb_enabled_when_project_set(tmp_path):
    cfg = _make_cfg(
        tmp_path,
        tinker={"wandb_project": "my-proj", "wandb_name": "exp-1"},
    )
    trainer = TinkerNeMoGymTrainer(cfg)
    fake_wandb = MagicMock()
    with patch.dict("sys.modules", {"wandb": fake_wandb}):
        trainer._maybe_init_wandb()
    fake_wandb.init.assert_called_once()
    kwargs = fake_wandb.init.call_args.kwargs
    assert kwargs["project"] == "my-proj"
    assert kwargs["name"] == "exp-1"
    assert trainer._wandb_enabled is True


# ---------------------------------------------------------------------------
# _run_step
# ---------------------------------------------------------------------------


def _install_training_mocks(trainer):
    """Populate trainer with mocked tinker clients ready for _run_step."""
    fwd_future = MagicMock()
    fwd_result = MagicMock()
    fwd_result.metrics = {"loss:sum": 1.25}
    fwd_future.result_async = AsyncMock(return_value=fwd_result)
    opt_future = MagicMock()
    opt_future.result_async = AsyncMock(return_value=None)

    trainer.training_client = MagicMock()
    trainer.training_client.forward_backward_async = AsyncMock(return_value=fwd_future)
    trainer.training_client.optim_step_async = AsyncMock(return_value=opt_future)
    trainer.training_client.save_weights_and_get_sampling_client_async = AsyncMock(
        return_value="new-sampling-client"
    )
    trainer.training_client.save_state_async = AsyncMock(
        return_value=MagicMock(result_async=AsyncMock(return_value=None))
    )
    trainer.dataset = [{"user_messages": ["hi"], "metadata": {}}]
    return trainer


@pytest.mark.asyncio
async def test_run_step_variable_rewards_triggers_full_pipeline(cfg):
    """Variable rewards → fwd_bwd, optim_step, save_weights, set_sampling_client all run once."""
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))

    # Two rollouts in one group, distinct rewards (so build_batch won't drop).
    groups_raw = [[{"reward": 1.0}, {"reward": 0.0}]]
    fake_traj = MagicMock(reward=1.0)
    fake_datums = [MagicMock(), MagicMock()]
    fake_meta = {"mean_reward": 0.5, "n_datums": 2, "n_dropped_constant": 0}

    with (
        patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=groups_raw)),
        patch("tinker_nemogym.trainer.extract_trajectory", return_value=fake_traj),
        patch(
            "tinker_nemogym.trainer.build_batch_with_trajectories",
            return_value=(fake_datums, [object()] * len(fake_datums), fake_meta),
        ),
        patch("tinker_nemogym.trainer.tmodel.set_sampling_client") as mock_set,
    ):
        metrics = await trainer._run_step(0)

    trainer.training_client.forward_backward_async.assert_awaited_once()
    trainer.training_client.optim_step_async.assert_awaited_once()
    trainer.training_client.save_weights_and_get_sampling_client_async.assert_awaited_once_with()
    mock_set.assert_called_once_with("new-sampling-client", version=1)
    assert metrics["step"] == 0
    assert metrics["n_datums"] == 2
    assert metrics["mean_reward"] == pytest.approx(0.5)
    assert metrics["loss"] == pytest.approx(1.25)
    assert trainer.current_sampling_client == "new-sampling-client"


@pytest.mark.asyncio
async def test_run_step_constant_reward_skips_training(cfg, caplog):
    """Constant-reward batch → build_batch returns no datums → forward_backward not called."""
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))

    groups_raw = [[{"reward": 1.0}, {"reward": 1.0}]]
    fake_traj = MagicMock(reward=1.0)
    fake_meta = {"mean_reward": 1.0, "n_datums": 0, "n_dropped_constant": 1}

    with (
        patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=groups_raw)),
        patch("tinker_nemogym.trainer.extract_trajectory", return_value=fake_traj),
        patch(
            "tinker_nemogym.trainer.build_batch_with_trajectories",
            return_value=([], [], fake_meta),
        ),
        patch("tinker_nemogym.trainer.tmodel.set_sampling_client") as mock_set,
    ):
        with caplog.at_level("WARNING"):
            metrics = await trainer._run_step(0)

    trainer.training_client.forward_backward_async.assert_not_called()
    trainer.training_client.optim_step_async.assert_not_called()
    trainer.training_client.save_weights_and_get_sampling_client_async.assert_not_called()
    mock_set.assert_not_called()
    assert metrics["n_datums"] == 0
    assert metrics["n_dropped"] == 1
    assert any("constant reward" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_save_checkpoint_triggers_at_save_every_boundary(tmp_path):
    """Save fires when (step+1) % save_every == 0, not otherwise."""
    cfg = _make_cfg(tmp_path, training={"save_every": 5, "n_steps": 1, "batch_size": 1})
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))

    # step=3 → (3+1) % 5 == 4, no save.
    await trainer._maybe_save_checkpoint(3)
    trainer.training_client.save_state_async.assert_not_called()

    # step=4 → (4+1) % 5 == 0, save triggered.
    await trainer._maybe_save_checkpoint(4)
    trainer.training_client.save_state_async.assert_awaited_once()
    called_name = trainer.training_client.save_state_async.call_args.kwargs.get("name")
    assert called_name is not None
    # Tinker validates weights labels as [A-Za-z0-9._-]; the trainer now builds
    # a safe label (not a filesystem path). The step counter lives at the tail.
    assert called_name.endswith("step-5")
    assert "/" not in called_name


@pytest.mark.asyncio
async def test_maybe_save_checkpoint_noop_when_save_every_zero(tmp_path):
    cfg = _make_cfg(tmp_path, training={"save_every": 0, "n_steps": 1, "batch_size": 1})
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))
    await trainer._maybe_save_checkpoint(9)
    trainer.training_client.save_state_async.assert_not_called()


# ---------------------------------------------------------------------------
# Review 05 §4.1 — training errors are wrapped as TrainingError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_step_wraps_fwd_bwd_failure_as_training_error(cfg):
    """When forward_backward_async raises, the error stored on metrics is a TrainingError."""
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))
    trainer.training_client.forward_backward_async = AsyncMock(
        side_effect=RuntimeError("fwd exploded")
    )

    groups_raw = [[{"reward": 1.0}, {"reward": 0.0}]]
    fake_traj = MagicMock(reward=1.0)
    fake_datums = [MagicMock(), MagicMock()]
    fake_meta = {"mean_reward": 0.5, "n_datums": 2, "n_dropped_constant": 0}

    with (
        patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=groups_raw)),
        patch("tinker_nemogym.trainer.extract_trajectory", return_value=fake_traj),
        patch(
            "tinker_nemogym.trainer.build_batch_with_trajectories",
            return_value=(fake_datums, [object()] * len(fake_datums), fake_meta),
        ),
    ):
        metrics = await trainer._run_step(0)

    assert "fwd_bwd_error" in metrics
    assert "TrainingError" in metrics["fwd_bwd_error"]


@pytest.mark.asyncio
async def test_run_step_wraps_hot_swap_failure_as_training_error(cfg):
    """When save_weights_and_get_sampling_client_async raises, metrics carry a TrainingError."""
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))
    trainer.training_client.save_weights_and_get_sampling_client_async = AsyncMock(
        side_effect=RuntimeError("hot-swap exploded")
    )

    groups_raw = [[{"reward": 1.0}, {"reward": 0.0}]]
    fake_traj = MagicMock(reward=1.0)
    fake_datums = [MagicMock(), MagicMock()]
    fake_meta = {"mean_reward": 0.5, "n_datums": 2, "n_dropped_constant": 0}

    with (
        patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=groups_raw)),
        patch("tinker_nemogym.trainer.extract_trajectory", return_value=fake_traj),
        patch(
            "tinker_nemogym.trainer.build_batch_with_trajectories",
            return_value=(fake_datums, [object()] * len(fake_datums), fake_meta),
        ),
        patch("tinker_nemogym.trainer.tmodel.set_sampling_client"),
    ):
        metrics = await trainer._run_step(0)

    assert "hot_swap_error" in metrics
    assert "TrainingError" in metrics["hot_swap_error"]


# ---------------------------------------------------------------------------
# Review 07 §3 C3 — checkpoint metadata sidecar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_save_checkpoint_writes_meta_sidecar(tmp_path):
    """save_state_async fires → <label>.meta.json appears alongside the weights."""
    ckpt_dir = tmp_path / "ckpts"
    ckpt_dir.mkdir()
    cfg = _make_cfg(
        tmp_path,
        training={"save_every": 1, "n_steps": 1, "batch_size": 1, "random_seed": 7},
        tinker={"checkpoint_dir": str(ckpt_dir)},
    )
    trainer = _install_training_mocks(TinkerNeMoGymTrainer(cfg))
    # Populate the driver-side state we'd like to see round-trip.
    trainer._save_count = 3
    trainer.dataset_cursor = 12
    trainer.mean_reward_history = [0.1, 0.3, 0.5]
    trainer.run_id = "rid12345"

    await trainer._maybe_save_checkpoint(0)

    # Label format is ``<checkpoint_dir basename>-step-<N>``.
    expected = ckpt_dir / "ckpts-step-1.meta.json"
    assert expected.exists()
    payload = json.loads(expected.read_text())
    assert payload["step"] == 1
    assert payload["save_count"] == 3
    assert payload["dataset_cursor"] == 12
    assert payload["mean_reward_history"] == [0.1, 0.3, 0.5]
    assert payload["random_seed"] == 7
    assert payload["run_id"] == "rid12345"


def test_maybe_load_checkpoint_meta_restores_state(tmp_path):
    """When the trainer is constructed with resume_from_checkpoint, meta is loaded."""
    from tinker_nemogym.checkpoint_meta import CheckpointMeta, save_meta

    ckpt_dir = tmp_path / "ckpts"
    ckpt_dir.mkdir()
    save_meta(
        ckpt_dir,
        "ckpts-step-5",
        CheckpointMeta(
            step=5,
            save_count=3,
            mean_reward_history=[0.1, 0.2, 0.3],
            random_seed=42,
            dataset_cursor=20,
            run_id="rrr",
        ),
    )

    cfg = _make_cfg(
        tmp_path,
        tinker={
            "checkpoint_dir": str(ckpt_dir),
            "resume_from_checkpoint": "tinker://runid/weights/step_5",
        },
    )
    trainer = TinkerNeMoGymTrainer(cfg)
    trainer._maybe_load_checkpoint_meta("tinker://runid/weights/step_5")

    assert trainer._save_count == 3
    assert trainer.mean_reward_history == [0.1, 0.2, 0.3]
    assert trainer.dataset_cursor == 20
    assert trainer.run_id == "rrr"
    assert trainer._resumed_step == 5


def test_maybe_load_checkpoint_meta_noop_when_absent(tmp_path):
    """Missing sidecar → trainer state untouched (fresh values preserved)."""
    cfg = _make_cfg(tmp_path)
    trainer = TinkerNeMoGymTrainer(cfg)
    trainer._save_count = 42
    trainer._maybe_load_checkpoint_meta("tinker://runid/weights/step_99")
    assert trainer._save_count == 42  # unchanged
    assert trainer.mean_reward_history == []
    assert trainer.dataset_cursor == 0

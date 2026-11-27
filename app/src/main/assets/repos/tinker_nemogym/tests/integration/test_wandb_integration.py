"""Wandb lifecycle + logging tests — driven entirely through :class:`FakeWandb`.

We never import the real ``wandb`` module in these tests; ``patch_wandb``
replaces ``sys.modules["wandb"]`` for the duration of each test so the
trainer's ``import wandb`` picks up the fake.
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
from tinker_nemogym.testing import FakeWandb, make_fake_tinker_module, patch_wandb
from tinker_nemogym.trainer import TinkerNeMoGymTrainer
from tinker_nemogym.utils.process import pick_free_port


def _cfg(tmp_path, *, project: str | None = None, name: str | None = None, n_steps: int = 3):
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        json.dumps({"responses_create_params": {"input": [{"role": "user", "content": "x"}]}})
        + "\n"
    )
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(
            base_model="meta-llama/Llama-3.2-1B-Instruct",
            lora_rank=4,
            wandb_project=project,
            wandb_name=name,
        ),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(dataset_jsonl=str(dataset), group_size=2),
        training=TrainingConfig(n_steps=n_steps, batch_size=1, save_every=0),
    )


def _patch_run_step_pipeline(trainer, mean_rewards: list[float]) -> None:
    """Replace rollout_batch/extract/build_batch so _run_step resolves instantly.

    Tests only care about the wandb interactions, not whether tokens flow.
    Each call returns the next reward in ``mean_rewards`` (cycles).
    """
    trainer.dataset = [{"responses_create_params": {}}]
    state = {"i": 0}

    def _meta_for_call(*_a, **_kw):
        i = state["i"]
        state["i"] += 1
        r = mean_rewards[i % len(mean_rewards)]
        meta = {"mean_reward": r, "n_datums": 2, "n_dropped_constant": 0}
        datums = [MagicMock(), MagicMock()]
        return (datums, [object(), object()], meta)

    # Patch via object-level attributes; trainer._run_step uses module globals.
    patches = [
        patch("tinker_nemogym.trainer.rollout_batch", AsyncMock(return_value=[[{}, {}]])),
        patch("tinker_nemogym.trainer.extract_trajectory", return_value=MagicMock(reward=1.0)),
        patch("tinker_nemogym.trainer.build_batch_with_trajectories", side_effect=_meta_for_call),
    ]
    for p in patches:
        p.start()
    # Stash so caller can stop.
    trainer._test_patches = patches  # type: ignore[attr-defined]


def _unpatch(trainer) -> None:
    for p in getattr(trainer, "_test_patches", []):
        p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wandb_disabled_when_no_project(tmp_path) -> None:
    """wandb_project=None → trainer never touches wandb (not even import-to-init)."""
    cfg = _cfg(tmp_path, project=None, n_steps=0)
    fake = FakeWandb()
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            await trainer._cleanup()
    # Init never called; finish never called.
    assert fake.init_calls == []
    assert fake.finish_calls == 0


@pytest.mark.asyncio
async def test_wandb_run_name_uses_config(tmp_path) -> None:
    """config.tinker.wandb_name='my_run' → wandb.init called with name='my_run'."""
    cfg = _cfg(tmp_path, project="proj", name="my_run", n_steps=0)
    fake = FakeWandb()
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            await trainer._cleanup()
    assert len(fake.init_calls) == 1
    assert fake.init_calls[0]["project"] == "proj"
    assert fake.init_calls[0]["name"] == "my_run"


@pytest.mark.asyncio
async def test_wandb_log_called_per_step(tmp_path) -> None:
    """3 steps → wandb.log called 3 times, each payload has the expected keys."""
    cfg = _cfg(tmp_path, project="proj", n_steps=3)
    fake = FakeWandb()
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            _patch_run_step_pipeline(trainer, [0.25, 0.5, 0.75])
            try:
                await trainer.run()
            finally:
                _unpatch(trainer)
    assert len(fake.log_calls) == 3
    expected_keys = {"train/mean_reward", "train/n_datums", "train/n_dropped"}
    for entry in fake.log_calls:
        assert expected_keys.issubset(entry.keys()), f"missing keys in {entry}"


@pytest.mark.asyncio
async def test_wandb_finish_called_at_end(tmp_path) -> None:
    """Normal completion → wandb.finish called exactly once."""
    cfg = _cfg(tmp_path, project="proj", n_steps=2)
    fake = FakeWandb()
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            _patch_run_step_pipeline(trainer, [0.25, 0.75])
            try:
                await trainer.run()
            finally:
                _unpatch(trainer)
    assert fake.finish_calls == 1


@pytest.mark.asyncio
async def test_wandb_finish_called_on_exception(tmp_path) -> None:
    """An exception inside the loop must still fire wandb.finish() once."""
    cfg = _cfg(tmp_path, project="proj", n_steps=2)
    fake = FakeWandb()

    # Drive a failure by having setup() raise AFTER init ran. The simplest
    # reliable injection: make _run_step raise, and rely on the outer
    # finally-block that calls _finish_wandb.
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)

            async def _boom(step: int) -> dict:
                raise RuntimeError("simulated step failure")

            trainer._run_step = _boom  # type: ignore[assignment]
            await trainer.run()  # outer try/except swallows per-step failures
    assert fake.finish_calls == 1


@pytest.mark.asyncio
async def test_wandb_log_includes_loss_when_fwd_bwd_runs(tmp_path) -> None:
    """train/loss appears in the payload when fwd_bwd actually produced a loss."""
    cfg = _cfg(tmp_path, project="proj", n_steps=1)
    fake = FakeWandb()
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            _patch_run_step_pipeline(trainer, [0.5])
            try:
                await trainer.run()
            finally:
                _unpatch(trainer)
    assert len(fake.log_calls) == 1
    entry = fake.log_calls[0]
    # Fake LoRA client returns loss=0.5 via metrics["loss:sum"] → trainer
    # stores it as metrics["loss"] → we log it as train/loss.
    assert "train/loss" in entry


@pytest.mark.asyncio
async def test_wandb_log_failure_does_not_crash(tmp_path) -> None:
    """wandb.log raising should be logged and swallowed — run must complete."""
    cfg = _cfg(tmp_path, project="proj", n_steps=1)

    class _FlakyWandb(FakeWandb):
        def log(self, payload, step=None):  # type: ignore[override]
            super().log(payload, step=step)
            raise RuntimeError("network partition")

    fake = _FlakyWandb()
    with patch_wandb(fake):
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            _patch_run_step_pipeline(trainer, [0.5])
            try:
                await trainer.run()  # must not raise
            finally:
                _unpatch(trainer)
    # log was attempted; finish still ran.
    assert len(fake.log_calls) == 1
    assert fake.finish_calls == 1

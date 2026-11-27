"""Integration tests for checkpoint resume (``resume_from_checkpoint``).

Verifies three tiers:

1. :meth:`FakeLoRATrainingClient.load_state_async` records the requested
   path and returns a future — i.e. our fake matches the real SDK shape.
2. ``TinkerNeMoGymTrainer.setup()`` calls ``load_state_async`` **before**
   the initial ``save_weights_and_get_sampling_client_async`` when
   ``cfg.tinker.resume_from_checkpoint`` is set.
3. Full roundtrip: save in trainer A → resume in trainer B picks up the
   same path string.
"""

from __future__ import annotations

import json

import pytest

from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)
from tinker_nemogym.testing import FakeLoRATrainingClient, make_fake_tinker_module
from tinker_nemogym.trainer import TinkerNeMoGymTrainer
from tinker_nemogym.utils.process import pick_free_port


def _make_cfg(tmp_path, *, resume: str | None = None, save_every: int = 0):
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        json.dumps(
            {"responses_create_params": {"input": [{"role": "user", "content": "hi"}]}}
        )
        + "\n"
    )
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(
            base_model="meta-llama/Llama-3.2-1B-Instruct",
            lora_rank=4,
            resume_from_checkpoint=resume,
            checkpoint_dir=str(tmp_path / "ckpt"),
        ),
        model_server=ModelServerConfig(port=pick_free_port()),
        nemogym=NeMoGymConfig(dataset_jsonl=str(dataset), group_size=1),
        training=TrainingConfig(n_steps=1, batch_size=1, save_every=save_every),
    )


@pytest.mark.asyncio
async def test_fake_load_state_async_records_path() -> None:
    """Fake's load_state_async records the path + returns a ready future."""
    client = FakeLoRATrainingClient()
    fut = await client.load_state_async("fake://state/step_5")
    assert (await fut.result_async())["path"] == "fake://state/step_5"
    methods = [c.method for c in client.call_history]
    assert "load_state_async" in methods
    assert client._loaded_state == "fake://state/step_5"


@pytest.mark.asyncio
async def test_fake_load_state_with_optimizer_records_path() -> None:
    client = FakeLoRATrainingClient()
    await client.load_state_with_optimizer_async("fake://state/step_5")
    methods = [c.method for c in client.call_history]
    assert "load_state_with_optimizer_async" in methods
    assert client._loaded_state == "fake://state/step_5"


@pytest.mark.asyncio
async def test_trainer_resumes_from_checkpoint(tmp_path) -> None:
    """setup() with resume set → load_state_async called before the initial save."""
    cfg = _make_cfg(tmp_path, resume="fake://state/step_5")
    with make_fake_tinker_module():
        trainer = TinkerNeMoGymTrainer(cfg)
        await trainer.setup(start_model_server=False)

        methods = [c.method for c in trainer.training_client.call_history]
        # Must contain load_state_async.
        assert "load_state_async" in methods
        # And must precede the initial save_weights_and_get_sampling_client_async.
        assert methods.index("load_state_async") < methods.index(
            "save_weights_and_get_sampling_client_async"
        )
        # Path propagated.
        load_calls = [
            c for c in trainer.training_client.call_history if c.method == "load_state_async"
        ]
        assert load_calls[0].kwargs["path"] == "fake://state/step_5"
        await trainer._cleanup()


@pytest.mark.asyncio
async def test_trainer_no_resume_skips_load_state(tmp_path) -> None:
    """Without resume config, load_state_async is not called."""
    cfg = _make_cfg(tmp_path, resume=None)
    with make_fake_tinker_module():
        trainer = TinkerNeMoGymTrainer(cfg)
        await trainer.setup(start_model_server=False)
        methods = [c.method for c in trainer.training_client.call_history]
        assert "load_state_async" not in methods
        await trainer._cleanup()


@pytest.mark.asyncio
async def test_trainer_load_state_failure_is_non_fatal(tmp_path) -> None:
    """If load_state_async raises, setup() still completes (with ERROR log)."""
    cfg = _make_cfg(tmp_path, resume="fake://bad/path")
    from tinker_nemogym.testing.fakes import FakeLoRATrainingClient as _F

    original = _F.load_state_async

    async def _boom(self, path, weights_access_token=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("backend down")

    _F.load_state_async = _boom  # type: ignore[assignment]
    try:
        with make_fake_tinker_module():
            trainer = TinkerNeMoGymTrainer(cfg)
            await trainer.setup(start_model_server=False)
            # Initial sampling client still got created despite the load failure.
            assert trainer.current_sampling_client is not None
            await trainer._cleanup()
    finally:
        _F.load_state_async = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_trainer_full_roundtrip_save_then_resume(tmp_path) -> None:
    """Run trainer A, capture save path, resume a brand-new trainer B from it."""
    # Trainer A: save_every=1 so one save happens after step 0.
    cfg_a = _make_cfg(tmp_path, resume=None, save_every=1)
    with make_fake_tinker_module():
        trainer_a = TinkerNeMoGymTrainer(cfg_a)
        await trainer_a.setup(start_model_server=False)
        # Skip the rollout path entirely — we just want the save_state call.
        await trainer_a._maybe_save_checkpoint(0)
        save_calls = [
            c for c in trainer_a.training_client.call_history if c.method == "save_state_async"
        ]
        assert save_calls, "expected at least one save_state_async call"
        saved_path = save_calls[-1].kwargs["name"]
        await trainer_a._cleanup()

    assert saved_path  # non-empty

    # Trainer B: resume from the path we just captured.
    cfg_b = _make_cfg(tmp_path, resume=saved_path)
    with make_fake_tinker_module():
        trainer_b = TinkerNeMoGymTrainer(cfg_b)
        await trainer_b.setup(start_model_server=False)
        load_calls = [
            c for c in trainer_b.training_client.call_history if c.method == "load_state_async"
        ]
        assert load_calls, "expected load_state_async in B"
        assert load_calls[0].kwargs["path"] == saved_path
        await trainer_b._cleanup()

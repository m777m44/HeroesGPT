"""Tests for :mod:`tinker_nemogym.checkpoint_meta`."""

from __future__ import annotations

import json

from tinker_nemogym.checkpoint_meta import (
    CheckpointMeta,
    load_meta,
    meta_path,
    save_meta,
)


def test_checkpoint_meta_round_trip(tmp_path):
    meta = CheckpointMeta(
        step=10,
        save_count=5,
        mean_reward_history=[0.0, 0.25, 0.5, 0.8],
        wandb_run_id="abc123",
        random_seed=42,
        dataset_cursor=200,
        run_id="run-xyz",
    )
    save_meta(tmp_path, "ckpt-step-10", meta)
    loaded = load_meta(tmp_path, "ckpt-step-10")
    assert loaded is not None
    assert loaded.step == 10
    assert loaded.save_count == 5
    assert loaded.mean_reward_history == [0.0, 0.25, 0.5, 0.8]
    assert loaded.wandb_run_id == "abc123"
    assert loaded.random_seed == 42
    assert loaded.dataset_cursor == 200
    assert loaded.run_id == "run-xyz"


def test_load_meta_returns_none_when_missing(tmp_path):
    assert load_meta(tmp_path, "does_not_exist") is None


def test_save_meta_writes_to_expected_path(tmp_path):
    p = save_meta(tmp_path, "label42", CheckpointMeta(step=3))
    assert p == meta_path(tmp_path, "label42")
    assert p.exists()
    payload = json.loads(p.read_text())
    assert payload["step"] == 3


def test_unknown_keys_round_trip(tmp_path):
    """Future-added keys stay on the object and write back out unchanged."""
    raw = {
        "step": 7,
        "save_count": 2,
        "mean_reward_history": [],
        "wandb_run_id": None,
        "random_seed": None,
        "dataset_cursor": 0,
        "run_id": None,
        "future_field_we_dont_know_yet": "keep me",
    }
    p = meta_path(tmp_path, "fwd")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw))

    meta = load_meta(tmp_path, "fwd")
    assert meta is not None
    assert meta.extra == {"future_field_we_dont_know_yet": "keep me"}

    save_meta(tmp_path, "fwd", meta)
    reloaded = json.loads(p.read_text())
    assert reloaded["future_field_we_dont_know_yet"] == "keep me"


def test_save_then_load_via_trainer_surface(tmp_path):
    """End-to-end sanity: save via helper, load via helper."""
    meta = CheckpointMeta(step=1, save_count=1, dataset_cursor=4)
    save_meta(tmp_path, "L", meta)
    loaded = load_meta(tmp_path, "L")
    assert loaded == meta or (loaded is not None and loaded.step == 1)

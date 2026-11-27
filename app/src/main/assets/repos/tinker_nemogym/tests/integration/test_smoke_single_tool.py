"""End-to-end smoke test wiring for the example_single_tool_call environment.

Two tiers of tests:

1. Cheap, always-run sanity checks — that the on-disk artifacts (configs,
   dataset, script) exist and parse as expected. These guard against
   regressions even in CI without a Tinker key.

2. Live Tinker tests — marked `slow` + skipped when ``TINKER_API_KEY`` is
   unset. They instantiate :class:`TinkerNeMoGymTrainer` with the smoke
   config and (optionally) run a small training loop.

The heavy tests also depend on nemo-gym being running externally (the
:func:`scripts/smoke_single_tool.sh` launcher handles that). When nemo-gym
isn't reachable they degrade gracefully: ``setup()`` alone hits Tinker but
doesn't need the gym, while the 2-step training test is tolerant of rollout
failures (per-step try/except in ``trainer._run_step``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from tinker_nemogym.config import TinkerNeMoGymConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_YAML = REPO_ROOT / "configs" / "smoke_single_tool.yaml"
NEMOGYM_AGENT_YAML = REPO_ROOT / "configs" / "nemogym_agent.yaml"
NEMOGYM_RESOURCES_YAML = REPO_ROOT / "configs" / "nemogym_resources.yaml"
DATASET_JSONL = REPO_ROOT / "tinker_nemogym" / "environments" / "single_tool_call" / "dataset.jsonl"
LAUNCHER_SH = REPO_ROOT / "scripts" / "smoke_single_tool.sh"


# ---------------------------------------------------------------------------
# Always-run on-disk sanity
# ---------------------------------------------------------------------------


def test_smoke_configs_exist() -> None:
    """Every config + script + dataset shipped with the smoke test is on disk."""
    for p in (
        SMOKE_YAML,
        NEMOGYM_AGENT_YAML,
        NEMOGYM_RESOURCES_YAML,
        DATASET_JSONL,
        LAUNCHER_SH,
    ):
        assert p.is_file(), f"missing expected file: {p}"

    # dataset is non-empty JSONL
    lines = [ln for ln in DATASET_JSONL.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 1, "dataset.jsonl is empty"

    # launcher is executable
    assert os.access(LAUNCHER_SH, os.X_OK), "smoke_single_tool.sh is not executable"


def test_smoke_yaml_parses_as_TinkerNeMoGymConfig() -> None:
    """Loading the smoke YAML should produce a validated TinkerNeMoGymConfig."""
    cfg = TinkerNeMoGymConfig.from_yaml(SMOKE_YAML)
    # Spot-check a handful of invariants the launcher/trainer rely on.
    assert cfg.model_server.port == 8001
    assert cfg.nemogym.dataset_jsonl.endswith("dataset.jsonl")
    assert cfg.training.n_steps >= 1
    assert cfg.training.batch_size >= 1
    assert cfg.tinker.lora_rank >= 1
    # The dataset path is resolvable from the repo root.
    dataset_abs = (REPO_ROOT / cfg.nemogym.dataset_jsonl).resolve()
    assert dataset_abs.is_file(), f"dataset missing at {dataset_abs}"


def test_nemogym_agent_yaml_points_at_shim_port() -> None:
    """The nemo-gym agent config should route through http://127.0.0.1:8001 —
    our FastAPI shim. If someone changes the shim port this check fires.

    We use the ``openai_model`` policy_model server type (see
    docs/E2E_FIXES.md §1), which exposes ``openai_base_url`` rather than
    ``vllm_model``'s ``base_url``.
    """
    data = yaml.safe_load(NEMOGYM_AGENT_YAML.read_text())
    openai_block = data["policy_model"]["responses_api_models"]["openai_model"]
    assert openai_block["openai_base_url"].rstrip("/").endswith(":8001/v1")
    assert openai_block["openai_model"] == "tinker"


# ---------------------------------------------------------------------------
# Live Tinker tests (skipped without API key)
# ---------------------------------------------------------------------------

TINKER_KEY_PRESENT = bool(os.environ.get("TINKER_API_KEY"))
requires_tinker = pytest.mark.skipif(
    not TINKER_KEY_PRESENT,
    reason="TINKER_API_KEY not set — skipping live Tinker smoke test",
)


@pytest.mark.slow
@requires_tinker
@pytest.mark.asyncio
async def test_smoke_trainer_setup_only() -> None:
    """Instantiate TinkerNeMoGymTrainer with the smoke config and run setup().

    This contacts Tinker (LoRATrainingClient + initial SamplingClient) but
    does not require the nemo-gym agent to be running. Useful to confirm
    the Tinker creds + config + tokenizer plumbing work before attempting a
    full training pass.
    """
    from tinker_nemogym.trainer import TinkerNeMoGymTrainer

    cfg = TinkerNeMoGymConfig.from_yaml(SMOKE_YAML)
    trainer = TinkerNeMoGymTrainer(cfg)
    # start_model_server=False — no FastAPI shim, just the Tinker clients.
    await trainer.setup(start_model_server=False)
    assert trainer.training_client is not None
    assert trainer.current_sampling_client is not None
    assert trainer.tokenizer is not None
    assert trainer.dataset, "dataset should have loaded in setup()"


@pytest.mark.slow
@requires_tinker
@pytest.mark.asyncio
async def test_smoke_two_step_training(tmp_path: Path) -> None:
    """Full end-to-end: runs the first 2 training steps of the smoke config.

    Requires nemo-gym to be running externally (via ``scripts/smoke_single_tool.sh``
    or equivalent). Rollout failures are absorbed step-by-step (the trainer
    logs + continues), so this test asserts only that ``run()`` returns
    without raising and that a checkpoint directory was created.
    """
    from tinker_nemogym.trainer import TinkerNeMoGymTrainer

    cfg = TinkerNeMoGymConfig.from_yaml(SMOKE_YAML)
    # Redirect checkpoints under tmp_path to keep the test hermetic.
    cfg.tinker.checkpoint_dir = str(tmp_path / "checkpoints")
    cfg.training.n_steps = 2
    cfg.training.save_every = 1

    trainer = TinkerNeMoGymTrainer(cfg)
    await trainer.run()

    # save_every=1 means we requested a save after step 0 and step 1. The
    # tinker service may materialize either ``step_1`` or ``step_2``
    # depending on versioning — accept anything under the checkpoint dir.
    ckpt_dir = Path(cfg.tinker.checkpoint_dir)
    assert ckpt_dir.exists(), f"checkpoint dir was never created: {ckpt_dir}"

"""Smoke tests for :mod:`tinker_nemogym.cli` using Click's CliRunner.

The trainer itself is mocked out; these tests only validate argument parsing,
subcommand wiring, and that the trainer is invoked with the right arguments.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tinker_nemogym.cli import cli

MINIMAL_YAML = """\
tinker:
  base_model: meta-llama/Llama-3.2-1B-Instruct
model_server:
  port: 8001
nemogym:
  dataset_jsonl: {dataset}
training:
  n_steps: 1
  batch_size: 1
"""


@pytest.fixture
def valid_config(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({"user_messages": ["hi"], "metadata": {}}) + "\n")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(MINIMAL_YAML.format(dataset=dataset))
    return config_path


def test_cli_help_lists_both_subcommands():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "train" in result.output
    assert "serve" in result.output


def test_train_missing_config_exits_nonzero():
    runner = CliRunner()
    result = runner.invoke(cli, ["train"])
    # Click emits exit code 2 for usage errors (missing required option).
    assert result.exit_code != 0


def test_train_nonexistent_config_exits_nonzero(tmp_path):
    runner = CliRunner()
    bogus = tmp_path / "does-not-exist.yaml"
    result = runner.invoke(cli, ["train", "--config", str(bogus)])
    assert result.exit_code != 0
    # The path validator ("exists=True") rejects missing files.
    assert "does not exist" in result.output.lower() or "invalid value" in result.output.lower()


def test_train_valid_config_invokes_trainer(valid_config):
    """`train --config <valid.yaml>` should instantiate the trainer and call run()."""
    runner = CliRunner()

    mock_trainer_instance = MagicMock()
    mock_trainer_instance.run = MagicMock(return_value=_async_noop())
    mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

    with patch("tinker_nemogym.trainer.TinkerNeMoGymTrainer", mock_trainer_cls):
        result = runner.invoke(cli, ["train", "--config", str(valid_config)])

    assert result.exit_code == 0, result.output
    mock_trainer_cls.assert_called_once()
    mock_trainer_instance.run.assert_called_once()


def test_serve_valid_config_invokes_setup(valid_config):
    """`serve --config <valid.yaml>` should call trainer.setup() — we short-circuit
    the infinite sleep by making setup() raise, which the CLI surfaces as a nonzero
    exit without looping forever."""
    runner = CliRunner()

    class _Boom(RuntimeError):
        pass

    async def _setup(*args, **kwargs):
        raise _Boom("stop here")

    mock_trainer_instance = MagicMock()
    mock_trainer_instance.setup = _setup
    mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

    with patch("tinker_nemogym.trainer.TinkerNeMoGymTrainer", mock_trainer_cls):
        result = runner.invoke(cli, ["serve", "--config", str(valid_config)])

    # setup() raised → asyncio.run propagates → Click catches as nonzero.
    assert result.exit_code != 0
    mock_trainer_cls.assert_called_once()


def _async_noop():
    """Return an already-completed coroutine, so asyncio.run(...) on it is a no-op."""

    async def _f():
        return None

    return _f()


# ---------------------------------------------------------------------------
# Review 04 §5.1 — quality-of-life flags
# ---------------------------------------------------------------------------


def test_cli_version_flag():
    """--version exits 0 and prints *something* (package version)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    # Click's version_option formats as "<prog>, version <X>".
    assert "version" in result.output


def test_cli_train_version_flag():
    """train --version works on the subcommand too."""
    runner = CliRunner()
    result = runner.invoke(cli, ["train", "--version"])
    assert result.exit_code == 0
    assert "version" in result.output


def test_cli_log_level_flag(valid_config):
    """--log-level DEBUG is accepted and forwarded (no crash)."""
    runner = CliRunner()

    mock_trainer_instance = MagicMock()
    mock_trainer_instance.run = MagicMock(return_value=_async_noop())
    mock_trainer_cls = MagicMock(return_value=mock_trainer_instance)

    with patch("tinker_nemogym.trainer.TinkerNeMoGymTrainer", mock_trainer_cls):
        result = runner.invoke(
            cli, ["train", "--config", str(valid_config), "--log-level", "DEBUG"]
        )

    assert result.exit_code == 0, result.output
    mock_trainer_instance.run.assert_called_once()


def test_cli_log_level_rejects_unknown_value(valid_config):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["train", "--config", str(valid_config), "--log-level", "TRACE"]
    )
    assert result.exit_code != 0
    assert "invalid" in result.output.lower() or "choose" in result.output.lower()


def test_cli_wraps_validation_error_as_click_exception(tmp_path):
    """Bad YAML (fails pydantic validation) → friendly ClickException, not a tb."""
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n")
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        f"""\
tinker:
  base_model: meta-llama/Llama-3.2-1B-Instruct
  lora_rank: -1
model_server:
  port: 70000
nemogym:
  dataset_jsonl: {dataset}
training:
  n_steps: 1
  batch_size: 1
"""
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["train", "--config", str(bad_yaml)])
    assert result.exit_code != 0
    assert "Invalid config" in result.output

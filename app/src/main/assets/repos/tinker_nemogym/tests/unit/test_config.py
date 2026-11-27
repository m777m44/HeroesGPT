"""Tests for tinker_nemogym.config."""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from tinker_nemogym.config import (
    ModelServerConfig,
    NeMoGymConfig,
    TinkerConfig,
    TinkerNeMoGymConfig,
    TrainingConfig,
)

MINIMAL_YAML_TEMPLATE = """
tinker:
  base_model: meta-llama/Llama-3.2-1B-Instruct
model_server:
  port: 8001
nemogym:
  dataset_jsonl: {dataset}
training:
  n_steps: 4
"""

MINIMAL_YAML = MINIMAL_YAML_TEMPLATE.format(dataset="/tmp/x.jsonl")


def test_config_roundtrip(tmp_path):
    dataset = tmp_path / "x.jsonl"
    dataset.write_text("")
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL_YAML_TEMPLATE.format(dataset=str(dataset)))
    cfg = TinkerNeMoGymConfig.from_yaml(p)

    assert cfg.tinker.base_model == "meta-llama/Llama-3.2-1B-Instruct"
    assert cfg.tinker.lora_rank == 32  # default preserved
    assert cfg.model_server.port == 8001
    assert cfg.nemogym.dataset_jsonl == str(dataset)
    assert cfg.training.n_steps == 4
    # schema_version defaults to 1 when omitted from the YAML.
    assert cfg.schema_version == 1
    assert cfg.strict is True


def test_tinker_config_defaults():
    cfg = TinkerConfig()
    assert cfg.base_model == "meta-llama/Llama-3.1-8B-Instruct"
    assert cfg.lora_rank == 32
    assert cfg.learning_rate == 5e-4
    assert cfg.adam_beta1 == 0.9
    assert cfg.adam_beta2 == 0.95
    assert cfg.adam_eps == 1e-12
    assert cfg.loss_fn == "importance_sampling"
    assert cfg.wandb_project is None
    assert cfg.wandb_name is None
    assert cfg.checkpoint_dir == "./checkpoints"


def test_model_server_config_defaults():
    cfg = ModelServerConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8001
    assert cfg.stop_tokens == []


def test_nemogym_config_defaults():
    cfg = NeMoGymConfig(dataset_jsonl="/tmp/d.jsonl")
    assert cfg.agent_url == "http://127.0.0.1:11001"
    assert cfg.head_url == "http://127.0.0.1:11000"
    assert cfg.dataset_jsonl == "/tmp/d.jsonl"
    assert cfg.group_size == 4
    assert cfg.ng_run_yamls == []


def test_nemogym_config_agent_url_can_be_none():
    """Allow agent_url=None so the trainer can discover it dynamically."""
    cfg = NeMoGymConfig(dataset_jsonl="/tmp/d.jsonl", agent_url=None)
    assert cfg.agent_url is None


def test_training_config_defaults():
    cfg = TrainingConfig()
    assert cfg.n_steps == 100
    assert cfg.batch_size == 4
    assert cfg.max_tokens == 512
    assert cfg.temperature == 1.0
    assert cfg.save_every == 10
    assert cfg.eval_every == 20
    assert cfg.max_trainer_tokens == 8192


def test_nemogym_config_requires_dataset_jsonl():
    with pytest.raises(ValidationError) as exc_info:
        NeMoGymConfig()
    # Ensure the failing field is dataset_jsonl
    assert any(err["loc"] == ("dataset_jsonl",) for err in exc_info.value.errors())


def test_adam_eps_default_matches_sdk_default():
    """adam_eps default must match the Tinker SDK default (1e-12, not torch's 1e-8)."""
    import tinker

    cfg = TinkerConfig()
    sdk_default = tinker.AdamParams.model_fields["eps"].default
    assert cfg.adam_eps == sdk_default == 1e-12


# ---------------------------------------------------------------------------
# Review 01 §1.2 — warn on non-Instruct base models
# ---------------------------------------------------------------------------


def test_config_warns_on_non_instruct_base_model():
    """Non-Instruct / non-chat base_model should emit a UserWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        TinkerConfig(base_model="meta-llama/Llama-3.2-1B")
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert len(user_warnings) >= 1
    assert "Instruct" in str(user_warnings[0].message) or "chat" in str(
        user_warnings[0].message
    ).lower()


def test_config_does_not_warn_on_instruct_base_model():
    """Instruct / Chat variants should pass silently."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        TinkerConfig(base_model="meta-llama/Llama-3.2-1B-Instruct")
        TinkerConfig(base_model="Qwen/Qwen2.5-7B-Chat")
    # No UserWarning emitted for Instruct/Chat tags.
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings, [str(w.message) for w in user_warnings]


# ---------------------------------------------------------------------------
# Review 04 §2.1 / §6.1 — pydantic range + path-traversal guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("lora_rank", 0),
        ("lora_rank", -4),
        ("learning_rate", 0.0),
        ("learning_rate", -1e-4),
        ("adam_eps", 0.0),
    ],
)
def test_tinker_config_rejects_non_positive_numeric(field, bad_value):
    with pytest.raises(ValidationError):
        TinkerConfig(**{field: bad_value})


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("n_steps", -1),
        ("batch_size", 0),
        ("max_tokens", 0),
        ("max_trainer_tokens", 0),
        ("save_every", -1),
        ("temperature", -0.5),
        ("temperature", 2.5),
    ],
)
def test_training_config_rejects_invalid(field, bad_value):
    with pytest.raises(ValidationError):
        TrainingConfig(**{field: bad_value})


@pytest.mark.parametrize("bad_port", [0, -1, 70000])
def test_model_server_rejects_invalid_ports(bad_port):
    with pytest.raises(ValidationError):
        ModelServerConfig(port=bad_port)


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://host:1",
        "127.0.0.1:8001",
        "example.com",
    ],
)
def test_nemogym_config_rejects_non_http_urls(bad_url):
    with pytest.raises(ValidationError):
        NeMoGymConfig(dataset_jsonl="/tmp/d.jsonl", head_url=bad_url)


def test_checkpoint_dir_rejects_parent_traversal():
    with pytest.raises(ValidationError):
        TinkerConfig(checkpoint_dir="../../etc/secrets")
    with pytest.raises(ValidationError):
        TinkerConfig(resume_from_checkpoint="./foo/../../secret")


def test_checkpoint_dir_allows_tinker_uri():
    """``tinker://...`` paths are routed through the SDK, not the fs — accept."""
    cfg = TinkerConfig(resume_from_checkpoint="tinker://run-id/weights/step_5")
    assert cfg.resume_from_checkpoint == "tinker://run-id/weights/step_5"



# ---------------------------------------------------------------------------
# Review 06 §6 — eager config validation (B2)
# ---------------------------------------------------------------------------


def _make_full_cfg(dataset_jsonl: str, **overrides):
    """Build a TinkerNeMoGymConfig with all four sub-blocks populated."""
    tinker_kwargs = {"base_model": "meta-llama/Llama-3.2-1B-Instruct"}
    tinker_kwargs.update(overrides.pop("tinker", {}))
    return TinkerNeMoGymConfig(
        tinker=TinkerConfig(**tinker_kwargs),
        model_server=ModelServerConfig(),
        nemogym=NeMoGymConfig(dataset_jsonl=dataset_jsonl),
        training=TrainingConfig(),
        **overrides,
    )


def test_eager_validation_fails_fast_on_missing_dataset(tmp_path):
    """strict=True (default) → nonexistent dataset path raises at construct time."""
    bogus = str(tmp_path / "does_not_exist.jsonl")
    with pytest.raises(ValidationError, match="dataset_jsonl"):
        _make_full_cfg(bogus)


def test_eager_validation_accepts_existing_dataset(tmp_path):
    ds = tmp_path / "ok.jsonl"
    ds.write_text("")
    cfg = _make_full_cfg(str(ds))
    assert cfg.nemogym.dataset_jsonl == str(ds)


def test_strict_false_bypasses_path_checks(tmp_path):
    """strict=False → missing paths are allowed (deferred-create workflows)."""
    bogus = str(tmp_path / "not_yet.jsonl")
    cfg = _make_full_cfg(bogus, strict=False)
    assert cfg.strict is False
    assert cfg.nemogym.dataset_jsonl == bogus


def test_createme_suffix_bypasses_path_check(tmp_path):
    """'@createme' suffix allows deferred creation without disabling strict entirely."""
    path = str(tmp_path / "will_exist.jsonl@createme")
    cfg = _make_full_cfg(path)
    assert cfg.nemogym.dataset_jsonl == path


def test_checkpoint_dir_parent_must_exist(tmp_path):
    ds = tmp_path / "d.jsonl"
    ds.write_text("")
    # Four levels deep under a non-existent root — no ancestor exists within
    # 2 levels, so strict validation rejects.
    missing_parent = str(tmp_path / "a" / "b" / "c" / "d" / "ckpts")
    with pytest.raises(ValidationError, match="checkpoint_dir"):
        _make_full_cfg(str(ds), tinker={"checkpoint_dir": missing_parent})


def test_checkpoint_dir_one_level_of_mkdir_ok(tmp_path):
    """Common case: parent dir will be created by the trainer — accept 1-2 missing levels."""
    ds = tmp_path / "d.jsonl"
    ds.write_text("")
    # One missing level — tmp_path exists, "sub/" doesn't yet, final dir doesn't yet.
    ok = str(tmp_path / "sub" / "ckpts")
    cfg = _make_full_cfg(str(ds), tinker={"checkpoint_dir": ok})
    assert cfg.tinker.checkpoint_dir == ok


def test_checkpoint_dir_tinker_uri_skips_parent_check(tmp_path):
    ds = tmp_path / "d.jsonl"
    ds.write_text("")
    cfg = _make_full_cfg(
        str(ds),
        tinker={"checkpoint_dir": "tinker://run-id/weights"},
    )
    assert cfg.tinker.checkpoint_dir == "tinker://run-id/weights"


# ---------------------------------------------------------------------------
# base_model pattern validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "Llama 3.2 Instruct",  # whitespace
        "meta/Llama;rm -rf",  # shell metachars
        "name$with$dollar",
    ],
)
def test_base_model_rejects_invalid_characters(bad_id):
    with pytest.raises(ValidationError, match="base_model"):
        TinkerConfig(base_model=bad_id)


# ---------------------------------------------------------------------------
# schema_version validation (D2)
# ---------------------------------------------------------------------------


def test_schema_version_defaults_to_current(tmp_path):
    ds = tmp_path / "d.jsonl"
    ds.write_text("")
    cfg = _make_full_cfg(str(ds))
    from tinker_nemogym.config import CURRENT_SCHEMA_VERSION

    assert cfg.schema_version == CURRENT_SCHEMA_VERSION


def test_schema_version_rejects_future_version(tmp_path):
    ds = tmp_path / "d.jsonl"
    ds.write_text("")
    with pytest.raises(ValidationError, match="schema_version"):
        _make_full_cfg(str(ds), schema_version=999)


def test_schema_version_rejects_zero_or_negative(tmp_path):
    ds = tmp_path / "d.jsonl"
    ds.write_text("")
    with pytest.raises(ValidationError, match="schema_version"):
        _make_full_cfg(str(ds), schema_version=0)


def test_from_yaml_wraps_io_errors_as_ConfigError(tmp_path):
    """Missing/unreadable files bubble up as :class:`ConfigError`, not OSError."""
    from tinker_nemogym.errors import ConfigError

    with pytest.raises(ConfigError, match="could not open"):
        TinkerNeMoGymConfig.from_yaml(str(tmp_path / "nope.yaml"))


def test_from_yaml_wraps_yaml_syntax_as_ConfigError(tmp_path):
    from tinker_nemogym.errors import ConfigError

    bad = tmp_path / "bad.yaml"
    bad.write_text("tinker: :\n  : invalid\n- -\n")
    with pytest.raises(ConfigError):
        TinkerNeMoGymConfig.from_yaml(bad)

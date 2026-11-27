"""Pydantic configuration schema for tinker-nemogym.

Four nested blocks: `tinker`, `model_server`, `nemogym`, `training`.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ConfigError

# Schema version currently supported by the loader. Bump when we rename or
# restructure fields in a way that requires a migration; the loader rejects
# any YAML whose top-level ``schema_version`` exceeds this.
CURRENT_SCHEMA_VERSION: int = 1

# Loose pattern for HuggingFace / Tinker model ids. We don't try to enforce
# the full HuggingFace id grammar (``org/name[@revision]``) — we just reject
# obvious junk (spaces, shell metacharacters) so YAML typos surface at load
# time instead of exploding inside the Tinker SDK.
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-./:]+$")


def _safe_resolve_path(p: str) -> Path:
    """Resolve a path string and reject ``..`` traversal.

    The returned :class:`pathlib.Path` is fully resolved (symlinks expanded).
    Relative paths are anchored to the current working directory at resolve
    time. Absolute paths are accepted as-is (callers are expected to be
    trusted operators picking an explicit disk location).

    Raises:
        ValueError: if the *literal* input contains a ``..`` component,
            regardless of whether the resolved path happens to escape
            the CWD. This is a belt-and-suspenders guard so attempts like
            ``"./foo/../../etc/passwd"`` are rejected at the config layer.
    """
    # Reject traversal syntax in the literal input — even if resolve() would
    # collapse it, we don't want silent escapes.
    if ".." in Path(p).parts:
        raise ValueError(f"Path {p!r} contains parent-directory traversal ('..')")
    return Path(p).expanduser().resolve()


def _validate_url(v: str) -> str:
    if not isinstance(v, str):
        raise TypeError(f"URL must be a string, got {type(v).__name__}")
    if not (v.startswith("http://") or v.startswith("https://")):
        raise ValueError(f"URL must start with http:// or https://, got {v!r}")
    return v


class TinkerConfig(BaseModel):
    """Tinker training client + loss configuration."""

    base_model: str = Field(
        default="meta-llama/Llama-3.1-8B-Instruct",
        description=(
            "HuggingFace model id. Must be on Tinker's allow-list — "
            "see `service_client.get_server_capabilities()`. WARNING: non-Instruct / non-chat "
            "base models (e.g. raw 'Llama-3.1-8B') will be assigned the ``role_colon`` "
            "renderer by tinker_cookbook, which produces garbage when given "
            "OpenAI-style chat messages from nemo-gym agents. Use an Instruct "
            "or Chat variant unless you know your renderer handles the "
            "base-model chat template."
        ),
    )
    lora_rank: int = Field(default=32, gt=0)
    learning_rate: float = Field(default=5e-4, gt=0)
    adam_beta1: float = 0.9
    adam_beta2: float = 0.95
    # Tinker SDK default is 1e-12 (see tinker.AdamParams), which also matches
    # the tinker-atropos reference implementation. Earlier torch.optim-style
    # defaults of 1e-8 lead to subtly worse numerics on LoRA fine-tunes.
    adam_eps: float = Field(default=1e-12, gt=0)
    loss_fn: Literal["importance_sampling", "ppo", "cispo", "dro"] = "importance_sampling"
    wandb_project: str | None = None
    wandb_name: str | None = None
    checkpoint_dir: str = "./checkpoints"
    # Resume from a previously-saved tinker state. When set, ``setup()`` calls
    # ``training_client.load_state_async(resume_from_checkpoint)`` before the
    # initial sampling client snapshot. Accepts any path string the underlying
    # tinker SDK understands (e.g. ``tinker://run-id/weights/step_5``).
    resume_from_checkpoint: str | None = None

    @field_validator("base_model")
    @classmethod
    def _validate_model_id(cls, v: str) -> str:
        """Reject model ids containing shell metacharacters / whitespace.

        We want YAML typos like ``base_model: "Llama 3.2 Instruct"`` to fail
        at load time with a clear message instead of exploding deep inside
        the Tinker SDK with an opaque HTTP error.
        """
        if not _MODEL_ID_PATTERN.match(v):
            raise ValueError(
                f"base_model={v!r} contains characters outside [A-Za-z0-9_\\-./:]. "
                "Expected a HuggingFace-style id like 'org/name' or 'org/name-version'."
            )
        return v

    @field_validator("base_model")
    @classmethod
    def _warn_on_non_instruct_base_model(cls, v: str) -> str:
        """Emit (not raise) a warning when the base model isn't a chat variant.

        nemo-gym agents always speak OpenAI chat format, so a base model
        without a tuned chat template will produce garbage outputs. We warn
        rather than error so users running deliberately custom setups can
        suppress the warning and continue.
        """
        lowered = v.lower()
        if not any(tag in lowered for tag in ("instruct", "chat")):
            warnings.warn(
                f"base_model={v!r} does not look like an Instruct/Chat variant. "
                "tinker_cookbook will assign the 'role_colon' renderer which "
                "usually produces garbage for OpenAI chat inputs. Prefer a "
                "*-Instruct or *-Chat HuggingFace id.",
                UserWarning,
                stacklevel=2,
            )
        return v

    @field_validator("checkpoint_dir", "resume_from_checkpoint")
    @classmethod
    def _reject_traversal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Allow ``tinker://...`` URIs through unmolested — the SDK resolves
        # them internally, not the filesystem.
        if v.startswith(("tinker://", "http://", "https://")):
            return v
        # The path string itself may not contain ``..`` components.
        if ".." in Path(v).parts:
            raise ValueError(
                f"{v!r} contains parent-directory traversal ('..'), which is not allowed"
            )
        return v


class ModelServerConfig(BaseModel):
    """The FastAPI server that looks like a nemo-gym model to the agent."""

    host: str = "127.0.0.1"
    port: int = Field(default=8001, ge=1, le=65535)
    # Stop sequences exposed to callers; typically the tokenizer's special EOT tokens.
    stop_tokens: list[str] = Field(default_factory=list)


class NeMoGymConfig(BaseModel):
    """How we talk to nemo-gym."""

    # Optional: when None, the trainer discovers the agent URL by polling
    # ``head_url + /server_instances`` for the first ``responses_api_agents``
    # entry. Useful because nemo-gym allocates random ports at startup.
    agent_url: str | None = "http://127.0.0.1:11001"  # SimpleAgent /run endpoint
    head_url: str = "http://127.0.0.1:11000"  # HeadServer
    dataset_jsonl: str  # path to input dataset (agent-style rows) — REQUIRED
    group_size: int = Field(default=4, gt=0)
    # If empty, we expect the user to launch nemo-gym themselves via `ng_run`.
    # If populated, we'll spawn it as a subprocess.
    ng_run_yamls: list[str] = Field(default_factory=list)

    @field_validator("agent_url")
    @classmethod
    def _v_agent_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_url(v)

    @field_validator("head_url")
    @classmethod
    def _v_head_url(cls, v: str) -> str:
        return _validate_url(v)


class TrainingConfig(BaseModel):
    """Outer training-loop knobs."""

    n_steps: int = Field(default=100, ge=0)  # 0 == setup only (useful for tests)
    batch_size: int = Field(default=4, gt=0)  # problems per step
    max_tokens: int = Field(default=512, gt=0)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    save_every: int = Field(default=10, ge=0)  # 0 disables periodic saves
    eval_every: int = Field(default=20, ge=0)
    # Soft cap on total trajectory length (prompt + response) that we send to
    # ``forward_backward_async``. Datums exceeding this are skipped (with a
    # WARNING) so we don't silently overflow Tinker's per-model max_seq_len.
    max_trainer_tokens: int = Field(default=8192, gt=0)
    # GRPO: by default we drop groups whose rewards are all equal (they'd
    # contribute zero gradient). Set False for offline e2e tests that use a
    # deterministic verifier which always returns the same reward.
    drop_constant_reward: bool = True
    # Optional seed for deterministic rollout batching / dataset traversal
    # order. When set, is persisted to the checkpoint metadata and restored
    # on resume so a resumed run can continue from the same dataset cursor
    # it would have reached fresh.
    random_seed: int | None = Field(default=None)

    # --- Diagnostic / precision-gap measurement ------------------------
    # When True, after each step's rollouts but BEFORE ``forward_backward``
    # runs, the trainer calls ``training_client.forward_async`` with the
    # same trajectories + ``cross_entropy`` loss to recover the *trainer-
    # side* per-token logprobs, then diffs them against the per-token
    # logprobs we stamped at sample time. Reports ``beta_mean``,
    # ``beta_std``, ``beta_abs_mean``, ``beta_max`` in the step metrics
    # (see the HuggingFace BF16 paper
    # https://huggingface.co/spaces/aminediroHF/trainer-generator-bf16-mismatch).
    # Costs ≈1 extra forward per step, no backward.
    measure_precision_gap: bool = Field(
        default=False,
        description=(
            "When True, run an extra trainer-side forward pass per step to "
            "measure the sampler↔trainer precision gap (β). Adds one "
            "forward call per step (no backward) so it roughly halves "
            "throughput — intended for diagnostics, not production."
        ),
    )


class TinkerNeMoGymConfig(BaseModel):
    """Top-level config composed of the four sub-blocks.

    ``schema_version`` lets us bump the format without silently corrupting
    old YAMLs — the loader rejects any schema_version > ``CURRENT_SCHEMA_VERSION``
    with a migration message. When omitted, defaults to 1.

    ``strict`` (default True) controls whether eager filesystem checks fire
    at ``from_yaml`` time:

    * ``nemogym.dataset_jsonl`` must refer to an existing file.
    * ``tinker.checkpoint_dir`` parent directory must exist (the subdir
      itself is allowed to be missing — we create it).

    Set ``strict: false`` at the top of the YAML to bypass these for
    specialised setups (e.g. datasets generated just-in-time by a wrapper
    script). Everything else (pydantic type validation, range checks,
    traversal guards) still runs.
    """

    model_config = ConfigDict(validate_assignment=False)

    schema_version: int = Field(
        default=CURRENT_SCHEMA_VERSION,
        description=(
            "Schema version of the YAML. Bumped when incompatible renames "
            "ship. Loader rejects schema_version > current."
        ),
    )
    strict: bool = Field(
        default=True,
        description=(
            "When True (default), from_yaml() eagerly checks that paths "
            "referenced by the config actually exist. Set False for setups "
            "that materialise files just-in-time."
        ),
    )

    tinker: TinkerConfig
    model_server: ModelServerConfig
    nemogym: NeMoGymConfig
    training: TrainingConfig

    @field_validator("schema_version")
    @classmethod
    def _v_schema_version(cls, v: int) -> int:
        if v > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version={v} is newer than this library supports "
                f"(max {CURRENT_SCHEMA_VERSION}). Upgrade tinker-nemogym, "
                "or downgrade the YAML to a supported schema_version."
            )
        if v < 1:
            raise ValueError(f"schema_version must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def _eager_path_checks(self) -> TinkerNeMoGymConfig:
        """When ``strict`` is True, verify referenced paths look reachable.

        Only runs for filesystem-style paths — ``tinker://...`` URIs on
        ``resume_from_checkpoint`` are left for the SDK to resolve.
        """
        if not self.strict:
            return self

        ds = self.nemogym.dataset_jsonl
        # Pydantic already resolved the string; allow "@createme" suffix as
        # an explicit opt-out (caller will materialise it before train()).
        if not ds.endswith("@createme") and not Path(ds).expanduser().exists():
            raise ValueError(
                f"nemogym.dataset_jsonl={ds!r} does not exist. Fix the path "
                "or set strict: false in the YAML. (Append '@createme' to the "
                "path for deferred creation.)"
            )

        ck = self.tinker.checkpoint_dir
        if not ck.startswith(("tinker://", "http://", "https://")):
            # Walk up the path looking for an existing directory. We accept
            # up to 2 missing levels (e.g. the user wrote
            # ``./checkpoints/run_42`` under a fresh CWD — we'll mkdir -p
            # both ``checkpoints/`` and ``run_42/``). Anything deeper is a
            # red flag for a typo'd absolute path.
            resolved = Path(ck).expanduser()
            current: Path | None = resolved.parent
            depth = 0
            while current is not None and not current.exists():
                depth += 1
                if depth > 2:
                    raise ValueError(
                        f"tinker.checkpoint_dir={ck!r} has no existing ancestor within "
                        "2 parent levels; check for typos or set strict: false."
                    )
                parent = current.parent
                # Break at the filesystem root to avoid an infinite loop.
                if parent == current:
                    break
                current = parent
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> TinkerNeMoGymConfig:
        """Load a YAML file and parse it into a validated TinkerNeMoGymConfig.

        Raises :class:`ConfigError` (subclass of :class:`TinkerNeMoGymError`)
        when the file can't be opened or parsed; pydantic validation errors
        propagate unchanged so callers can still catch them narrowly.
        """
        try:
            with open(path) as f:
                data: Any = yaml.safe_load(f)
        except OSError as e:
            raise ConfigError(f"could not open config file {path!r}: {e}") from e
        except yaml.YAMLError as e:
            raise ConfigError(f"could not parse YAML {path!r}: {e}") from e
        if not isinstance(data, dict):
            raise ConfigError(
                f"config YAML {path!r} must deserialize to a mapping, got {type(data).__name__}"
            )
        return cls.model_validate(data)


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ModelServerConfig",
    "NeMoGymConfig",
    "TinkerConfig",
    "TinkerNeMoGymConfig",
    "TrainingConfig",
    "_safe_resolve_path",
]

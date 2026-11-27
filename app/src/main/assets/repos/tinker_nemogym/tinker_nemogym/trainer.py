"""Main Tinker ↔ nemo-gym RL trainer.

Wires together:

1. Tinker: ``ServiceClient`` + ``LoRATrainingClient`` + ``SamplingClient`` for
   training + inference.
2. tinker-nemogym: ``tinker_responses_model`` (FastAPI shim that masquerades as
   a nemo-gym model and hot-swaps its ``SamplingClient``).
3. nemo-gym agent: consumed via :mod:`tinker_nemogym.rollout_driver` which POSTs
   to the agent's ``/run`` endpoint.

The main loop mirrors tinker-atropos' canonical call graph:

    rollout_batch → extract_trajectory → build_batch
      → forward_backward_async + optim_step_async (pipelined)
      → save_weights_and_get_sampling_client_async
      → tinker_responses_model.set_sampling_client

Wandb integration is optional (guarded by ``cfg.tinker.wandb_project``). The
FastAPI shim can be suppressed (``setup(start_model_server=False)``) for tests
and programmatic in-process usage.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

import aiohttp
import tinker
import uvicorn
from tinker import types as tt  # noqa: F401  (re-exported for downstream convenience)

from . import tinker_responses_model as tmodel
from .config import TinkerNeMoGymConfig
from .datum_builder import (
    build_batch,  # noqa: F401  (kept for backwards-compat patching by tests)
    build_batch_with_trajectories,
    extract_trajectory,
)
from .errors import CheckpointError, TinkerNeMoGymError, TrainingError
from .precision_gap import (
    _per_token_trainer_logprobs_from_output,
    compute_precision_gap_metrics,
)
from .rollout_driver import load_jsonl, rollout_batch

logger = logging.getLogger(__name__)


class TinkerNeMoGymTrainer:
    """RL trainer that connects a tinker LoRA training client to a nemo-gym agent.

    Public surface:

    * :meth:`setup` — creates all tinker clients, loads the dataset, and
      optionally starts the FastAPI shim in a background thread.
    * :meth:`run` — setup + main RL loop. Blocks until ``n_steps`` iterations
      finish (or an unrecoverable error).
    * :meth:`_run_step` — one training step (exposed for unit tests).

    Attributes (set after :meth:`setup`):

    * ``service_client``: :class:`tinker.ServiceClient`
    * ``training_client``: :class:`tinker.LoRATrainingClient`
    * ``current_sampling_client``: :class:`tinker.SamplingClient`
    * ``tokenizer``, ``renderer``: tinker_cookbook primitives
    * ``dataset``: ``list[dict]`` of agent-style prompt rows
    """

    def __init__(
        self,
        config: TinkerNeMoGymConfig,
        *,
        service_client_factory: Any = None,
    ):
        """Construct a trainer.

        Args:
            config: Fully-validated top-level config.
            service_client_factory: Optional zero-arg callable that returns
                a :class:`tinker.ServiceClient` (or duck-typed stand-in).
                Defaults to :class:`tinker.ServiceClient` itself. Tests and
                power users inject a factory to stub the Tinker backend
                without monkey-patching the ``tinker`` module — see
                :func:`tinker_nemogym.testing.make_fake_tinker_module`
                which now also exports a ``fake_service_client_factory``.
        """
        self.cfg = config
        # Store as-given; resolved lazily in setup() so that monkey-patches
        # of ``tinker.ServiceClient`` applied AFTER trainer construction
        # (the historical pattern in our test suite) still take effect.
        self._service_client_factory_override = service_client_factory

        # Tinker clients (populated by setup()).
        self.service_client: Any = None
        self.training_client: Any = None
        self.current_sampling_client: Any = None

        # tokenizer + renderer (populated by setup()).
        self.tokenizer: Any = None
        self.renderer: Any = None

        # Optional FastAPI shim (populated by setup() when start_model_server=True).
        self._server_thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

        # Dataset of agent-style prompt rows.
        self.dataset: list[dict] = []

        # Resolved nemo-gym agent URL. Populated by :meth:`setup` — either copied
        # from cfg.nemogym.agent_url or discovered via the HeadServer.
        self.agent_url: str | None = None

        # Wandb state.
        self._wandb_enabled: bool = False

        # Counter incremented every time we hot-swap the sampler. Used only for
        # logging (the tinker SDK dropped the `name=` kwarg from
        # ``save_weights_and_get_sampling_client_async`` in 0.18+).
        self._save_count: int = 0

        # Per-run short identifier. Assigned in :meth:`setup` (not __init__)
        # so constructor-only tests don't leak a run_id into later calls.
        self.run_id: str | None = None
        self._run_id_token: Any = None

        # Review 07 §3 C3: resume-state metadata. Populated by
        # :meth:`_maybe_save_checkpoint` (writes) and :meth:`setup` on
        # resume (reads). None when no metadata has been loaded/written yet.
        self.mean_reward_history: list[float] = []
        self.dataset_cursor: int = 0
        self._resumed_step: int = 0

        # Shared aiohttp session for rollout_batch calls. Created in setup(),
        # closed in _cleanup(). Pooling connections across all steps avoids
        # TLS/TCP re-handshakes on each rollout.
        self._http_session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    @property
    def _service_client_factory(self) -> Any:
        """Resolve the factory lazily so late monkey-patches of
        ``tinker.ServiceClient`` still take effect. Precedence: explicit
        override > current ``tinker.ServiceClient``.
        """
        if self._service_client_factory_override is not None:
            return self._service_client_factory_override
        return tinker.ServiceClient

    async def setup(self, start_model_server: bool = True) -> None:
        """One-time setup. Safe to skip the FastAPI shim for tests / in-process use.

        Args:
            start_model_server: If True (default), start the
                :mod:`tinker_responses_model` FastAPI app in a daemon thread
                on ``cfg.model_server.{host,port}``. Set False when another
                process owns the shim or during unit tests.
        """
        # 1. Tokenizer + renderer (tinker_cookbook picks a chat template for the
        # base model).
        from tinker_cookbook import model_info
        from tinker_cookbook.renderers import get_renderer
        from tinker_cookbook.tokenizer_utils import get_tokenizer

        # 0. Assign a short run_id and make it visible to every log record
        # for the duration of this trainer's lifetime (Review 07 §3).
        from .utils.logging import RUN_ID_VAR, new_run_id

        if self.run_id is None:
            self.run_id = new_run_id()
        self._run_id_token = RUN_ID_VAR.set(self.run_id)
        logger.info("Starting run_id=%s", self.run_id)

        # 0b. Preflight checks (Review 07 §3 C2) — fail fast with actionable
        # messages BEFORE we burn time on the tokenizer / Tinker handshake.
        await self._preflight_checks()

        self.tokenizer = get_tokenizer(self.cfg.tinker.base_model)
        renderer_name = model_info.get_recommended_renderer_name(self.cfg.tinker.base_model)
        self.renderer = get_renderer(renderer_name, self.tokenizer)
        logger.info(
            "Loaded tokenizer + renderer for %s (renderer=%s)",
            self.cfg.tinker.base_model,
            renderer_name,
        )

        # 2. Wandb (optional, must happen before long-running tinker calls so
        # failures surface early).
        self._maybe_init_wandb()

        # 3. Tinker service + LoRA training client.
        self.service_client = self._service_client_factory()
        self.training_client = await self.service_client.create_lora_training_client_async(
            base_model=self.cfg.tinker.base_model,
            rank=self.cfg.tinker.lora_rank,
        )
        logger.info(
            "Created LoRATrainingClient (base_model=%s, rank=%d)",
            self.cfg.tinker.base_model,
            self.cfg.tinker.lora_rank,
        )

        # 3b. Optionally restore from a checkpoint BEFORE snapshotting the
        # initial sampling client — otherwise the first rollout would use
        # fresh LoRA weights, not the resumed ones.
        resume = self.cfg.tinker.resume_from_checkpoint
        if resume:
            logger.info("Resuming from checkpoint: %s", resume)
            try:
                load_future = await self.training_client.load_state_async(resume)
                if hasattr(load_future, "result_async"):
                    await load_future.result_async()
            except Exception as e:
                # Non-fatal: log loudly and continue with fresh weights. A
                # hard failure here would be surprising for short-lived test
                # runs; production users get a clear ERROR either way.
                logger.error(
                    "load_state_async(%r) failed: %r — continuing without resume",
                    resume,
                    e,
                )

            # Also restore the driver-side metadata (step, cursor, ...).
            self._maybe_load_checkpoint_meta(resume)

        # 4. Initial sampling client — this snapshots the freshly-initialized
        # LoRA weights and hands back a sampler we can route inference through.
        # NOTE: the tinker SDK dropped ``name=`` from this method in 0.18+;
        # passing it only emits a DeprecationWarning, so we track save count
        # ourselves via ``self._save_count`` for logging.
        self.current_sampling_client = (
            await self.training_client.save_weights_and_get_sampling_client_async()
        )
        self._save_count += 1
        logger.info("Initial sampling client ready (save #%d)", self._save_count)

        # 5. Wire the FastAPI shim to our tokenizer + sampling client and spin
        # it up in a daemon thread if requested.
        tmodel.init(
            base_model=self.cfg.tinker.base_model,
            tokenizer=self.tokenizer,
            renderer=self.renderer,
        )
        tmodel.set_sampling_client(self.current_sampling_client, version=self._save_count)
        if start_model_server:
            self._start_server_thread()

        # 6. Load the dataset of prompt rows.
        self.dataset = load_jsonl(self.cfg.nemogym.dataset_jsonl)
        logger.info("Loaded %d prompts from %s", len(self.dataset), self.cfg.nemogym.dataset_jsonl)

        # 7. Resolve the nemo-gym agent URL. If the user set one explicitly,
        # use it; otherwise discover via the HeadServer (polls
        # ``head_url + /server_instances``). nemo-gym allocates random ports
        # at startup so hard-coding the URL isn't portable.
        if self.cfg.nemogym.agent_url is not None:
            self.agent_url = self.cfg.nemogym.agent_url
            logger.info("Using explicit agent_url from config: %s", self.agent_url)
        else:
            from .utils.process import discover_agent_url

            logger.info(
                "agent_url not configured; discovering via HeadServer at %s",
                self.cfg.nemogym.head_url,
            )
            self.agent_url = discover_agent_url(self.cfg.nemogym.head_url)
            logger.info("Discovered agent URL: %s", self.agent_url)

        # 8. Create the shared aiohttp session. Reused by every rollout_batch
        # call for this trainer's lifetime; closed in _cleanup().
        self._http_session = aiohttp.ClientSession()

    async def _preflight_checks(self) -> None:
        """Validate the operating environment before any heavy calls.

        Goals (in priority order):

        1. Dataset file exists. (Config layer already enforces this when
           ``strict=True``; re-checked here so ``strict=false`` runs still
           surface a sane error before the training loop starts.)
        2. Tinker API key + base_model on the supported list, via
           ``ServiceClient.get_server_capabilities_async()``. Raises
           :class:`TinkerNeMoGymError` on auth / model-not-found.
        3. When ``agent_url`` is not explicitly configured, HeadServer is
           reachable. Raises :class:`AgentDiscoveryError` with an actionable
           message ("nemo-gym not running; run ng_run first") on failure.

        None of these raise on transient network blips — they all have short
        timeouts and a single retry isn't attempted (the next trainer run
        will retry). Kept non-fatal for fields we can't easily verify
        (e.g. wandb creds) so a misconfigured wandb project doesn't block
        training.
        """
        # 1) Dataset file sanity re-check.
        ds = self.cfg.nemogym.dataset_jsonl
        if not ds.endswith("@createme") and not Path(ds).expanduser().exists():
            raise TinkerNeMoGymError(
                f"preflight: nemogym.dataset_jsonl={ds!r} does not exist. "
                "Create it first or fix the path."
            )

        # 2) Tinker service reachability + base_model lookup.
        await self._preflight_tinker()

        # 3) HeadServer reachability when dynamic discovery is in play.
        if self.cfg.nemogym.agent_url is None:
            await self._preflight_head_server()

    async def _preflight_tinker(self) -> None:
        """Probe :meth:`tinker.ServiceClient.get_server_capabilities_async`.

        Silently accepts if the SDK is an older version lacking the method
        (the training-client creation path will still surface a real error);
        this keeps us forward-compatible without forcing a hard SDK pin.
        """
        try:
            probe = self._service_client_factory()
        except Exception as e:
            raise TinkerNeMoGymError(
                "preflight: could not instantiate tinker.ServiceClient — "
                "check that TINKER_API_KEY is set in the environment "
                f"(original error: {e!r})"
            ) from e

        caps_fn = getattr(probe, "get_server_capabilities_async", None)
        if caps_fn is None:  # pragma: no cover - SDK too old
            logger.debug("Tinker SDK has no get_server_capabilities_async; skipping probe")
            return
        try:
            caps = await caps_fn()
        except Exception as e:
            msg = repr(e).lower()
            if "auth" in msg or "api_key" in msg or "api key" in msg or "401" in msg:
                raise TinkerNeMoGymError(
                    "preflight: Tinker rejected the API key. "
                    "Check TINKER_API_KEY in the environment."
                ) from e
            raise TinkerNeMoGymError(
                "preflight: Tinker server capabilities lookup failed "
                f"({type(e).__name__}: {e!r})"
            ) from e

        # ``caps`` shape: pydantic model with ``.supported_models`` list (0.18+).
        supported = getattr(caps, "supported_models", None)
        if supported is None:
            supported = getattr(caps, "models", None)
        if not isinstance(supported, (list, tuple)):
            return  # unknown payload; don't make assumptions
        # Normalise to list-of-strings for comparison.
        supported_ids: list[str] = []
        for entry in supported:
            name = getattr(entry, "model_name", None) or getattr(entry, "name", None) or entry
            supported_ids.append(str(name))

        if self.cfg.tinker.base_model not in supported_ids:
            logger.warning(
                "preflight: base_model=%s is NOT in Tinker's supported_models list. "
                "Supported: %s",
                self.cfg.tinker.base_model,
                supported_ids,
            )

    async def _preflight_head_server(self) -> None:
        """Probe the nemo-gym HeadServer with a short HTTP GET."""
        import aiohttp as _aiohttp

        from .errors import AgentDiscoveryError

        url = self.cfg.nemogym.head_url.rstrip("/") + "/server_instances"
        try:
            timeout = _aiohttp.ClientTimeout(total=3.0)
            async with _aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url) as r:
                    if r.status >= 500:
                        raise AgentDiscoveryError(
                            f"preflight: HeadServer at {self.cfg.nemogym.head_url} "
                            f"returned HTTP {r.status}"
                        )
        except AgentDiscoveryError:
            raise
        except Exception as e:
            raise AgentDiscoveryError(
                f"preflight: HeadServer at {self.cfg.nemogym.head_url} is unreachable "
                f"({type(e).__name__}: {e!r}). "
                "Is nemo-gym running? Try: ng_run <resources.yaml> <agent.yaml>"
            ) from e

    def _maybe_init_wandb(self) -> None:
        """Initialize wandb if ``cfg.tinker.wandb_project`` is set. No-op otherwise."""
        project = self.cfg.tinker.wandb_project
        if not project:
            logger.info("wandb disabled (no wandb_project configured)")
            self._wandb_enabled = False
            return
        try:
            import wandb

            wandb.init(
                project=project,
                name=self.cfg.tinker.wandb_name,
                config=self.cfg.model_dump(),
            )
            self._wandb_enabled = True
            logger.info("wandb initialized (project=%s)", project)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("wandb init failed, continuing without wandb: %r", e)
            self._wandb_enabled = False

    def _start_server_thread(self) -> None:
        """Launch the FastAPI shim via uvicorn in a daemon thread.

        Blocks until the server thread reports ``started == True`` (or the
        10-second timeout elapses) so callers that immediately POST to the
        shim can't race the listener.
        """
        cfg = uvicorn.Config(
            tmodel.app,
            host=self.cfg.model_server.host,
            port=self.cfg.model_server.port,
            log_level="warning",
        )
        server = uvicorn.Server(cfg)
        self._server = server

        def _run() -> None:
            # uvicorn.Server.serve() is a coroutine; run it in this thread's
            # event loop.
            asyncio.run(server.serve())

        t = threading.Thread(target=_run, daemon=True, name="tinker-nemogym-server")
        t.start()
        self._server_thread = t

        # uvicorn flips server.started to True once the socket is bound and
        # lifespan startup completed. Poll (at most ~10s) so the trainer
        # can't return before the shim is actually accepting connections.
        import time as _time

        deadline = _time.monotonic() + 10.0
        while _time.monotonic() < deadline:
            if getattr(server, "started", False):
                break
            _time.sleep(0.05)

        logger.info(
            "FastAPI shim listening on http://%s:%d (started=%s)",
            self.cfg.model_server.host,
            self.cfg.model_server.port,
            getattr(server, "started", False),
        )

    # ------------------------------------------------------------------
    # Main training loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Full lifecycle: ``setup()`` then loop ``cfg.training.n_steps`` steps."""
        await self.setup()
        try:
            for step in range(self.cfg.training.n_steps):
                try:
                    metrics = await self._run_step(step)
                    # Include hot-swap (save_count) + loss whenever present so
                    # external observers can verify hot-swap cadence and loss
                    # progression without parsing wandb/checkpoint state.
                    save_count = metrics.get("save_count")
                    loss = metrics.get("loss")
                    extras = []
                    if save_count is not None:
                        extras.append(f"save_count={save_count}")
                    if loss is not None:
                        extras.append(f"loss={loss:.4f}")
                    extras_str = (" " + " ".join(extras)) if extras else ""
                    logger.info(
                        "Step %d: mean_reward=%.3f n_datums=%d dropped=%d%s",
                        metrics["step"],
                        metrics["mean_reward"],
                        metrics["n_datums"],
                        metrics["n_dropped"],
                        extras_str,
                    )
                    # Track mean reward + advance dataset cursor for resume.
                    self.mean_reward_history.append(float(metrics.get("mean_reward", 0.0)))
                    self.dataset_cursor += self.cfg.training.batch_size
                    if self._wandb_enabled:
                        self._log_wandb_metrics(metrics)
                    await self._maybe_save_checkpoint(step)
                except Exception as e:
                    # A single bad step shouldn't tear down the run — log and
                    # continue so the next prompt has a chance.
                    logger.exception("Step %d failed: %r", step, e)
        finally:
            # Close out wandb first (safe even if init never ran — the call
            # is guarded) then join the FastAPI shim thread.
            self._finish_wandb()
            await self._cleanup()

    async def _run_step(self, step: int) -> dict:
        """Execute one RL step. Returns a metrics dict (also used by tests).

        Thin orchestrator that delegates to three helpers:
          * :meth:`_do_rollouts`         — network hit against nemo-gym.
          * :meth:`_build_datums_from_rollouts` — parse + GRPO + size-cap.
          * :meth:`_do_training_step`    — fwd_bwd + optim + hot-swap.

        Returned metrics always contain: ``step``, ``mean_reward``,
        ``n_datums``, ``n_dropped`` (may also include ``loss`` when the step
        actually ran forward_backward).
        """
        if not self.dataset:
            raise RuntimeError("dataset is empty; did setup() run?")

        batch_prompts = self._pick_batch(step)
        groups_raw = await self._do_rollouts(step, batch_prompts)
        if groups_raw is None:
            return {"step": step, "mean_reward": 0.0, "n_datums": 0, "n_dropped": 0}

        datums, trajectories, metrics = self._build_datums_from_rollouts(step, groups_raw)
        if not datums:
            return metrics

        # Optional precision-gap shadow forward pass (see
        # :meth:`_maybe_measure_precision_gap`). Runs BEFORE the real
        # forward_backward so we measure against the same weights that
        # produced the sampler_version stamp on each rollout.
        await self._maybe_measure_precision_gap(step, datums, trajectories, metrics)

        await self._do_training_step(step, datums, metrics)
        return metrics

    # ------------------------------------------------------------------
    # _run_step helpers
    # ------------------------------------------------------------------

    def _pick_batch(self, step: int) -> list[dict]:
        """Slice ``batch_size`` prompts from the dataset with wrap-around.

        When :attr:`cfg.training.random_seed` is set and we're resuming,
        ``dataset_cursor`` is used as the starting offset so we don't
        re-train on the same prefix.
        """
        batch_size = self.cfg.training.batch_size
        cursor_base = self.dataset_cursor
        start = (cursor_base + step * batch_size) % len(self.dataset)
        batch = [self.dataset[(start + i) % len(self.dataset)] for i in range(batch_size)]
        return batch

    async def _do_rollouts(
        self, step: int, batch_prompts: list[dict]
    ) -> list[list[dict]] | None:
        """Fire rollout_batch; return None on failure (caller treats as skip)."""
        agent_url = self.agent_url or self.cfg.nemogym.agent_url
        if agent_url is None:
            raise RuntimeError("agent_url is not set; did setup() run?")
        try:
            return await rollout_batch(
                agent_url,
                batch_prompts,
                self.cfg.nemogym.group_size,
                session=self._http_session,
            )
        except (aiohttp.ClientError, TimeoutError) as e:
            # Network issues are transient — log + skip the step.
            logger.warning("Step %d: rollout_batch failed: %r — skipping step", step, e)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Step %d: rollout_batch raised unexpected %s: %r — skipping step",
                step,
                type(e).__name__,
                e,
            )
            return None

    def _build_datums_from_rollouts(
        self, step: int, groups_raw: list[list[dict]]
    ) -> tuple[list[tinker.Datum], list[Any], dict[str, Any]]:
        """Parse rollouts, compute GRPO advantages, apply size cap, return
        datums + trajectories + metrics.

        Returns a 3-tuple ``(datums, trajectories, metrics)`` where
        ``trajectories[i]`` is the :class:`RawTrajectory` that produced
        ``datums[i]``. Callers use this alignment for the optional
        precision-gap shadow forward pass (see
        :meth:`_maybe_measure_precision_gap`).
        """
        trajectory_groups: dict[str, list] = {}
        prompt_token_counts: list[float] = []
        completion_token_counts: list[float] = []
        # Per-rollout diagnostics aggregated to step-level scalars so the
        # wandb log / console line surfaces them without swamping the user
        # with per-sample detail.
        sample_latency_ms_list: list[float] = []
        staleness_list: list[int] = []
        for i, group in enumerate(groups_raw):
            if not group:
                logger.warning("Step %d prompt %d: empty rollout group", step, i)
                continue
            parsed = []
            for r in group:
                try:
                    traj = extract_trajectory(r)
                    parsed.append(traj)
                    usage = traj.metadata.get("response_usage")
                    if isinstance(usage, dict):
                        pt = usage.get("prompt_tokens") or usage.get("input_tokens")
                        ct = usage.get("completion_tokens") or usage.get("output_tokens")
                        if pt is not None:
                            prompt_token_counts.append(float(pt))
                        if ct is not None:
                            completion_token_counts.append(float(ct))
                    lat = traj.metadata.get("sample_latency_ms")
                    if isinstance(lat, (int, float)):
                        sample_latency_ms_list.append(float(lat))
                    # Compute staleness when the rollout carries a version
                    # and we've done at least one hot-swap. Rollouts from
                    # the current sampler have staleness 0; stale rollouts
                    # are those whose sampler was superseded in-flight.
                    if traj.sampler_version is not None:
                        staleness_list.append(
                            max(0, self._save_count - int(traj.sampler_version))
                        )
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(
                        "Step %d prompt %d: extract_trajectory failed: %r", step, i, e
                    )
            if parsed:
                trajectory_groups[f"step{step}_p{i}"] = parsed

        if not trajectory_groups:
            logger.warning("Step %d: no usable rollouts; skipping training", step)
            return [], [], {"step": step, "mean_reward": 0.0, "n_datums": 0, "n_dropped": 0}

        datums, trajectories, meta = build_batch_with_trajectories(
            trajectory_groups,
            drop_constant_reward=self.cfg.training.drop_constant_reward,
            max_trainer_tokens=self.cfg.training.max_trainer_tokens,
        )
        metrics: dict[str, Any] = {
            "step": step,
            "mean_reward": float(meta["mean_reward"]),
            "n_datums": int(meta["n_datums"]),
            "n_dropped": int(meta["n_dropped_constant"]),
            "n_dropped_oversize": int(meta.get("n_dropped_oversize", 0)),
        }
        # Review 02 §4.2: surface token-usage aggregates when the model server
        # populated the OpenAI ``usage`` block on /v1/responses.
        if prompt_token_counts:
            metrics["prompt_tokens_mean"] = float(
                sum(prompt_token_counts) / len(prompt_token_counts)
            )
        if completion_token_counts:
            metrics["completion_tokens_mean"] = float(
                sum(completion_token_counts) / len(completion_token_counts)
            )
        # Latency / staleness diagnostics (see HuggingFace BF16 paper).
        if sample_latency_ms_list:
            arr = sorted(sample_latency_ms_list)
            metrics["sample_latency_ms_mean"] = float(
                sum(arr) / len(arr)
            )
            metrics["sample_latency_ms_p50"] = float(arr[len(arr) // 2])
            # p95 — nearest-rank rule, clamped to last index.
            p95_idx = min(len(arr) - 1, int(round(0.95 * (len(arr) - 1))))
            metrics["sample_latency_ms_p95"] = float(arr[p95_idx])
            metrics["sample_latency_ms_max"] = float(arr[-1])
        if staleness_list:
            metrics["staleness_mean"] = float(
                sum(staleness_list) / len(staleness_list)
            )
            metrics["staleness_max"] = int(max(staleness_list))
            metrics["staleness_n_stale"] = int(
                sum(1 for s in staleness_list if s > 0)
            )
        if not datums:
            logger.warning(
                "Step %d: all groups had constant reward, skipping training step", step
            )
        return datums, trajectories, metrics

    async def _do_training_step(
        self, step: int, datums: list[tinker.Datum], metrics: dict[str, Any]
    ) -> None:
        """Run fwd_bwd + optim_step + hot-swap sampler, mutating ``metrics`` in-place.

        Exception policy (Review 04 §2.4):
          * ``tinker.AuthenticationError`` / ``PermissionDeniedError`` —
            re-raised. Auth failures are not transient; keep trying would
            just burn quota. Let the outer loop crash the run.
          * ``tinker.RateLimitError`` / ``RequestFailedError`` /
            ``SidecarDiedError`` — log + mark step as failed. Transient;
            next step may succeed.
          * Everything else — log + mark step as failed + continue.
        """
        adam = tinker.AdamParams(
            learning_rate=self.cfg.tinker.learning_rate,
            beta1=self.cfg.tinker.adam_beta1,
            beta2=self.cfg.tinker.adam_beta2,
            eps=self.cfg.tinker.adam_eps,
        )
        try:
            fwd_future = await self.training_client.forward_backward_async(
                datums, loss_fn=self.cfg.tinker.loss_fn
            )
            opt_future = await self.training_client.optim_step_async(adam)
            fwd_result = await fwd_future.result_async()
            await opt_future.result_async()
        except (tinker.AuthenticationError, tinker.PermissionDeniedError) as e:
            logger.error(
                "Step %d: tinker auth/permission error — fatal, not retrying: %r", step, e
            )
            raise
        except tinker.RateLimitError as e:
            logger.warning(
                "Step %d: tinker rate limit — skipping this step, backoff handled upstream: %r",
                step,
                e,
            )
            metrics["fwd_bwd_error"] = repr(e)
            return
        except (tinker.RequestFailedError, tinker.SidecarDiedError) as e:
            logger.error(
                "Step %d: tinker transient failure (%s) — skipping step: %r",
                step,
                type(e).__name__,
                e,
            )
            metrics["fwd_bwd_error"] = repr(e)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            wrapped = TrainingError(
                f"step {step}: forward_backward/optim_step failed ({type(e).__name__})"
            )
            wrapped.__cause__ = e
            logger.error(
                "Step %d: forward_backward/optim_step failed (%s): %r — skipping this step",
                step,
                type(e).__name__,
                e,
            )
            metrics["fwd_bwd_error"] = repr(wrapped)
            return

        # Capture loss if the fwd_bwd result exposes it (shape varies by tinker version).
        loss_val: float | None = None
        try:
            metrics_dict = getattr(fwd_result, "metrics", None)
            if isinstance(metrics_dict, dict):
                # "loss:sum" is the tinker-atropos convention.
                if "loss:sum" in metrics_dict:
                    loss_val = float(metrics_dict["loss:sum"])
                elif "loss" in metrics_dict:
                    loss_val = float(metrics_dict["loss"])
        except (TypeError, ValueError):  # pragma: no cover - best-effort metric extraction
            loss_val = None
        if loss_val is not None:
            metrics["loss"] = loss_val

        # Hot-swap sampling client. Auth errors re-raised; transient logged + swallowed.
        try:
            new_sampler = await self.training_client.save_weights_and_get_sampling_client_async()
            self._save_count += 1
            self.current_sampling_client = new_sampler
            tmodel.set_sampling_client(new_sampler, version=self._save_count)
            metrics["sampler_version"] = getattr(new_sampler, "version", None)
            metrics["save_count"] = self._save_count
        except (tinker.AuthenticationError, tinker.PermissionDeniedError):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            wrapped = TrainingError(
                f"step {step}: hot-swap (save_weights_and_get_sampling_client_async) failed"
            )
            wrapped.__cause__ = e
            logger.error(
                "Step %d: hot-swap failed (%s): %r — keeping previous sampler",
                step,
                type(e).__name__,
                e,
            )
            metrics["hot_swap_error"] = repr(wrapped)

    async def _maybe_measure_precision_gap(
        self,
        step: int,
        datums: list[tinker.Datum],
        trajectories: list[Any],
        metrics: dict[str, Any],
    ) -> None:
        """Run a shadow trainer-side forward pass and record β metrics.

        No-op unless ``cfg.training.measure_precision_gap`` is set. When
        enabled, submits ``datums`` through ``training_client.forward_async``
        with the ``cross_entropy`` loss (same input shape, different surrogate)
        to get the trainer's per-token logprobs, then diffs them against the
        sampler-side ``response_logprobs`` already on every trajectory.

        Implements the HuggingFace BF16-mismatch measurement: each step's
        ``beta_*`` scalars answer "how big is the precision gap between the
        sampler and the trainer **at the same weights**?". Large values mean
        PPO-style clipping is being driven by kernel numerics rather than
        real policy shift.

        Failures here are *always* non-fatal — β is a diagnostic signal, not
        a training ingredient. We log WARNING and move on.
        """
        if not self.cfg.training.measure_precision_gap:
            return
        if not datums:
            return
        try:
            fwd_future = await self.training_client.forward_async(
                datums, loss_fn="cross_entropy"
            )
            if hasattr(fwd_future, "result_async"):
                fwd_result = await fwd_future.result_async()
            else:
                fwd_result = fwd_future
        except Exception as e:
            logger.warning(
                "Step %d: precision-gap forward_async failed (%s): %r — skipping β",
                step,
                type(e).__name__,
                e,
            )
            metrics["precision_gap_error"] = repr(e)
            return

        try:
            per_datum = _per_token_trainer_logprobs_from_output(
                fwd_result, n_datums=len(datums)
            )
            beta = compute_precision_gap_metrics(per_datum, trajectories)
        except Exception as e:  # pragma: no cover - defensive; helper doesn't raise
            logger.warning(
                "Step %d: precision-gap metric computation failed: %r", step, e
            )
            metrics["precision_gap_error"] = repr(e)
            return

        if beta:
            metrics.update(beta)
            logger.info(
                "Step %d precision-gap: beta_mean=%.4g beta_abs_mean=%.4g beta_max=%.4g "
                "(n_tokens=%d n_datums=%d skipped=%d)",
                step,
                beta.get("beta_mean", float("nan")),
                beta.get("beta_abs_mean", float("nan")),
                beta.get("beta_max", float("nan")),
                beta.get("beta_n_tokens", 0),
                beta.get("beta_n_datums", 0),
                beta.get("beta_n_skipped_datums", 0),
            )

    def _log_wandb_metrics(self, metrics: dict) -> None:
        """Log per-step metrics to wandb (if enabled).

        Emits the following keys (all prefixed ``train/``) for every step:
        ``mean_reward``, ``n_datums``, ``n_dropped``, ``sampler_version``,
        and — when fwd_bwd ran — ``loss``. Uses ``step=metrics["step"] + 1``
        so wandb's x-axis matches the 1-indexed checkpoint numbering.
        """
        try:
            import wandb  # lazy import — tests that don't touch wandb stay fast
        except Exception as e:  # pragma: no cover - no wandb installed
            logger.warning("wandb import failed: %r", e)
            return
        try:
            step = int(metrics.get("step", 0))
            payload: dict[str, Any] = {
                "train/mean_reward": metrics.get("mean_reward", 0.0),
                "train/n_datums": metrics.get("n_datums", 0),
                "train/n_dropped": metrics.get("n_dropped", 0),
            }
            if "loss" in metrics:
                payload["train/loss"] = metrics["loss"]
            if "sampler_version" in metrics and metrics["sampler_version"] is not None:
                payload["train/sampler_version"] = metrics["sampler_version"]
            # Diagnostic extras — all optional; include when present.
            for k in (
                "sample_latency_ms_mean",
                "sample_latency_ms_p50",
                "sample_latency_ms_p95",
                "sample_latency_ms_max",
                "staleness_mean",
                "staleness_max",
                "staleness_n_stale",
                "beta_mean",
                "beta_std",
                "beta_abs_mean",
                "beta_max",
                "beta_n_tokens",
                "beta_n_datums",
                "prompt_tokens_mean",
                "completion_tokens_mean",
            ):
                if k in metrics and metrics[k] is not None:
                    payload[f"train/{k}"] = metrics[k]
            wandb.log(payload, step=step + 1)
        except Exception as e:  # pragma: no cover
            logger.warning("wandb.log failed: %r", e)

    def _finish_wandb(self) -> None:
        """Call ``wandb.finish()`` if init ran. Safe to call more than once;
        :class:`FakeWandb` increments a counter so tests can assert "exactly one
        finish" even when exceptions fired earlier in the lifecycle.
        """
        if not self._wandb_enabled:
            return
        try:
            import wandb

            wandb.finish()
        except Exception as e:  # pragma: no cover
            logger.warning("wandb.finish failed: %r", e)

    async def _maybe_save_checkpoint(self, step: int) -> None:
        """Persist weights every ``cfg.training.save_every`` steps.

        Convention: we save after completing step ``save_every - 1`` (so e.g.
        for ``save_every=10`` the first checkpoint lands after step 9 — i.e.
        when ``(step+1) % save_every == 0``). Step 0 never triggers a save.
        """
        save_every = self.cfg.training.save_every
        if save_every <= 0:
            return
        if (step + 1) % save_every != 0:
            return
        # Tinker validates the `name` as a "weights label" — only
        # [A-Za-z0-9._-] allowed (no slashes). We derive a safe identifier
        # from the checkpoint_dir basename + step counter, and separately
        # log the filesystem-style path for operator readability.
        dir_basename = Path(self.cfg.tinker.checkpoint_dir).name or "ckpt"
        safe_label = f"{dir_basename}-step-{step + 1}"
        ckpt_path = Path(self.cfg.tinker.checkpoint_dir) / f"step_{step + 1}"
        logger.info("Saving checkpoint label=%s (logical path: %s)", safe_label, ckpt_path)
        try:
            future = await self.training_client.save_state_async(name=safe_label)
            # Await completion so caller sees errors; older tinker versions may
            # return an object without result_async — be forgiving.
            if hasattr(future, "result_async"):
                result = await future.result_async()
                # Log the returned tinker:// URI so operators can plug it into
                # ``tinker.resume_from_checkpoint`` for a warm restart. The URI
                # embeds the run_id which isn't otherwise visible to the caller.
                uri = getattr(result, "path", None)
                if uri:
                    logger.info(
                        "Checkpoint saved: label=%s uri=%s", safe_label, uri
                    )
            # Write the metadata sidecar so a future resume can restore the
            # driver-side state (step, reward history, dataset cursor, seed).
            self._write_checkpoint_meta(safe_label, step + 1)
        except Exception as e:  # pragma: no cover - remote call
            wrapped = CheckpointError(
                f"save_state_async failed at step {step} (label={safe_label})"
            )
            wrapped.__cause__ = e
            logger.warning(
                "save_state_async failed at step %d (label=%s): %r",
                step,
                safe_label,
                e,
            )

    def _write_checkpoint_meta(self, label: str, step_next: int) -> None:
        """Persist a ``<label>.meta.json`` sidecar next to the weights."""
        from .checkpoint_meta import CheckpointMeta, save_meta

        meta = CheckpointMeta(
            step=step_next,
            save_count=self._save_count,
            mean_reward_history=list(self.mean_reward_history),
            wandb_run_id=self._current_wandb_run_id(),
            random_seed=self.cfg.training.random_seed,
            dataset_cursor=self.dataset_cursor,
            run_id=self.run_id,
        )
        try:
            save_meta(self.cfg.tinker.checkpoint_dir, label, meta)
        except OSError as e:  # pragma: no cover - filesystem failure
            logger.warning("Failed to write checkpoint meta for %s: %r", label, e)

    def _maybe_load_checkpoint_meta(self, resume_uri: str) -> None:
        """Try to locate + load a metadata sidecar for the given resume URI.

        We probe two candidate labels:

        * The final path component of the resume URI (e.g. ``step_5``).
        * That component prefixed with the checkpoint_dir basename, matching
          the label we wrote in :meth:`_write_checkpoint_meta`
          (``<dir>-step-<N>``).
        """
        from .checkpoint_meta import load_meta

        tail = resume_uri.rstrip("/").split("/")[-1]
        dir_basename = Path(self.cfg.tinker.checkpoint_dir).name or "ckpt"
        candidates = [tail, f"{dir_basename}-{tail.replace('_', '-')}"]
        for cand in candidates:
            meta = load_meta(self.cfg.tinker.checkpoint_dir, cand)
            if meta is not None:
                logger.info(
                    "Restored checkpoint meta (label=%s): step=%d save_count=%d cursor=%d",
                    cand,
                    meta.step,
                    meta.save_count,
                    meta.dataset_cursor,
                )
                self._save_count = meta.save_count
                self.mean_reward_history = list(meta.mean_reward_history)
                self.dataset_cursor = meta.dataset_cursor
                self._resumed_step = meta.step
                if meta.run_id:
                    self.run_id = meta.run_id
                return
        logger.info(
            "No checkpoint meta found for resume=%r; driver state starts fresh",
            resume_uri,
        )

    def _current_wandb_run_id(self) -> str | None:
        """Return wandb.run.id when wandb is initialised, else None."""
        if not self._wandb_enabled:
            return None
        try:
            import wandb

            run = getattr(wandb, "run", None)
            if run is not None:
                return getattr(run, "id", None)
        except Exception:  # pragma: no cover
            return None
        return None

    async def _cleanup(self) -> None:
        """Best-effort cleanup: close the shared session, signal uvicorn to exit."""
        if self._http_session is not None:
            try:
                await self._http_session.close()
            except Exception as e:  # pragma: no cover - best-effort
                logger.warning("Failed to close _http_session: %r", e)
            self._http_session = None
        if self._server is not None:
            self._server.should_exit = True
        if self._server_thread is not None:
            # Give the server a moment to shut down. Don't hang the caller if it
            # refuses — daemon=True means Python will reap it on exit anyway.
            self._server_thread.join(timeout=5.0)
        # Release the run_id context var so subsequent logs don't inherit
        # a stale id. Safe even if setup() never ran — the token is None.
        if self._run_id_token is not None:
            try:
                from .utils.logging import RUN_ID_VAR

                RUN_ID_VAR.reset(self._run_id_token)
            except (ValueError, LookupError):  # pragma: no cover - token mismatch
                pass
            self._run_id_token = None


__all__ = ["TinkerNeMoGymTrainer"]

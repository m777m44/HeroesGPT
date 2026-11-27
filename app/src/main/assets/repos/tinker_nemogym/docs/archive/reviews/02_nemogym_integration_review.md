# Review 02 — NeMo-Gym integration fidelity & under-utilized features

**Scope.** Deep-dive pass #2 of 4. This review only looks at how
tinker-nemogym talks to nemo-gym: (a) are we honoring nemo-gym's actual
API contracts, and (b) what capabilities does nemo-gym ship that we are
silently bypassing? It does not re-audit the Tinker side (that's pass #1)
or cross-cutting robustness (pass #3).

**Primary source files reviewed.**
- `nemo_gym/base_responses_api_model.py` (56 LOC)
- `nemo_gym/base_responses_api_agent.py` (71 LOC)
- `nemo_gym/base_resources_server.py` (88 LOC)
- `nemo_gym/server_utils.py` — `BaseServer`, `SimpleServer`, `ServerClient`,
  `HeadServer`, `run_webserver`, ulimit/log-prefix/session middleware (746 LOC)
- `nemo_gym/openai_utils.py` — `TokenIDLogProbMixin`, `NeMoGymResponse`,
  `NeMoGym*ForTraining` shapes (552 LOC)
- `nemo_gym/rollout_collection.py` — `ng_collect_rollouts` (478 LOC)
- `nemo_gym/reward_profile.py` — `RewardProfiler` / `AggregateMetricsMixin`
- `nemo_gym/global_config.py`, `nemo_gym/config_types.py` — Hydra
  composition, `BaseServerConfig`, agent/model/resources refs
- `nemo_gym/benchmarks.py`, `nemo_gym/prompt.py`, `nemo_gym/hf_utils.py`
- `responses_api_agents/simple_agent/app.py`
- `responses_api_models/vllm_model/app.py` (for the reference
  `TokenIDLogProbMixin` producer pattern)
- Tinker-nemogym: `tinker_responses_model.py`, `rollout_driver.py`,
  `datum_builder.py`, `trainer.py`, `config.py`, all `configs/*.yaml`
- `analysis/01_nemogym_architecture.md`, `E2E_FIXES.md`

---

## §1. Executive summary

tinker-nemogym currently *works* against an externally-launched
`ng_run` stack (openai_model → simple_agent → example_single_tool_call).
It reaches end-to-end on the happy path: the `TinkerResponsesAPIModel`
subclass is spelled correctly, `TokenIDLogProbMixin` fields round-trip,
multi-turn trajectories concatenate, and `/run` responses parse into
`RawTrajectory → tinker.Datum`.

The fidelity gap is in *everything around* that happy path. We are
re-implementing plumbing nemo-gym already ships (`ServerClient`,
`ng_collect_rollouts`, `aggregate_metrics`, Hydra config composition,
ulimit/log-prefix/session middleware, HF/GitLab dataset plumbing) with
shallower equivalents. We also silently discard rich fields on the
`/run` response (`usage`, `response.id`, per-turn `ForTraining` items
beyond the concatenated token stream, cookies for session state) and
we never propagate session cookies outbound, which silently breaks
stateful envs like `example_session_state_mgmt`.

| Priority | Item | Summary |
|---|---|---|
| **MUST-FIX** | #1 / §2.1 | `TinkerResponsesAPIModel.setup_webserver` does not call `setup_exception_middleware` — exceptions bypass nemo-gym's uniform error envelope. Also we override the app instead of delegating to `super().setup_webserver()`, which makes the base-class session-middleware order fragile. |
| **MUST-FIX** | #8 / §2.8 | Rollout driver uses `aiohttp.ClientSession()` with **no cookie jar propagation**. Session-stateful envs (`example_session_state_mgmt`, `multichallenge`, `tau2`) silently lose per-task session; reward will be ~0 for any env that relies on `seed_session`. |
| **MUST-FIX** | #5 / §2.5 | We hard-code `agent_url: http://127.0.0.1:11001` in configs. nemo-gym allocates ports dynamically and exposes them at `GET {head}/server_instances`. E2E_FIXES.md acknowledges this but the code still uses a hard-coded port. |
| **MUST-FIX** | #11 / §2.11 | We don't expose a `baseline_model` / ref-logprob server, so `loss_fn="cispo"` / `"ppo"` (which need a KL to reference) are configurable but non-functional. Either drop them from the Literal or wire a second sampling client. |
| **SHOULD-CONSIDER** | #3 / §2.3 | We drop `response.usage`, `response.id`, and any non-message output items (reasoning traces, refusals, tool-call arguments) when building metadata. These are useful for wandb logs and debugging but need zero new nemo-gym work. |
| **SHOULD-CONSIDER** | #4 / §2.4 | Our `rollout_driver` duplicates ~1/3 of `ng_collect_rollouts` (concurrency, retry, per-step flush) without its better features: tqdm, agent-grouped "examples left", materialized-inputs cache, resume-from-cache, constant seed per rollout, `/aggregate_metrics` side-car. Use `ServerClient` + helper classes instead of rolling our own aiohttp. |
| **SHOULD-CONSIDER** | #7 / §2.7 | We use plain YAML + pydantic. nemo-gym uses Hydra + OmegaConf with `+key=val` CLI overrides, `_inherit_from`, interpolation, and explicit dry-run mode. Adopting it for our top-level config reduces a whole category of "YAML copy-pasted-with-slight-edits" drift. |
| **SHOULD-CONSIDER** | #10 / §2.10 | nemo-gym logs `Rollouts` table + `key_metrics/*` to wandb through `get_wandb_run()`. We initialize our own wandb run and post different keys. Risk: when both are enabled the runs collide. |
| **SHOULD-CONSIDER** | #13 / §2.13 | Reward computed over the *final* `/run` response only (aligned with nemo-gym contract), but we ignore per-turn intermediate reward signals that some resources servers expose as fields on `BaseVerifyResponse` subclasses (`partial_reward`, `step_rewards`). |
| **SHOULD-CONSIDER** | #16 / §2.16 | Our `/v1/responses` route validates nothing (takes `dict`), has no `/v1/chat/completions` pydantic coercion, and omits the `validation_exception_handler` + `uvicorn_logging_show_200_ok` filter that `SimpleServer.run_webserver()` wires. |
| **FUTURE-WORK** | #14 / §2.14 | We ship two env smoke tests (`example_single_tool_call`, `example_multi_step`). nemo-gym ships ~60 resources servers + 13 agent flavors. The "Candidate benchmark envs" table in §3 lists the 8 that should be wired next. |
| **FUTURE-WORK** | #15 / §2.15 | We load datasets via `load_jsonl(path)` only. nemo-gym has first-class `hf_utils.download_hf_dataset_as_jsonl` and `gitlab_utils` for the benchmark registry. |
| **FUTURE-WORK** | #12 / §2.12 | Best-of-N is not a native nemo-gym feature but `num_repeats` + `num_repeats_add_seed` in `ng_collect_rollouts` is close. Mirror it for eval. |
| **FUTURE-WORK** | #6 / §2.6 | Multi-agent routing works by luck (we set `agent_url` as a single URL). Supporting multiple agents in one run needs a routing table keyed on `agent_ref.name` (the field nemo-gym already puts on every row). |
| **FUTURE-WORK** | #9 / §2.9 | We do not initialize Ray. If we move to `code_gen` or `terminal_multi_harness` (which subprocess-execute under Ray workers) we must call `initialize_ray()` from server_utils. |
| **FUTURE-WORK** | #2 / §2.2 | `TokenIDLogProbMixin` triple is the minimum. nemo-gym also exposes `response.usage`, per-token `logprobs` objects (structured, not flat floats), `reasoning` summaries, `call_id` chains. Room to collect more for richer diagnostics. |

---

## §2. Per-checklist detail

### 2.1 `SimpleResponsesAPIModel` subclass correctness

**What we're doing.** `tinker_responses_model.TinkerResponsesAPIModel`
subclasses `SimpleResponsesAPIModel` (guarded by a `try/except
ImportError`). Its `setup_webserver()` returns the module-level
`app = FastAPI()` (built at import time with its own `/health`,
`/v1/chat/completions`, `/v1/responses` routes) rather than letting the
parent class build a fresh FastAPI and register the abstract methods as
routes. `chat_completions` / `responses` delegate to the module-level
endpoint functions.

```python
def setup_webserver(self) -> FastAPI:
    self.setup_session_middleware(app)
    return app
```

**What nemo-gym offers.** The parent `SimpleResponsesAPIModel.setup_webserver`
is a four-liner that (1) builds a fresh FastAPI, (2) wires
`setup_session_middleware`, (3) mounts `/v1/chat/completions` and
`/v1/responses` on the *bound methods* (so subclasses get pydantic
validation of the request body via `NeMoGymChatCompletionCreateParamsNonStreaming`
and `NeMoGymResponseCreateParamsNonStreaming`). `SimpleServer.run_webserver`
(the classmethod we *don't* call) additionally wires
`setup_exception_middleware` (uniform 500 JSON envelope), a
`RequestValidationError` handler that pretty-prints the body,
`profiling_config` / `setup_profiling` (`/stats` endpoint), ulimit
bump, log-prefixing, and a uvicorn 200-OK access-log filter.

**Gap analysis.**
- **We bypass request-body validation.** Our endpoints take
  `body: dict = Body(...)`; a malformed request reaches our hand-rolled
  `_extract_messages_chat` instead of being rejected by pydantic. The
  parent class would have given us free validation against the OpenAI
  schema.
- **Exception middleware missing.** Our routes catch `RuntimeError`
  themselves and map to 500/503 manually. nemo-gym's
  `setup_exception_middleware` + `ClientResponseError` special-case
  would standardize the envelope across agent↔model server failures.
- **Session middleware ordering is fragile.** We call
  `self.setup_session_middleware(app)` *after* the app already has all
  its routes registered. Starlette docs warn that middleware must be
  added before serving. Right now this happens to work because the shim
  starts via `uvicorn.run()` in our trainer thread, not via
  `run_webserver()`, but once we add exception middleware the ordering
  matters.
- **We never call `run_webserver()`.** That's what mounts all of the
  above. Our `trainer._start_server_thread` calls `uvicorn.Server`
  directly with `tmodel.app`, bypassing the lifecycle.
- **Not hooking overridable methods.** `SimpleServer` has
  `get_session_middleware_key()`, `setup_profiling()`, `set_ulimit()`,
  `prefix_server_logs()`. Of these, `set_ulimit()` is actually
  important for long runs (file descriptor exhaustion under many
  concurrent rollouts).

**Proposed change.**
Two-part: delegate to the parent for the routing, but keep a pre-built
app for uvicorn multi-worker import-by-string compatibility.

```python
class TinkerResponsesAPIModel(SimpleResponsesAPIModel):
    config: TinkerResponsesAPIModelConfig

    def setup_webserver(self) -> FastAPI:
        # Let the parent wire /v1/chat/completions + /v1/responses on our
        # bound methods (free request validation + consistent envelope).
        app = super().setup_webserver()
        app.get("/health")(self._health)  # our extra route
        return app

    async def chat_completions(
        self,
        body: NeMoGymChatCompletionCreateParamsNonStreaming = Body(),
    ) -> NeMoGymChatCompletion:
        return await chat_completions_endpoint(body.model_dump(exclude_unset=True))

    async def responses(
        self,
        body: NeMoGymResponseCreateParamsNonStreaming = Body(),
    ) -> NeMoGymResponse:
        return await responses_endpoint(body.model_dump(exclude_unset=True))
```

And move the uvicorn thread startup to use `SimpleServer.run_webserver()`
when `cfg.model_server.use_run_webserver: True` so we get
`set_ulimit + prefix_server_logs + exception middleware + validation
handler` for free. Keep the direct `uvicorn.run(app)` path as the
fast-test fallback.

**Severity: MUST-FIX.** Validation + exception envelope are expected
contracts on the nemo-gym side.

### 2.2 `TokenIDLogProbMixin` — data we're not harvesting

**What we're doing.** `_route_to_tinker` returns `{text,
prompt_token_ids, generation_token_ids, generation_log_probs,
stop_reason}`, and we attach only the three-tuple on every output
message.

**What nemo-gym offers.** `openai_utils.py` defines five
`*ForTraining` variants with the mixin:
- `NeMoGymEasyInputMessageForTraining`
- `NeMoGymMessageForTraining`
- `NeMoGymResponseOutputMessageForTraining`
- `NeMoGymResponseFunctionToolCallForTraining` ← **we never emit this**
- `NeMoGymResponseReasoningItemForTraining` ← **we never emit this**

The `RESPONSES_TO_TRAIN` dict maps each plain shape to its ForTraining
sibling. The `NeMoGymResponse` pydantic validator auto-selects the
training variant when the three-tuple is present.

vLLM's `return_token_id_information: true` reference implementation
(`responses_api_models/vllm_model/app.py:770–780`) attaches the mixin
on individual function_call and reasoning items too, not just the
assistant message. Downstream `SimpleAgent.responses` treats tool
calls as generations (they are — they contribute tokens to the loss).

**Gap analysis.** Our shim does not speak function-calling (tool use).
If we ever point it at a multi-turn agent with tools (for example
`simple_agent` against `example_single_tool_call`, which is designed
around tool calls), the first assistant turn may emit a
`function_call` item rather than a `message` item. Our shim currently
only emits `type: "message"` outputs, so the agent loop short-circuits
and never calls the tool. Reward is effectively 0 for tool-heavy
envs.

**Proposed change.** Detect function-call structure in the sampled text
(or in the renderer's parse_response output) and emit a
`function_call` output item *with the training mixin*, not a message:

```python
parsed_message, _ = _renderer.parse_response(gen_tokens)
tool_calls = parsed_message.get("tool_calls") or []
if tool_calls:
    output_items = [
        {
            "type": "function_call",
            "id": f"fc_{uuid4().hex}",
            "call_id": tc["id"],
            "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"],
            "status": "completed",
            "prompt_token_ids": prompt_token_ids,
            "generation_token_ids": gen_tokens,
            "generation_log_probs": gen_logprobs,
        }
        for tc in tool_calls
    ]
else:
    output_items = [ ... current message shape ... ]
```

Also harvest and expose `response.usage` so it flows downstream to
`RewardProfiler` (see §2.3).

**Severity: FUTURE-WORK.** Needed before we wire `example_single_tool_call`
in a way that actually trains on tool usage. Today the env happens to
reward "any output" so we get 1.0 without calling the tool.

### 2.3 `/run` response schema — fields we're discarding

**What we're doing.** `datum_builder.extract_trajectory` takes
`run_response["reward"]` and `run_response["response"]`, and dumps
every other top-level key into `metadata`. It then iterates
`response.output` to find/concatenate ForTraining items.

**What nemo-gym offers.** The full `/run` response is a
`BaseVerifyResponse` (or subclass) that inherits from `BaseVerifyRequest`
which inherits from `BaseRunRequest`. Shape:

```python
class BaseVerifyResponse(BaseModel):
    responses_create_params: NeMoGymResponseCreateParamsNonStreaming
    response: NeMoGymResponse     # full output history
    reward: float
```

`NeMoGymResponse.usage` carries `{input_tokens, output_tokens,
total_tokens, input_tokens_details.cached_tokens,
output_tokens_details.reasoning_tokens}`. `response.output` is a *list*
of heterogeneous items (messages, reasoning summaries, function calls,
function-call outputs). Subclasses in real envs
(e.g. `SimpleAgentVerifyResponse`) use `ConfigDict(extra="allow")`
to ship per-env diagnostic fields.

**Gap analysis.**
- We never log `usage.total_tokens` even though
  `rollout_collection._call_aggregate_metrics` already sends it as
  wandb scalars.
- We discard reasoning-summary output items entirely (empty
  `generation_token_ids` on reasoning items — but the text is still
  useful for debug).
- We don't preserve `response.id` — without it cross-correlating a
  tinker-nemogym wandb run with `ng_reward_profile` output is painful.
- Extra fields (`model_response_metadata`, `tool_call_traces`, …) from
  env-specific verify responses flow to `metadata` but we never look
  at them.

**Proposed change.** Plumb a few well-known fields into the trainer
metrics dict:

```python
@dataclass
class RawTrajectory:
    prompt_tokens: list[int]
    response_tokens: list[int]
    response_logprobs: list[float]
    reward: float
    # NEW:
    response_id: str | None = None
    usage: dict | None = None
    n_turns: int = 1          # len of ForTraining items before concat
    metadata: dict = field(default_factory=dict)
```

and in `_run_step` log `mean_usage_total_tokens`, `mean_n_turns`,
and `wandb.Table(list_of_response_ids)` once per step.

**Severity: SHOULD-CONSIDER.** Zero new nemo-gym dependency, pure
additive diagnostics that help us answer "did the rollouts actually
happen the way we think they did" during training runs.

### 2.4 `ng_collect_rollouts` patterns we should clone

**What we're doing.** `rollout_driver.rollout_batch` creates a
`ClientSession`, fires `len(prompts) * group_size` concurrent
`_call_once` coroutines, `asyncio.gather`s them, and reshapes into a
nested list. `rollout_group_with_retry` retries individual slots with
exponential backoff (well, linear — no backoff).

**What nemo-gym offers.** `RolloutCollectionHelper.run_from_config`
(rollout_collection.py:250–342) does all of the following that we don't:
1. **Materialized inputs cache** — writes every fully-expanded prompt
   row to `<output>_materialized_inputs.jsonl` *before* launching any
   rollout. Gives you `ng_reward_profile` compatibility and a
   replay-able test corpus for free.
2. **Resume-from-cache** — reads the materialized inputs + existing
   rollouts, computes the set-difference keyed on
   `(task_index, rollout_index)`, only runs the missing ones.
3. **tqdm with maxinterval=60** plus a per-agent "examples left"
   top-5 printout at 20/40/60/80/90/95/98/99/100% completion. Under 100
   concurrent rollouts across 5 agents this is the difference between a
   useful log and `KeyboardInterrupt-ing in confusion`.
4. **Per-row responses_create_params overrides** via OmegaConf with
   full interpolation support.
5. **Per-rollout seed injection** — when `num_repeats_add_seed=True`,
   sets `metadata.extra_body = {"seed": rollout_idx}` so vLLM samples
   deterministically per-slot. Useful for eval reproducibility.
6. **Per-row flush** — writes each result to the output file as it
   arrives (not at the end), which means a Ctrl-C at 80% still gives
   you 80% of the rollouts.
7. **Aggregate-metrics side-car** — after rollouts complete, POSTs
   `/aggregate_metrics` on each agent (group by `agent_ref.name`),
   writes `<output>_aggregate_metrics.json`, **and** logs the
   primitive-typed metrics to wandb with `key_metrics/` prefixing. We
   have `AggregateMetricsMixin` available but don't call it.
8. **Prompt config materialization** via
   `load_prompt_config / apply_prompt_to_row` — lets you parameterize
   a prompt template from a YAML file separately from the dataset.
9. **`task_index` + `rollout_index`** as stable keys that survive
   resume, sort, and downstream joins.

**Gap analysis.** Our inner loop is clean but we're on our own for all
of the above. Re-implementing each is incremental; adopting
`ServerClient` (see §2.5) is a single refactor that unlocks
`ServerClient.post(server_name=..., url_path="/run")` and sets the
stage for the rest.

**Proposed change (minimal).** Inside the training loop, after every
step (or every N steps), invoke nemo-gym's collector as a
side-effecting evaluator:

```python
from nemo_gym.rollout_collection import RolloutCollectionHelper, RolloutCollectionConfig

async def _eval_step(self, step: int):
    rch = RolloutCollectionHelper()
    cfg = RolloutCollectionConfig(
        agent_name=self.cfg.nemogym.agent_name,
        input_jsonl_fpath=self.cfg.nemogym.eval_dataset,
        output_jsonl_fpath=f"{self.cfg.tinker.checkpoint_dir}/eval_step{step}.jsonl",
        num_samples_in_parallel=32,
        num_repeats=self.cfg.training.eval_num_repeats,
        resume_from_cache=False,
    )
    await rch.run_from_config(cfg)
```

This gives us resumable eval + aggregate metrics + wandb logging in
one call. For the *training* rollouts we keep the custom driver
(because we need per-prompt group shaping for GRPO and tighter
latency), but refactor it to use `ServerClient.post` instead of a raw
`aiohttp.post` so session cookies and retry logic come for free.

**Severity: SHOULD-CONSIDER.** Biggest bang-per-buck item in the
review. Most of the wins are eval-path and free-standing from the
training loop.

### 2.5 `HeadServer /server_instances` + `ServerClient`

**What we're doing.** We hard-code `agent_url: http://127.0.0.1:11001`
in `smoke_single_tool.yaml` and `nemogym.agent_url` in
`TinkerNeMoGymConfig`. We use raw aiohttp in `rollout_driver`.

**What nemo-gym offers.**
- `HeadServer` exposes `GET /server_instances` returning a list of
  `ServerInstanceDisplayConfig` (name, host, port, server_type,
  status). This is the canonical service-discovery mechanism.
- `ServerClient.load_from_global_config(head_server_config)` fetches
  the global config from `GET /global_config_dict_yaml`, parses into
  OmegaConf, and caches. Its `.post(server_name, url_path, **kwargs)`
  looks up the server by name, builds the URL, and POSTs — with
  automatic retry (MAX_NUM_TRIES=3), `ServerDisconnectedError` +
  `ClientOSError` handling, `orjson` body serialization, a shared
  `TCPConnector(limit=...)`-sized pool, and pydantic-model body
  coercion (`BaseModel.model_dump(exclude_unset=True)`).
- E2E_FIXES.md #explicitly mentions "we discover [the agent port]
  at runtime by polling GET {head_url}/server_instances" — but the
  code still doesn't do that.

**Gap analysis.** Hard-coded ports are fine for the smoke script
(which orchestrates the stack itself), but break every other use
case: concurrent nemo-gym stacks, CI runners with random-port
allocators, launching multiple agent instances for A/B, running
under the real `ng_run` which picks from
`[port_range_low, port_range_high]`.

**Proposed change.**

```python
# tinker_nemogym/rollout_driver.py
from nemo_gym.server_utils import ServerClient
from nemo_gym.config_types import BaseServerConfig

class NeMoGymRolloutDriver:
    def __init__(self, head_host: str, head_port: int, agent_name: str):
        head_cfg = BaseServerConfig(host=head_host, port=head_port)
        self.client = ServerClient.load_from_global_config(head_cfg)
        self.agent_name = agent_name

    async def rollout_group(self, payload: dict, group_size: int) -> list[dict]:
        coros = [
            self._one(payload) for _ in range(group_size)
        ]
        return await asyncio.gather(*coros)

    async def _one(self, payload: dict) -> dict:
        resp = await self.client.post(
            server_name=self.agent_name,
            url_path="/run",
            json=payload,
        )
        await raise_for_status(resp)
        return await get_response_json(resp)
```

Config becomes `nemogym.head_host: 127.0.0.1`, `nemogym.head_port:
11000`, `nemogym.agent_name: example_single_tool_call_simple_agent`.
No more hardcoded agent port.

**Severity: MUST-FIX.** Discoverability correctness. Every other item
in this review (session cookies, retry, multi-agent, concurrency
tuning) becomes trivial once we're on `ServerClient`.

### 2.6 Multiple-agent routing

**What we're doing.** Single `agent_url`; every rollout goes through
the same agent.

**What nemo-gym offers.** `rollout_collection._preprocess_rows_from_config`
reads `agent_ref = {"name": "..."}` from each row (or falls back to
`config.agent_name`) and `run_examples` dispatches per-row on
`server_name=row["agent_ref"]["name"]`. This is how the same dataset
can train multiple agent variants in one rollout sweep (e.g.
`simple_agent` + `proof_refinement_agent` on the same math row).

**Gap analysis.** Our `rollout_batch(agent_url, prompts, group_size)`
signature doesn't let us route per-prompt. For our current
single-agent use case this is fine, but the moment we want to mix
baseline + policy rollouts (§2.11) or A/B two agent flavors, we hit a
wall.

**Proposed change.** Drop `agent_url` from the driver signature;
take `ServerClient` instead; read `agent_ref.name` from each row
with a config-level fallback.

```python
async def rollout_row(self, row: dict) -> dict:
    agent_name = (
        row.get("agent_ref", {}).get("name")
        or self.default_agent_name
    )
    return await self.client.post(agent_name, "/run", json=row)
```

**Severity: FUTURE-WORK.** Not needed for MVP training. Important once
we do ablations.

### 2.7 Hydra / OmegaConf config composition

**What we're doing.** `config.TinkerNeMoGymConfig.from_yaml` → plain
`yaml.safe_load` → pydantic validation. CLI parses a single
`--config path.yaml`.

**What nemo-gym offers.**
- Hydra `+key=value` CLI overrides with dotted paths (`+tinker.lora_rank=16`).
- OmegaConf interpolation (`${oc.env:PORT}`, `${now:%Y%m%d}`) and custom
  resolvers (`inherit_from`, `copy`, `_delete_key`).
- Multi-file composition: `+config_paths=[configs/a.yaml,configs/b.yaml]`
  merges dicts depth-first with later files overriding earlier ones.
- Global config dict is a single source of truth across every server
  process (`NEMO_GYM_CONFIG_DICT` env var); any subprocess can re-read.
- `ng_dump_config` materializes the merged view for debugging.
- Built-in dry-run mode (`DRY_RUN_KEY_NAME`) that spins up the config
  but skips actual server startup.

**Gap analysis.** Our YAMLs are already copy-paste drifting:
`smoke_single_tool.yaml` has `wandb_project: null` but
`smoke_multi_step.yaml` doesn't; `nemogym_agent.yaml` duplicates the
openai_model stanza across smoke configs. Hydra's inheritance would
collapse 80% of the duplication.

**Proposed change.** Two-tier:
1. **tinker-nemogym's own top-level config** stays pydantic (small,
   strict, owned by us).
2. **nemogym.ng_run_yamls** already exists — promote it from a
   placeholder to a real list that the trainer passes through to
   `ng_run` / `hydra.compose`. Support `+key=value` overrides via
   `nemogym.ng_run_overrides: dict`.

```yaml
nemogym:
  head_host: 127.0.0.1
  head_port: 11000
  agent_name: example_single_tool_call_simple_agent
  ng_run_yamls:
    - ../nemo-gym/resources_servers/example_single_tool_call/configs/example_single_tool_call.yaml
    - configs/nemogym_agent.yaml    # our override that swaps policy_model
  ng_run_overrides:
    policy_model.responses_api_models.openai_model.openai_base_url: http://127.0.0.1:${tinker.model_server.port}/v1
```

Then `launch_training.py --config configs/smoke_single_tool.yaml
--ng-auto-launch` could shell out to `ng_run` with the composed args.

**Severity: SHOULD-CONSIDER.** Pure quality-of-life; blocks no work.

### 2.8 Session state / cookies

**What we're doing.** `rollout_driver._call_once` creates a new
`ClientSession()` with default (empty) cookies for every rollout batch
and never passes cookies along.

**What nemo-gym offers.** `SimpleAgent.run`:

```python
async def run(self, request: Request, body: SimpleAgentRunRequest):
    cookies = request.cookies

    seed_session_response = await self.server_client.post(
        server_name=self.config.resources_server.name,
        url_path="/seed_session",
        json=body.model_dump(),
        cookies=cookies,              # in
    )
    cookies = seed_session_response.cookies  # out

    response = await self.server_client.post(
        server_name=self.config.name,
        url_path="/v1/responses",
        json=body.responses_create_params,
        cookies=cookies,              # forwards session to model too
    )
    ...
```

The `SessionMiddleware` setup in `SimpleServer.setup_session_middleware`
sets a per-server-class cookie (`session_cookie="SimpleAgent___<name>"`)
so each server maintains independent session IDs. `example_session_state_mgmt`
uses this to give each task a fresh in-memory kv store keyed on
session ID. `multichallenge`, `tau2`, `newton_bench` also rely on it.

**Gap analysis.** Because our driver opens a fresh
`ClientSession()` with no cookie jar and never threads a per-task
cookie in and out, *every* rollout looks like a brand-new client to
the agent. For the stateful envs, this means either (a) shared
in-memory state across all rollouts of all tasks (data leakage), or
(b) the env creates a new session on every request and nothing gets
seeded (no state). Either way, the reward computation is wrong.

**Proposed change.** Switch driver to `ServerClient` (§2.5). aiohttp's
`ClientSession` shared by `ServerClient` uses `DummyCookieJar`
(ignores Set-Cookie), so we *explicitly* pass cookies through:

```python
async def rollout_group_with_session(
    self, row: dict, group_size: int,
) -> list[dict]:
    # One task = one session cookie baseline. Each group member gets
    # an isolated derived session by including a fresh cookie.
    coros = []
    for k in range(group_size):
        # We mint a per-slot cookie so each rollout has independent state
        # in the resources server (matches how ng_collect_rollouts would
        # via task_index+rollout_index).
        cookies = {
            "SimpleResourcesServer___<env>": f"task{row['_ng_task_index']}_roll{k}",
        }
        coros.append(self._post_run(row, cookies))
    return await asyncio.gather(*coros)
```

(Cookie name comes from the resources server class + config.name —
discoverable via `GET /server_instances`.)

**Severity: MUST-FIX.** Silent correctness bug for any stateful env.

### 2.9 Ray integration

**What we're doing.** Nothing. We don't import ray.

**What nemo-gym offers.** `server_utils.initialize_ray()` is called
from `SimpleServer.run_webserver()` and populates
`ray_head_node_address` in the global config so child servers connect
to the same cluster. Resources servers like `code_gen`,
`terminal_multi_harness`, `swe_agents`, `arc_agi`, `browsecomp_advanced_harness`,
and `cvdp` use `@ray.remote` to subprocess-execute user code safely,
horizontally scale heavy verifier work, and cap per-test timeouts.

**Gap analysis.** If we launch `ng_run` as a subprocess (our
`ng_run_yamls` pathway), it will bring up Ray itself — no action
needed from us. If we import `nemo_gym.server_utils` directly
(e.g. after §2.5), we need to ensure we're not racing ray init with
the child servers. Not a problem today because we don't.

**Proposed change.** Non-urgent. If/when we move to `code_gen` as a
smoke env (§3), add:

```python
from nemo_gym.server_utils import initialize_ray
initialize_ray()   # idempotent — reuses existing cluster
```

at the top of `TinkerNeMoGymTrainer.setup`.

**Severity: FUTURE-WORK.**

### 2.10 wandb + mlflow hooks

**What we're doing.** `trainer._maybe_init_wandb` calls `wandb.init`
directly with our own project/name and logs `train/mean_reward`,
`train/n_datums`, `train/n_dropped`, `train/loss`,
`train/sampler_version` at `step=step+1`.

**What nemo-gym offers.**
- `global_config._WANDB_RUN` is the stack-wide singleton populated by
  `set_wandb_run`. `get_wandb_run()` returns it or None.
- `rollout_collection` logs a `Rollouts` table and `key_metrics/<agent>/`
  + `<agent>/` scalars to that run.
- `reward_profile` also logs histograms/distributions via the same run.
- mlflow integration is for dataset artifact upload
  (`ng_upload_dataset_to_gitlab`) via `mlflow_tracking_uri` — orthogonal
  to training telemetry.

**Gap analysis.** If we both call `wandb.init` in-process *and* run
`ng_collect_rollouts` (§2.4) in the same process, we get two runs
logging to possibly different projects — wandb will happily multiplex
but the user gets confused. Also, because we never set
`_WANDB_RUN` on the nemo-gym side, any rollout-side key_metrics are
lost.

**Proposed change.**

```python
def _maybe_init_wandb(self):
    if not self.cfg.tinker.wandb_project:
        return
    import wandb
    from nemo_gym import global_config as ng_gc
    run = wandb.init(project=..., name=..., config=self.cfg.model_dump())
    ng_gc._WANDB_RUN = run   # share the run with nemo-gym
    self._wandb_enabled = True
```

Also emit `nemogym/<agent_name>/key_metrics` at step-end by calling
`AggregateMetricsMixin.compute_metrics` on the step's rollouts.

**Severity: SHOULD-CONSIDER.**

### 2.11 policy_model vs baseline_model

**What we're doing.** One sampling client → one `policy_model` → one
agent. `loss_fn` can be set to `cispo` / `ppo` which reference a KL to
a baseline, but we don't have one.

**What nemo-gym offers.** The config schema has no first-class
"baseline_model" concept, but nothing stops you from declaring a second
`responses_api_models.openai_model` instance pointing at a frozen
reference — in fact, the openai_model is the right way to point at a
different endpoint. E.g.:

```yaml
baseline_model:
  responses_api_models:
    openai_model:
      entrypoint: app.py
      openai_base_url: http://127.0.0.1:8002/v1   # different shim
      openai_api_key: tinker-nemogym-baseline
      openai_model: tinker-baseline
```

and an agent that queries both (needs a custom agent or a flag on
`simple_agent`). Alternatively we compute reference logprobs locally
via a second `SamplingClient` on the *pre-training* weights.

**Gap analysis.** Right now the `loss_fn` Literal advertises modes we
don't implement.

**Proposed change.** Pick one:
- (a) **Drop** `"ppo"` and `"cispo"` from `loss_fn: Literal` until we
  implement reference logprobs.
- (b) **Implement** a ref-logprob path: hold a snapshot
  `SamplingClient` from step_0 that we *don't* hot-swap; before each
  `forward_backward`, re-sample its logprobs on the same
  `prompt_tokens + response_tokens` and attach them as
  `ref_logprobs` in the datum.

```python
# during _run_step, after extract_trajectory:
ref_result = await self.ref_sampling_client.sample_async(
    prompt=tt.ModelInput.from_ints(traj.prompt_tokens + traj.response_tokens[:-1]),
    num_samples=1,
    sampling_params=tt.SamplingParams(max_tokens=0, temperature=0.0),
)
traj.ref_logprobs = list(ref_result.sequences[0].logprobs)
```

**Severity: MUST-FIX** (option (a), drop misleading enum values today)
**or FUTURE-WORK** (option (b), wire properly).

### 2.12 Best-of-N sampling

**What we're doing.** GRPO groups (`group_size` copies per prompt,
advantages = group-centered rewards) via `rollout_group`. No
"pick the best" selection — every sample becomes a training datum.

**What nemo-gym offers.** Not a first-class feature, but
`rollout_collection`'s `num_repeats` + `num_repeats_add_seed` + the
downstream `ng_reward_profile` mean@k computation is the native
equivalent for eval-time BoN.

**Gap analysis.** For training, GRPO beats BoN (every sample trains,
not just the winner). For eval, we don't do BoN today either.

**Proposed change.** Add eval-time BoN to `_eval_step`:

```python
async def _eval_step(self, step: int, n: int = 4):
    groups_raw = await self.driver.rollout_batch(
        self.eval_dataset, group_size=n, timeout_sec=900,
    )
    pass_at_n = sum(
        any(r.get("reward", 0) >= 1.0 for r in group)
        for group in groups_raw
    ) / len(groups_raw)
    mean_at_n = sum(
        max((r.get("reward", 0) for r in group), default=0.0)
        for group in groups_raw
    ) / len(groups_raw)
    ...
```

**Severity: FUTURE-WORK.**

### 2.13 Tool-use chain rewards — final or trajectory?

**What we're doing.** We use the single scalar `run_response["reward"]`
that the agent returns. That scalar is, per the `BaseVerifyResponse`
contract, whatever the *final* `/verify` call returned.

**What nemo-gym offers.** The base contract is "one reward per rollout
at the end". But several resources servers expose *per-step* signals
via subclass extensions to `BaseVerifyResponse` (`extra="allow"`):
- `multichallenge` exposes `per_turn_reward`.
- `proof_refinement_agent` exposes `refinement_deltas`.
- `swe_agents` exposes `patch_applied`, `tests_passed_count`,
  `tests_failed_count`.

There's no first-class hook for mid-trajectory rewards in the datum
— GRPO's advantage is per-trajectory too. But you can (a) use
per-step signals as auxiliary loss targets, or (b) use them to
filter/weight datums.

**Gap analysis.** We're honoring the contract; the open question is
whether we want to.

**Proposed change.** Harvest the extra fields into `RawTrajectory.metadata`
(which we already do) and in `build_batch` support an optional
`reward_fn(run_response) -> float` override so env-specific
post-processing stays out of the core loop:

```python
def build_batch(
    trajectory_groups,
    drop_constant_reward: bool = True,
    reward_fn: Callable[[RawTrajectory], float] | None = None,
) -> tuple[list[Datum], dict]:
    for group in trajectory_groups.values():
        rewards = [
            reward_fn(t) if reward_fn else t.reward
            for t in group
        ]
        ...
```

**Severity: SHOULD-CONSIDER.**

### 2.14 Benchmark env catalog

See §3 table.

### 2.15 HF dataset loaders

**What we're doing.** `rollout_driver.load_jsonl(path)` — local
filesystem only.

**What nemo-gym offers.**
- `hf_utils.download_hf_dataset_as_jsonl(repo_id, split, …)` — uses
  `datasets.load_dataset` with split support, auto-converts to JSONL.
- `gitlab_utils.download_dataset_from_gitlab` — via mlflow tracking.
- `DatasetConfig.gitlab_identifier` and `huggingface_identifier`
  pydantic shapes + `dataset_orchestrator.py` that prepares them.
- `ng_prepare_data +mode=train_preparation +should_download=true
  +data_source=gitlab` — one-shot CLI that downloads everything
  declared in the resources_servers' `datasets:` list.

**Gap analysis.** For the smoke envs we ship the JSONL in-tree. For
real envs we'd need to either run `ng_prepare_data` out-of-band or
teach our trainer to call it.

**Proposed change.**

```python
# config.py:
class NeMoGymConfig(BaseModel):
    dataset_source: Literal["jsonl", "hf", "gitlab"] = "jsonl"
    dataset_jsonl: str | None = None
    dataset_hf_repo: str | None = None
    dataset_hf_artifact: str | None = None
    dataset_gitlab_name: str | None = None
    dataset_gitlab_version: str | None = None

# trainer.py:
def _load_dataset(self) -> list[dict]:
    from nemo_gym.hf_utils import download_hf_dataset_as_jsonl
    if self.cfg.nemogym.dataset_source == "hf":
        local = download_hf_dataset_as_jsonl(
            repo_id=self.cfg.nemogym.dataset_hf_repo,
            artifact_fpath=self.cfg.nemogym.dataset_hf_artifact,
            output_fpath=f"{self.cfg.tinker.checkpoint_dir}/data.jsonl",
            hf_token=os.environ.get("HF_TOKEN"),
        )
        return load_jsonl(local)
    ...
```

**Severity: FUTURE-WORK.**

### 2.16 Envelope patterns

**What we're doing.** Our shim has `/health` (good) but no
`/metrics`, no profiling, no ulimit bump, no graceful shutdown beyond
`should_exit = True`.

**What nemo-gym offers.** `SimpleServer`:
- `setup_profiling(app, profiling_config)` mounts `/stats` and
  wraps `app.router.lifespan_context` to start/stop a yappi/py-spy
  profiler.
- `set_ulimit(target_soft_limit=65535)` bumps `RLIMIT_NOFILE`; under
  100+ concurrent rollouts we hit `[Errno 24] Too many open files`
  without this.
- `prefix_server_logs` namespaces stdout/stderr with `({config.name})`
  — invaluable when 5 uvicorn workers share a terminal.
- `run_webserver()` passes `timeout_graceful_shutdown=0.5`,
  `timeout_worker_healthcheck=30` to uvicorn.
- `@app.exception_handler(RequestValidationError)` pretty-prints the
  offending body.
- `No200Filter` on the `uvicorn.access` logger silences successful
  rollouts so errors stand out.

**Gap analysis.** Our shim stdout under a real 32-group rollout is a
firehose of `200 OK` lines. We also hit the open-files wall at around
500 concurrent rollouts in informal testing.

**Proposed change.** When `setup_webserver` delegates to `super()`
(§2.1), most of the above comes for free. For the standalone path we
use in trainer.py, at minimum:

```python
def _start_server_thread(self):
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (65535, 65535))
    except Exception as e:
        logger.warning("set_ulimit failed: %r", e)
    ...
```

**Severity: SHOULD-CONSIDER.**

---

## §3. Candidate benchmark envs (smoke-tests for the next pass)

Columns:
- **Reward signal**: what you're optimizing.
- **Turns**: typical agent turn depth (1 = single shot; ≥ 2 = multi-turn).
- **Difficulty**: L / M / H heuristic for a 1B-param model.
- **Why**: role in the test matrix.

| Env | Reward signal | Turns | Difficulty | Why good for smoke |
|---|---|---|---|---|
| **example_single_tool_call** | 1.0 iff exactly one tool call emitted | 1 | L | ✅ already wired. Constant-reward; used to validate plumbing, not learning. |
| **example_multi_step** | 1.0 if multi-step tool sequence valid | 2–5 | L | ✅ already wired. Validates multi-turn ForTraining concatenation (§2.2). |
| **example_session_state_mgmt** | 1.0 if session KV matches target | 3–8 | L | Validates **cookie propagation fix** (§2.8). Zero-ML env — pure plumbing. |
| **format_verification** (citation_format, freeform_formatting) | Binary: regex match | 1 | L | Cheapest real learning signal. Deterministic, fast, no LLM judge, no external deps. Ideal "does GRPO actually move the mean?" test. |
| **instruction_following** | Binary per-instruction; sum/count | 1 | M | Classic RLVR setup, IFEval-style rules. Well-behaved reward curve; good for benchmarking against tinker-atropos numbers. |
| **reasoning_gym** | Binary or graded on ~100 task types | 1–2 | M | Huge variety (algebra, graph theory, logic). `domain: knowledge`. Good stress test for `num_repeats` + tokenizer edge cases. |
| **structured_outputs** (json_yaml_xml_v1) | Binary: valid JSON/YAML/XML | 1 | L | Tests the renderer's tool/format handling without tools; complements `format_verification`. |
| **math_with_code** | Binary: final answer matches | 1–3 | M | Requires Python execution → **exercises Ray path (§2.9)**. Good canary for compute-heavy envs before we tackle `code_gen`. |
| **mcqa** | Binary: argmax(option) matches | 1 | L | Simplest possible RLVR. Sanity-checks `group_size>1` actually gets reward variance (4-way MC has ≤ 25% baseline → strong learning signal). |
| **xstest** | Binary: over-refusal/harmful classification | 1 | L-M | Safety smoke. Heterogeneous reward dist; tests `drop_constant_reward` doesn't drop everything. |

**Recommended wiring order.**
1. `example_session_state_mgmt` — validates cookie fix (§2.8).
2. `format_verification` + `mcqa` — validates GRPO learning signal.
3. `instruction_following` — bigger prompts, longer generations;
   stresses our token-level bookkeeping.
4. `reasoning_gym` — breadth; exposes tokenizer/renderer edge cases.
5. `math_with_code` → `code_gen` — gets us on Ray.

---

## §4. Refactors to do BEFORE the first real Tinker run

Ordered by severity × blast-radius. Each is landable standalone.

1. **(§2.8) Cookie propagation.** Switch `rollout_driver` to use
   `ServerClient` *and* plumb a per-(task, rollout) cookie through.
   Non-negotiable — silent correctness bug.
2. **(§2.5) Dynamic agent discovery.** Replace `agent_url` with
   `head_host + head_port + agent_name`; fetch server_instances;
   resolve agent base URL at trainer setup. Fixes every port-collision
   / ephemeral-port scenario.
3. **(§2.1) `SimpleResponsesAPIModel` delegation.** Stop overriding
   `setup_webserver` wholesale; let the parent wire
   `chat_completions`/`responses` routes with pydantic validation.
   Gets us free request validation + the
   `RequestValidationError` pretty printer.
4. **(§2.11) Either drop `"ppo"/"cispo"` from `loss_fn` enum or
   implement ref-logprobs.** Don't ship misleading knobs.
5. **(§2.16) `set_ulimit` in `_start_server_thread` + uvicorn
   no-200-OK filter.** 10-line change, unblocks large rollouts.
6. **(§2.3) Harvest `response.usage`, `response.id`, `n_turns` into
   trajectory metadata + wandb.** Diagnostic foundation for
   per-step debugging.
7. **(§2.10) Set `nemo_gym.global_config._WANDB_RUN` from our
   trainer's wandb init.** One line; makes any nemo-gym helper we
   later call participate in the same run.

---

## §5. Longer-term feature list

- **(§2.4) Adopt `ng_collect_rollouts` for evaluation.** Add
  `_eval_step(step, dataset, num_repeats=4)` that shells through
  `RolloutCollectionHelper.run_from_config`. Free aggregate_metrics +
  resume + materialized-inputs cache.
- **(§2.2) Emit `function_call`-typed outputs with
  `TokenIDLogProbMixin`.** Needed for real tool use; requires renderer
  integration with the tool-call grammar.
- **(§2.6) Per-row multi-agent routing.** Replace `agent_url` with
  `default_agent_name`; dispatch on `row.agent_ref.name`. Enables A/B
  and baseline↔policy mixing.
- **(§2.7) Hydra-compose `ng_run` config from tinker-nemogym.**
  Collapse the 4 config YAMLs; add `+override` CLI support.
- **(§2.9) `initialize_ray()` hook.** Prerequisite for `code_gen`,
  `terminal_multi_harness`, `swe_agents`.
- **(§2.11-b) Ref-logprob sampling client** for PPO / CISPO / DRO.
  Hold a non-hot-swapped baseline sampler; attach `ref_logprobs` to
  datums; extend the loss-fn pipeline.
- **(§2.12) Best-of-N eval.** mean@k, pass@k via eval-time
  `num_repeats_add_seed`. Integrates with reward_profile.
- **(§2.13) `reward_fn` hook in `build_batch`** for env-specific
  reward shaping from `BaseVerifyResponse` extras.
- **(§2.14) Wire the 8 benchmark envs** in §3 one by one, with one
  integration test apiece that asserts non-trivial reward variance +
  non-zero loss after 10 steps.
- **(§2.15) HF / GitLab dataset loading** via `nemo_gym.hf_utils` /
  `gitlab_utils`. Fall through to local JSONL as today.
- **(§2.16) `/metrics` Prometheus endpoint** on our shim so we can
  scrape sample latency under real load (nemo-gym already has
  `prometheus_client` in the openai_model venv — pattern exists).
- **Graceful shutdown** that drains in-flight rollouts before stopping
  the shim (today we set `should_exit=True` and hope).
- **Profiling hook**: expose our shim at `/stats` via
  `setup_profiling` so we can py-spy the sampling hot path under real
  workloads.
- **Dataset orchestrator CLI**: `tinker-nemogym prepare-data` that
  wraps `ng_prepare_data` with our config to produce ready-to-train
  JSONL in one shot.

---

*Reviewer note.* Pass #2 deliberately does not re-audit the Tinker
side of the integration (pass #1) or cross-cutting resilience (pass
#3). The items above are scoped to the nemo-gym boundary only.

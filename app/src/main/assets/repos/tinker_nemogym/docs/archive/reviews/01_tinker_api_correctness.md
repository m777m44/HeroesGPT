# Review #1 — Tinker SDK API correctness

**Scope**: Does `tinker-nemogym` call the real Tinker SDK correctly? Every
assumption (1–14) is cross-checked against the installed SDK source at
`/home/phuc/workspace/rl/small_prs/pr003_tinker_nemogym_integration/.venv/lib/python3.12/site-packages/tinker/`
and the reference patterns in `tinker_cookbook` + `tinker-atropos`.

Verdicts used:

- **OK** — behaviour verified to match the SDK.
- **WRONG** — will fail or silently misbehave on the real backend.
- **SUSPECT** — likely wrong on a live run; needs confirmation.
- **VERIFY-AGAINST-LIVE-API** — plausible, but only a live smoke test can prove it.

---

## Must-fix before live run (blocking)

1. **(#7) Deprecated `name=` kwarg on `save_weights_and_get_sampling_client_async`.**
   Emits a `DeprecationWarning` at every step and at least one test suite (or
   future SDK release) will turn it into an error. Drop the kwarg; if a
   stable/resumable checkpoint name is required use
   `save_weights_for_sampler_async(name=...)` plus
   `service_client.create_sampling_client_async(model_path=...)` — that is the
   path the cookbook + tinker-atropos both use.
2. **(#7) `load_state_async(path)` is positional only.**
   Our `trainer.setup()` uses it correctly, but the config field is named
   `resume_from_checkpoint` — make sure we pass the *path string* that starts
   with `tinker://` (see SDK docstring). Current code passes the raw config
   string; users who pass a local directory will silently fail. Add a runtime
   check or clearer docstring.
3. **(#9) `adam_eps` default `1e-8` differs from Tinker's `1e-12`.**
   Not wrong per se, but `AdamParams.eps` defaults to `1e-12` in the SDK and
   the cookbook's RL examples do not override it. Our default (`1e-8`, in
   `config.TinkerConfig`) is 4 orders of magnitude larger. For LoRA RL this is
   aggressive — worth at least a config comment, ideally change to `1e-8` only
   intentionally (atropos uses `eps=1e-8`, cookbook leaves default). **SUSPECT.**
4. **(#2) The `logprobs` sentinel is `1.0`. tinker-atropos uses `1.0`; the
   tinker-cookbook RL pipeline uses `0.0`.** Both "work" because the server-side
   `importance_sampling` loss is `exp(new_logprob - old_logprob) * advantage`
   *masked by `advantages != 0`*. That masking means any value on prompt
   positions is arithmetically harmless as long as `advantages[i] == 0` on
   those positions — which we do. **But**: tinker-atropos also zeros
   *advantages where `logprob == 1.0`* (see `trainer.py:252`), i.e. it treats
   `1.0` as *the* mask. If the live server ever tightens this contract to
   "sentinel must be 0.0 or NaN" we lose. Document clearly and consider
   switching to `0.0` to match the canonical cookbook reference.
   Verdict: **VERIFY-AGAINST-LIVE-API**, with a strong recommendation to
   either document the atropos convention or flip to cookbook's `0.0`.
5. **(#12) `base_model="meta-llama/Llama-3.2-1B"` selects the `role_colon`
   renderer, not `llama3`.** `model_info.get_llama_info()` maps
   `"Llama-3.2-1B"` → `_ROLE_COLON` (a minimal `role: content` template)
   because it's the non-Instruct base. The Instruct variant
   (`Llama-3.2-1B-Instruct`) maps to `_LLAMA3`. This is a **real behaviour
   difference**: our FastAPI shim happily accepts OpenAI chat messages, renders
   them through `role_colon`, but the model was never trained with those
   role tags. Training will technically still run but the policy will learn a
   role-template it has no prior for. **Must fix the default**: either default
   to `meta-llama/Llama-3.2-1B-Instruct`, or document that the user must
   explicitly override `base_model` + `renderer_name`. **SUSPECT / likely
   WRONG as a default.**

## Nice-to-have (non-blocking)

6. **(#5) Sampling is missing `top_p` / `top_k` / `seed` passthrough.** Our
   shim ignores them; OpenAI API clients often send `top_p`. No correctness
   issue (defaults: `top_p=1`, `top_k=-1`), but worth mapping through.
7. **(#5) `stop` list typing is loose.** The SDK accepts
   `str | Sequence[str] | Sequence[int] | None`. We sometimes forward an
   empty list (before the fallback kicks in); the fallback is correct, so OK.
8. **(#13) Hot-swap race window.** We `set_sampling_client` after the new
   sampler is ready, but in-flight `sample_async()` calls on the old client
   still complete against the old weights. That's fine (SamplingClient's
   session id is immutable), but *newly arriving* requests between
   `fwd_bwd_future.result_async()` and `set_sampling_client(...)` go to the
   **old** client. For an on-policy RL loop that is expected. Confirm in the
   docstring.
9. **(#14) Exception breadth.** We catch `except Exception` in several
   trainer paths. The SDK raises a rich hierarchy: `BadRequestError`,
   `RateLimitError`, `InternalServerError`, `RequestFailedError`,
   `APIConnectionError`, `APITimeoutError`, `SidecarDiedError`, etc. For most
   of those we correctly want to retry/skip, but `AuthenticationError` /
   `PermissionDeniedError` should fail fast (no point continuing).
10. **(#6) `SampleResponse` docstring drift.** The SDK docstring (sampling_client.py:309)
    says `result.samples`; the real attribute is `result.sequences`. Our code
    reads `.sequences` — correct, but the SDK's own docstring is misleading.
    Consider a pinned assertion in a test.

---

## Detailed findings

### 1. `Datum` / `ModelInput` / `TensorData` construction

**Tinker SDK** (`tinker/types/datum.py:25-88`):

```python
class Datum(StrictBase):
    loss_fn_inputs: LossFnInputs
    model_input: ModelInput
    ...
_key_to_type = {
    "target_tokens": "int64",
    "weights":       "float32",
    "advantages":    "float32",
    "logprobs":      "float32",
    "clip_low_threshold":  "float32",
    "clip_high_threshold": "float32",
}
```

`LossFnInputs` is a `Dict[str, TensorData]` (`loss_fn_inputs.py:9`).
`ModelInput.from_ints(List[int])` returns `ModelInput(chunks=[EncodedTextChunk(tokens=...)])`
(`model_input.py:14-19`). `TensorData.from_numpy(array)` auto-detects dtype
(`tensor_data.py:47-53` + `_convert_numpy_dtype_to_tensor`).

**Our code** (`tinker_nemogym/datum_builder.py:262-269`):

```python
model_input = tt.ModelInput.from_ints(input_tokens)
return tinker.Datum(
    model_input=model_input,
    loss_fn_inputs={
        "target_tokens": tt.TensorData.from_numpy(target_arr),     # int64
        "advantages":    tt.TensorData.from_numpy(advantages),     # float32
        "logprobs":      tt.TensorData.from_numpy(logprobs),       # float32
    },
)
```

For `loss_fn="importance_sampling"` the cookbook reference
(`tinker_cookbook/recipes/rl_loop.py:218-226`) emits exactly the same three
keys (`target_tokens`, `logprobs`, `advantages`) and tinker-atropos does too
(`tinker-atropos/tinker_atropos/trainer.py:297-307`). Neither the cookbook
nor atropos passes a `"mask"` key, and the IS loss masks implicitly through
`advantages == 0`. Shape: 1-D, length = `len(target_tokens)`. Dtypes match
`_key_to_type`. `from_numpy` flattens + reshapes correctly.

**Verdict: OK.**

### 2. Logprob sentinel = `1.0` on prompt positions

**Our code** (`datum_builder.py:31`, `datum_builder.py:254-259`):

```python
PROMPT_LOGPROB_SENTINEL: float = 1.0
...
logprobs = np.concatenate([
    np.full(n_prompt_targets, PROMPT_LOGPROB_SENTINEL, dtype=np.float32),
    np.asarray(traj.response_logprobs, dtype=np.float32),
])
```

**tinker-atropos** (`tinker-atropos/tinker_atropos/trainer.py:252`,
`trainer.py:283-285`, `trainer.py:314-315`):

```python
all_advantages_padded = [0.0 if lp == 1.0 else advantage for lp in all_logprobs]
...
logprob_array_actual = logprob_array[(logprob_array != 0.0) & (logprob_array != 1.0)]
```

i.e. atropos itself uses `1.0` as an internal sentinel — the trajectories are
assumed to arrive from Atropos with `1.0` already stamped on prompt positions,
and atropos then zeros their advantages.

**tinker-cookbook** (`recipes/rl_loop.py:207`, `rl/data_processing.py:180`)
instead uses **`0.0`**:

```python
padded_logprobs = [0.0] * ob_len + logprobs
...
SequenceAccumulator.sampled_logprobs.extend([0.0] * delta_ob_len + ac_with_logprobs.logprobs)
```

Both conventions are safe *because* the server-side `importance_sampling`
loss applies the `advantages != 0` mask and our prompt-advantage slice is
zero (`datum_builder.py:248-253`). The ratio `exp(new_lp - old_lp)` is
computed on every position but multiplied by a zero advantage at prompt
positions, so the sentinel value is numerically dead.

**However**, `exp(new_lp - 1.0)` vs `exp(new_lp - 0.0)` can still end up in
batch-level reductions (sum-of-ratios for diagnostics) and can trip numeric
sanity checks. The safer default is `0.0` (cookbook), and our choice of
`1.0` is only defensible if we preserve the atropos "mask-by-value" semantics
— which we do, implicitly, through `advantages == 0`.

**Verdict: VERIFY-AGAINST-LIVE-API.** Recommended fix if live run complains:

```python
# datum_builder.py
PROMPT_LOGPROB_SENTINEL: float = 0.0   # match tinker-cookbook, not atropos
```

### 3. Advantage masking = zeros on prompt positions

**Our code** (`datum_builder.py:248-253`): `np.zeros(n_prompt_targets)` then
the per-response advantage scalar. **Cookbook**
(`rl_loop.py:208`) and **atropos** (`trainer.py:252`) do the same. **Verdict: OK.**

### 4. Token shift

**Our code** (`datum_builder.py:240-242`):

```python
all_tokens = traj.prompt_tokens + traj.response_tokens
input_tokens = all_tokens[:-1]
target_tokens = all_tokens[1:]
```

**tinker-cookbook** (`supervised/common.py:45-98`): the canonical helper
`create_rightshifted_model_input_and_leftshifted_targets` does exactly this
(input = all but last token; target = all but first). **tinker-atropos**
(`trainer.py:247-248`) does the same slice.

The server does **not** do its own shift — the `tokens` field of
`ModelInput` is fed verbatim to the model. **Verdict: OK.**

### 5. `SamplingParams` fields

**Tinker SDK** (`tinker/types/sampling_params.py`):

```python
class SamplingParams(BaseModel):
    max_tokens:  Optional[int] = None
    seed:        Optional[int] = None
    stop:        Union[str, Sequence[str], Sequence[int], None] = None
    temperature: float = 1
    top_k:       int   = -1
    top_p:       float = 1
```

**Our code** (`tinker_responses_model.py:143-147`):

```python
sampling_params = tt.SamplingParams(
    max_tokens=max_tokens,
    temperature=temperature,
    stop=effective_stop,
)
```

`stop` is either `list[str]` / `list[int]` (from the renderer's
`get_stop_sequences()`, see `renderers/base.py:1200`) or `None`. That is
accepted by the `Union` signature. `max_tokens` / `temperature` match.

**Verdict: OK**, but we drop `top_p`, `top_k`, `seed` that callers might set.
No `logprobs` field on `SamplingParams` — per-token response logprobs are
**always** returned on `SampledSequence.logprobs` (we read them directly in
`_route_to_tinker`, line 161). Prompt logprobs require the separate
`include_prompt_logprobs=True` kwarg on `sample_async` — we do not pass it,
and we don't need to.

### 6. `SampleResponse` field names

**Tinker SDK** (`tinker/types/sample_response.py`):

```python
class SampleResponse(BaseModel):
    sequences: Sequence[SampledSequence]
    type: Literal["sample"] = "sample"
    prompt_logprobs: Optional[List[Optional[float]]] = None
    topk_prompt_logprobs: Optional[list[Optional[list[tuple[int, float]]]]] = None
```

**`SampledSequence`** (`tinker/types/sampled_sequence.py`):

```python
class SampledSequence(BaseModel):
    stop_reason: StopReason           # Literal["length", "stop"]
    tokens: List[int]
    logprobs: Optional[List[float]] = None
```

**Our code** (`tinker_responses_model.py:156-161`):

```python
if not result.sequences: raise RuntimeError(...)
seq = result.sequences[0]
gen_tokens = list(seq.tokens)
gen_logprobs = list(seq.logprobs) if seq.logprobs is not None else []
```

and `seq.stop_reason` (line 188) is forwarded back as a string
(`"length"` / `"stop"`).

**Verdict: OK**, with a caveat: `logprobs` is declared `Optional[List[float]]`
in the SDK, so our guard `if seq.logprobs is not None` is required (we have
it). The SDK docstring at `sampling_client.py:309` mis-references the field
as `result.samples` — a SDK bug, not ours.

### 7. `save_weights_and_get_sampling_client_async` / `save_state_async` / `load_state_async`

**Tinker SDK** (`tinker/lib/public_interfaces/training_client.py`):

- `save_weights_and_get_sampling_client_async(self, name: str | None = None, retry_config=...)` — lines 1026-1041. **`name` is deprecated and has no effect**; calling with `name=...` emits a `DeprecationWarning` every time.
- `save_state_async(self, name: str, ttl_seconds=None)` — lines 658-662, `name` is positional keyword, required.
- `load_state_async(self, path: str, weights_access_token=None)` — lines 729-733, `path` is positional-or-keyword, required.

**Our code** (`trainer.py:152-154`, `trainer.py:373-375`, `trainer.py:442`):

```python
self.current_sampling_client = (
    await self.training_client.save_weights_and_get_sampling_client_async(name="step_0")
)
...
new_sampler = await self.training_client.save_weights_and_get_sampling_client_async(
    name=f"step_{step + 1}"
)
...
future = await self.training_client.save_state_async(name=str(ckpt_path))
```

`save_state_async(name=...)` is **OK** — matches the SDK signature.

`save_weights_and_get_sampling_client_async(name=...)` is **WRONG** (or at
least deprecated): the SDK will emit a warning and ignore the argument.
Moreover, the *returned sampler is ephemeral and server-named* — we cannot
reuse `"step_N"` to look it up later, so the name string carries no
information for us.

**Proposed fix** (`trainer.py`):

```python
# step 4 — initial sampler
self.current_sampling_client = (
    await self.training_client.save_weights_and_get_sampling_client_async()
)

# step 6 — hot-swap
new_sampler = await self.training_client.save_weights_and_get_sampling_client_async()
```

If a **named, persistent** sampler weight checkpoint is desired (recommended
for recoverability), use the cookbook/atropos pattern:

```python
save_resp = await self.training_client.save_weights_for_sampler_async(
    name=f"step_{step + 1}"
)
save_result = await save_resp.result_async()
new_sampler = await self.service_client.create_sampling_client_async(
    model_path=save_result.path,
)
```

`load_state_async(path)` — our call at `trainer.py:137` is
`await self.training_client.load_state_async(resume)`, which is **OK** (passes
`resume` as positional `path`). Note the path string must be a
`tinker://...` URI as produced by `save_state_async`.

**Verdict: WRONG (name kwarg) — must fix.** The rest: **OK**.

### 8. LoRA rank default (32)

**Tinker SDK** (`service_client.py:169`): default is `rank: int = 32` for
`create_lora_training_client`. No documented upper bound in the SDK — the
server decides what's supported per base model. **Our default** (`config.py:19`):
`lora_rank: int = 32`.

**Verdict: OK** (matches SDK default). **Nice-to-have**: document that rank
must be a power of two or server-accepted value; the SDK does not validate
client-side.

### 9. `AdamParams` kwargs

**Tinker SDK** (`tinker/types/optim_step_request.py:12-29`):

```python
class AdamParams(StrictBase):
    learning_rate: float = 0.0001
    beta1:         float = 0.9
    beta2:         float = 0.95
    eps:           float = 1e-12
    weight_decay:  float = 0.0
    grad_clip_norm: float = 0.0
```

**Our code** (`trainer.py:331-336`):

```python
adam = tinker.AdamParams(
    learning_rate=self.cfg.tinker.learning_rate,
    beta1=self.cfg.tinker.adam_beta1,
    beta2=self.cfg.tinker.adam_beta2,
    eps=self.cfg.tinker.adam_eps,
)
```

Kwarg names match exactly. `weight_decay` / `grad_clip_norm` are not exposed
through our config — **nice-to-have** to add them. `eps` default of `1e-8`
in our config (line 23) vs SDK `1e-12` — matches tinker-atropos
(`trainer.py:428` `AdamParams(..., eps=1e-8)`), mismatches cookbook (uses
default `1e-12`). Not a correctness bug but flagged **SUSPECT** because it
silently diverges from the SDK default.

**Verdict: OK for kwarg names; SUSPECT for `eps` default.**

### 10. Async API ordering (fwd-bwd + optim pipelining)

**Tinker SDK** (`training_client.py:302-328`, `569-573`): both
`forward_backward_async` and `optim_step_async` are thin wrappers — they
return an `APIFuture` synchronously (via `run_coroutine_threadsafe`) and
*immediately* enqueue the request. `_take_turn(request_id)` inside the SDK
ensures the server sees them in FIFO order. The recommended pattern from
the docstring at `training_client.py:292-295`:

```python
fwdbwd_future = training_client.forward_backward(data, "cross_entropy")
optim_future  = training_client.optim_step(types.AdamParams(learning_rate=1e-4))
fwdbwd_result = await fwdbwd_future
optim_result  = await optim_future
```

**Our code** (`trainer.py:337-345`):

```python
fwd_future = await self.training_client.forward_backward_async(datums, loss_fn=...)
opt_future = await self.training_client.optim_step_async(adam)
fwd_result = await fwd_future.result_async()
await opt_future.result_async()
```

This is the async version of the same pattern: both `await` calls return
the enqueued `APIFuture` without blocking on the server. The two results
are awaited afterwards, achieving the same pipelining.

tinker-atropos does the same (`trainer.py:422-436`) and the cookbook RL
loop does the same (`rl_loop.py:232-237`).

**Verdict: OK.**

### 11. APIFuture vs regular coroutine

`APIFuture` (`tinker/lib/public_interfaces/api_future.py:15-78`) exposes
`result()` / `result_async()` and is directly awaitable via
`__await__ = lambda self: self.result_async().__await__()`. Our code uses
`await fwd_future.result_async()` (explicit) which is fine; `await fwd_future`
would also work. `AwaitableConcurrentFuture` is the other concrete subclass
and likewise awaitable.

**Verdict: OK.**

### 12. Renderer + tokenizer compatibility

**Tinker cookbook** (`tinker_cookbook/model_info.py:63-72`):

```python
return {
    "Llama-3.2-1B-Instruct": ModelAttributes(org, "3.2", "1B", True,  _LLAMA3),
    ...
    "Llama-3.2-1B":          ModelAttributes(org, "3.2", "1B", False, _ROLE_COLON),
    ...
}
```

where `_ROLE_COLON = ("role_colon",)` (`model_info.py:19`) and
`_LLAMA3 = ("llama3",)` (`model_info.py:18`).

`get_recommended_renderer_name("meta-llama/Llama-3.2-1B")` → `"role_colon"`
(`model_info.py:239-249`).

**Our default** (`config.py:18`): `base_model: str = "meta-llama/Llama-3.2-1B"`
→ picks `role_colon` renderer. `role_colon` formats messages as
`"user: ...\nassistant: ..."` — fine for *base-LM continuation training*, but
**not** what most users expect when they POST OpenAI-style chat messages to
our FastAPI shim. The shim's `_extract_messages_chat` (line 208) and
`_route_to_tinker` (line 125) will dutifully push user/assistant tuples
through `role_colon`, and the model (base Llama-3.2-1B, *not* the Instruct
variant) has zero chat-format priors. Empirically the RL loop may "work" —
it will learn *something* — but out-of-distribution from a chat perspective.

**Verdict: SUSPECT / WRONG as a default.** Fix:

```python
# config.py
class TinkerConfig(BaseModel):
    base_model: str = "meta-llama/Llama-3.2-1B-Instruct"
    ...
```

(or document that users must pass an Instruct model for OpenAI-style chat
endpoints).

Additional note: `get_renderer("llama3", tokenizer)` (`renderers/__init__.py:114`)
requires the tokenizer to be the Llama-3 tokenizer — which `get_tokenizer`
ensures via `_load_tokenizer_from_model_info`. No issue there.

### 13. Hot-swap timing / race

**Our code** (`trainer.py:370-381`):

```python
new_sampler = await self.training_client.save_weights_and_get_sampling_client_async(
    name=f"step_{step + 1}"
)
self.current_sampling_client = new_sampler
tmodel.set_sampling_client(new_sampler)
```

and `tinker_responses_model._route_to_tinker` takes a *local snapshot* of
the client (`tinker_responses_model.py:118` — `client = get_sampling_client()`)
before each `client.sample_async(...)` call. The lock
(`_sampling_client_lock`) serialises the swap; requests already holding the
snapshot continue on the old client. SDK-level: `SamplingClient`'s identity
is `sampling_session_id` (`sampling_client.py:150-157`) — each session is
an immutable reference to a weights snapshot, so concurrent samples on the
old and new clients cannot corrupt each other on the server side.

The only hazard is that a *batch* of rollouts kicked off from the
`rollout_driver` can straddle the swap — some rollouts in the batch saw
the old weights, others saw the new. We await
`rollout_batch(...)` fully (trainer.py:283-287) **before** stepping the
optimizer, so within one training step we never mix. Between steps,
any lingering in-flight HTTP requests from step N would already be
finished before step N+1 starts.

**Verdict: OK** (race is benign), but add a docstring note.

### 14. Exception types

**Tinker SDK** raises (see `_exceptions.py:1-209`):

- `TinkerError` (base)
- `APIError` (base), subclasses: `APIConnectionError`, `APITimeoutError`,
  `APIStatusError` → `BadRequestError` (400), `AuthenticationError` (401),
  `PermissionDeniedError` (403), `NotFoundError` (404), `ConflictError`
  (409), `UnprocessableEntityError` (422), `RateLimitError` (429),
  `InternalServerError` (500+), `APIResponseValidationError`
- `RequestFailedError` (async request completed in failed state — carries
  `request_id` + `category`)
- `SidecarError` → `SidecarStartupError`, `SidecarDiedError`, `SidecarIPCError`

**Our code** (`trainer.py:257-260`, `288-290`, `346-353`, `379-381`):
everywhere catches bare `except Exception`. That's acceptable for the
per-step resilience we want, but:

- **Authentication / permission errors are not worth retrying.** Wrap the
  `setup()` path so `AuthenticationError` / `PermissionDeniedError` fail
  fast.
- **`RequestFailedError`** carries a `category` field (`RequestErrorCategory`)
  indicating whether the error is fatal; we ignore it.
- **`SidecarDiedError`**: if the subprocess sampler dies, every subsequent
  `sample_async` will raise. We'd spin forever logging warnings. Detecting
  `SidecarDiedError` and aborting is cleaner.

Proposed narrow catch (trainer run-loop):

```python
from tinker import (
    AuthenticationError, PermissionDeniedError,
    APIConnectionError, APITimeoutError, RateLimitError,
    InternalServerError, RequestFailedError,
    SidecarDiedError,
)

FATAL = (AuthenticationError, PermissionDeniedError, SidecarDiedError)
TRANSIENT = (APIConnectionError, APITimeoutError, RateLimitError,
             InternalServerError, RequestFailedError)

try:
    ...
except FATAL:
    raise                # do not continue the loop
except TRANSIENT as e:
    logger.warning("transient tinker error: %r", e)
    continue
except Exception as e:
    logger.exception("unexpected error: %r", e)
    continue
```

**Verdict: SUSPECT / nice-to-have.** The current broad catch won't *break*
the loop, but it masks conditions that should abort.

---

## Summary table

| # | Topic                                    | Verdict                       |
|---|------------------------------------------|-------------------------------|
| 1 | Datum / ModelInput / TensorData          | OK                            |
| 2 | Logprob sentinel = 1.0                   | VERIFY-AGAINST-LIVE-API       |
| 3 | Advantage masking (zeros on prompt)      | OK                            |
| 4 | Token shift (input[:-1], target[1:])     | OK                            |
| 5 | SamplingParams keys                      | OK (top_p/top_k dropped)      |
| 6 | SampleResponse field names               | OK                            |
| 7 | save_weights_..._async(name=...)         | **WRONG** (deprecated kwarg)  |
| 8 | LoRA rank default 32                     | OK                            |
| 9 | AdamParams kwargs                        | OK (eps default SUSPECT)      |
| 10| Async fwd_bwd+optim pipelining           | OK                            |
| 11| APIFuture semantics                      | OK                            |
| 12| Renderer for Llama-3.2-1B (base)         | **SUSPECT** (picks role_colon)|
| 13| Hot-swap timing                          | OK                            |
| 14| Exception breadth                        | SUSPECT                       |

---

_Sources read:_
`tinker/__init__.py`, `tinker/types/{datum,model_input,tensor_data,loss_fn_inputs,loss_fn_type,sampling_params,sample_response,sampled_sequence,stop_reason,optim_step_request,forward_backward_output}.py`,
`tinker/_exceptions.py`,
`tinker/lib/public_interfaces/{api_future,sampling_client,service_client,training_client}.py`,
`tinker_cookbook/{model_info,renderers/__init__,renderers/base}.py`,
`tinker_cookbook/rl/data_processing.py`,
`tinker_cookbook/supervised/common.py`,
`tinker_cookbook/recipes/rl_loop.py`,
`tinker-atropos/tinker_atropos/trainer.py`,
plus our own:
`tinker_nemogym/{datum_builder,trainer,tinker_responses_model,config}.py`.

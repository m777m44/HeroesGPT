# Custom env + Nemotron end-to-end

Bring your own nemo-gym env, train Nemotron-3-Nano-30B against it, monitor
live. Everything needed is inside **tinker-nemogym** — no manual sibling-repo
edits required.

## 1. Define the env (lives inside tinker-nemogym)

A nemo-gym env is a `SimpleResourcesServer` subclass with an async
`verify()` method. `verify()` sees the full request (`responses_create_params`
+ any extra top-level fields from the JSONL row + the model's
`response.output_text`) and returns a `BaseVerifyResponse` with a `reward`
float.

Ours lives at
[`tinker_nemogym/environments/json_format/nemogym_server/app.py`](../tinker_nemogym/environments/json_format/nemogym_server/app.py)
— **inside this repo**, tracked and versioned here. The grading body (simplified):

```python
async def verify(self, body: JSONFormatVerifyRequest) -> JSONFormatVerifyResponse:
    text = _strip_fence((body.response.output_text or "").strip())

    parsed_ok = False
    parsed = None
    try:
        parsed = json.loads(text)
        parsed_ok = True
    except (json.JSONDecodeError, ValueError):
        parsed_ok = False

    required = body.required_keys or []
    keys_ok = parsed_ok and bool(required) and _keys_match(
        parsed, required, body.expected_count,
    )

    if parsed_ok and keys_ok:
        reward = 1.0      # valid JSON + all required keys present
    elif parsed_ok:
        reward = 0.5      # valid JSON, keys missing/wrong — partial credit
    else:
        reward = 0.0      # not JSON

    return JSONFormatVerifyResponse(
        **body.model_dump(), reward=reward,
        parsed_ok=parsed_ok, keys_ok=keys_ok,
    )
```

Three-level reward ⇒ natural within-group variance for GRPO.

### Directory layout

```
tinker_nemogym/environments/json_format/
├── __init__.py
├── README.md
├── dataset.jsonl
└── nemogym_server/             # the resources_server (single source of truth)
    ├── __init__.py
    ├── app.py
    ├── configs/tng_json_format.yaml
    └── requirements.txt
```

`scripts/smoke_json_format.sh` file-symlinks this dir's contents into
`nemo-gym/resources_servers/tng_json_format/` at startup so `ng_run` can
discover it, and removes them on exit. One link per file (app.py, configs/,
requirements.txt) — NOT the whole dir — so `ng_run`'s editable-install
detection (`dir_path.resolve() / "../../pyproject.toml"`) still resolves to
`nemo-gym/pyproject.toml` correctly.

## 2. Wire it (three YAMLs, all inside this repo)

**`configs/nemogym_json_format_resources.yaml`**

```yaml
tng_json_format:
  resources_servers:
    tng_json_format:
      entrypoint: app.py
      domain: instruction_following
      verified: false
      description: Grade JSON-output compliance
```

**`configs/nemogym_json_format_agent.yaml`** (agent → :8001 shim)

```yaml
policy_model:
  responses_api_models:
    openai_model:
      entrypoint: app.py
      openai_base_url: http://127.0.0.1:8001/v1  # our Tinker shim
      openai_api_key: tinker-nemogym-shim
      openai_model: tinker

tng_json_format_simple_agent:
  responses_api_agents:
    simple_agent:
      entrypoint: app.py
      resources_server: {type: resources_servers, name: tng_json_format}
      model_server:     {type: responses_api_models, name: policy_model}
      datasets:
      - name: example
        type: example
        jsonl_fpath: ../tinker-nemogym/tinker_nemogym/environments/json_format/dataset.jsonl
```

**`configs/smoke_json_format_nemotron.yaml`** (the trainer)

```yaml
schema_version: 1
tinker:
  base_model: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
  lora_rank: 32
  wandb_project: tinker-nemogym-json-format
  wandb_name: nemotron-nano-json-format-run1
nemogym:
  agent_url: null              # dynamic discovery via HeadServer
  head_url: http://127.0.0.1:11000
  dataset_jsonl: tinker_nemogym/environments/json_format/dataset.jsonl
  group_size: 8
training:
  n_steps: 5
  batch_size: 2
  max_tokens: 512
  temperature: 1.0
  drop_constant_reward: true   # skip groups where all 8 rollouts tied
```

Key knobs: `agent_url: null` → trainer auto-discovers the agent port off
`/server_instances`. `group_size: 8` at `batch_size: 2` = 16 parallel
rollouts/step.

## 3. Run the end-to-end

```bash
export TINKER_API_KEY=***
bash scripts/smoke_json_format.sh
```

That's literally it. The script:

1. Symlinks `tinker_nemogym/environments/json_format/nemogym_server` contents
   into `nemo-gym/resources_servers/tng_json_format/`.
2. Launches `ng_run` with the two YAMLs.
3. Waits for HeadServer on :11000.
4. Runs the trainer against the resulting stack.
5. On exit/interrupt, stops `ng_run` and removes the symlink dir.

To boot only the nemo-gym side (no Tinker call), set `SKIP_TINKER=1`.

Expected output: ~1 min warmup (Nemotron-30B first step cold-starts ~3 min
on Tinker GPUs), then:

```
Step 0: mean_reward=0.56 loss=-0.004 save_count=0
Step 1: mean_reward=0.69 loss=-0.007 save_count=0
Step 2: mean_reward=0.75 loss=-0.006 save_count=1
...
```

## 4. Monitor

### A. wandb (recommended)

The trainer emits metrics per step under `wandb_project`. In offline mode
(default when unauth'd) runs land in `./wandb/offline-run-*/`. Sync later:

```bash
wandb sync ./wandb/offline-run-*
```

The smoke script prints the live run URL as soon as it shows up.

### B. Terminal monitor

```bash
bash scripts/monitor_run.sh
```

Live-tails `/tmp/tinker_nemogym_*.log`, greps `Step N:` / `mean_reward` /
`loss` / `save_count`, shows recent wandb `debug.log`, and lists
nemo-gym's `:11xxx` ports (HeadServer + sub-servers).

## Common pitfalls

- **Nemotron-30B first run cold-start ~3min** — model loading on Tinker
  GPUs. Subsequent steps are fast.
- **All rewards 1.0 or all 0.0** → group gets dropped by
  `drop_constant_reward`. Increase `group_size` or diversify prompts.
- **Checkpoint label invalid** → labels must match `[A-Za-z0-9._-]+`
  (no slashes). See `checkpoint_meta.py`.
- **`agent_url` points at the wrong port** → leave it `null` unless you
  know the port; the trainer reads it from the HeadServer at startup.
- **"$SERVER_DST already exists"** on startup → a previous run didn't clean
  up. Remove `nemo-gym/resources_servers/tng_json_format/` manually and
  retry. The script refuses to clobber unknown files as a safety net.

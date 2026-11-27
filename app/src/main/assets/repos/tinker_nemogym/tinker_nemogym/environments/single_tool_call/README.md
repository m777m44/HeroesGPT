# `example_single_tool_call` environment bundle

Thin wrapper around nemo-gym's reference environment
[`example_single_tool_call`](https://github.com/NVIDIA-NeMo/Gym/tree/main/resources_servers/example_single_tool_call) —
a trivial single-step tool-calling task where the model is asked about the
weather in a city and is expected to emit a `get_weather(city=...)` function
call.

The environment's resources server implements:

| endpoint       | behavior                                                                |
| -------------- | ----------------------------------------------------------------------- |
| `POST /get_weather` | Returns `{"weather_description": "The weather in {city} is cold."}` |
| `POST /verify`      | Unconditionally returns reward `1.0`                                |

Because verify always returns 1.0, this env is not useful for learning — it's a
**smoke test** of the full tinker-nemogym pipeline end-to-end:

1. `TinkerNeMoGymTrainer` boots its FastAPI shim on `:8001`.
2. nemo-gym is launched via `ng_run` pointing the SimpleAgent at `:8001`.
3. The trainer POSTs each row below into the agent's `/run` endpoint,
   harvesting `{reward, response_with_token_ids_and_logprobs}`.
4. Tinker's `forward_backward_async(loss_fn="importance_sampling")` runs on
   the returned datums; weights update; a fresh sampling client is hot-swapped
   into the shim; repeat.

## Dataset

`dataset.jsonl` contains the 5 example rows mirrored from
`nemo-gym/resources_servers/example_single_tool_call/data/example.jsonl`
(Apache-2.0, NVIDIA). Each row follows nemo-gym's agent input schema
(`responses_create_params.input` + `responses_create_params.tools`).

## How to run

From the repo root:

```bash
export TINKER_API_KEY=...
bash scripts/smoke_single_tool.sh
```

The script launches nemo-gym (resources + agent) and the tinker-nemogym
trainer, which together implement the data flow diagrammed in
`docs/architecture.html`.

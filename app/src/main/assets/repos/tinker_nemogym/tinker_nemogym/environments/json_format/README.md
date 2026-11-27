# `json_format` environment bundle (varied-reward, structured-output)

Thin wrapper around nemo-gym's
[`tng_json_format`](../../../../nemo-gym/resources_servers/tng_json_format/)
resources server. Grades whether the model obeys a JSON-output contract:

| endpoint       | behavior                                                                                   |
| -------------- | ------------------------------------------------------------------------------------------ |
| `POST /verify` | 1.0 if valid JSON AND all `required_keys` present (on each item if list); 0.5 if parses but keys off; 0.0 otherwise |

## Why this env

Cheap, single-turn, but naturally varied reward: base models frequently
emit Markdown fences, preamble, or miss keys — all three levels (0.0 / 0.5
/ 1.0) show up in a small batch. Pairs well with `drop_constant_reward:
true`.

## Dataset

`dataset.jsonl` — 10 prompts, each shaped like a nemo-gym `BaseRunRequest`
with `responses_create_params.input` containing a user message plus
grading metadata at the top level (`required_keys`, `expected_count`,
`uuid`). See the first row for an example.

## How to run

From the repo root:

```bash
export TINKER_API_KEY=***
bash scripts/smoke_json_format.sh
```

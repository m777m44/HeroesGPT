# `mcqa` environment bundle (varied-reward single-turn)

Thin wrapper around nemo-gym's reference environment
[`mcqa`](https://github.com/NVIDIA-NeMo/Gym/tree/main/resources_servers/mcqa)
— a multiple-choice question answering task (e.g. MMLU-style). The model is
shown a question + 10 labeled options and expected to emit
`\boxed{<LETTER>}`. The resources server extracts the letter and compares
against `expected_answer`, returning reward 0.0 or 1.0.

## Why this env

`example_single_tool_call` always returns 1.0, so after GRPO centers rewards
every advantage is zero and the `forward_backward` call is a no-op on the
gradient. `mcqa` is single-turn (fast, cheap) but produces *varied* rewards
as long as the policy isn't perfect — which is the normal case for a base
model. With the default `drop_constant_reward: True`, training only happens
on groups that actually have reward variance.

| endpoint         | behavior                                                               |
| ---------------- | ---------------------------------------------------------------------- |
| `POST /verify`   | Parses `\boxed{X}` from the assistant text, returns 1.0 iff `X == expected_answer` else 0.0 |

## Dataset

`dataset.jsonl` — 5 example rows mirrored from
`nemo-gym/resources_servers/mcqa/data/example.jsonl` (Apache-2.0, NVIDIA).
Each row provides `options` (list of single-key dicts) and `expected_answer`
(a single uppercase letter) alongside a chat prompt. Grading mode defaults
to `strict_single_letter_boxed`.

## How to run

From the repo root:

```bash
export TINKER_API_KEY=***
bash scripts/smoke_mcqa.sh
```

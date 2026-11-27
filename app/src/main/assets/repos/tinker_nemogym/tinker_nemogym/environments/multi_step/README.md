# multi_step environment

Wraps nemo-gym's ``example_multi_step`` resources server: a synonym-value
extraction task that forces the model to issue *multiple* ``get_synonym_value``
tool calls before committing its final ``extract_synonym_values`` answer. This
exercises:

1. **Multi-turn tool-use rollouts** — the agent accumulates
   ``function_call`` + ``function_call_output`` items across turns before
   the model emits its final message.
2. **Varied reward** — the verifier returns a hard 0/1 plus an
   ``order_instruction_following_failure`` + ``set_overlap`` soft signal
   that varies across rollouts; useful for GRPO sanity checks.
3. **Interleaved ForTraining outputs** — nemo-gym attaches one
   ``NeMoGym*ForTraining`` item *per* assistant turn, so the response has
   several ``generation_token_ids`` / ``generation_log_probs`` blocks. Our
   ``datum_builder`` concatenates them in order (see
   :func:`tinker_nemogym.datum_builder._collect_training_outputs`).

## Files

* ``dataset.jsonl`` — copied verbatim from
  ``nemo-gym/resources_servers/example_multi_step/data/example.jsonl``. The
  five rows are enough for smoke/unit tests; training would use the full
  GitLab dataset.

## Configs

* ``configs/smoke_multi_step.yaml`` — trainer config pointing at this
  dataset and the multi-step agent port.
* ``configs/nemogym_multi_step_resources.yaml`` — resources-server block
  only (mirrors the upstream ``example_multi_step.yaml``).
* ``configs/nemogym_multi_step_agent.yaml`` — policy_model (our shim) +
  SimpleAgent block referencing the resources server above.

To run against live Tinker (requires ``TINKER_API_KEY``):

```bash
export TINKER_API_KEY=***
bash scripts/smoke_multi_step.sh
```

The script launches nemo-gym's ``ng_run`` stack, then drives the trainer
through the full multi-turn RL loop against real Tinker GPUs.

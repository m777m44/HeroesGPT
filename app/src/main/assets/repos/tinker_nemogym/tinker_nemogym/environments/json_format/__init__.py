"""JSON-format-compliance environment bundle.

Thin wrapper around nemo-gym's ``tng_json_format`` resources server. The model
is asked to produce JSON with specific keys and graded on:

* 1.0 — output is valid JSON AND contains all required keys
* 0.5 — output parses as JSON but keys are missing / wrong
* 0.0 — output does not parse as JSON

Varied reward (not constant), so GRPO actually produces non-zero advantages
and Tinker ``forward_backward_async`` computes a non-trivial gradient.
"""

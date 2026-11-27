"""MCQA (multi-choice question answering) environment bundle.

Thin wrapper around nemo-gym's ``mcqa`` resources server. Unlike
``example_single_tool_call`` which returns constant reward 1.0, MCQA grades
the assistant's answer against ``expected_answer`` and returns 0.0 or 1.0.
That variance is the whole point — with ``drop_constant_reward=True`` we see
groups actually produce non-zero advantages and Tinker ``forward_backward_async``
computes a non-trivial gradient.
"""

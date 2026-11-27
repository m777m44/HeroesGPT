"""Shared pytest fixtures for tinker-nemogym tests.

The most important hook here (Review 04 §5.2) is an autouse fixture that
resets the module-global state of :mod:`tinker_nemogym.tinker_responses_model`
between every test. The module stashes an active ``SamplingClient``,
tokenizer, and renderer at import scope; leaving those populated across
tests caused order-dependent failures when tests were run out of order
(e.g. under ``-p no:randomly`` vs ``pytest-xdist``).
"""

from __future__ import annotations

import pytest

from tinker_nemogym import tinker_responses_model as _shim


@pytest.fixture(autouse=True)
def _reset_tinker_responses_model_globals():
    """Force-reset the shim's module globals around every test.

    Yields before *and* after to guarantee isolation both ways: a test that
    mutates globals then fails mid-way won't leak state into the next test.
    """
    _shim._reset_for_tests()
    try:
        yield
    finally:
        _shim._reset_for_tests()

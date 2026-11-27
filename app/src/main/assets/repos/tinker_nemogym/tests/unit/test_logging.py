"""Tests for :mod:`tinker_nemogym.utils.logging`."""

from __future__ import annotations

import json
import logging

import pytest

from tinker_nemogym.utils.logging import (
    RUN_ID_VAR,
    RunIdFilter,
    configure_logging,
    new_run_id,
)


def test_new_run_id_is_8_hex_chars():
    rid = new_run_id()
    assert len(rid) == 8
    assert all(c in "0123456789abcdef" for c in rid)


def test_new_run_id_is_unique():
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50  # vanishingly small collision chance


def test_filter_injects_run_id_onto_record():
    rec = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hi", args=None, exc_info=None,
    )
    token = RUN_ID_VAR.set("abcd1234")
    try:
        RunIdFilter().filter(rec)
    finally:
        RUN_ID_VAR.reset(token)
    assert rec.run_id == "abcd1234"


def test_filter_defaults_to_dash_outside_run():
    rec = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hi", args=None, exc_info=None,
    )
    RunIdFilter().filter(rec)
    assert rec.run_id == "-"


def test_configure_logging_human_format_contains_run_id(caplog):
    """Human format writes the run_id next to the message."""
    configure_logging(level="INFO", json=False)
    logger = logging.getLogger("tinker_nemogym.tests.logging")

    token = RUN_ID_VAR.set("deadbeef")
    try:
        with caplog.at_level("INFO"):
            logger.info("hello from test")
    finally:
        RUN_ID_VAR.reset(token)

    records = [r for r in caplog.records if r.message == "hello from test"]
    assert records
    # The filter attaches ``run_id`` onto the record regardless of formatter.
    assert records[0].run_id == "deadbeef"


def test_configure_logging_json_format(capsys):
    configure_logging(level="INFO", json=True)
    logger = logging.getLogger("tinker_nemogym.tests.logging_json")

    token = RUN_ID_VAR.set("cafebabe")
    try:
        logger.info("json payload test")
    finally:
        RUN_ID_VAR.reset(token)

    err = capsys.readouterr().err
    # Last non-empty line should parse as JSON with a run_id key.
    lines = [line for line in err.splitlines() if line.strip()]
    assert lines
    payload = json.loads(lines[-1])
    assert payload["run_id"] == "cafebabe"
    assert payload["msg"] == "json payload test"
    assert payload["level"] == "INFO"


def test_configure_logging_is_idempotent():
    """Calling configure_logging N times does NOT accumulate N handlers."""
    configure_logging(level="INFO", json=False)
    configure_logging(level="INFO", json=False)
    configure_logging(level="INFO", json=False)
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "_tinker_nemogym", False)]
    assert len(ours) == 1


@pytest.fixture(autouse=True)
def _reset_handlers():
    """Reset the logger handlers around each test so tests don't leak state."""
    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_tinker_nemogym", False):
            root.removeHandler(h)

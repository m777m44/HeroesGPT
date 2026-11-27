#!/usr/bin/env python3
"""Thin entry point: ``python launch_training.py --config path/to/config.yaml``.

Dispatches directly to the ``train`` subcommand of :mod:`tinker_nemogym.cli`.
"""
from __future__ import annotations

import sys

from tinker_nemogym.cli import train

if __name__ == "__main__":
    # Click commands are invokable as standalone CLIs; forward argv.
    train.main(args=sys.argv[1:], prog_name="launch_training.py")

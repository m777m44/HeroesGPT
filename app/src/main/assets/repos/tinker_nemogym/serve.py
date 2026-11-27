#!/usr/bin/env python3
"""Thin entry point: ``python serve.py --config path/to/config.yaml``.

Dispatches directly to the ``serve`` subcommand of :mod:`tinker_nemogym.cli`,
which starts only the FastAPI model shim (no training loop).
"""
from __future__ import annotations

import sys

from tinker_nemogym.cli import serve

if __name__ == "__main__":
    serve.main(args=sys.argv[1:], prog_name="serve.py")

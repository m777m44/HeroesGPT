"""Test bootstrap: put this repo on sys.path (flat imports of tirith_scan) and, for the
registration test, a hermes-agent checkout (HERMES_AGENT_REPO, default ~/.hermes/hermes-agent)."""

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_HERMES_AGENT = Path(
    os.environ.get("HERMES_AGENT_REPO", Path.home() / ".hermes" / "hermes-agent")
).expanduser()

for p in (str(_HERMES_AGENT), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

collect_ignore = ["__init__.py", "tirith_scan.py"]

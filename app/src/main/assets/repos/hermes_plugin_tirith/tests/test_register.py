"""Load the plugin the way Hermes does and drive the registered hook (needs a hermes-agent checkout)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


class _Ctx:
    def __init__(self, settings):
        self.settings, self.hooks = settings, {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def _load():
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.tirith_under_test", _ROOT / "__init__.py",
        submodule_search_locations=[str(_ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(os.name == "nt", reason="shell-script fake binary")
def test_hook_scans_only_terminal_and_reads_settings_per_call(tmp_path):
    fake = tmp_path / "tirith"
    fake.write_text(f"#!{sys.executable}\nimport json,sys\n"
                    "print(json.dumps({'findings':[{'rule_id':'r1','severity':'HIGH','title':'T'}]}))\n"
                    "sys.exit(1)\n", encoding="utf-8")
    fake.chmod(0o755)
    ctx = _Ctx({"path": str(fake)})
    _load().register(ctx)
    hook = ctx.hooks["pre_tool_call"]
    assert hook(tool_name="read_file", args={"path": "x"}) is None
    assert hook(tool_name="terminal", args={"command": "echo hi"})["rule_key"] == "tirith:r1"
    ctx.settings["ignore_rules"] = ["r1"]
    assert hook(tool_name="terminal", args={"command": "echo hi"}) is None

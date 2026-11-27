"""tirith pre-exec scanning for Hermes, as an opt-in plugin.

Every ``terminal`` call is scanned with ``tirith check`` before it runs. A finding at or above
``min_severity`` returns an ``approve`` directive from ``pre_tool_call``, so the command goes to
Hermes's own approval gate (CLI prompt, gateway buttons, Desktop card; cron and other unattended
runs follow ``approvals.*_mode``). The plugin never approves anything itself and never blocks
outright: the human, or the operator's unattended policy, decides.

The scan logic lives in ``tirith_scan.py`` so it can be tested without Hermes.
"""

from __future__ import annotations

try:
    from .tirith_scan import Settings, decide
except ImportError:  # flat import in the plugin's own test run
    from tirith_scan import Settings, decide


def register(ctx) -> None:
    def _settings() -> Settings:
        # Read at call time: the multiplexed gateway reuses one ctx across profiles.
        return Settings.from_mapping({key: ctx.get_config(key) for key in Settings.KEYS})

    def pre_tool_call(tool_name: str = "", args: dict | None = None, **_kwargs):
        if tool_name != "terminal" or not isinstance(args, dict):
            return None
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return None
        return decide(command, _settings())

    ctx.register_hook("pre_tool_call", pre_tool_call)

"""tirith invocation and verdict mapping, free of Hermes imports so it tests standalone."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
_EXIT_ACTIONS = {0: "allow", 1: "block", 2: "warn"}
_MAX_LISTED = 5
_warned: set[str] = set()
_warned_lock = threading.Lock()


def _warn_once(key: str, message: str, *args) -> None:
    with _warned_lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message, *args)


def _rank(severity: str) -> int:
    try:
        return _SEVERITIES.index(str(severity).upper())
    except ValueError:
        return len(_SEVERITIES)  # unknown severity: treat as serious rather than drop it


@dataclass(frozen=True)
class Settings:
    path: str = "tirith"
    timeout: int = 5
    offline: bool = True
    min_severity: str = "LOW"
    ignore_rules: frozenset = field(default_factory=frozenset)
    fail_closed: bool = False

    KEYS = ("path", "timeout", "offline", "min_severity", "ignore_rules", "fail_closed")

    @classmethod
    def from_mapping(cls, values: dict) -> Settings:
        """Unset (None) values fall back to the defaults; malformed ones too, with a warning."""
        base = cls()
        out = {}
        for key in cls.KEYS:
            value = values.get(key)
            if value is None:
                continue
            if key == "ignore_rules":
                if isinstance(value, (list, tuple, set)):
                    out[key] = frozenset(str(v) for v in value)
                    continue
            elif key == "timeout":
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    out[key] = value
                    continue
            elif key in ("offline", "fail_closed"):
                if isinstance(value, bool):
                    out[key] = value
                    continue
            elif key == "min_severity":
                if str(value).upper() in _SEVERITIES:
                    out[key] = str(value).upper()
                    continue
            elif isinstance(value, str) and value.strip():
                out[key] = value.strip()
                continue
            _warn_once(f"bad-setting:{key}", "tirith plugin: ignoring invalid setting %s=%r", key, value)
        return cls(**{**base.__dict__, **out})


def resolve_binary(path: str) -> str | None:
    expanded = os.path.expanduser(path)
    if os.sep in expanded or (os.altsep and os.altsep in expanded):
        return expanded if os.path.isfile(expanded) and os.access(expanded, os.X_OK) else None
    return shutil.which(expanded)


def scan(command: str, settings: Settings) -> dict:
    """``{"status": "ok", "action", "findings"}`` or ``{"status": "error", "reason"}``."""
    binary = resolve_binary(settings.path)
    if binary is None:
        return {"status": "error", "reason": f"tirith executable not found ({settings.path})"}
    argv = [binary, "check", "--json", "--non-interactive", "--shell", "posix"]
    if settings.offline:
        argv.append("--offline")
    argv += ["--", command]
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=settings.timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": f"tirith timed out after {settings.timeout}s"}
    except OSError as exc:
        return {"status": "error", "reason": f"tirith could not start: {exc}"}
    action = _EXIT_ACTIONS.get(result.returncode)
    if action is None:
        return {"status": "error", "reason": f"tirith exited with code {result.returncode}"}
    try:
        findings = json.loads(result.stdout or "{}").get("findings") or []
    except (json.JSONDecodeError, AttributeError):
        findings = []
    return {"status": "ok", "action": action, "findings": [f for f in findings if isinstance(f, dict)]}


def _describe(findings: list[dict]) -> str:
    # Severity + title + rule id only: tirith's free-text description carries "Safer: ..." advice that
    # can point at third-party tools, and Hermes renders this text verbatim on approval cards.
    lines = list(dict.fromkeys(  # tirith repeats a finding per matched span; show each once
        f"[{f.get('severity', '?')}] {f.get('title') or f.get('rule_id', 'finding')} ({f.get('rule_id', '?')})"
        for f in findings))
    extra = [f"+{len(lines) - _MAX_LISTED} more"] if len(lines) > _MAX_LISTED else []
    return "tirith: " + "; ".join(lines[:_MAX_LISTED] + extra)


def decide(command: str, settings: Settings) -> dict | None:
    """``pre_tool_call`` directive for one command, or ``None`` to let it through untouched."""
    result = scan(command, settings)
    if result["status"] == "error":
        _warn_once(f"error:{result['reason']}", "tirith plugin: %s", result["reason"])
        if not settings.fail_closed:
            return None
        return {"action": "approve", "rule_key": "tirith:unavailable",
                "message": f"tirith could not scan this command ({result['reason']}) and fail_closed is on"}
    if result["action"] == "allow":
        return None
    floor = _rank(settings.min_severity)
    relevant = [f for f in result["findings"]
                if f.get("rule_id") not in settings.ignore_rules and _rank(f.get("severity", "")) >= floor]
    if not relevant:
        if result["findings"]:
            return None  # every finding was filtered by the operator's settings
        relevant = [{"severity": "?", "title": f"tirith returned {result['action']} without details",
                     "rule_id": "unknown"}]
    # The rule key scopes "allow for this session" to the exact set of rules seen, so approving one
    # finding never covers a later command that trips a different one.
    rule_key = "tirith:" + ",".join(sorted({str(f.get("rule_id", "unknown")) for f in relevant}))
    return {"action": "approve", "message": _describe(relevant), "rule_key": rule_key}

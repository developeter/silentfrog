#!/usr/bin/env python3
"""PreToolUse hook: block bare `git commit` so caveman-commit drafts the message first.

Fires only when the Bash tool is invoked. The companion settings.json
narrows further via `if: "Bash(git commit*)"`. We then inspect the
exact command and allow it only when a quoted ``-m "..."`` (or
``-F file``) is present — i.e. the user has already supplied a
message. Bare ``git commit`` (which would open the editor) is denied
with a routing note pointing at the ``caveman-commit`` skill.
"""

from __future__ import annotations

import json
import re
import sys

_ALLOWED_FORMS = (
    re.compile(r'\bgit\s+commit\b[^|;&]*\s-m\s+(["\']).+?\1', re.DOTALL),
    re.compile(r"\bgit\s+commit\b[^|;&]*\s-F\s+\S+"),
    re.compile(r"\bgit\s+commit\b[^|;&]*\s--amend\b"),  # editor allowed on amend
    re.compile(r"\bgit\s+commit\b[^|;&]*\s--no-edit\b"),
    re.compile(r"\bgit\s+commit\b[^|;&]*\s--allow-empty-message\b"),
    re.compile(r"\bgit\s+commit\b[^|;&]*\s--message=\S+"),
)


def _payload() -> dict:
    raw = sys.stdin.read() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _command(payload: dict) -> str:
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    if isinstance(tool_input, dict):
        return str(tool_input.get("command", ""))
    return ""


def _is_bare_commit(command: str) -> bool:
    if "git commit" not in command:
        return False
    return not any(pattern.search(command) for pattern in _ALLOWED_FORMS)


def main() -> int:
    command = _command(_payload())
    if not _is_bare_commit(command):
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Bare `git commit` would open the editor unattended. "
                        "Use the `caveman-commit` skill to draft a Conventional "
                        "Commits-style message first, then re-run with "
                        '`git commit -m "..."`.'
                    ),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

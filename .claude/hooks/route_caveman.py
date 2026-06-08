#!/usr/bin/env python3
"""UserPromptSubmit hook: inject caveman routing notes based on keywords.

Fires on every prompt submission. We never block — we only enrich the
context with a one-line system note pointing at the appropriate
caveman skill when the prompt mentions a commit or review task.
"""
from __future__ import annotations

import json
import re
import sys

_COMMIT_RE = re.compile(
    r"\b(commit message|pr description|pr body|caveman-commit|"
    r"draft(?:\s+the)?\s+commit|conventional commits|scrivi(?:\s+il)?\s+commit)\b",
    re.IGNORECASE,
)
_REVIEW_RE = re.compile(
    r"\b(code review|pr review|pr feedback|review (?:this|the)\s+(?:pr|diff|change)|"
    r"caveman-review|revisiona(?:re)?\s+(?:la|il)\s+pr)\b",
    re.IGNORECASE,
)

_COMMIT_NOTE = (
    "The user is asking about a commit. Use the `caveman-commit` skill to "
    "draft the message in Conventional Commits format (subject ≤ 50 chars; "
    "body only when the why is non-obvious). If the user already authored a "
    "verbatim message, use it as-is."
)
_REVIEW_NOTE = (
    "The user is asking for a code review. Use the `caveman-review` skill — "
    "ultra-compressed one-line comments (location, problem, fix). Skip "
    "celebratory noise."
)


def _payload() -> dict:
    raw = sys.stdin.read() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _prompt(payload: dict) -> str:
    return str(payload.get("prompt", "")) if isinstance(payload, dict) else ""


def _additional_context(prompt: str) -> str:
    if _COMMIT_RE.search(prompt):
        return _COMMIT_NOTE
    if _REVIEW_RE.search(prompt):
        return _REVIEW_NOTE
    return ""


def main() -> int:
    note = _additional_context(_prompt(_payload()))
    if not note:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": note,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

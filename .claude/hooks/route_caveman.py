#!/usr/bin/env python3
"""UserPromptSubmit hook: inject concise workflow routing notes.

The hook never blocks. It routes commit/review requests to Caveman, explicit
adversarial reviews to the lean reviewer, and roadmap implementation prompts
to the single-PR workflow.
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
    r"ready for review|stopping for review|review before (?:commit|committing)|"
    r"caveman-review|revisiona(?:re)?\s+(?:la|il)\s+pr)\b",
    re.IGNORECASE,
)
_ADVERSARIAL_RE = re.compile(
    r"\b(adversarial review|analytical review|pre-commit review|"
    r"review avversaria|revisione avversaria|analytical review sub-agent)\b",
    re.IGNORECASE,
)
_ROADMAP_ACTION = (
    r"(?:start|continue|resume|implement|ship|proceed|go\s+ahead|kick\s+off|"
    r"avvia|avviare|continua|continuare|implementa|procedi|inizia|vai\s+avanti)"
)
_ROADMAP_PR = r"(?:PR[-\s]?\d+|H[0-7]|E[01])"
_ROADMAP_RE = re.compile(
    rf"\b{_ROADMAP_ACTION}\b.{{0,80}}\b{_ROADMAP_PR}\b|"
    rf"\b{_ROADMAP_PR}\b.{{0,80}}\b{_ROADMAP_ACTION}\b",
    re.IGNORECASE,
)

_COMMIT_NOTE = (
    "The user is asking about a commit. Use the `caveman-commit` skill to "
    "draft the message in Conventional Commits format (subject <= 50 chars; "
    "body only when the why is non-obvious). If the user already authored a "
    "verbatim message, use it as-is."
)
_REVIEW_NOTE = (
    "The user is asking for a code review. Use the `caveman-review` skill: "
    "ultra-compressed one-line comments (location, problem, fix). Skip "
    "celebratory noise."
)
_ADVERSARIAL_NOTE = (
    "The user explicitly requested adversarial analysis. Delegate once to "
    "`lean-adversarial-reviewer`, keep its probe budget, then use "
    "`caveman-review` to report only reproducible blockers and later-scope items."
)
_ROADMAP_NOTE = (
    "The user is starting or continuing one numbered roadmap item. Use the "
    "`ship-roadmap-pr` skill: one PR only, conditional lean adversarial review, "
    "no bonus refactors, one final full gate, and stop before commit unless "
    "the user explicitly authorized committing."
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
    if _ADVERSARIAL_RE.search(prompt):
        return _ADVERSARIAL_NOTE
    if _ROADMAP_RE.search(prompt):
        return _ROADMAP_NOTE
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

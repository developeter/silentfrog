#!/usr/bin/env python3
"""Stop hook: remind the user to /caveman-commit when staged changes are pending.

Fires when the session is about to stop. We never block — we only
emit a one-line systemMessage so the user notices uncommitted work.
"""
from __future__ import annotations

import json
import subprocess
import sys


def _has_staged_changes() -> bool:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    # git diff --cached --quiet returns 1 when there ARE staged changes,
    # 0 when the index is clean.
    return result.returncode == 1


def main() -> int:
    if not _has_staged_changes():
        return 0
    print(
        json.dumps(
            {
                "systemMessage": (
                    "Staged changes detected — consider running the "
                    "`caveman-commit` skill before exiting."
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

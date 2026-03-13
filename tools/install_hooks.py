from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    hooks_path = repo_root / ".githooks"
    if not hooks_path.is_dir():
        print(f"Missing hooks directory: {hooks_path}", file=sys.stderr)
        return 1
    cmd = ["git", "config", "core.hooksPath", str(hooks_path)]
    completed = subprocess.run(cmd, cwd=repo_root, check=False)
    if completed.returncode:
        print("Failed to configure git hooks path.", file=sys.stderr)
        return completed.returncode
    print(f"Git hooks configured: {hooks_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

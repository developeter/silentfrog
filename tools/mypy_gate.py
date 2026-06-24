"""Per-module mypy gate (H5 ramp).

mypy over the whole package still reports ~200 errors, so the gate runs only
on an explicit allowlist of already-clean, non-GUI domain modules and
requires ZERO errors. ``--follow-imports=silent`` type-checks the
allowlisted modules' dependencies without reporting their errors, so
unrelated type debt never blocks this gate.

Ramp rule: ADD a module here only once it is mypy-clean. The tolerated error
budget for allowlisted modules is zero, so it can only shrink as the list
grows. GUI modules are deliberately last and out of scope for this ramp.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Already mypy-clean non-GUI domain modules (verified under the project mypy
# config). Keep alphabetical; expand only with modules that already pass.
ALLOWLIST: tuple[str, ...] = (
    "src/silentfrog/audit_issues.py",
    "src/silentfrog/crawl_options.py",
    "src/silentfrog/crawl_run_repository.py",
    "src/silentfrog/crawl_store.py",
    "src/silentfrog/frontier.py",
    "src/silentfrog/research_evidence.py",
    "src/silentfrog/robots_matcher.py",
    "src/silentfrog/robots_simulator.py",
    "src/silentfrog/update_trust.py",
)

# Scope error reporting to the allowlist; dependencies are followed silently.
MYPY_GATE_FLAGS: tuple[str, ...] = ("--follow-imports=silent",)


class AllowlistError(RuntimeError):
    pass


def gate_targets() -> list[str]:
    """Allowlist paths, validated to exist so a rename cannot silently drop a
    module from the gate."""
    missing = [rel for rel in ALLOWLIST if not (_REPO_ROOT / rel).is_file()]
    if missing:
        raise AllowlistError("mypy allowlist points at missing files: " + ", ".join(missing))
    return list(ALLOWLIST)


def gate_command(mypy_invocation: Sequence[str]) -> list[str]:
    """Compose ``<mypy_invocation> --follow-imports=silent <allowlist...>``."""
    return [*mypy_invocation, *MYPY_GATE_FLAGS, *gate_targets()]


def main() -> int:
    cmd = gate_command([sys.executable, "-m", "mypy"])
    print(f"[mypy-gate] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=_REPO_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

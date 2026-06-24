"""Deterministic dependency-policy gate (H5 / AGENTS.md §4.5).

No network: a PyPI release-age check would be flaky, so the ">=48h old"
verification stays a release-time human step. This gate enforces only what is
decidable offline and never flaky:

  * the base (install-time) runtime dependency set is frozen to an approved
    allowlist — a NEW base dependency fails the gate until it is explicitly
    approved here. That is the "zero new base deps without sign-off" rule;
    heavy/optional deps must live in extras, not the base set;
  * poetry.lock exists and is committed (tracked by git).

It does not check versions or extras content, so routine version bumps and
new extras never trip it.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Approved base runtime dependencies. Adding a name here is the deliberate
# sign-off the supply-chain rule requires; keep it in sync with the base set in
# pyproject.toml's [project.dependencies] (extras are intentionally excluded).
APPROVED_BASE_DEPENDENCIES: frozenset[str] = frozenset(
    {
        "pyside6",
        "qtpy",
        "numpy",
        "pandas",
        "urllib3",
        "requests",
        "openpyxl",
        "httpx",
        "beautifulsoup4",
        "lxml",
        "html5lib",
        "tldextract",
        "xlsxwriter",
        "aiohttp",
        "certifi",
        "nltk",
        "pillow",
        "humanize",
        "extruct",
        "w3lib",
    }
)

_NAME_BOUNDARY = re.compile(r"[ \[(<>=!~;]")


def canonical_name(requirement: str) -> str:
    """PEP 503-normalized distribution name from a PEP 508 requirement string."""
    head = _NAME_BOUNDARY.split(requirement.strip(), 1)[0]
    return re.sub(r"[-_.]+", "-", head).lower()


def base_dependency_names(pyproject_text: str) -> set[str]:
    data = tomllib.loads(pyproject_text)
    deps = data.get("project", {}).get("dependencies", [])
    return {canonical_name(dep) for dep in deps}


def unapproved_dependencies(names: set[str], approved: frozenset[str]) -> set[str]:
    return names - approved


def _lock_violations(repo_root: Path) -> list[str]:
    lock = repo_root / "poetry.lock"
    if not lock.is_file():
        return ["poetry.lock is missing — commit the lock alongside dependency changes"]
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "poetry.lock"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return []  # git unavailable: cannot verify tracking, lock file is present
    if tracked.returncode != 0:
        return ["poetry.lock exists but is not tracked by git — commit it"]
    return []


def policy_violations(repo_root: Path) -> list[str]:
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    unapproved = unapproved_dependencies(base_dependency_names(text), APPROVED_BASE_DEPENDENCIES)
    violations: list[str] = []
    if unapproved:
        names = ", ".join(sorted(unapproved))
        violations.append(
            f"unapproved base dependency: {names}. Move it to an extra, or approve it in "
            "tools/dependency_policy.py (APPROVED_BASE_DEPENDENCIES) once it clears §4.5."
        )
    violations.extend(_lock_violations(repo_root))
    return violations


def main() -> int:
    violations = policy_violations(_REPO_ROOT)
    if violations:
        for violation in violations:
            print(f"[dep-policy] FAIL: {violation}")
        return 1
    print("[dep-policy] OK: base deps approved, poetry.lock tracked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

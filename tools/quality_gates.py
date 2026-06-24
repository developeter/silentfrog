"""Run all v1.1 quality gates in order.

Order matches docs/geo_roadmap.md v1.1 §N3b plus the §4.5
supply-chain check:

    0. poetry lock --check           (lock-file drift)
    1. dependency-policy             (approved base deps + lock tracked)
    2. ruff check                    (lint)
    3. ruff format --check           (format drift)
    4. mypy (allowlist)              (H5 per-module ramp, zero errors)
    5. pytest --cov=src/silentfrog    (test + coverage XML)
    6. diff-cover --fail-under=85    (per-touched-file coverage)

Returns 0 only when every step exits 0.

Invoked from tools/doctor.py after the existing test-run step, and
from .github/workflows/code-review.yml on every pull request.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COVERAGE_XML = _REPO_ROOT / "coverage.xml"
_DEFAULT_COMPARE_BRANCH = "origin/dev"
_DEFAULT_COVERAGE_THRESHOLD = 85

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools import mypy_gate  # noqa: E402


@dataclass(frozen=True)
class GateResult:
    name: str
    exit_code: int
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _run(name: str, cmd: list[str], cwd: Path) -> GateResult:
    print(f"[gate] {name}: {' '.join(cmd)}")
    import time

    start = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=cwd, check=False)
        code = result.returncode
    except FileNotFoundError as exc:
        print(f"[gate] {name}: executable not found ({exc})")
        code = 127
    duration = time.monotonic() - start
    status = "OK" if code == 0 else f"FAIL ({code})"
    print(f"[gate] {name}: {status} in {duration:.1f}s")
    return GateResult(name=name, exit_code=code, duration_s=duration)


def _poetry_lock_check(cwd: Path) -> GateResult:
    # `poetry check --lock` replaced `poetry lock --check` in 2.x.
    # Fall back to the older flag when running against an older poetry.
    return _run("poetry lock-check", ["poetry", "check", "--lock"], cwd)


def _ruff_check(cwd: Path) -> GateResult:
    return _run(
        "ruff check",
        ["poetry", "run", "ruff", "check", "src/", "tests/", "tools/", ".claude/hooks/"],
        cwd,
    )


def _ruff_format_check(cwd: Path) -> GateResult:
    return _run(
        "ruff format --check",
        [
            "poetry",
            "run",
            "ruff",
            "format",
            "--check",
            "src/",
            "tests/",
            "tools/",
            ".claude/hooks/",
        ],
        cwd,
    )


def _mypy(cwd: Path) -> GateResult:
    # H5: per-module allowlist (tools/mypy_gate.py), not the whole package —
    # only already-clean non-GUI domain modules, enforced at zero errors.
    return _run("mypy (allowlist)", mypy_gate.gate_command(["poetry", "run", "mypy"]), cwd)


def _dependency_policy(cwd: Path) -> GateResult:
    # Deterministic supply-chain gate (tools/dependency_policy.py): approved
    # base-dep set + poetry.lock tracked. stdlib-only, so run it directly.
    return _run("dependency-policy", [sys.executable, "tools/dependency_policy.py"], cwd)


def _pytest_with_coverage(cwd: Path) -> GateResult:
    return _run(
        "pytest + coverage",
        [
            "poetry",
            "run",
            "pytest",
            "-q",
            "--cov=src/silentfrog",
            "--cov-report=xml",
            "--cov-report=term-missing:skip-covered",
        ],
        cwd,
    )


def _diff_cover(cwd: Path, compare_branch: str, threshold: int) -> GateResult:
    if not _COVERAGE_XML.is_file():
        print("[gate] diff-cover: coverage.xml not found — pytest step must run first")
        return GateResult(name="diff-cover", exit_code=1, duration_s=0.0)
    return _run(
        "diff-cover",
        [
            "poetry",
            "run",
            "diff-cover",
            str(_COVERAGE_XML),
            f"--compare-branch={compare_branch}",
            f"--fail-under={threshold}",
        ],
        cwd,
    )


def _skip_diff_cover_on_first_run(cwd: Path, compare_branch: str) -> bool:
    """diff-cover is meaningless without a known compare branch.

    On a freshly cloned shallow CI checkout or before the first push
    to origin/dev the compare branch may not exist. In that case we
    skip diff-cover (rather than fail) and log it.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", compare_branch],
            cwd=cwd,
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return True
    if result.returncode != 0:
        print(f"[gate] diff-cover: compare branch {compare_branch} not found locally — skipping")
        return True
    return False


@dataclass
class GateConfig:
    skip_diff_cover: bool = False
    compare_branch: str = _DEFAULT_COMPARE_BRANCH
    coverage_threshold: int = _DEFAULT_COVERAGE_THRESHOLD


def run_gates(cwd: Path, config: GateConfig) -> list[GateResult]:
    # H5: the mypy step is the per-module allowlist gate — always on (it is
    # fast and zero-error scoped), so there is no transitional skip flag.
    results: list[GateResult] = [
        _poetry_lock_check(cwd),
        _dependency_policy(cwd),
        _ruff_check(cwd),
        _ruff_format_check(cwd),
        _mypy(cwd),
        _pytest_with_coverage(cwd),
    ]
    if config.skip_diff_cover or _skip_diff_cover_on_first_run(cwd, config.compare_branch):
        print("[gate] diff-cover: SKIPPED")
    else:
        results.append(_diff_cover(cwd, config.compare_branch, config.coverage_threshold))
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-diff-cover", action="store_true", help="skip the per-file coverage gate")
    parser.add_argument(
        "--compare-branch",
        default=_DEFAULT_COMPARE_BRANCH,
        help=f"branch diff-cover compares against (default: {_DEFAULT_COMPARE_BRANCH})",
    )
    parser.add_argument(
        "--coverage-threshold",
        type=int,
        default=_DEFAULT_COVERAGE_THRESHOLD,
        help=f"diff-cover --fail-under value (default: {_DEFAULT_COVERAGE_THRESHOLD})",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = GateConfig(
        skip_diff_cover=args.skip_diff_cover,
        compare_branch=args.compare_branch,
        coverage_threshold=args.coverage_threshold,
    )

    if shutil.which("poetry") is None:
        print("[gate] poetry not on PATH — quality gates require Poetry to run.")
        return 1

    results = run_gates(_REPO_ROOT, config)

    failed = [r for r in results if not r.ok]
    summary = ", ".join(f"{r.name}={'OK' if r.ok else 'FAIL'}" for r in results)
    print(f"\n[gate] summary: {summary}")
    if failed:
        print(f"[gate] FAIL: {len(failed)} of {len(results)} gates failed")
        return 1
    print(f"[gate] OK: {len(results)} gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

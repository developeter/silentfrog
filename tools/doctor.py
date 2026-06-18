from __future__ import annotations

import argparse
import importlib.resources as resources
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.source_install import installer_paths  # noqa: E402

MIN_PYTHON = (3, 12)
POETRY_REQUIRED_IMPORTS = (
    "PyQt5",
    "pandas",
    "requests",
    "bs4",
    "lxml",
    "xlsxwriter",
    "aiohttp",
    "humanize",
)
# Import names provided by the runtime distributions declared in pyproject.toml.
# Distribution name → import name only differs for these entries; keep them paired
# with comments so a refresh after a dep change stays an easy two-line edit.
VENV_REQUIRED_IMPORTS = (
    "PySide6",  # pyside6
    "qtpy",
    "numpy",
    "pandas",
    "urllib3",
    "requests",
    "openpyxl",
    "httpx",
    "bs4",  # beautifulsoup4
    "lxml",
    "html5lib",
    "tldextract",
    "xlsxwriter",
    "aiohttp",
    "certifi",
    "nltk",
    "PIL",  # pillow
    "humanize",
)
REQUIRED_PATHS = (
    Path("src/silentfrog/assets/icon.png"),
    Path("src/silentfrog/assets/icon.ico"),
    Path("src/silentfrog/resources/stopwords_en.txt"),
    Path("src/silentfrog/resources/stopwords_it.txt"),
    Path("src/silentfrog/resources/stopwords_es.txt"),
    Path("src/silentfrog/resources/stopwords_fr.txt"),
)
REQUIRED_PACKAGE_FILES = (
    "assets/icon.png",
    "assets/icon.ico",
    "resources/stopwords_en.txt",
    "resources/stopwords_it.txt",
    "resources/stopwords_es.txt",
    "resources/stopwords_fr.txt",
)
QUICK_TESTS = (
    "tests/test_sanity.py",
    "tests/test_module_splits.py",
    "tests/test_crawl_options.py",
)


@dataclass(frozen=True)
class DoctorTarget:
    label: str
    python: Path
    required_imports: tuple[str, ...]
    run_tests: bool


class DoctorError(RuntimeError):
    pass


def _run(cmd: list[str], label: str, env: dict[str, str] | None = None) -> None:
    print(f"[doctor] {label}: {' '.join(str(part) for part in cmd)}")
    completed = subprocess.run(cmd, check=False, env=env)
    if completed.returncode:
        raise DoctorError(f"{label} failed with exit code {completed.returncode}.")


def _check_python() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        min_version = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        raise DoctorError(f"Python {min_version}+ required, current interpreter is {current}.")
    current = ".".join(str(part) for part in sys.version_info[:3])
    print(f"[doctor] Python OK: {current}")


def _check_paths() -> None:
    missing = [str(path) for path in REQUIRED_PATHS if not path.exists()]
    if missing:
        joined = "\n - ".join(missing)
        raise DoctorError(f"Missing required project files:\n - {joined}")
    print("[doctor] Project files OK")


def _check_imports_via(python: Path, modules: tuple[str, ...], label: str) -> None:
    if not python.is_file():
        raise DoctorError(f"{label}: interpreter not found at {python}.")
    code = "\n".join(f"import {name}" for name in modules)
    completed = subprocess.run([str(python), "-c", code], check=False, capture_output=True, text=True)
    if completed.returncode:
        raise DoctorError(f"{label}: missing or broken dependencies.\n  stderr: {completed.stderr.strip()}")
    print(f"[doctor] Dependency imports OK ({label})")


def _check_packaged_files() -> None:
    try:
        package_root = resources.files("silentfrog")
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise DoctorError(f"Unable to resolve package resources: {exc!r}") from exc
    missing = [rel_path for rel_path in REQUIRED_PACKAGE_FILES if not package_root.joinpath(rel_path).is_file()]
    if missing:
        joined = "\n - ".join(missing)
        raise DoctorError(f"Missing files in package resources:\n - {joined}")
    print("[doctor] Package resources OK")


def _run_compile_check() -> None:
    _run([sys.executable, "-m", "compileall", "-q", "src"], "Compile check")


def _run_code_shape_check() -> None:
    _run([sys.executable, "tools/code_shape_guard.py"], "Code-shape guard")


def _run_tests(quick: bool) -> None:
    pytest_cmd = [sys.executable, "-m", "pytest", "-q"]
    if quick:
        pytest_cmd.extend(QUICK_TESTS)
    _run(pytest_cmd, "Test run")


def _run_ruff_quick() -> None:
    """v1.1 N3b: --quick mode runs ruff check only (no format, no mypy)."""
    _run([sys.executable, "-m", "ruff", "check", "--quiet", "src/", "tests/", "tools/"], "Ruff quick")


def _run_quality_gates(skip_diff_cover: bool) -> None:
    """v1.1 N3b: full mode runs the whole gate orchestrator after tests."""
    cmd = [sys.executable, "tools/quality_gates.py", "--skip-mypy"]
    if skip_diff_cover:
        cmd.append("--skip-diff-cover")
    _run(cmd, "Quality gates")


def doctor_targets_for_mode(mode: str, repo_root: Path) -> tuple[DoctorTarget, ...]:
    poetry = DoctorTarget(
        label="poetry",
        python=Path(sys.executable),
        required_imports=POETRY_REQUIRED_IMPORTS,
        run_tests=True,
    )
    venv = DoctorTarget(
        label="venv",
        python=installer_paths(repo_root).python,
        required_imports=VENV_REQUIRED_IMPORTS,
        run_tests=False,
    )
    by_mode = {
        "poetry": (poetry,),
        "venv": (venv,),
        "both": (poetry, venv),
    }
    if mode not in by_mode:
        raise DoctorError(f"Unknown doctor mode: {mode}")
    return by_mode[mode]


@dataclass(frozen=True)
class DoctorRunRequest:
    """Typed inputs to :func:`plan_doctor_run` — a config object instead of
    boolean-flag-soup parameters (AGENTS.md §1)."""

    skip_tests: bool
    skip_gates: bool
    quick: bool
    mode: str
    any_target_runs_tests: bool


@dataclass(frozen=True)
class DoctorRunPlan:
    """Which test/gate steps ``main()`` runs for one CLI invocation.

    pytest is executed by BOTH the standalone test step and the full
    quality gates (``tools/quality_gates.py``); ruff-quick does not run it.
    ``pytest_runs`` must never exceed 1 — that double run was the bug this
    plan exists to prevent.
    """

    run_standalone_tests: bool
    run_ruff_quick: bool
    run_full_gates: bool

    @property
    def pytest_runs(self) -> int:
        return int(self.run_standalone_tests) + int(self.run_full_gates)


def plan_doctor_run(request: DoctorRunRequest) -> DoctorRunPlan:
    """Pure dispatch decision for ``main()``.

    The full (non-quick) gates run pytest+coverage themselves, so the
    standalone pytest step is suppressed whenever they will run — the two
    are never combined.
    """
    if request.skip_tests:
        return DoctorRunPlan(False, False, False)
    gates_enabled = not request.skip_gates and request.mode != "venv"
    run_full_gates = gates_enabled and not request.quick
    run_ruff_quick = gates_enabled and request.quick
    run_standalone_tests = request.any_target_runs_tests and not run_full_gates
    return DoctorRunPlan(run_standalone_tests, run_ruff_quick, run_full_gates)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Silentfrog doctor: dependency, resource, compile and test checks.")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Run environment checks only, skip pytest.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a small smoke test set instead of the full test suite.",
    )
    parser.add_argument(
        "--mode",
        choices=("poetry", "venv", "both"),
        default="poetry",
        help="Where to look for runtime dependencies. 'venv' validates the installer-produced .venv.",
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        help="Skip the v1.1 N3b quality_gates step (ruff/mypy/coverage). Used by venv-only doctor flows.",
    )
    parser.add_argument(
        "--skip-diff-cover",
        action="store_true",
        help="Skip the per-touched-file coverage gate (useful on fresh clones without origin/dev).",
    )
    return parser


def _run_target_checks(target: DoctorTarget) -> None:
    _check_imports_via(target.python, target.required_imports, label=target.label)


def main() -> int:
    args = _build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        _check_python()
        _check_paths()
        targets = doctor_targets_for_mode(args.mode, repo_root)
        for target in targets:
            _run_target_checks(target)
        _check_packaged_files()
        _run_code_shape_check()
        _run_compile_check()
        plan = plan_doctor_run(
            DoctorRunRequest(
                skip_tests=args.skip_tests,
                skip_gates=args.skip_gates,
                quick=args.quick,
                mode=args.mode,
                any_target_runs_tests=any(target.run_tests for target in targets),
            )
        )
        if plan.run_standalone_tests:
            _run_tests(quick=args.quick)
        # v1.1 N3b — quality gates. The full set runs pytest+coverage itself,
        # so it is never combined with the standalone test run above.
        if plan.run_full_gates:
            _run_quality_gates(skip_diff_cover=args.skip_diff_cover)
        elif plan.run_ruff_quick:
            _run_ruff_quick()
    except DoctorError as exc:
        print(f"[doctor] FAIL: {exc}", file=sys.stderr)
        return 1
    print("[doctor] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

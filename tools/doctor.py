from __future__ import annotations

import argparse
import importlib
import importlib.resources as resources
import subprocess
import sys
from pathlib import Path


MIN_PYTHON = (3, 12)
REQUIRED_IMPORTS = (
    "PyQt5",
    "pandas",
    "requests",
    "bs4",
    "lxml",
    "xlsxwriter",
    "aiohttp",
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


class DoctorError(RuntimeError):
    pass


def _run(cmd: list[str], label: str, env: dict[str, str] | None = None) -> None:
    print(f"[doctor] {label}: {' '.join(cmd)}")
    completed = subprocess.run(cmd, check=False, env=env)
    if completed.returncode:
        raise DoctorError(f"{label} failed with exit code {completed.returncode}.")


def _check_python() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        min_version = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        raise DoctorError(
            f"Python {min_version}+ required, current interpreter is {current}."
        )
    current = ".".join(str(part) for part in sys.version_info[:3])
    print(f"[doctor] Python OK: {current}")


def _check_paths() -> None:
    missing = [str(path) for path in REQUIRED_PATHS if not path.exists()]
    if missing:
        joined = "\n - ".join(missing)
        raise DoctorError(f"Missing required project files:\n - {joined}")
    print("[doctor] Project files OK")


def _check_imports() -> None:
    failures: list[str] = []
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - diagnostic path
            failures.append(f"{module_name}: {exc!r}")
    if failures:
        joined = "\n - ".join(failures)
        raise DoctorError(f"Missing or broken dependencies:\n - {joined}")
    print("[doctor] Dependency imports OK")


def _check_packaged_files() -> None:
    try:
        package_root = resources.files("silentfrog")
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise DoctorError(f"Unable to resolve package resources: {exc!r}") from exc
    missing = [
        rel_path
        for rel_path in REQUIRED_PACKAGE_FILES
        if not package_root.joinpath(rel_path).is_file()
    ]
    if missing:
        joined = "\n - ".join(missing)
        raise DoctorError(f"Missing files in package resources:\n - {joined}")
    print("[doctor] Package resources OK")


def _run_compile_check() -> None:
    _run([sys.executable, "-m", "compileall", "-q", "src"], "Compile check")


def _run_tests(quick: bool) -> None:
    pytest_cmd = [sys.executable, "-m", "pytest", "-q"]
    if quick:
        pytest_cmd.extend(QUICK_TESTS)
    _run(pytest_cmd, "Test run")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Silentfrog doctor: dependency, resource, compile and test checks."
    )
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
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        _check_python()
        _check_paths()
        _check_imports()
        _check_packaged_files()
        _run_compile_check()
        if not args.skip_tests:
            _run_tests(quick=args.quick)
    except DoctorError as exc:
        print(f"[doctor] FAIL: {exc}", file=sys.stderr)
        return 1
    print("[doctor] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

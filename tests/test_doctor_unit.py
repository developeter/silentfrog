from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.doctor import (
    DoctorError,
    POETRY_REQUIRED_IMPORTS,
    VENV_REQUIRED_IMPORTS,
    _build_parser,
    _check_imports_via,
    doctor_targets_for_mode,
)


def test_doctor_targets_for_mode_poetry(tmp_path: Path) -> None:
    targets = doctor_targets_for_mode("poetry", tmp_path)
    assert len(targets) == 1
    assert targets[0].label == "poetry"
    assert targets[0].python == Path(sys.executable)
    assert targets[0].required_imports == POETRY_REQUIRED_IMPORTS
    assert targets[0].run_tests is True


def test_doctor_targets_for_mode_venv(tmp_path: Path) -> None:
    targets = doctor_targets_for_mode("venv", tmp_path)
    assert len(targets) == 1
    assert targets[0].label == "venv"
    assert targets[0].python == tmp_path / ".venv" / "bin" / "python"
    assert targets[0].required_imports == VENV_REQUIRED_IMPORTS
    assert targets[0].run_tests is False


def test_doctor_targets_for_mode_both_runs_poetry_then_venv(tmp_path: Path) -> None:
    targets = doctor_targets_for_mode("both", tmp_path)
    assert tuple(target.label for target in targets) == ("poetry", "venv")


def test_doctor_targets_for_mode_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(DoctorError, match="Unknown doctor mode"):
        doctor_targets_for_mode("nope", tmp_path)


def test_check_imports_via_missing_python(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "python"
    with pytest.raises(DoctorError, match="interpreter not found"):
        _check_imports_via(missing, ("sys",), label="probe")


def test_check_imports_via_succeeds_with_stdlib_module() -> None:
    # The current Python is guaranteed to be able to import sys/os/pathlib.
    _check_imports_via(Path(sys.executable), ("sys", "os", "pathlib"), label="probe")


def test_check_imports_via_raises_on_missing_module() -> None:
    with pytest.raises(DoctorError, match="missing or broken"):
        _check_imports_via(Path(sys.executable), ("__definitely_not_a_module__",), label="probe")


def test_build_parser_accepts_mode_argument() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--mode", "venv", "--skip-tests"])
    assert args.mode == "venv"
    assert args.skip_tests is True
    args = parser.parse_args([])
    assert args.mode == "poetry"


def test_venv_required_imports_includes_pyside6_and_not_pyqt5() -> None:
    assert "PySide6" in VENV_REQUIRED_IMPORTS
    assert "PyQt5" not in VENV_REQUIRED_IMPORTS

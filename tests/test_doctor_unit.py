from __future__ import annotations

import itertools
import platform
import sys
from pathlib import Path

import pytest


def _expected_venv_python(repo_root: Path) -> Path:
    if platform.system().lower().startswith("win"):
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.doctor import (
    POETRY_REQUIRED_IMPORTS,
    VENV_REQUIRED_IMPORTS,
    DoctorError,
    DoctorRunRequest,
    _build_parser,
    _check_imports_via,
    doctor_targets_for_mode,
    plan_doctor_run,
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
    assert targets[0].python == _expected_venv_python(tmp_path)
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


# PR-0/E0 regression: the doctor must never run pytest twice. The full
# (non-quick) gates run pytest+coverage themselves, so the standalone test
# step must be suppressed in that path.


def _req(
    *,
    skip_tests=False,
    skip_gates=False,
    quick=False,
    mode="poetry",
    any_target_runs_tests=True,
) -> DoctorRunRequest:
    # Unannotated params on purpose: keeps each test expressing only the flag
    # under test, and avoids tripping the bool-arg shape guard on the helper.
    return DoctorRunRequest(
        skip_tests=skip_tests,
        skip_gates=skip_gates,
        quick=quick,
        mode=mode,
        any_target_runs_tests=any_target_runs_tests,
    )


def test_plan_default_full_mode_runs_pytest_once_via_gates() -> None:
    plan = plan_doctor_run(_req())
    assert plan.run_full_gates is True
    assert plan.run_standalone_tests is False
    assert plan.run_ruff_quick is False
    assert plan.pytest_runs == 1


def test_plan_quick_mode_runs_pytest_once_via_standalone() -> None:
    plan = plan_doctor_run(_req(quick=True))
    assert plan.run_standalone_tests is True
    assert plan.run_ruff_quick is True
    assert plan.run_full_gates is False
    assert plan.pytest_runs == 1


def test_plan_skip_gates_runs_standalone_only() -> None:
    plan = plan_doctor_run(_req(skip_gates=True))
    assert plan.run_standalone_tests is True
    assert plan.run_full_gates is False
    assert plan.run_ruff_quick is False
    assert plan.pytest_runs == 1


def test_plan_venv_mode_runs_no_pytest() -> None:
    # venv targets carry run_tests=False and gates are disabled in venv mode.
    plan = plan_doctor_run(_req(mode="venv", any_target_runs_tests=False))
    assert plan.run_standalone_tests is False
    assert plan.run_full_gates is False
    assert plan.run_ruff_quick is False
    assert plan.pytest_runs == 0


def test_plan_skip_tests_runs_nothing() -> None:
    plan = plan_doctor_run(_req(skip_tests=True))
    assert plan.pytest_runs == 0
    assert plan.run_ruff_quick is False
    assert plan.run_full_gates is False


def test_plan_never_runs_pytest_twice_across_all_flag_combinations() -> None:
    bools = (False, True)
    for skip_tests, skip_gates, quick, any_tests in itertools.product(bools, bools, bools, bools):
        for mode in ("poetry", "venv", "both"):
            plan = plan_doctor_run(
                _req(
                    skip_tests=skip_tests,
                    skip_gates=skip_gates,
                    quick=quick,
                    mode=mode,
                    any_target_runs_tests=any_tests,
                )
            )
            assert plan.pytest_runs <= 1, (
                f"double pytest run: skip_tests={skip_tests} skip_gates={skip_gates} "
                f"quick={quick} mode={mode} any_tests={any_tests}"
            )
            # ruff-quick and the full gates are mutually exclusive.
            assert not (plan.run_ruff_quick and plan.run_full_gates)

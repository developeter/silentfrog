"""Smoke tests for tools.quality_gates.

The individual gate commands shell out to poetry/ruff/mypy/etc., so
the unit tests stub `subprocess.run` and assert on the orchestrator
logic only. Smoke-only — we trust the underlying tools.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.quality_gates import (  # noqa: E402
    GateConfig,
    GateResult,
    _skip_diff_cover_on_first_run,
    run_gates,
)


def _stub_run(monkeypatch, exit_codes: list[int]) -> list[list[str]]:
    """Replace subprocess.run with a stub that yields ``exit_codes`` in order."""
    captured: list[list[str]] = []
    seq = iter(exit_codes)

    def _fake_run(cmd, cwd=None, check=False, capture_output=False):
        captured.append(list(cmd))
        try:
            code = next(seq)
        except StopIteration:
            code = 0
        return MagicMock(returncode=code, stdout=b"", stderr=b"")

    monkeypatch.setattr("tools.quality_gates.subprocess.run", _fake_run)
    return captured


def test_run_gates_all_pass(monkeypatch, tmp_path) -> None:
    # 0=lock, 1=dep-policy, 2=ruff check, 3=ruff format, 4=mypy, 5=pytest,
    # 6=git rev-parse (diff-cover branch lookup), 7=diff-cover
    captured = _stub_run(monkeypatch, [0, 0, 0, 0, 0, 0, 0, 0])
    # coverage.xml stub so the diff-cover step runs
    monkeypatch.setattr("tools.quality_gates._COVERAGE_XML", tmp_path / "coverage.xml")
    (tmp_path / "coverage.xml").write_text("<coverage/>", encoding="utf-8")

    results = run_gates(tmp_path, GateConfig())

    # Every invocable gate ran; the git rev-parse call ALSO went through the
    # stub but it isn't a "gate" — confirm the H5 gates are present and on.
    names = [r.name for r in results]
    assert "poetry lock-check" in names
    assert "dependency-policy" in names
    assert "ruff check" in names
    assert "ruff format --check" in names
    assert "mypy (allowlist)" in names  # H5 mypy gate is always on
    assert "pytest + coverage" in names
    assert "diff-cover" in names
    assert all(r.ok for r in results)
    # First command must be poetry lock-check.
    assert captured[0][:2] == ["poetry", "check"]
    assert captured[0][2] == "--lock"


def test_run_gates_first_failure_propagates(monkeypatch, tmp_path) -> None:
    # ruff check (3rd gate, after lock + dependency-policy) fails.
    _stub_run(monkeypatch, [0, 0, 1, 0, 0, 0, 0, 0])
    monkeypatch.setattr("tools.quality_gates._COVERAGE_XML", tmp_path / "coverage.xml")
    (tmp_path / "coverage.xml").write_text("<coverage/>", encoding="utf-8")

    results = run_gates(tmp_path, GateConfig())

    failed = [r for r in results if not r.ok]
    assert len(failed) == 1
    assert failed[0].name == "ruff check"


def test_skip_diff_cover_when_compare_branch_missing(monkeypatch, tmp_path) -> None:
    # git rev-parse returns non-zero -> diff-cover skipped.
    def _fake_run(cmd, cwd=None, check=False, capture_output=False):
        return MagicMock(returncode=128, stdout=b"", stderr=b"unknown ref")

    monkeypatch.setattr("tools.quality_gates.subprocess.run", _fake_run)
    assert _skip_diff_cover_on_first_run(tmp_path, "origin/missing-branch") is True


def test_skip_diff_cover_when_git_missing(monkeypatch, tmp_path) -> None:
    def _fake_run(cmd, cwd=None, check=False, capture_output=False):
        raise FileNotFoundError("git")

    monkeypatch.setattr("tools.quality_gates.subprocess.run", _fake_run)
    assert _skip_diff_cover_on_first_run(tmp_path, "origin/dev") is True


def test_gate_result_ok_property() -> None:
    assert GateResult(name="x", exit_code=0, duration_s=0.1).ok is True
    assert GateResult(name="x", exit_code=1, duration_s=0.1).ok is False

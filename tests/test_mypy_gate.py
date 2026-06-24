"""Focused tests for the H5 per-module mypy gate (tools/mypy_gate.py).

These guard the gate's shape, not mypy itself: the allowlist stays non-empty,
non-GUI, points at real files, and the command keeps errors scoped to the
allowlist. The actual zero-error run is a gate step, not a unit test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools import mypy_gate  # noqa: E402


def test_allowlist_non_empty_and_non_gui() -> None:
    assert mypy_gate.ALLOWLIST  # an empty allowlist would make the gate vacuous
    # H5 scope is domain modules; GUI typing is explicitly a later ramp.
    gui = [m for m in mypy_gate.ALLOWLIST if "gui" in Path(m).name.lower()]
    assert gui == []


def test_allowlist_files_exist() -> None:
    missing = [m for m in mypy_gate.ALLOWLIST if not (_REPO_ROOT / m).is_file()]
    assert missing == []


def test_gate_command_scopes_errors_to_allowlist() -> None:
    cmd = mypy_gate.gate_command(["poetry", "run", "mypy"])
    # follow-imports=silent keeps unrelated type debt from blocking the gate.
    assert "--follow-imports=silent" in cmd
    for module in mypy_gate.ALLOWLIST:
        assert module in cmd

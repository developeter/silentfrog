"""Regression guard for PR-0/E0: the test suite must import ``silentfrog``
from the working tree under ``src/`` — not a stale, non-editable copy in
``.venv/site-packages``. If this breaks, coverage silently drops to 0% and
tests stop exercising local edits."""

from __future__ import annotations

from pathlib import Path

import silentfrog


def test_silentfrog_imported_from_src() -> None:
    imported = Path(silentfrog.__file__).resolve().parent
    expected = (Path(__file__).resolve().parent.parent / "src" / "silentfrog").resolve()
    assert imported == expected, f"tests import {imported}, expected {expected} (conftest src-priority broke)"

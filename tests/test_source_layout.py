"""Regression guard for PR-0/E0: the test suite must import ``silentfrog``
from the working tree under ``src/`` — not a stale, non-editable copy in
``.venv/site-packages``. If this breaks, coverage silently drops to 0% and
tests stop exercising local edits."""

from __future__ import annotations

import sys
from pathlib import Path

import silentfrog


def test_silentfrog_imported_from_src() -> None:
    imported = Path(silentfrog.__file__).resolve().parent
    expected = (Path(__file__).resolve().parent.parent / "src" / "silentfrog").resolve()
    assert imported == expected, f"tests import {imported}, expected {expected} (conftest src-priority broke)"


def _first_index(needle: str) -> int:
    """Earliest ``sys.path`` slot whose resolved form ends with ``needle``."""
    matches = (i for i, p in enumerate(sys.path) if p and Path(p).resolve().name == needle)
    return next(matches, -1)


def test_src_precedes_site_packages() -> None:
    """A stray editable install appends src/ *behind* site-packages, which the
    import check above only catches while a stale installed copy still exists.
    Pin the ordering itself so the fragile state is caught either way."""
    src_at = _first_index("src")
    site_at = _first_index("site-packages")
    assert src_at >= 0, "conftest did not put src/ on sys.path"
    assert site_at < 0 or src_at < site_at, f"src/ at {src_at} must precede site-packages at {site_at}"

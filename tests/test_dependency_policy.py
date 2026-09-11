"""Focused tests for the deterministic dependency-policy gate.

The verified risk: a new base runtime dependency slips in without sign-off.
The gate must pass on the current tree and flag any unapproved base dep.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools import dependency_policy  # noqa: E402


def test_canonical_name_strips_extras_and_constraints() -> None:
    assert dependency_policy.canonical_name("httpx[http2] (>=0.28.1,<0.29.0)") == "httpx"
    assert dependency_policy.canonical_name("beautifulsoup4 (>=4.13.4,<5.0.0)") == "beautifulsoup4"


def test_current_base_dependencies_are_all_approved() -> None:
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    names = dependency_policy.base_dependency_names(text)
    unapproved = dependency_policy.unapproved_dependencies(names, dependency_policy.APPROVED_BASE_DEPENDENCIES)
    assert unapproved == set()


def test_unapproved_new_base_dependency_is_flagged() -> None:
    # Reintroducing the defect (an unsanctioned base dep) must be caught.
    names = set(dependency_policy.APPROVED_BASE_DEPENDENCIES) | {"sketchy-new-pkg"}
    flagged = dependency_policy.unapproved_dependencies(names, dependency_policy.APPROVED_BASE_DEPENDENCIES)
    assert flagged == {"sketchy-new-pkg"}


def test_policy_passes_on_current_tree() -> None:
    assert dependency_policy.policy_violations(_REPO_ROOT) == []


def test_keyring_is_an_approved_base_dependency() -> None:
    # user decision 2026-09-11: keyring moved from the semrush/google
    # extras to base so the optional API-key fields are storable on a
    # stock install (no extra required). Regression guard for that move.
    assert "keyring" in dependency_policy.APPROVED_BASE_DEPENDENCIES
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "keyring" in dependency_policy.base_dependency_names(text)

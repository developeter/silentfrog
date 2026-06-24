"""Regression guard for the private security-disclosure policy (H7 / PR-19).

F9 found SECURITY.md directing reporters to a *public* GitHub issue, which
exposes users before a fix ships. PR-19 switched it to GitHub private
vulnerability reporting. This test fails if that regression returns.
"""

from __future__ import annotations

from pathlib import Path

_SECURITY = Path(__file__).resolve().parents[1] / "SECURITY.md"


def test_security_policy_uses_private_reporting() -> None:
    text = _SECURITY.read_text(encoding="utf-8")
    # Collapse markdown line-wrapping so phrase checks survive reflowing.
    flat = " ".join(text.lower().split())
    # The private channel is documented (GitHub private advisory form).
    assert "security/advisories/new" in flat
    assert "report a vulnerability" in flat
    # The fixed defect: never tell reporters to disclose a vuln publicly.
    assert "do not open a public issue" in flat

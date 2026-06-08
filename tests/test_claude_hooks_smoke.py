"""Smoke tests for the project-level Claude Code hooks.

The actual hook process is invoked via ``python <hook>.py`` by the
Claude Code harness; here we exercise the same scripts in-process by
piping a synthetic JSON payload through stdin and inspecting the
JSON output. We do NOT spin up the harness — these are unit tests on
the hook's decision logic.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOK_DIR = _REPO_ROOT / ".claude" / "hooks"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"


def _run_hook(script_name: str, payload: dict) -> dict:
    script = _HOOK_DIR / script_name
    if not script.is_file():
        pytest.skip(f"hook script not available: {script}")
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    body = result.stdout.strip()
    return json.loads(body) if body else {}


def test_settings_json_parses_and_declares_three_events() -> None:
    data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    assert "hooks" in data
    for event in ("PreToolUse", "UserPromptSubmit", "Stop"):
        assert event in data["hooks"], f"missing event: {event}"
        groups = data["hooks"][event]
        assert isinstance(groups, list) and groups
        for group in groups:
            for handler in group.get("hooks", []):
                assert handler["type"] == "command"
                assert handler["command"] == "python"
                args = handler.get("args") or []
                assert any("${CLAUDE_PROJECT_DIR}" in arg for arg in args), (
                    "hook args must reference ${CLAUDE_PROJECT_DIR} so the "
                    "harness resolves them on every machine"
                )


def test_check_bare_commit_blocks_bare_form() -> None:
    payload = {"tool_input": {"command": "git commit"}}
    output = _run_hook("check_bare_commit.py", payload)
    decision = output["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny"
    assert "caveman-commit" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_check_bare_commit_allows_dash_m_with_quoted_message() -> None:
    payload = {"tool_input": {"command": 'git commit -m "feat: thing"'}}
    output = _run_hook("check_bare_commit.py", payload)
    assert output == {}, f"quoted -m must pass through unchanged; got {output}"


def test_check_bare_commit_allows_dash_F_form() -> None:
    payload = {"tool_input": {"command": "git commit -F /tmp/msg.txt"}}
    assert _run_hook("check_bare_commit.py", payload) == {}


def test_check_bare_commit_allows_amend_and_no_edit() -> None:
    payload = {"tool_input": {"command": "git commit --amend --no-edit"}}
    assert _run_hook("check_bare_commit.py", payload) == {}


def test_check_bare_commit_ignores_non_commit_bash() -> None:
    # A bare `git status` should never trigger the deny path.
    payload = {"tool_input": {"command": "git status"}}
    assert _run_hook("check_bare_commit.py", payload) == {}


def test_route_caveman_injects_commit_note() -> None:
    payload = {"prompt": "write a commit message for the diff"}
    output = _run_hook("route_caveman.py", payload)
    note = output["hookSpecificOutput"]["additionalContext"]
    assert "caveman-commit" in note
    assert "Conventional Commits" in note


def test_route_caveman_injects_review_note() -> None:
    payload = {"prompt": "please review this PR end to end"}
    output = _run_hook("route_caveman.py", payload)
    note = output["hookSpecificOutput"]["additionalContext"]
    assert "caveman-review" in note


def test_route_caveman_stays_quiet_on_unrelated_prompts() -> None:
    payload = {"prompt": "explain how Core Web Vitals are measured"}
    assert _run_hook("route_caveman.py", payload) == {}


def test_route_caveman_handles_italian_commit_keyword() -> None:
    # The maintainer often writes prompts in Italian; the regex
    # explicitly covers "scrivi il commit".
    payload = {"prompt": "scrivi il commit message per queste modifiche"}
    output = _run_hook("route_caveman.py", payload)
    assert "caveman-commit" in output["hookSpecificOutput"]["additionalContext"]


def test_staged_changes_reminder_is_silent_when_index_clean(tmp_path, monkeypatch) -> None:
    # The hook runs `git diff --cached --quiet` in $CWD. We can't
    # easily guarantee a clean index on the dev tree, so we point the
    # hook at a tmp git repo we control.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    result = subprocess.run(
        [sys.executable, str(_HOOK_DIR / "staged_changes_reminder.py")],
        input="{}",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_staged_changes_reminder_emits_message_when_index_dirty(tmp_path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    # Configure identity locally so commits inside the repo would work
    # if needed; we only need a staged file for this assertion.
    (tmp_path / "x.txt").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "x.txt"], check=True)
    monkeypatch.chdir(tmp_path)
    result = subprocess.run(
        [sys.executable, str(_HOOK_DIR / "staged_changes_reminder.py")],
        input="{}",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout.strip())
    assert "caveman-commit" in output["systemMessage"]

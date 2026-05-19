"""Update-check domain logic for Silentfrog.

This module is intentionally Qt-free and network-isolated behind a single
async entry point so the rest of the app (and the GUI in
``update_gui.py``) can read it as plain dataclasses + pure functions.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import aiohttp  # type: ignore[import]  # aiohttp stubs missing
from aiohttp import ClientTimeout  # type: ignore[import]  # aiohttp stubs missing


GITHUB_OWNER = "developeter"
GITHUB_REPO = "silentfrog"
UPDATE_BRANCH = "dev"

REVISION_FILE_NAME = ".silentfrog_revision"

_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def commit_api_url(branch: str = UPDATE_BRANCH) -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits/{branch}"


class InstallMode(str, Enum):
    DEVELOPER = "developer"
    USER = "user"
    UNKNOWN = "unknown"


class UpdateStatus(str, Enum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DEV_MODE_USE_GIT = "dev_mode_use_git"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LocalRevision:
    sha: str
    mode: InstallMode
    repo_root: Path


@dataclass(frozen=True)
class RemoteRevision:
    sha: str
    committed_at: datetime
    message: str


def find_repo_root() -> Path:
    """Locate the install root (the directory containing ``pyproject.toml``).

    Walks up from this module's resolved path. Works for both dev
    clones (file lives under ``<repo>/src/silentfrog/``) and user-mode
    installs created by ``install_silentfrog.py`` (file lives under
    ``<repo>/.venv/Lib/site-packages/silentfrog/``, so walking up still
    reaches ``<repo>``).
    """
    here = Path(__file__).resolve()
    for directory in (here.parent, *here.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return here.parent


def read_local_revision(repo_root: Path) -> LocalRevision:
    """Resolve the current install's revision and how it was installed.

    Order of precedence: an explicit ``.silentfrog_revision`` file wins
    (this is how user-mode installs declare their pinned commit). Falling
    back to ``git rev-parse HEAD`` covers the maintainer's own dev
    clones where no revision file is written.
    """
    if (repo_root / ".git").exists():
        sha = _read_git_head(repo_root)
        return LocalRevision(sha=sha, mode=InstallMode.DEVELOPER, repo_root=repo_root)
    revision_file = repo_root / REVISION_FILE_NAME
    if revision_file.is_file():
        sha = revision_file.read_text(encoding="utf-8").strip()
        return LocalRevision(sha=sha, mode=InstallMode.USER, repo_root=repo_root)
    return LocalRevision(sha="", mode=InstallMode.UNKNOWN, repo_root=repo_root)


def _read_git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


async def fetch_remote_revision(
    branch: str = UPDATE_BRANCH,
    timeout_seconds: int = 8,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[RemoteRevision]:
    """Fetch the latest commit on ``branch`` from GitHub.

    Returns ``None`` on any network or parse error so the caller can map
    that into ``UpdateStatus.OFFLINE`` without exception handling
    leaking into the GUI layer.
    """
    url = commit_api_url(branch)
    own_session = session is None
    client = session or aiohttp.ClientSession(headers=_GITHUB_HEADERS)
    try:
        async with client.get(url, timeout=ClientTimeout(total=timeout_seconds)) as response:
            if response.status != 200:
                return None
            payload = await response.text()
    except Exception:
        return None
    finally:
        if own_session:
            await client.close()
    return _parse_commit_payload(payload)


def _parse_commit_payload(payload: str) -> Optional[RemoteRevision]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    sha = data.get("sha")
    commit = data.get("commit") or {}
    author = commit.get("author") or {}
    iso_date = author.get("date")
    message = commit.get("message") or ""
    if not isinstance(sha, str) or not isinstance(iso_date, str):
        return None
    return RemoteRevision(
        sha=sha,
        committed_at=_parse_iso8601_utc(iso_date),
        message=str(message),
    )


def _parse_iso8601_utc(value: str) -> datetime:
    # GitHub commit timestamps are "2026-05-19T08:15:30Z"; ``fromisoformat``
    # in 3.11+ accepts the trailing Z, but we keep the substitution for
    # symmetry with older paths.
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def compare(local: LocalRevision, remote: Optional[RemoteRevision]) -> UpdateStatus:
    if local.mode is InstallMode.DEVELOPER:
        return UpdateStatus.DEV_MODE_USE_GIT
    if remote is None:
        return UpdateStatus.OFFLINE
    if not local.sha:
        return UpdateStatus.UNKNOWN
    if local.sha == remote.sha:
        return UpdateStatus.UP_TO_DATE
    return UpdateStatus.UPDATE_AVAILABLE


def write_revision_file(repo_root: Path, sha: str) -> Path:
    """Persist the active revision for user-mode installs.

    The bootstrap script and ``tools/update_silentfrog`` write this so
    ``read_local_revision`` can answer without invoking git.
    """
    revision_file = repo_root / REVISION_FILE_NAME
    revision_file.write_text(sha.strip() + os.linesep, encoding="utf-8")
    return revision_file

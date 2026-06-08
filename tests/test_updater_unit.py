from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import pytest

from silentfrog.updater import (  # type: ignore[reportMissingImports]
    REVISION_FILE_NAME,
    UPDATE_BRANCH,
    InstallMode,
    LocalRevision,
    RemoteRevision,
    UpdateStatus,
    commit_api_url,
    compare,
    default_ssl_context,
    fetch_remote_revision,
    read_local_revision,
    write_revision_file,
)


def test_default_ssl_context_uses_certifi_bundle() -> None:
    import certifi

    # certifi must ship a non-empty CA file; the SSL context must inherit
    # those CAs so HTTPS to api.github.com works on python.org Framework
    # Python that ships without system CAs.
    assert Path(certifi.where()).is_file()
    ctx = default_ssl_context()
    assert ctx.cert_store_stats()["x509_ca"] > 0


def test_read_local_revision_dev_mode_reads_git_head(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    expected_sha = "abc1234abc1234abc1234abc1234abc1234abc12"

    def fake_run(cmd, cwd, capture_output, text, check):
        assert cmd == ["git", "rev-parse", "HEAD"]
        assert cwd == tmp_path
        return subprocess.CompletedProcess(cmd, 0, stdout=expected_sha + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    local = read_local_revision(tmp_path)
    assert local.mode is InstallMode.DEVELOPER
    assert local.sha == expected_sha
    assert local.repo_root == tmp_path


def test_read_local_revision_user_mode_reads_revision_file(tmp_path: Path) -> None:
    sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    (tmp_path / REVISION_FILE_NAME).write_text(sha + "\n", encoding="utf-8")
    local = read_local_revision(tmp_path)
    assert local.mode is InstallMode.USER
    assert local.sha == sha


def test_read_local_revision_unknown_when_neither_marker_present(tmp_path: Path) -> None:
    local = read_local_revision(tmp_path)
    assert local.mode is InstallMode.UNKNOWN
    assert local.sha == ""


def test_read_local_revision_dev_mode_handles_missing_git_binary(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("git not installed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    local = read_local_revision(tmp_path)
    assert local.mode is InstallMode.DEVELOPER
    assert local.sha == ""


def test_write_revision_file_persists_sha(tmp_path: Path) -> None:
    sha = "feedfacefeedfacefeedfacefeedfacefeedface"
    path = write_revision_file(tmp_path, sha)
    assert path.name == REVISION_FILE_NAME
    assert path.read_text(encoding="utf-8").strip() == sha


@pytest.mark.parametrize(
    "local_sha, local_mode, remote, expected",
    [
        ("a" * 40, InstallMode.USER, None, UpdateStatus.OFFLINE),
        ("a" * 40, InstallMode.USER, ("a" * 40,), UpdateStatus.UP_TO_DATE),
        ("a" * 40, InstallMode.USER, ("b" * 40,), UpdateStatus.UPDATE_AVAILABLE),
        ("", InstallMode.UNKNOWN, ("a" * 40,), UpdateStatus.UNKNOWN),
        ("a" * 40, InstallMode.DEVELOPER, ("b" * 40,), UpdateStatus.DEV_MODE_USE_GIT),
        ("a" * 40, InstallMode.DEVELOPER, None, UpdateStatus.DEV_MODE_USE_GIT),
    ],
)
def test_compare_status_matrix(
    local_sha: str,
    local_mode: InstallMode,
    remote: Optional[tuple[str]],
    expected: UpdateStatus,
    tmp_path: Path,
) -> None:
    local = LocalRevision(sha=local_sha, mode=local_mode, repo_root=tmp_path)
    remote_rev = None
    if remote is not None:
        remote_rev = RemoteRevision(
            sha=remote[0],
            committed_at=datetime(2026, 5, 19, tzinfo=UTC),
            message="anything",
        )
    assert compare(local, remote_rev) is expected


def test_commit_api_url_is_pinned_to_developeter_repo() -> None:
    url = commit_api_url()
    assert url == ("https://api.github.com/repos/developeter/silentfrog/commits/" + UPDATE_BRANCH)


@pytest.mark.asyncio
async def test_fetch_remote_revision_parses_github_payload(monkeypatch) -> None:
    payload = json.dumps(
        {
            "sha": "f" * 40,
            "commit": {
                "author": {"date": "2026-05-19T08:15:30Z"},
                "message": "Test commit\n\nbody",
            },
        }
    )

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return payload

    class FakeSession:
        def get(self, _url, timeout=None):
            return FakeResponse()

    remote = await fetch_remote_revision(session=FakeSession())  # type: ignore[arg-type]
    assert remote is not None
    assert remote.sha == "f" * 40
    assert remote.committed_at.year == 2026
    assert remote.message.startswith("Test commit")


@pytest.mark.asyncio
async def test_fetch_remote_revision_returns_none_on_http_error() -> None:
    class FakeResponse:
        status = 503

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return ""

    class FakeSession:
        def get(self, _url, timeout=None):
            return FakeResponse()

    remote = await fetch_remote_revision(session=FakeSession())  # type: ignore[arg-type]
    assert remote is None


@pytest.mark.asyncio
async def test_fetch_remote_revision_swallows_network_exception() -> None:
    class FakeSession:
        def get(self, _url, timeout=None):
            raise RuntimeError("simulated network failure")

    remote = await fetch_remote_revision(session=FakeSession())  # type: ignore[arg-type]
    assert remote is None

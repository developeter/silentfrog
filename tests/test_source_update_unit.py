from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.source_update import (  # noqa: E402
    build_update_plan,
    copy_source_files,
    download_archive,
    extract_archive,
    pyproject_changed,
    validate_archive,
)


def test_download_archive_passes_certifi_ssl_context(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args, **kwargs):
            return b""

    def fake_urlopen(req, timeout, context):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["context"] = context
        return _FakeResponse()

    monkeypatch.setattr("tools.source_update.urlopen", fake_urlopen)
    plan = build_update_plan("v2.0.0", "developeter", "silentfrog", "silentfrog-2.0.0.zip")
    download_archive(plan, tmp_path / "archive.zip")
    import ssl

    assert isinstance(captured["context"], ssl.SSLContext)
    assert captured["context"].cert_store_stats()["x509_ca"] > 0
    assert captured["url"].endswith("/releases/download/v2.0.0/silentfrog-2.0.0.zip")
    assert captured["timeout"] == 60


def _make_archive(zip_path: Path, files: dict[str, str], top_dir: str) -> Path:
    with zipfile.ZipFile(zip_path, "w") as zf:
        for relative, content in files.items():
            zf.writestr(f"{top_dir}/{relative}", content)
    return zip_path


def _make_fake_silentfrog_tree(root: Path, *, version: str = "1.0.0") -> None:
    (root / "src" / "silentfrog").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "silentfrog" / "gui.py").write_text("old code\n", encoding="utf-8")
    (root / "tools" / "doctor.py").write_text("old doctor\n", encoding="utf-8")
    (root / "tests" / "test_old.py").write_text("old test\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "silentfrog"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("old readme\n", encoding="utf-8")


def test_build_update_plan_targets_signed_release_asset() -> None:
    # H7/PR-18: the source archive is a named asset on the signed Release, not
    # a mutable branch/commit archive.
    plan = build_update_plan("v2.0.0", "developeter", "silentfrog", "silentfrog-2.0.0.zip")
    assert plan.revision == "v2.0.0"
    assert plan.archive_url == (
        "https://github.com/developeter/silentfrog/releases/download/v2.0.0/silentfrog-2.0.0.zip"
    )


def test_extract_archive_returns_single_inner_directory(tmp_path: Path) -> None:
    zip_path = tmp_path / "archive.zip"
    _make_archive(
        zip_path,
        {"pyproject.toml": '[project]\nname = "silentfrog"\n'},
        top_dir="silentfrog-abc",
    )
    extracted = extract_archive(zip_path, tmp_path / "out")
    assert extracted.name == "silentfrog-abc"
    assert (extracted / "pyproject.toml").is_file()


def test_extract_archive_raises_if_top_level_is_not_single_dir(tmp_path: Path) -> None:
    zip_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a/pyproject.toml", "x")
        zf.writestr("b/pyproject.toml", "y")
    with pytest.raises(RuntimeError, match="one top-level"):
        extract_archive(zip_path, tmp_path / "out")


def test_validate_archive_accepts_silentfrog_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "silentfrog"\n', encoding="utf-8")
    validate_archive(tmp_path)


def test_validate_archive_rejects_missing_pyproject(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing pyproject.toml"):
        validate_archive(tmp_path)


def test_validate_archive_rejects_unknown_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "something-else"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a Silentfrog"):
        validate_archive(tmp_path)


def test_pyproject_changed_detects_version_bump(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    new = tmp_path / "new"
    repo.mkdir()
    new.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "silentfrog"\nversion = "1.0.0"\n', encoding="utf-8")
    (new / "pyproject.toml").write_text('[project]\nname = "silentfrog"\nversion = "1.0.1"\n', encoding="utf-8")
    assert pyproject_changed(repo, new) is True


def test_pyproject_changed_returns_false_when_identical(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    new = tmp_path / "new"
    repo.mkdir()
    new.mkdir()
    content = '[project]\nname = "silentfrog"\nversion = "1.0.0"\n'
    (repo / "pyproject.toml").write_text(content, encoding="utf-8")
    (new / "pyproject.toml").write_text(content, encoding="utf-8")
    assert pyproject_changed(repo, new) is False


def test_copy_source_files_overwrites_existing_sources(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    new = tmp_path / "new"
    _make_fake_silentfrog_tree(repo)
    _make_fake_silentfrog_tree(new)
    (new / "src" / "silentfrog" / "gui.py").write_text("new code\n", encoding="utf-8")
    (new / "README.md").write_text("new readme\n", encoding="utf-8")
    copied = copy_source_files(new, repo)
    assert (repo / "src" / "silentfrog" / "gui.py").read_text(encoding="utf-8") == "new code\n"
    assert (repo / "README.md").read_text(encoding="utf-8") == "new readme\n"
    assert (repo / "src" / "silentfrog" / "gui.py") in copied


def test_copy_source_files_preserves_venv_and_secrets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    new = tmp_path / "new"
    _make_fake_silentfrog_tree(repo)
    _make_fake_silentfrog_tree(new)
    (repo / ".venv").mkdir()
    (repo / ".venv" / "marker.txt").write_text("dont touch\n", encoding="utf-8")
    (repo / ".env").write_text("API_KEY=abc\n", encoding="utf-8")
    (repo / "secrets.local.json").write_text('{"x": 1}\n', encoding="utf-8")
    (repo / ".silentfrog_revision").write_text("oldsha\n", encoding="utf-8")
    # Even if the archive tries to ship these, they should be skipped.
    (new / ".venv").mkdir()
    (new / ".venv" / "marker.txt").write_text("HOSTILE\n", encoding="utf-8")
    (new / ".env").write_text("HOSTILE=1\n", encoding="utf-8")
    (new / "secrets.local.json").write_text("HOSTILE\n", encoding="utf-8")
    (new / ".silentfrog_revision").write_text("HOSTILE_SHA\n", encoding="utf-8")
    copy_source_files(new, repo)
    assert (repo / ".venv" / "marker.txt").read_text(encoding="utf-8") == "dont touch\n"
    assert (repo / ".env").read_text(encoding="utf-8") == "API_KEY=abc\n"
    assert (repo / "secrets.local.json").read_text(encoding="utf-8") == '{"x": 1}\n'
    assert (repo / ".silentfrog_revision").read_text(encoding="utf-8") == "oldsha\n"


def test_copy_source_files_creates_missing_subdirectories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    new = tmp_path / "new"
    _make_fake_silentfrog_tree(repo)
    _make_fake_silentfrog_tree(new)
    new_dir = new / "src" / "silentfrog" / "newpkg"
    new_dir.mkdir(parents=True)
    (new_dir / "added.py").write_text("hello\n", encoding="utf-8")
    copy_source_files(new, repo)
    assert (repo / "src" / "silentfrog" / "newpkg" / "added.py").is_file()

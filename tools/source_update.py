"""File-level helpers used by ``tools.update_silentfrog``.

Kept as a separate module so the orchestration script reads as plain
prose and the pure file operations can be tested without subprocess or
network calls. No GUI imports.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import ssl
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

import certifi

# python.org Framework Python on macOS ships with an empty SSL trust
# store unless ``Install Certificates.command`` was run. urllib then
# refuses HTTPS to github.com with CERTIFICATE_VERIFY_FAILED. certifi
# is already a runtime dependency, so the updater stays self-contained
# on every supported Python install.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# Release assets live at a predictable URL, so the apply path never has to
# trust the GitHub API's asset listing — it fetches the signed manifest and
# the archive named *inside* that manifest directly. H7/PR-18.
_RELEASE_ASSET_URL = "https://github.com/{owner}/{repo}/releases/download/{tag}/{name}"
MANIFEST_NAME = "manifest.json"
MANIFEST_SIGNATURE_NAME = "manifest.json.minisig"


# File and directory names at the install root that ``copy_source_files``
# must never overwrite. ``.silentfrog_revision`` is also preserved here
# because the caller updates it explicitly at the very end.
_PRESERVED_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        ".git",
        ".env",
        ".env.local",
        ".silentfrog_revision",
        "secrets.local.json",
        "build",
    }
)


@dataclass(frozen=True)
class UpdatePlan:
    revision: str  # the release tag (e.g. "v2.0.0")
    archive_url: str


def release_asset_url(owner: str, repo: str, tag: str, name: str) -> str:
    """The stable download URL of a named asset on a tag's GitHub Release."""
    return _RELEASE_ASSET_URL.format(owner=owner, repo=repo, tag=tag, name=name)


def build_update_plan(tag: str, owner: str, repo: str, archive_name: str) -> UpdatePlan:
    """Compose the download URL for the signed release's source archive.

    ``archive_name`` is read from the *verified* manifest, never guessed, so a
    crawl can only ever fetch the archive the signature commits to."""
    return UpdatePlan(revision=tag, archive_url=release_asset_url(owner, repo, tag, archive_name))


def fetch_release_manifest(
    owner: str,
    repo: str,
    tag: str,
    log: Callable[[str], None] = lambda _msg: None,
) -> tuple[bytes, str]:
    """Download the signed manifest and its detached minisign signature."""
    manifest_url = release_asset_url(owner, repo, tag, MANIFEST_NAME)
    signature_url = release_asset_url(owner, repo, tag, MANIFEST_SIGNATURE_NAME)
    log(f"[update] fetching signed manifest {manifest_url}")
    return _fetch_bytes(manifest_url), _fetch_bytes(signature_url).decode("utf-8")


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"Accept": "application/octet-stream"})
    with urlopen(request, timeout=60, context=_SSL_CONTEXT) as response:
        return response.read()


def download_archive(
    plan: UpdatePlan,
    destination: Path,
    log: Callable[[str], None] = lambda _msg: None,
) -> Path:
    """Download ``plan.archive_url`` to ``destination`` and return the path."""
    log(f"[update] downloading {plan.archive_url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(plan.archive_url, headers={"Accept": "application/octet-stream"})
    with urlopen(request, timeout=60, context=_SSL_CONTEXT) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)
    return destination


def extract_archive(archive_path: Path, target_dir: Path) -> Path:
    """Unzip ``archive_path`` into ``target_dir`` and return the inner root.

    GitHub archives nest everything under ``<repo>-<sha>/`` so we
    return that single inner directory rather than the unzip target.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as zf:
        zf.extractall(target_dir)
    children = [p for p in target_dir.iterdir() if p.is_dir()]
    if len(children) != 1:
        raise RuntimeError(f"Expected one top-level directory in archive, got {len(children)}")
    return children[0]


def validate_archive(extracted_root: Path) -> None:
    """Sanity-check that the extracted tree is really a Silentfrog repo."""
    pyproject = extracted_root / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeError(f"Extracted archive missing pyproject.toml: {extracted_root}")
    content = pyproject.read_text(encoding="utf-8")
    if 'name = "silentfrog"' not in content:
        raise RuntimeError(f"pyproject.toml in archive is not a Silentfrog project: {pyproject}")


def pyproject_changed(repo_root: Path, extracted_root: Path) -> bool:
    """``True`` when the archive's pyproject.toml differs from the current one."""
    return _sha256(repo_root / "pyproject.toml") != _sha256(extracted_root / "pyproject.toml")


def copy_source_files(extracted_root: Path, repo_root: Path) -> list[Path]:
    """Replace files at ``repo_root`` with files from ``extracted_root``.

    Skips top-level entries listed in ``_PRESERVED_NAMES``. Returns the
    list of paths written so callers can log them.
    """
    written: list[Path] = []
    for source in _files_to_copy(extracted_root):
        relative = source.relative_to(extracted_root)
        if _is_preserved(relative):
            continue
        destination = repo_root / relative
        _copy_file(source, destination)
        written.append(destination)
    return written


def _files_to_copy(extracted_root: Path) -> Iterable[Path]:
    return (path for path in extracted_root.rglob("*") if path.is_file())


def _is_preserved(relative: Path) -> bool:
    return relative.parts[0] in _PRESERVED_NAMES


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(io.DEFAULT_BUFFER_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

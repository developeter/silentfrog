"""Apply an update to a user-mode Silentfrog install.

Run as ``python -m tools.update_silentfrog --revision <sha>``. The GUI
calls this via ``QProcess`` from the "Apply and restart" button in
:class:`silentfrog.update_gui.UpdateDialog`.

Refuses to run on developer clones (``.git`` directory present) so a
maintainer's working tree is never touched by the in-app updater. See
``docs/`` for the full update story.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from silentfrog.updater import (  # noqa: E402
    GITHUB_OWNER,
    GITHUB_REPO,
    InstallMode,
    find_repo_root,
    read_local_revision,
    write_revision_file,
)
from tools.source_update import (  # noqa: E402
    build_update_plan,
    copy_source_files,
    download_archive,
    extract_archive,
    pyproject_changed,
    validate_archive,
)


EXIT_OK = 0
EXIT_USAGE_ERROR = 1
EXIT_DEVELOPER_MODE = 2
EXIT_DOWNLOAD_ERROR = 3
EXIT_INSTALL_ERROR = 4


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = find_repo_root()
    local = read_local_revision(repo_root)
    if local.mode is InstallMode.DEVELOPER:
        print("[update] Developer install detected. Use `git pull` instead.")
        return EXIT_DEVELOPER_MODE

    plan = build_update_plan(args.revision, GITHUB_OWNER, GITHUB_REPO)
    print(f"[update] Pulling {args.revision[:7]} from {plan.archive_url}")
    with tempfile.TemporaryDirectory(prefix="silentfrog-update-") as workdir_str:
        workdir = Path(workdir_str)
        archive_path = workdir / "silentfrog.zip"
        try:
            download_archive(plan, archive_path, log=print)
        except OSError as exc:
            print(f"[update] download failed: {exc}")
            return EXIT_DOWNLOAD_ERROR
        extracted_root = extract_archive(archive_path, workdir / "extracted")
        validate_archive(extracted_root)
        deps_changed = pyproject_changed(repo_root, extracted_root)
        copied = copy_source_files(extracted_root, repo_root)
        print(f"[update] Wrote {len(copied)} files")

    installer_exit = _refresh_install(repo_root, deps_changed=deps_changed)
    if installer_exit != 0:
        return EXIT_INSTALL_ERROR

    revision_path = write_revision_file(repo_root, args.revision)
    print(f"[update] Recorded {args.revision[:7]} in {revision_path.name}")
    return EXIT_OK


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply an update to a user-mode Silentfrog install"
    )
    parser.add_argument(
        "--revision",
        required=True,
        help="Target commit sha (or tag) to fetch from GitHub.",
    )
    return parser.parse_args(argv)


def _refresh_install(repo_root: Path, deps_changed: bool) -> int:
    """Bring the installed package in sync with the freshly written sources.

    When ``deps_changed`` is True we re-run the full ``install_silentfrog.py``
    so pip can resolve any new runtime requirements. On Windows, that
    regenerates ``.venv/Scripts/silentfrog.exe`` which conflicts with a
    still-running GUI process; the caller (the in-app updater) is
    expected to restart the GUI after this returns.

    When ``deps_changed`` is False we sync the source files directly
    into the venv's ``site-packages/silentfrog/`` directory, bypassing
    pip entirely. This is safer than ``pip install . --no-deps`` for
    two reasons:

    * pip uninstalls the existing package before installing the new
      wheel; a Windows file-lock on a child binary then leaves the
      install broken (no silentfrog package at all in site-packages).
      ``shutil.copy2`` is non-destructive — partial failure means some
      files are old, but the package still imports.
    * pip would regenerate the ``silentfrog.exe`` console-script
      wrapper in ``.venv/Scripts/``, which Windows cannot overwrite
      while the GUI is still using it. Direct file copy never touches
      ``Scripts/``.
    """
    if deps_changed:
        return _run([sys.executable, "install_silentfrog.py"], cwd=repo_root)
    return _sync_site_packages(repo_root)


def _sync_site_packages(repo_root: Path) -> int:
    """Copy ``src/silentfrog/`` into the venv's installed package dir.

    Skips ``__pycache__`` (Python regenerates it on next import).
    """
    source_pkg = repo_root / "src" / "silentfrog"
    target_pkg = _venv_site_packages(repo_root) / "silentfrog"
    if not source_pkg.is_dir():
        print(f"[update] source package missing: {source_pkg}")
        return 1
    if not target_pkg.is_dir():
        print(f"[update] installed package missing: {target_pkg}")
        return 1
    copied = 0
    for src_file in source_pkg.rglob("*"):
        if not src_file.is_file():
            continue
        relative = src_file.relative_to(source_pkg)
        if relative.parts and relative.parts[0] == "__pycache__":
            continue
        dest = target_pkg / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest)
        copied += 1
    print(f"[update] Synced {copied} files into {target_pkg}")
    return 0


def _venv_site_packages(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv" / "Lib" / "site-packages"
    libs = sorted((repo_root / ".venv" / "lib").glob("python3.*"))
    if not libs:
        # Fallback to the tested baseline if no python3.* dir exists yet.
        return repo_root / ".venv" / "lib" / "python3.12" / "site-packages"
    return libs[0] / "site-packages"


def _run(command: list[str], cwd: Path) -> int:
    print(f"[update] {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

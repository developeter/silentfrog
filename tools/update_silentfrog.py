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
    """Bring ``.venv`` in sync with the freshly written sources.

    When ``deps_changed`` is True we re-run the full ``install_silentfrog.py``
    so pip can resolve any new runtime requirements. When it's False we
    only refresh the ``silentfrog`` package itself, which is much faster.
    """
    if deps_changed:
        return _run([sys.executable, "install_silentfrog.py"], cwd=repo_root)
    venv_python = _venv_python(repo_root)
    return _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-deps",
            "--no-build-isolation",
            ".",
        ],
        cwd=repo_root,
    )


def _run(command: list[str], cwd: Path) -> int:
    print(f"[update] {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


def _venv_python(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


if __name__ == "__main__":
    raise SystemExit(main())

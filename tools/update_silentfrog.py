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
import stat
import subprocess
import sys
import tempfile
import tomllib
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
from tools.source_install import launcher_script_paths  # noqa: E402
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
    parser = argparse.ArgumentParser(description="Apply an update to a user-mode Silentfrog install")
    parser.add_argument(
        "--revision",
        required=True,
        help="Target commit sha (or tag) to fetch from GitHub.",
    )
    return parser.parse_args(argv)


def _refresh_install(repo_root: Path, deps_changed: bool) -> int:
    """Bring the installed package in sync with the freshly written sources.

    Both paths sync source files via ``shutil.copy2`` and never touch
    ``.venv/Scripts/silentfrog.exe``, so the running GUI's console-script
    wrapper stays available. When ``deps_changed`` is True we additionally
    install/upgrade the runtime deps via direct ``pip install <pkg>``
    calls — never ``pip install .``, which on Windows would uninstall
    the silentfrog wheel first (deleting ``silentfrog.exe`` mid-process)
    and fail with exit code 4 because the running GUI holds an exclusive
    lock on that exe.
    """
    exit_code = _sync_site_packages(repo_root)
    if exit_code != 0:
        return exit_code
    _ensure_executable_launchers(repo_root)
    if deps_changed:
        return _install_runtime_deps(repo_root)
    return 0


def _runtime_dep_specs(pyproject_path: Path) -> list[str]:
    """Return ``[project] dependencies`` specs from pyproject.toml."""
    if not pyproject_path.is_file():
        return []
    try:
        with pyproject_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"[update] could not parse pyproject.toml: {exc}")
        return []
    project = data.get("project", {})
    deps = project.get("dependencies", []) if isinstance(project, dict) else []
    if not isinstance(deps, list):
        return []
    return [str(spec) for spec in deps if isinstance(spec, str) and spec.strip()]


def _venv_python(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


def _install_runtime_deps(repo_root: Path) -> int:
    """Install/upgrade only the runtime deps named in pyproject.toml.

    Pip writes the named packages into ``site-packages`` without
    rebuilding or reinstalling silentfrog itself, so the running GUI's
    ``silentfrog.exe`` wrapper is never touched.
    """
    specs = _runtime_dep_specs(repo_root / "pyproject.toml")
    if not specs:
        print("[update] pyproject.toml has no [project] dependencies; skipping pip step.")
        return 0
    python = _venv_python(repo_root)
    if not python.is_file():
        print(f"[update] venv python not found: {python}")
        return 1
    print(f"[update] Installing {len(specs)} runtime deps into the venv.")
    return _run(
        [str(python), "-m", "pip", "install", "--upgrade", "--no-input", *specs],
        cwd=repo_root,
    )


def _ensure_executable_launchers(repo_root: Path) -> None:
    """Restore the +x bit on launcher shell scripts after copy_source_files.

    GitHub source archives (downloaded as .zip) drop POSIX execute bits,
    so launcher scripts arrive as `-rw-r--r--`. Without +x the Desktop
    `.command` (which `exec`s `run_silentfrog.sh`) fails silently and
    the user sees a Terminal window but no Silentfrog GUI.
    """
    executable_suffixes = (".sh", ".command")
    bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    for path in launcher_script_paths(repo_root):
        if path.suffix not in executable_suffixes:
            continue
        if not path.is_file():
            continue
        mode = path.stat().st_mode
        if mode & bits == bits:
            continue
        path.chmod(mode | bits)


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

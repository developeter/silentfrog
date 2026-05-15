from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from stat import S_IXGRP, S_IXOTH, S_IXUSR
from typing import Iterable

MIN_PYTHON = (3, 12)
MAX_PYTHON = (3, 15)
SUPPORTED_PYTHON_LABEL = "Python 3.12, 3.13, or 3.14"
RUNTIME_WHEEL_REQUIREMENTS = (
    "pyside6>=6.8,<7.0",
    "qtpy>=2.4.3,<3.0.0",
    "numpy>=2.2.6,<3.0.0",
    "pandas>=2.2.3,<3.0.0",
    "urllib3>=2.4.0,<3.0.0",
    "requests>=2.32.3,<3.0.0",
    "openpyxl>=3.1",
    "httpx[http2]>=0.28.1,<0.29.0",
    "beautifulsoup4>=4.13.4,<5.0.0",
    "lxml>=6.0.2,<7.0",
    "html5lib>=1.1,<2.0",
    "tldextract>=5.3.0,<6.0.0",
    "xlsxwriter>=3.2.9,<4.0.0",
    "aiohttp>=3.12.0,<4.0.0",
    "certifi>=2025.1.31,<2027.0.0",
    "nltk>=3.9.1,<4.0.0",
    "pillow>=12.2.0,<13.0.0",
    "humanize>=4.12.3,<5.0.0",
)
MACOS_PYTHON_CANDIDATES = (
    "python3.14",
    "python3.13",
    "python3.12",
    "/usr/local/bin/python3.14",
    "/opt/homebrew/bin/python3.14",
    "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3",
    "/usr/local/bin/python3.13",
    "/opt/homebrew/bin/python3.13",
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
    "/usr/local/bin/python3.12",
    "/opt/homebrew/bin/python3.12",
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
)
NON_MACOS_PYTHON_CANDIDATES = ("python3.14", "python3.13", "python3.12", "python3")


@dataclass(frozen=True)
class InstallerPaths:
    root: Path
    venv_dir: Path
    python: Path
    launcher: Path


def is_windows(system_name: str | None = None) -> bool:
    return (system_name or platform.system()).lower().startswith("win")


def validate_python_version(version: tuple[int, int], system_name: str | None = None) -> str | None:
    if MIN_PYTHON <= version < MAX_PYTHON:
        return None
    found = ".".join(map(str, version))
    return f"{SUPPORTED_PYTHON_LABEL} is required. Found {found}."


def installer_paths(root: Path, system_name: str | None = None) -> InstallerPaths:
    venv_dir = root / ".venv"
    if is_windows(system_name):
        bin_dir = venv_dir / "Scripts"
        launcher = bin_dir / "silentfrog.exe"
        python = bin_dir / "python.exe"
    else:
        bin_dir = venv_dir / "bin"
        launcher = bin_dir / "silentfrog"
        python = bin_dir / "python"
    return InstallerPaths(root=root, venv_dir=venv_dir, python=python, launcher=launcher)


def desktop_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Desktop"


def install_plan(root: Path, interpreter: str, system_name: str | None = None) -> list[list[str]]:
    paths = installer_paths(root, system_name)
    return [
        [interpreter, "-m", "venv", str(paths.venv_dir)],
        [str(paths.python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "poetry-core"],
        [
            str(paths.python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--only-binary=:all:",
            *RUNTIME_WHEEL_REQUIREMENTS,
        ],
        [str(paths.python), "-m", "pip", "install", "--upgrade", "--no-deps", "--no-build-isolation", "."],
        [
            str(paths.python),
            "-c",
            "import importlib.resources as r; p = r.files('silentfrog').joinpath('assets/icon.png'); assert p.is_file(), p",
        ],
    ]


def render_run_bat() -> str:
    return "\n".join(
        [
            "@echo off",
            "REM Launch Silentfrog from the local .venv when available.",
            "REM Falls back to Poetry for developers.",
            "",
            "setlocal",
            "pushd %~dp0",
            'set "QT_API=pyside6"',
            'set "LAUNCHER=%~dp0.venv\\Scripts\\silentfrog.exe"',
            'if exist "%LAUNCHER%" (',
            '  call "%LAUNCHER%" %*',
            ") else (",
            "  poetry run silentfrog %*",
            ")",
            "echo.",
            "echo Silentfrog exited. Press any key to close this window.",
            "pause >nul",
            "popd",
        ]
    ) + "\n"


def render_run_sh() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "# Launch Silentfrog from the local .venv when available.",
            "# Falls back to Poetry for developers.",
            "",
            "set -eu",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            'export QT_API="${QT_API:-pyside6}"',
            "",
            'launcher="$script_dir/.venv/bin/silentfrog"',
            'if [ -x "$launcher" ]; then',
            '  exec "$launcher" "$@"',
            "fi",
            "",
            'exec poetry run silentfrog "$@"',
        ]
    ) + "\n"


def render_desktop_command_launcher(root: Path) -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            f'cd {json.dumps(str(root))}',
            f'exec {json.dumps(str(root / "run_silentfrog.sh"))} "$@"',
        ]
    ) + "\n"


def windows_shortcut_command(root: Path, shortcut_path: Path) -> list[str]:
    target = root / "run_silentfrog.bat"
    icon = root / "src" / "silentfrog" / "assets" / "icon.ico"
    script = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({json.dumps(str(shortcut_path))})",
            f"$shortcut.TargetPath = {json.dumps(str(target))}",
            f"$shortcut.WorkingDirectory = {json.dumps(str(root))}",
            f"$shortcut.IconLocation = {json.dumps(str(icon))}",
            "$shortcut.Save()",
        ]
    )
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]


def render_install_bat() -> str:
    return "\n".join(
        [
            "@echo off",
            "setlocal",
            "pushd %~dp0",
            "where py >nul 2>nul",
            "if %errorlevel%==0 (",
            "  py -3 install_silentfrog.py %*",
            ") else (",
            "  python install_silentfrog.py %*",
            ")",
            "popd",
        ]
    ) + "\n"


def render_install_sh() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            *_macos_python_selector_lines(),
            'exec "$silentfrog_python" install_silentfrog.py "$@"',
        ]
    ) + "\n"


def render_install_command() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            'echo "Installing Silentfrog..."',
            '"$script_dir/install_silentfrog.sh" "$@"',
            "status=$?",
            'echo ""',
            'if [ "$status" -eq 0 ]; then',
            '  echo "Silentfrog installed. You can now use the Desktop launcher or run_silentfrog.sh."',
            "else",
            '  echo "Silentfrog installation failed with exit code $status."',
            "fi",
            'echo "Press Return to close this window."',
            "read -r _",
            'exit "$status"',
        ]
    ) + "\n"


def render_reinstall_sh() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            *_macos_python_selector_lines(),
            'exec "$silentfrog_python" install_silentfrog.py --recreate-venv "$@"',
        ]
    ) + "\n"


def render_reinstall_command() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            'echo "Reinstalling Silentfrog with a fresh local .venv..."',
            '"$script_dir/reinstall_silentfrog.sh" "$@"',
            "status=$?",
            'echo ""',
            'if [ "$status" -eq 0 ]; then',
            '  echo "Silentfrog reinstalled. You can now use the Desktop launcher or run_silentfrog.sh."',
            "else",
            '  echo "Silentfrog reinstall failed with exit code $status."',
            "fi",
            'echo "Press Return to close this window."',
            "read -r _",
            'exit "$status"',
        ]
    ) + "\n"


def _macos_python_selector_lines() -> list[str]:
    return [
        'silentfrog_python=""',
        "try_silentfrog_python() {",
        "  candidate=$1",
        '  [ -n "$candidate" ] || return 1',
        '  if command -v "$candidate" >/dev/null 2>&1; then',
        '    version=$("$candidate" -c \'import sys; print("%d.%d" % sys.version_info[:2])\' 2>/dev/null || true)',
        '    case "$version" in',
        "      3.12|3.13|3.14)",
        '        silentfrog_python="$candidate"',
        "        return 0",
        "        ;;",
        "    esac",
        "  fi",
        "  return 1",
        "}",
        'if [ -n "${SILENTFROG_PYTHON:-}" ]; then',
        '  try_silentfrog_python "$SILENTFROG_PYTHON" || true',
        "fi",
        'if [ -z "$silentfrog_python" ] && [ "$(uname -s)" = "Darwin" ]; then',
        _shell_candidate_loop(MACOS_PYTHON_CANDIDATES),
        '    try_silentfrog_python "$candidate" && break',
        "  done",
        "fi",
        'if [ -z "$silentfrog_python" ] && [ "$(uname -s)" != "Darwin" ]; then',
        _shell_candidate_loop(NON_MACOS_PYTHON_CANDIDATES),
        '    try_silentfrog_python "$candidate" && break',
        "  done",
        "fi",
        'if [ -z "$silentfrog_python" ]; then',
        '  echo "[install] Python 3.12, 3.13, or 3.14 was not found."',
        '  echo "[install] Install one supported Python version, then run this installer again."',
        "  exit 1",
        "fi",
    ]


def _shell_candidate_loop(candidates: tuple[str, ...]) -> str:
    return f"  for candidate in {' '.join(candidates)}; do"


def _write_file(path: Path, content: str, executable: bool = False) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    if executable:
        current = path.stat().st_mode
        path.chmod(current | S_IXUSR | S_IXGRP | S_IXOTH)


def write_launchers(root: Path) -> None:
    _write_file(root / "run_silentfrog.bat", render_run_bat())
    _write_file(root / "run_silentfrog.sh", render_run_sh(), executable=True)
    _write_file(root / "install_silentfrog.bat", render_install_bat())
    _write_file(root / "install_silentfrog.sh", render_install_sh(), executable=True)
    _write_file(root / "install_silentfrog.command", render_install_command(), executable=True)
    _write_file(root / "reinstall_silentfrog.sh", render_reinstall_sh(), executable=True)
    _write_file(root / "reinstall_silentfrog.command", render_reinstall_command(), executable=True)


def create_desktop_launcher(root: Path, system_name: str | None = None, home: Path | None = None) -> Path | None:
    desktop = desktop_dir(home)
    desktop.mkdir(parents=True, exist_ok=True)
    if is_windows(system_name):
        shortcut = desktop / "Silentfrog.lnk"
        subprocess.run(windows_shortcut_command(root, shortcut), check=True)
        return shortcut

    command_path = desktop / "Silentfrog.command"
    _write_file(command_path, render_desktop_command_launcher(root), executable=True)
    return command_path


def _run(command: Iterable[str], cwd: Path) -> None:
    printable = " ".join(command)
    print(f"[install] {printable}")
    subprocess.run(list(command), cwd=str(cwd), check=True)


def _is_dependency_wheel_preflight(command: list[str]) -> bool:
    return "--only-binary=:all:" in command


def _print_dependency_wheel_failure() -> None:
    print("[install] Dependency wheel preflight failed.")
    print("[install] Silentfrog requires binary wheels for Python 3.12, 3.13, or 3.14 on your OS/CPU.")
    print("[install] This source installer does not compile desktop dependencies from source.")
    print("[install] Use a packaged Silentfrog app, or try another supported Python version.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Silentfrog from source into a local .venv")
    parser.add_argument("--recreate-venv", action="store_true", help="Delete and recreate the local .venv before installing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    version_error = validate_python_version((sys.version_info.major, sys.version_info.minor), platform.system())
    if version_error:
        print(f"[install] {version_error}")
        print("[install] Install Python 3.12, 3.13, or 3.14, then run this command again.")
        return 1

    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").exists():
        print("[install] pyproject.toml not found. Run this script from the project root copy.")
        return 1

    paths = installer_paths(root)
    if args.recreate_venv and paths.venv_dir.exists():
        import shutil

        print(f"[install] Removing {paths.venv_dir}")
        shutil.rmtree(paths.venv_dir)

    try:
        for command in install_plan(root, sys.executable):
            try:
                _run(command, root)
            except subprocess.CalledProcessError:
                if _is_dependency_wheel_preflight(command):
                    _print_dependency_wheel_failure()
                raise
        write_launchers(root)
        try:
            launcher_path = create_desktop_launcher(root)
        except (OSError, subprocess.CalledProcessError) as exc:
            launcher_path = None
            print(f"[install] Desktop launcher not created: {exc}")
    except subprocess.CalledProcessError as exc:
        print(f"[install] Command failed with exit code {exc.returncode}.")
        return exc.returncode or 1

    run_hint = "run_silentfrog.bat" if is_windows() else "./run_silentfrog.sh"
    print("[install] Silentfrog installed successfully.")
    print(f"[install] Start the app with: {run_hint}")
    if launcher_path is not None:
        print(f"[install] Desktop launcher created: {launcher_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

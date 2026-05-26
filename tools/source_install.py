from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from stat import S_IXGRP, S_IXOTH, S_IXUSR
from typing import Iterable, Mapping

MIN_PYTHON = (3, 12)
MAX_PYTHON = (3, 15)
SUPPORTED_PYTHON_LABEL = "Python 3.12, 3.13, or 3.14"
_PEP621_PAREN_RE = re.compile(r"^([^\s(]+)\s*\(([^)]+)\)\s*$")
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


@dataclass(frozen=True)
class RuntimeRequirements:
    pip_args: tuple[str, ...]


def _normalize_pep508(spec: str) -> str:
    stripped = spec.strip()
    match = _PEP621_PAREN_RE.match(stripped)
    if match is None:
        return stripped
    name, version = match.group(1), match.group(2).strip()
    return f"{name}{version}"


def load_runtime_requirements(pyproject: Path) -> RuntimeRequirements:
    if not pyproject.is_file():
        raise RuntimeError(f"pyproject.toml not found at {pyproject}")
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    project = data.get("project")
    if not isinstance(project, dict):
        raise RuntimeError(f"pyproject.toml has no [project] table: {pyproject}")
    raw_deps = project.get("dependencies")
    if not isinstance(raw_deps, list):
        raise RuntimeError(f"pyproject.toml has no [project].dependencies list: {pyproject}")
    normalized = tuple(_normalize_pep508(str(spec)) for spec in raw_deps)
    return RuntimeRequirements(pip_args=normalized)


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


_LAUNCHER_SCRIPT_NAMES = (
    "run_silentfrog.bat",
    "run_silentfrog.sh",
    "install_silentfrog.bat",
    "install_silentfrog.sh",
    "install_silentfrog.command",
    "reinstall_silentfrog.sh",
    "reinstall_silentfrog.command",
    "uninstall_silentfrog.sh",
    "uninstall_silentfrog.command",
    "uninstall_silentfrog.bat",
)


def launcher_script_paths(root: Path) -> tuple[Path, ...]:
    return tuple(root / name for name in _LAUNCHER_SCRIPT_NAMES)


_PYTHON_ORG_FRAMEWORK_RE = re.compile(
    r"/Library/Frameworks/Python\.framework/Versions/(?P<minor>3\.\d+)/"
)


def detect_python_org_certificate_installer(python_exe: Path) -> Path | None:
    match = _PYTHON_ORG_FRAMEWORK_RE.search(str(python_exe))
    if match is None:
        return None
    candidate = Path(f"/Applications/Python {match.group('minor')}/Install Certificates.command")
    return candidate if candidate.is_file() else None


def run_certificate_installer(installer: Path) -> int:
    try:
        completed = subprocess.run(["/bin/sh", str(installer)], check=False)
    except OSError as exc:
        print(f"[install] Certificate installer could not be launched: {exc}")
        return 1
    return completed.returncode


def strip_quarantine(target: Path) -> int:
    if platform.system().lower() != "darwin":
        return 0
    try:
        completed = subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", str(target)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return 0
    return completed.returncode


def app_data_dir(
    system_name: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    env_map = env if env is not None else os.environ
    override = env_map.get("SILENTFROG_DATA_DIR")
    if override:
        return Path(override)
    home_path = home or Path.home()
    name = (system_name or platform.system()).lower()
    if name.startswith("win"):
        base = env_map.get("LOCALAPPDATA") or str(home_path / "AppData" / "Local")
        return Path(base) / "Silentfrog"
    if name == "darwin":
        return home_path / "Library" / "Application Support" / "Silentfrog"
    xdg = env_map.get("XDG_DATA_HOME") or str(home_path / ".local" / "share")
    return Path(xdg) / "silentfrog"


@dataclass(frozen=True)
class UninstallTargets:
    root: Path
    venv_dir: Path
    desktop_lnk: Path
    desktop_command: Path
    launcher_scripts: tuple[Path, ...]
    user_data_dir: Path


def uninstall_targets(
    root: Path,
    system_name: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> UninstallTargets:
    paths = installer_paths(root, system_name)
    desktop = desktop_dir(home)
    return UninstallTargets(
        root=root,
        venv_dir=paths.venv_dir,
        desktop_lnk=desktop / "Silentfrog.lnk",
        desktop_command=desktop / "Silentfrog.command",
        launcher_scripts=launcher_script_paths(root),
        user_data_dir=app_data_dir(system_name=system_name, home=home, env=env),
    )


def install_plan(
    root: Path,
    interpreter: str,
    system_name: str | None = None,
    requirements: RuntimeRequirements | None = None,
) -> list[list[str]]:
    paths = installer_paths(root, system_name)
    if requirements is None:
        requirements = load_runtime_requirements(root / "pyproject.toml")
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
            *requirements.pip_args,
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


# macOS .app bundle scaffolding. A native bundle is the only way to
# get the menu bar to read "Silentfrog" instead of "Python" (macOS reads
# the app menu name from CFBundleName in Info.plist; without a bundle it
# falls back to the process name, which is the Python interpreter). The
# bundle also removes the Terminal popup that a .command would open.

def render_macos_app_info_plist(version: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        '    <key>CFBundleName</key>\n'
        '    <string>Silentfrog</string>\n'
        '    <key>CFBundleDisplayName</key>\n'
        '    <string>Silentfrog</string>\n'
        '    <key>CFBundleIdentifier</key>\n'
        '    <string>com.silentfrog.app</string>\n'
        f'    <key>CFBundleVersion</key>\n'
        f'    <string>{version}</string>\n'
        f'    <key>CFBundleShortVersionString</key>\n'
        f'    <string>{version}</string>\n'
        '    <key>CFBundleExecutable</key>\n'
        '    <string>Silentfrog</string>\n'
        '    <key>CFBundleIconFile</key>\n'
        '    <string>icon.icns</string>\n'
        '    <key>CFBundlePackageType</key>\n'
        '    <string>APPL</string>\n'
        '    <key>LSMinimumSystemVersion</key>\n'
        '    <string>11.0</string>\n'
        '    <key>NSHighResolutionCapable</key>\n'
        '    <true/>\n'
        '    <key>LSArchitecturePriority</key>\n'
        '    <array>\n'
        '        <string>arm64</string>\n'
        '        <string>x86_64</string>\n'
        '    </array>\n'
        '</dict>\n'
        '</plist>\n'
    )


def render_macos_app_launcher() -> str:
    # LaunchServices selects Rosetta (x86_64) when launching a shell-script
    # bundle on Apple Silicon, which then can't load the arm64 wheels we
    # installed (numpy, lxml, etc. crash with "incompatible architecture").
    # Detect Apple Silicon hardware via sysctl — independent of the
    # Rosetta-masked uname output — and re-exec under `arch -arm64`.
    # Intel Macs (hw.optional.arm64 = 0) keep the native x86_64 path.
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'DIR="$(cd "$(dirname "$0")" && pwd)"',
            'ROOT="$(cd "$DIR/../../.." && pwd)"',
            'export QT_API="${QT_API:-pyside6}"',
            'if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then',
            '    exec /usr/bin/arch -arm64 "$ROOT/.venv/bin/silentfrog" "$@"',
            'fi',
            'exec "$ROOT/.venv/bin/silentfrog" "$@"',
        ]
    ) + "\n"


def project_version(pyproject: Path | None = None) -> str:
    """Read [project].version from pyproject.toml; fallback to '0.0.0'.

    Kept as a small helper rather than importing from tools.package_app so
    source_install stays self-contained even on installs where the
    packaging tooling has been pruned.
    """
    path = pyproject or (Path(__file__).resolve().parents[1] / "pyproject.toml")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return "0.0.0"
    project = data.get("project") if isinstance(data, dict) else None
    version = project.get("version") if isinstance(project, dict) else None
    return version if isinstance(version, str) and version else "0.0.0"


def create_macos_app_bundle(root: Path, icon_source: Path | None = None) -> Path:
    """Build (or refresh) ``<root>/Silentfrog.app`` as a native macOS bundle.

    Returns the path to the bundle root. Idempotent: safe to re-run.
    """
    bundle = root / "Silentfrog.app"
    contents = bundle / "Contents"
    macos_dir = contents / "MacOS"
    resources = contents / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    info_plist = contents / "Info.plist"
    info_plist.write_text(render_macos_app_info_plist(project_version()), encoding="utf-8")
    launcher = macos_dir / "Silentfrog"
    _write_file(launcher, render_macos_app_launcher(), executable=True)
    icon_src = icon_source or (root / "src" / "silentfrog" / "assets" / "icon.icns")
    icon_dest = resources / "icon.icns"
    if icon_src.is_file():
        import shutil

        shutil.copyfile(icon_src, icon_dest)
    return bundle


def windows_shortcut_command(root: Path, shortcut_path: Path) -> list[str]:
    # Target the venv's gui-script wrapper directly. `run_silentfrog.bat`
    # would do the same thing semantically but it forces a `cmd` window
    # to flash on every launch; the .exe wrapper (gui-script flavour
    # since the `[project.gui-scripts]` move in pyproject.toml) has no
    # console attached and double-click is silent. The .bat sticks
    # around as a terminal-friendly debug entry point.
    target = root / ".venv" / "Scripts" / "silentfrog.exe"
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
            'xattr -dr com.apple.quarantine "$script_dir" >/dev/null 2>&1 || true',
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
            'xattr -dr com.apple.quarantine "$script_dir" >/dev/null 2>&1 || true',
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


def render_uninstall_sh() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            *_macos_python_selector_lines(),
            'exec "$silentfrog_python" -m tools.source_uninstall "$@"',
        ]
    ) + "\n"


def render_uninstall_command() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            'script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)',
            'cd "$script_dir"',
            'echo "Uninstalling Silentfrog..."',
            '"$script_dir/uninstall_silentfrog.sh" "$@"',
            "status=$?",
            'echo ""',
            'if [ "$status" -eq 0 ]; then',
            '  echo "Silentfrog uninstalled. Local crawl history was preserved unless --purge was used."',
            "else",
            '  echo "Silentfrog uninstall failed with exit code $status."',
            "fi",
            'echo "Press Return to close this window."',
            "read -r _",
            'exit "$status"',
        ]
    ) + "\n"


def render_uninstall_bat() -> str:
    return "\n".join(
        [
            "@echo off",
            "setlocal",
            "pushd %~dp0",
            "where py >nul 2>nul",
            "if %errorlevel%==0 (",
            "  py -3 -m tools.source_uninstall %*",
            ") else (",
            "  python -m tools.source_uninstall %*",
            ")",
            "popd",
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
    _write_file(root / "uninstall_silentfrog.sh", render_uninstall_sh(), executable=True)
    _write_file(root / "uninstall_silentfrog.command", render_uninstall_command(), executable=True)
    _write_file(root / "uninstall_silentfrog.bat", render_uninstall_bat())


def create_desktop_launcher(root: Path, system_name: str | None = None, home: Path | None = None) -> Path | None:
    desktop = desktop_dir(home)
    desktop.mkdir(parents=True, exist_ok=True)
    if is_windows(system_name):
        shortcut = desktop / "Silentfrog.lnk"
        subprocess.run(windows_shortcut_command(root, shortcut), check=True)
        return shortcut

    # macOS: build a native .app bundle inside the install dir so the
    # menu bar reads "Silentfrog" (from CFBundleName) instead of the
    # interpreter name "Python", and so double-click no longer spawns a
    # Terminal window. Drop a Desktop symlink pointing at it. Keep
    # Silentfrog.command around as a terminal-friendly debug entry.
    real_launcher = root / "Silentfrog.command"
    _write_file(real_launcher, render_desktop_command_launcher(root), executable=True)
    bundle = create_macos_app_bundle(root)
    desktop_link = desktop / "Silentfrog.app"
    if desktop_link.is_symlink() or desktop_link.exists():
        if desktop_link.is_symlink() or desktop_link.is_file():
            desktop_link.unlink()
        else:
            import shutil

            shutil.rmtree(desktop_link)
    desktop_link.symlink_to(bundle)
    # The pre-bundle install layout dropped a Silentfrog.command symlink
    # on the Desktop. Tidy it up so users see exactly one Silentfrog
    # entry on their Desktop after the upgrade.
    stale_command = desktop / "Silentfrog.command"
    if stale_command.is_symlink() or stale_command.is_file():
        stale_command.unlink()
    return desktop_link


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
    parser.add_argument(
        "--revision",
        default=None,
        help=(
            "Commit sha to record in .silentfrog_revision for the in-app "
            "updater. Set by the bootstrap script; omit for dev clones."
        ),
    )
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

    try:
        requirements = load_runtime_requirements(root / "pyproject.toml")
    except RuntimeError as exc:
        print(f"[install] {exc}")
        return 1

    paths = installer_paths(root)
    if args.recreate_venv and paths.venv_dir.exists():
        import shutil

        print(f"[install] Removing {paths.venv_dir}")
        shutil.rmtree(paths.venv_dir)

    try:
        for command in install_plan(root, sys.executable, requirements=requirements):
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

    _post_install_macos_helpers(root, paths.python)
    if args.revision:
        _persist_revision(root, args.revision)
    run_hint = "run_silentfrog.bat" if is_windows() else "./run_silentfrog.sh"
    print("[install] Silentfrog installed successfully.")
    print(f"[install] Start the app with: {run_hint}")
    if launcher_path is not None:
        print(f"[install] Desktop launcher created: {launcher_path}")
    return 0


REVISION_FILE_NAME = ".silentfrog_revision"


def _persist_revision(root: Path, revision: str) -> None:
    # The installer runs under the user's host Python before .venv is
    # populated, so we cannot import silentfrog itself. Write the file
    # directly; src/silentfrog/updater.py knows the same filename.
    path = root / REVISION_FILE_NAME
    path.write_text(revision.strip() + os.linesep, encoding="utf-8")
    print(f"[install] Recorded revision {revision[:7]} in {path.name}")


def _post_install_macos_helpers(root: Path, venv_python: Path) -> None:
    if platform.system().lower() != "darwin":
        return
    strip_quarantine(root)
    installer = detect_python_org_certificate_installer(venv_python)
    if installer is None:
        return
    print(f"[install] Running macOS certificate helper: {installer}")
    status = run_certificate_installer(installer)
    if status:
        print(f"[install] Certificate helper exited with code {status}. If HTTPS fetches fail later, run it manually.")


if __name__ == "__main__":
    raise SystemExit(main())

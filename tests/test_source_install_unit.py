from __future__ import annotations

import json
from pathlib import Path

from tools.source_install import (
    RUNTIME_WHEEL_REQUIREMENTS,
    create_desktop_launcher,
    desktop_dir,
    installer_paths,
    install_plan,
    render_desktop_command_launcher,
    render_install_bat,
    render_install_command,
    render_install_sh,
    render_reinstall_command,
    render_reinstall_sh,
    render_run_bat,
    render_run_sh,
    validate_python_version,
    windows_shortcut_command,
    write_launchers,
)


def test_validate_python_version_rejects_old_versions() -> None:
    assert validate_python_version((3, 11)) == "Python 3.12, 3.13, or 3.14 is required. Found 3.11."
    assert validate_python_version((3, 12)) is None
    assert validate_python_version((3, 15)) == "Python 3.12, 3.13, or 3.14 is required. Found 3.15."


def test_validate_python_version_accepts_supported_versions_on_macos() -> None:
    assert validate_python_version((3, 12), "Darwin") is None
    assert validate_python_version((3, 13), "Darwin") is None
    assert validate_python_version((3, 14), "Darwin") is None
    assert validate_python_version((3, 14), "Windows") is None


def test_installer_paths_for_windows_and_unix(tmp_path: Path) -> None:
    windows_paths = installer_paths(tmp_path, "Windows")
    unix_paths = installer_paths(tmp_path, "Darwin")

    assert windows_paths.python == tmp_path / ".venv" / "Scripts" / "python.exe"
    assert windows_paths.launcher == tmp_path / ".venv" / "Scripts" / "silentfrog.exe"
    assert unix_paths.python == tmp_path / ".venv" / "bin" / "python"
    assert unix_paths.launcher == tmp_path / ".venv" / "bin" / "silentfrog"


def test_desktop_dir_uses_home_desktop(tmp_path: Path) -> None:
    assert desktop_dir(tmp_path) == tmp_path / "Desktop"


def test_install_plan_targets_local_venv(tmp_path: Path) -> None:
    plan = install_plan(tmp_path, "python3", "Darwin")

    assert plan[0] == ["python3", "-m", "venv", str(tmp_path / ".venv")]
    assert plan[1][:5] == [str(tmp_path / ".venv" / "bin" / "python"), "-m", "pip", "install", "--upgrade"]
    assert "poetry-core" in plan[1]
    assert "--only-binary=:all:" in plan[2]
    assert "pyside6>=6.8,<7.0" in plan[2]
    assert "numpy>=2.2.6,<3.0.0" in plan[2]
    assert not any("pyqt5" in requirement.lower() for requirement in RUNTIME_WHEEL_REQUIREMENTS)
    assert plan[3][-3:] == ["--no-deps", "--no-build-isolation", "."]


def test_launcher_renderers_prefer_local_venv() -> None:
    run_bat = render_run_bat()
    run_sh = render_run_sh()
    install_bat = render_install_bat()
    install_sh = render_install_sh()
    install_command = render_install_command()
    reinstall_sh = render_reinstall_sh()
    reinstall_command = render_reinstall_command()

    assert ".venv\\Scripts\\silentfrog.exe" in run_bat
    assert 'QT_API=pyside6' in run_bat
    assert "poetry run silentfrog" in run_bat
    assert ".venv/bin/silentfrog" in run_sh
    assert 'QT_API="${QT_API:-pyside6}"' in run_sh
    assert 'poetry run silentfrog "$@"' in run_sh
    assert "install_silentfrog.py" in install_bat
    assert "install_silentfrog.py" in install_sh
    assert install_sh.index("python3.14") < install_sh.index("python3.13") < install_sh.index("python3.12")
    assert "python3.12" in install_sh
    assert "/usr/local/bin/python3.14" in install_sh
    assert "/usr/local/bin/python3.12" in install_sh
    assert "Python 3.12, 3.13, or 3.14 was not found." in install_sh
    assert "install_silentfrog.sh" in install_command
    assert "Press Return to close this window." in install_command
    assert "--recreate-venv" in reinstall_sh
    assert "reinstall_silentfrog.sh" in reinstall_command
    assert "fresh local .venv" in reinstall_command


def test_macos_launcher_renderers_are_plain_sh_compatible() -> None:
    rendered = "\n".join(
        [
            render_run_sh(),
            render_install_sh(),
            render_install_command(),
            render_reinstall_sh(),
            render_reinstall_command(),
        ]
    )

    assert "BASH_SOURCE" not in rendered
    assert "[[" not in rendered
    assert "set -euo pipefail" not in rendered
    assert "candidates=(" not in rendered
    assert render_install_sh().startswith("#!/bin/sh")
    assert render_reinstall_sh().startswith("#!/bin/sh")


def test_render_desktop_command_launcher_runs_repo_launcher(tmp_path: Path) -> None:
    rendered = render_desktop_command_launcher(tmp_path)

    assert json.dumps(str(tmp_path)) in rendered
    assert json.dumps(str(tmp_path / "run_silentfrog.sh")) in rendered
    assert 'exec ' in rendered


def test_windows_shortcut_command_targets_repo_launcher(tmp_path: Path) -> None:
    command = windows_shortcut_command(tmp_path, tmp_path / "Desktop" / "Silentfrog.lnk")
    joined = " ".join(command)

    assert command[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert "run_silentfrog.bat" in joined
    assert "icon.ico" in joined
    assert "Silentfrog.lnk" in joined


def test_create_desktop_launcher_writes_command_file_on_unix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    launcher = create_desktop_launcher(root, system_name="Darwin", home=tmp_path)

    assert launcher == tmp_path / "Desktop" / "Silentfrog.command"
    assert launcher.is_file()
    content = launcher.read_text(encoding="utf-8")
    assert json.dumps(str(root / "run_silentfrog.sh")) in content


def test_write_launchers_keeps_macos_scripts_lf_only(tmp_path: Path) -> None:
    write_launchers(tmp_path)

    for filename in ("install_silentfrog.sh", "reinstall_silentfrog.sh", "run_silentfrog.sh"):
        assert b"\r\n" not in (tmp_path / filename).read_bytes()

from __future__ import annotations

import json
from pathlib import Path

from tools.source_install import (
    create_desktop_launcher,
    desktop_dir,
    installer_paths,
    install_plan,
    render_desktop_command_launcher,
    render_install_bat,
    render_install_command,
    render_install_sh,
    render_run_bat,
    render_run_sh,
    validate_python_version,
    windows_shortcut_command,
)


def test_validate_python_version_rejects_old_versions() -> None:
    assert validate_python_version((3, 11)) == "Python 3.12+ is required. Found 3.11."
    assert validate_python_version((3, 12)) is None


def test_validate_python_version_requires_python_312_on_macos() -> None:
    assert validate_python_version((3, 12), "Darwin") is None
    assert validate_python_version((3, 14), "Darwin") == (
        "Python 3.12 is required for the macOS installer path. Found 3.14."
    )
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
    assert plan[2][-1] == "."


def test_launcher_renderers_prefer_local_venv() -> None:
    run_bat = render_run_bat()
    run_sh = render_run_sh()
    install_bat = render_install_bat()
    install_sh = render_install_sh()
    install_command = render_install_command()

    assert ".venv\\Scripts\\silentfrog.exe" in run_bat
    assert 'QT_API=pyside6' in run_bat
    assert "poetry run silentfrog" in run_bat
    assert ".venv/bin/silentfrog" in run_sh
    assert 'QT_API="${QT_API:-pyside6}"' in run_sh
    assert 'poetry run silentfrog "$@"' in run_sh
    assert "install_silentfrog.py" in install_bat
    assert "install_silentfrog.py" in install_sh
    assert "python3.12" in install_sh
    assert "/usr/local/bin/python3.12" in install_sh
    assert "brew install python@3.12" in install_sh
    assert "install_silentfrog.sh" in install_command
    assert "Press Return to close this window." in install_command


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

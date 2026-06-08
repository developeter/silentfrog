from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

# Skip tests that exercise macOS-only code paths (Framework Python
# certificate installer detection, .app bundle layout, Desktop
# symlinks, exec-bit permission semantics). On Windows the file-mode
# and symlink behaviour differs in ways these assertions don't
# anticipate; running them there produces noise without catching
# anything we care about.
_macos_only = pytest.mark.skipif(
    platform.system().lower() != "darwin",
    reason="macOS-only path / permission / bundle semantics",
)

from tools.source_install import (
    RuntimeRequirements,
    _normalize_pep508,
    app_data_dir,
    create_desktop_launcher,
    create_macos_app_bundle,
    desktop_dir,
    detect_python_org_certificate_installer,
    install_plan,
    installer_paths,
    launcher_script_paths,
    load_runtime_requirements,
    render_desktop_command_launcher,
    render_install_bat,
    render_install_command,
    render_install_sh,
    render_macos_app_info_plist,
    render_macos_app_launcher,
    render_reinstall_command,
    render_reinstall_sh,
    render_run_bat,
    render_run_sh,
    render_uninstall_bat,
    render_uninstall_command,
    render_uninstall_sh,
    strip_quarantine,
    uninstall_targets,
    validate_python_version,
    windows_shortcut_command,
    write_launchers,
)

_FAKE_PYPROJECT = """
[project]
name = "silentfrog"
version = "1.0.0"
dependencies = [
    "pyside6 (>=6.8,<7.0)",
    "numpy (>=2.2.6,<3.0.0)",
    "httpx[http2] (>=0.28.1,<0.29.0)",
    "openpyxl (>=3.1)",
]

[project.optional-dependencies]
pyqt5-backend = [
    "pyqt5 (==5.15.11)",
]
"""


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
    plan = install_plan(
        tmp_path,
        "python3",
        "Darwin",
        requirements=RuntimeRequirements(pip_args=("pyside6>=6.8,<7.0", "numpy>=2.2.6,<3.0.0")),
    )

    assert plan[0] == ["python3", "-m", "venv", str(tmp_path / ".venv")]
    assert plan[1][:5] == [str(tmp_path / ".venv" / "bin" / "python"), "-m", "pip", "install", "--upgrade"]
    assert "poetry-core" in plan[1]
    assert "--only-binary=:all:" in plan[2]
    assert "pyside6>=6.8,<7.0" in plan[2]
    assert "numpy>=2.2.6,<3.0.0" in plan[2]
    assert not any("pyqt5" in arg.lower() for arg in plan[2])
    assert plan[3][-3:] == ["--no-deps", "--no-build-isolation", "."]


def test_normalize_pep508_strips_pep621_parens() -> None:
    assert _normalize_pep508("pyside6 (>=6.8,<7.0)") == "pyside6>=6.8,<7.0"
    assert _normalize_pep508("httpx[http2] (>=0.28.1,<0.29.0)") == "httpx[http2]>=0.28.1,<0.29.0"
    assert _normalize_pep508("openpyxl (>=3.1)") == "openpyxl>=3.1"


def test_normalize_pep508_passes_through_plain_pep508() -> None:
    assert _normalize_pep508("requests>=2.32") == "requests>=2.32"
    assert _normalize_pep508("  certifi  ") == "certifi"


def test_load_runtime_requirements_strips_pep621_parens(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_FAKE_PYPROJECT, encoding="utf-8")
    requirements = load_runtime_requirements(pyproject)
    assert "pyside6>=6.8,<7.0" in requirements.pip_args
    assert "httpx[http2]>=0.28.1,<0.29.0" in requirements.pip_args
    assert "openpyxl>=3.1" in requirements.pip_args
    assert not any("pyqt5" in spec.lower() for spec in requirements.pip_args)


def test_install_plan_pulls_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(_FAKE_PYPROJECT, encoding="utf-8")
    plan = install_plan(tmp_path, "python3", "Darwin")
    assert "pyside6>=6.8,<7.0" in plan[2]
    assert "numpy>=2.2.6,<3.0.0" in plan[2]
    assert not any("pyqt5" in arg.lower() for arg in plan[2])


def test_load_runtime_requirements_rejects_missing_pyproject(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="pyproject.toml not found"):
        load_runtime_requirements(tmp_path / "missing.toml")


def test_load_runtime_requirements_rejects_missing_project_table(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.poetry]\nname = 'x'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"no \[project\] table"):
        load_runtime_requirements(pyproject)


def test_load_runtime_requirements_rejects_missing_dependencies(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'x'\nversion = '0.1.0'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"no \[project\].dependencies"):
        load_runtime_requirements(pyproject)


def test_launcher_renderers_prefer_local_venv() -> None:
    run_bat = render_run_bat()
    run_sh = render_run_sh()
    install_bat = render_install_bat()
    install_sh = render_install_sh()
    install_command = render_install_command()
    reinstall_sh = render_reinstall_sh()
    reinstall_command = render_reinstall_command()

    assert ".venv\\Scripts\\silentfrog.exe" in run_bat
    assert "QT_API=pyside6" in run_bat
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
    assert "exec " in rendered


def test_windows_shortcut_command_targets_venv_gui_script(tmp_path: Path) -> None:
    """Regression: targeting run_silentfrog.bat opened cmd.exe every launch.
    The Desktop shortcut now points at the venv's gui-script .exe wrapper,
    which has no console attached on Windows.
    """
    command = windows_shortcut_command(tmp_path, tmp_path / "Desktop" / "Silentfrog.lnk")
    joined = " ".join(command)

    assert command[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert "silentfrog.exe" in joined
    assert ".venv" in joined and "Scripts" in joined
    assert "run_silentfrog.bat" not in joined
    assert "icon.ico" in joined
    assert "Silentfrog.lnk" in joined


def test_render_macos_app_info_plist_carries_silentfrog_bundle_name() -> None:
    plist = render_macos_app_info_plist("1.2.3")
    assert "<key>CFBundleName</key>" in plist
    assert "<string>Silentfrog</string>" in plist
    assert "<key>CFBundleExecutable</key>" in plist
    assert "<string>1.2.3</string>" in plist
    assert plist.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_render_macos_app_launcher_execs_venv_silentfrog() -> None:
    launcher = render_macos_app_launcher()
    assert launcher.startswith("#!/bin/sh")
    assert "$ROOT/.venv/bin/silentfrog" in launcher
    assert "set -eu" in launcher


def test_render_macos_app_launcher_forces_arm64_on_apple_silicon() -> None:
    launcher = render_macos_app_launcher()
    # Bundles launched via `open` on Apple Silicon get Rosetta-mapped
    # to x86_64, which then fails to load the arm64 wheels installed
    # in the venv. The launcher must detect arm64 hardware and re-exec
    # with `arch -arm64`. Intel Macs fall through to the native path.
    assert "hw.optional.arm64" in launcher
    assert "/usr/bin/arch -arm64" in launcher


def test_render_macos_app_info_plist_pins_arch_priority() -> None:
    plist = render_macos_app_info_plist("1.0.0")
    assert "<key>LSArchitecturePriority</key>" in plist
    # arm64 first so LaunchServices prefers native on Apple Silicon.
    arm_idx = plist.index("<string>arm64</string>")
    x86_idx = plist.index("<string>x86_64</string>")
    assert arm_idx < x86_idx


@_macos_only
def test_create_macos_app_bundle_has_required_layout(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    # Stub an icon source so the copy path runs.
    assets = root / "src" / "silentfrog" / "assets"
    assets.mkdir(parents=True)
    icon = assets / "icon.icns"
    icon.write_bytes(b"\x00\x00fake-icns")
    bundle = create_macos_app_bundle(root)
    assert bundle == root / "Silentfrog.app"
    info = bundle / "Contents" / "Info.plist"
    launcher = bundle / "Contents" / "MacOS" / "Silentfrog"
    icon_dest = bundle / "Contents" / "Resources" / "icon.icns"
    assert info.is_file() and "CFBundleName" in info.read_text(encoding="utf-8")
    assert launcher.is_file()
    import stat as _stat

    mode = launcher.stat().st_mode
    assert mode & _stat.S_IXUSR
    assert icon_dest.is_file()
    assert icon_dest.read_bytes() == b"\x00\x00fake-icns"


def test_create_macos_app_bundle_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    create_macos_app_bundle(root)
    # Second call must not raise (directories already exist).
    bundle = create_macos_app_bundle(root)
    assert (bundle / "Contents" / "Info.plist").is_file()


@_macos_only
def test_create_desktop_launcher_writes_app_bundle_symlink_on_unix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    launcher = create_desktop_launcher(root, system_name="Darwin", home=tmp_path)

    # Desktop entry is a symlink to the .app bundle inside the install
    # dir (the bundle is what gives macOS its menu-bar name).
    assert launcher == tmp_path / "Desktop" / "Silentfrog.app"
    assert launcher.is_symlink()
    bundle = root / "Silentfrog.app"
    assert launcher.resolve() == bundle.resolve()
    assert (bundle / "Contents" / "Info.plist").is_file()
    assert (bundle / "Contents" / "MacOS" / "Silentfrog").is_file()
    # The .command stays as a terminal-friendly debug entry inside the
    # install dir, but no longer on the Desktop.
    assert (root / "Silentfrog.command").is_file()
    assert not (tmp_path / "Desktop" / "Silentfrog.command").exists()


@_macos_only
def test_create_desktop_launcher_replaces_stale_command_symlink_on_unix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    # Simulate the previous-layout artifact: a Silentfrog.command symlink
    # on the Desktop from before the .app bundle migration.
    stale_target = root / "Silentfrog.command"
    stale_target.write_text("stale", encoding="utf-8")
    stale_link = desktop / "Silentfrog.command"
    stale_link.symlink_to(stale_target)
    launcher = create_desktop_launcher(root, system_name="Darwin", home=tmp_path)
    assert launcher.name == "Silentfrog.app"
    assert not stale_link.exists()


def test_write_launchers_keeps_macos_scripts_lf_only(tmp_path: Path) -> None:
    write_launchers(tmp_path)

    for filename in ("install_silentfrog.sh", "reinstall_silentfrog.sh", "run_silentfrog.sh"):
        assert b"\r\n" not in (tmp_path / filename).read_bytes()


_LAUNCHER_RENDERERS = {
    "run_silentfrog.bat": render_run_bat,
    "run_silentfrog.sh": render_run_sh,
    "install_silentfrog.bat": render_install_bat,
    "install_silentfrog.sh": render_install_sh,
    "install_silentfrog.command": render_install_command,
    "reinstall_silentfrog.sh": render_reinstall_sh,
    "reinstall_silentfrog.command": render_reinstall_command,
    "uninstall_silentfrog.bat": render_uninstall_bat,
    "uninstall_silentfrog.sh": render_uninstall_sh,
    "uninstall_silentfrog.command": render_uninstall_command,
}


@pytest.mark.parametrize("filename,renderer", sorted(_LAUNCHER_RENDERERS.items()))
def test_committed_launchers_match_render_output(filename: str, renderer) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    committed = (repo_root / filename).read_text(encoding="utf-8")
    assert committed == renderer(), f"{filename} on disk drifted from render_*(); re-run write_launchers() and commit"


def test_app_data_dir_for_windows(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = app_data_dir(system_name="Windows", home=home, env={"LOCALAPPDATA": str(tmp_path / "AppData")})
    assert result == tmp_path / "AppData" / "Silentfrog"


def test_app_data_dir_for_macos(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = app_data_dir(system_name="Darwin", home=home, env={})
    assert result == home / "Library" / "Application Support" / "Silentfrog"


def test_app_data_dir_for_linux(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = app_data_dir(system_name="Linux", home=home, env={"XDG_DATA_HOME": str(tmp_path / "xdg")})
    assert result == tmp_path / "xdg" / "silentfrog"


def test_app_data_dir_respects_override(tmp_path: Path) -> None:
    override = tmp_path / "custom"
    result = app_data_dir(system_name="Darwin", home=tmp_path, env={"SILENTFROG_DATA_DIR": str(override)})
    assert result == override


def test_uninstall_targets_collects_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    home = tmp_path / "home"
    targets = uninstall_targets(root, system_name="Darwin", home=home, env={})
    assert targets.venv_dir == root / ".venv"
    assert targets.desktop_command == home / "Desktop" / "Silentfrog.command"
    assert targets.desktop_lnk == home / "Desktop" / "Silentfrog.lnk"
    assert targets.user_data_dir == home / "Library" / "Application Support" / "Silentfrog"
    expected = set(launcher_script_paths(root))
    assert set(targets.launcher_scripts) == expected


def test_render_uninstall_sh_invokes_module() -> None:
    rendered = render_uninstall_sh()
    assert rendered.startswith("#!/bin/sh")
    assert "tools.source_uninstall" in rendered
    assert "python3.14" in rendered
    assert 'exec "$silentfrog_python" -m tools.source_uninstall "$@"' in rendered


def test_render_uninstall_command_waits_for_return() -> None:
    rendered = render_uninstall_command()
    assert "uninstall_silentfrog.sh" in rendered
    assert "Press Return to close this window." in rendered
    assert "preserved unless --purge" in rendered


def test_render_uninstall_bat_uses_module_dispatch() -> None:
    rendered = render_uninstall_bat()
    assert rendered.startswith("@echo off")
    assert "-m tools.source_uninstall" in rendered
    assert "where py" in rendered


def test_render_install_command_strips_quarantine() -> None:
    rendered = render_install_command()
    assert 'xattr -dr com.apple.quarantine "$script_dir"' in rendered
    assert ">/dev/null 2>&1 || true" in rendered


def test_render_reinstall_command_strips_quarantine() -> None:
    rendered = render_reinstall_command()
    assert 'xattr -dr com.apple.quarantine "$script_dir"' in rendered


@_macos_only
def test_detect_python_org_certificate_installer_for_each_minor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    for minor in ("3.12", "3.13", "3.14"):
        python_exe = Path(f"/Library/Frameworks/Python.framework/Versions/{minor}/bin/python3")
        result = detect_python_org_certificate_installer(python_exe)
        assert result == Path(f"/Applications/Python {minor}/Install Certificates.command")


def test_detect_python_org_certificate_installer_returns_none_for_brew_python() -> None:
    result = detect_python_org_certificate_installer(Path("/opt/homebrew/bin/python3.12"))
    assert result is None


def test_detect_python_org_certificate_installer_returns_none_when_installer_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    python_exe = Path("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3")
    assert detect_python_org_certificate_installer(python_exe) is None


def test_strip_quarantine_is_noop_on_non_darwin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.source_install.platform.system", lambda: "Linux")
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("tools.source_install.subprocess.run", fake_run)
    assert strip_quarantine(tmp_path) == 0
    assert called["value"] is False


def test_create_desktop_launcher_invokes_powershell_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr("tools.source_install.subprocess.run", fake_run)
    root = tmp_path / "repo"
    root.mkdir()
    result = create_desktop_launcher(root, system_name="Windows", home=tmp_path)
    assert result == tmp_path / "Desktop" / "Silentfrog.lnk"
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    joined = " ".join(cmd)
    assert "Silentfrog.lnk" in joined
    # Shortcut now targets the venv gui-script wrapper, not the .bat.
    assert "silentfrog.exe" in joined
    assert "run_silentfrog.bat" not in joined

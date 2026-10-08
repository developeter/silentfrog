from __future__ import annotations

import json
import platform
import subprocess
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

import tools.source_install as source_install
from tools.source_install import (
    DEFAULT_EXTRAS,
    ChromiumStatus,
    InstallSummary,
    RuntimeRequirements,
    _normalize_pep508,
    _parse_args,
    _run_chromium_post_step,
    _run_install_plan,
    _write_file,
    app_data_dir,
    create_desktop_launcher,
    create_macos_app_bundle,
    desktop_dir,
    detect_python_org_certificate_installer,
    install_plan,
    installer_paths,
    launcher_script_paths,
    load_runtime_requirements,
    post_install_plan,
    render_desktop_command_launcher,
    render_install_bat,
    render_install_command,
    render_install_sh,
    render_install_summary,
    render_macos_app_info_plist,
    render_macos_app_launcher,
    render_reinstall_command,
    render_reinstall_sh,
    render_run_bat,
    render_run_sh,
    render_uninstall_bat,
    render_uninstall_command,
    render_uninstall_sh,
    resolve_extras,
    step_label,
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
geo-render = [
    "playwright (>=1.43,<2.0)",
]
google = [
    "google-auth-oauthlib (>=1.4,<2)",
]
charts = [
    "pyqtgraph (>=0.13.7,<0.14)",
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
    # v1.1: switched from `--only-binary=:all:` (which broke on
    # extruct's pure-Python transitive deps like jstyleson that have
    # no wheels) to `--prefer-binary` + a targeted `--only-binary=`
    # allowlist for the heavy desktop deps. See tools/source_install.py.
    assert "--prefer-binary" in plan[2]
    targeted_only_binary = [arg for arg in plan[2] if arg.startswith("--only-binary=")]
    assert targeted_only_binary, "expected a targeted --only-binary list for heavy deps"
    # Heavy desktop deps stay wheel-only.
    for required in ("pyside6", "numpy", "lxml", "pillow"):
        assert required in targeted_only_binary[0]
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


def test_load_runtime_requirements_bundles_default_extras(tmp_path: Path) -> None:
    """Regression: a stock install used to skip every [project.optional-
    dependencies] extra, leaving the GEO rendering checkboxes and the
    'Connect Google...' button disabled after a fresh install."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_FAKE_PYPROJECT, encoding="utf-8")
    requirements = load_runtime_requirements(pyproject)
    assert requirements.extras == DEFAULT_EXTRAS
    assert "playwright>=1.43,<2.0" in requirements.pip_args
    assert "google-auth-oauthlib>=1.4,<2" in requirements.pip_args
    assert "pyqtgraph>=0.13.7,<0.14" in requirements.pip_args
    # stealth/embeddings stay opt-in, never bundled by default.
    assert not any("scrapling" in spec.lower() for spec in requirements.pip_args)
    assert not any("sentence-transformers" in spec.lower() for spec in requirements.pip_args)


def test_load_runtime_requirements_extras_none_yields_base_only(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_FAKE_PYPROJECT, encoding="utf-8")
    requirements = load_runtime_requirements(pyproject, extras=())
    assert requirements.extras == ()
    assert "pyside6>=6.8,<7.0" in requirements.pip_args
    assert not any("playwright" in spec.lower() for spec in requirements.pip_args)
    assert not any("google-auth-oauthlib" in spec.lower() for spec in requirements.pip_args)
    assert not any("pyqtgraph" in spec.lower() for spec in requirements.pip_args)


def test_load_runtime_requirements_rejects_unknown_extra(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_FAKE_PYPROJECT, encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unknown extra 'bogus'") as exc_info:
        load_runtime_requirements(pyproject, extras=("bogus",))
    message = str(exc_info.value)
    for name in ("geo-render", "google", "charts", "pyqt5-backend"):
        assert name in message


def test_install_plan_pulls_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(_FAKE_PYPROJECT, encoding="utf-8")
    plan = install_plan(tmp_path, "python3", "Darwin")
    assert "pyside6>=6.8,<7.0" in plan[2]
    assert "numpy>=2.2.6,<3.0.0" in plan[2]
    assert not any("pyqt5" in arg.lower() for arg in plan[2])
    # Default bundle: install_plan()'s indices/shape are unchanged (see
    # test_install_plan_targets_local_venv) but the pip install command now
    # carries the default extras' specs too.
    assert "playwright>=1.43,<2.0" in plan[2]


def test_post_install_plan_runs_chromium_only_when_geo_render_selected(tmp_path: Path) -> None:
    with_geo_render = RuntimeRequirements(pip_args=(), extras=("geo-render",))
    steps = post_install_plan(tmp_path, with_geo_render, "Darwin")
    assert len(steps) == 1
    assert steps[0] == [
        str(tmp_path / ".venv" / "bin" / "python"),
        "-m",
        "playwright",
        "install",
        "chromium",
    ]

    without_geo_render = RuntimeRequirements(pip_args=(), extras=("google", "charts"))
    assert post_install_plan(tmp_path, without_geo_render, "Darwin") == []


def test_parse_args_extras_accepts_none_and_comma_list() -> None:
    assert _parse_args(["--extras", "none"]).extras == "none"
    assert _parse_args(["--extras", "geo-render,google"]).extras == "geo-render,google"
    assert _parse_args([]).extras is None


def test_resolve_extras() -> None:
    assert resolve_extras(None) == DEFAULT_EXTRAS
    assert resolve_extras("none") == ()
    assert resolve_extras("None") == ()
    assert resolve_extras("geo-render, google") == ("geo-render", "google")
    assert resolve_extras("stealth") == ("stealth",)


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


def test_run_bat_launches_venv_exe_detached_without_holding_console() -> None:
    """Regression: run_silentfrog.bat used to `call` the windowed .exe and
    then `pause`, so a console stayed open for the whole app session
    (looked like "a cheap app" on Windows). It must now `start` the exe
    detached and return immediately on that path, with no pause; only the
    developer `poetry run` fallback keeps a console open.
    """
    run_bat = render_run_bat()
    venv_branch, _, fallback_branch = run_bat.partition("poetry run silentfrog")

    assert 'start "" "%LAUNCHER%" %*' in venv_branch
    assert "exit /b 0" in venv_branch
    assert 'call "%LAUNCHER%"' not in run_bat
    assert "pause" not in venv_branch
    assert "pause" in fallback_branch


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


# --- Installer feedback: .bat footer, CRLF launchers, summary, step labels ---


@pytest.mark.parametrize(
    "render,noun,rc_ref",
    [(render_install_bat, "install", "%SF_RC%"), (render_uninstall_bat, "uninstall", "!SF_RC!")],
)
def test_bat_footer_keeps_window_open_and_preserves_exit_code(render, noun: str, rc_ref: str) -> None:
    """Double-click used to flash a console and vanish; the footer must say
    whether it worked, wait for a key, and still hand the real code back."""
    lines = [line.strip() for line in render().splitlines()]
    guard = "if not defined SILENTFROG_NO_PAUSE if not defined CI pause"
    assert guard in lines
    assert f"exit /b {rc_ref}" in lines
    assert f"echo Silentfrog {noun} FAILED ^(exit code {rc_ref}^). Scroll up for the [{noun}] error above." in lines
    assert any(line.startswith(f"echo Silentfrog {noun} finished.") for line in lines)
    # Ordering: pause, then popd, then the preserved exit code last.
    assert lines.index(guard) < lines.index("popd") < lines.index(f"exit /b {rc_ref}")


def test_install_bat_captures_exit_code_right_after_python_call() -> None:
    rendered = render_install_bat()
    call_end = rendered.index("  python install_silentfrog.py %*")
    assert rendered.index('set "SF_RC=%errorlevel%"') > call_end
    assert "finished. You can close this window and start Silentfrog from the Desktop shortcut." in rendered


def test_uninstall_bat_runs_whole_body_in_one_block_because_it_deletes_itself() -> None:
    rendered = render_uninstall_bat()
    lines = rendered.splitlines()
    assert "setlocal EnableDelayedExpansion" in lines
    assert lines[3] == "(" and lines[-1] == ")"
    assert "py -3 -m tools.source_uninstall --keep-launcher uninstall_silentfrog.bat %*" in rendered
    assert "python -m tools.source_uninstall --keep-launcher uninstall_silentfrog.bat %*" in rendered


def test_run_bat_stays_detached_and_gets_no_install_footer() -> None:
    run_bat = render_run_bat()
    assert "SILENTFROG_NO_PAUSE" not in run_bat
    assert "SF_RC" not in run_bat
    venv_branch = run_bat.partition("poetry run silentfrog")[0]
    assert "pause" not in venv_branch
    assert 'start "" "%LAUNCHER%"' in run_bat


def test_write_file_uses_crlf_for_bat_and_lf_for_shell_launchers(tmp_path: Path) -> None:
    for name in ("a.bat", "b.sh", "c.command"):
        _write_file(tmp_path / name, "one\ntwo\n")
    assert (tmp_path / "a.bat").read_bytes() == b"one\r\ntwo\r\n"
    assert (tmp_path / "b.sh").read_bytes() == b"one\ntwo\n"
    assert (tmp_path / "c.command").read_bytes() == b"one\ntwo\n"


def test_write_launchers_writes_crlf_bat_and_lf_everything_else(tmp_path: Path) -> None:
    write_launchers(tmp_path)
    for path in sorted(tmp_path.iterdir()):
        data = path.read_bytes()
        if path.suffix == ".bat":
            assert data.count(b"\n") == data.count(b"\r\n") > 0, path.name
        else:
            assert b"\r" not in data, path.name


def test_gitattributes_pins_bat_to_crlf() -> None:
    attrs = (Path(__file__).resolve().parents[1] / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "*.bat text eol=crlf" in attrs
    assert "*.sh text eol=lf" in attrs


def _summary(**overrides) -> InstallSummary:
    fields = {
        "version": "2.0.0",
        "venv_dir": Path("C:/sf/.venv"),
        "python": Path("C:/sf/.venv/Scripts/python.exe"),
        "extras": ("geo-render", "google", "charts"),
        "chromium": ChromiumStatus.OK,
        "launcher": Path("C:/Users/me/Desktop/Silentfrog.lnk"),
        "run_hint": "run_silentfrog.bat",
    }
    fields.update(overrides)
    return InstallSummary(**fields)


def test_render_install_summary_full_success_block() -> None:
    lines = render_install_summary(_summary())
    assert all(line.startswith("[install] ") for line in lines)
    assert "Install complete" in lines[0]
    text = "\n".join(lines)
    assert "Silentfrog 2.0.0 installed in" in text
    assert "Optional extras: geo-render, google, charts" in text
    assert "Chromium for GEO rendering checks: OK" in text
    assert "Desktop launcher: " in text and "Silentfrog.lnk" in text
    assert lines[-1].endswith("or with: run_silentfrog.bat")


def test_render_install_summary_chromium_failed_carries_remedy_command() -> None:
    text = "\n".join(render_install_summary(_summary(chromium=ChromiumStatus.FAILED)))
    assert "Chromium for GEO rendering checks: FAILED - run: " in text
    assert "python.exe -m playwright install chromium" in text


def test_render_install_summary_chromium_not_requested_and_no_extras() -> None:
    text = "\n".join(render_install_summary(_summary(chromium=ChromiumStatus.NOT_REQUESTED, extras=())))
    assert "Chromium for GEO rendering checks: not requested" in text
    assert "Optional extras: none" in text


def test_render_install_summary_launcher_absent() -> None:
    text = "\n".join(render_install_summary(_summary(launcher=None)))
    assert "Desktop launcher: not created" in text


def test_step_labels_cover_every_install_plan_command(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(_FAKE_PYPROJECT, encoding="utf-8")
    plan = install_plan(tmp_path, "python")
    assert len(source_install._STEP_LABELS) == len(plan)
    assert step_label(1, 5) == "[install] Step 1/5: creating .venv"
    assert step_label(99, 100) == "[install] Step 99/100: running command"


def _record_runs(monkeypatch: pytest.MonkeyPatch, fail_at: int | None = None) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command, cwd) -> None:
        calls.append(list(command))
        if fail_at is not None and len(calls) == fail_at:
            raise subprocess.CalledProcessError(7, list(command))

    monkeypatch.setattr(source_install, "_run", fake_run)
    return calls


def test_run_install_plan_prints_step_labels_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_FAKE_PYPROJECT, encoding="utf-8")
    plan = install_plan(tmp_path, "python")
    calls = _record_runs(monkeypatch)

    _run_install_plan(tmp_path, plan)

    assert calls == plan
    labels = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[install] Step")]
    assert labels == [
        "[install] Step 1/5: creating .venv",
        "[install] Step 2/5: upgrading pip",
        "[install] Step 3/5: installing dependencies - this can take a few minutes",
        "[install] Step 4/5: installing Silentfrog",
        "[install] Step 5/5: verifying assets",
    ]


def _requirements(extras: tuple[str, ...]) -> RuntimeRequirements:
    return RuntimeRequirements(pip_args=(), extras=extras)


def test_run_chromium_post_step_returns_typed_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = installer_paths(tmp_path)
    calls = _record_runs(monkeypatch)
    assert _run_chromium_post_step(tmp_path, _requirements(()), paths) is ChromiumStatus.NOT_REQUESTED
    assert calls == []
    assert _run_chromium_post_step(tmp_path, _requirements(("geo-render",)), paths) is ChromiumStatus.OK
    assert calls[0][-3:] == ["playwright", "install", "chromium"]
    _record_runs(monkeypatch, fail_at=1)
    assert _run_chromium_post_step(tmp_path, _requirements(("geo-render",)), paths) is ChromiumStatus.FAILED


def _stub_main_side_effects(monkeypatch: pytest.MonkeyPatch, launcher: Path | None) -> None:
    monkeypatch.setattr(source_install, "_install_launchers", lambda root: launcher)
    monkeypatch.setattr(source_install, "_post_install_macos_helpers", lambda root, python: None)


def test_main_ends_with_summary_block_and_chromium_failure_stays_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    total = len(source_install._STEP_LABELS)
    _record_runs(monkeypatch, fail_at=total + 1)  # first post-install command = Chromium
    _stub_main_side_effects(monkeypatch, tmp_path / "Silentfrog.lnk")

    assert source_install.main([]) == 0

    out = capsys.readouterr().out.splitlines()
    banner = next(i for i, line in enumerate(out) if "Install complete" in line)
    repo_paths = installer_paths(Path(source_install.__file__).resolve().parents[1])
    expected = InstallSummary(
        version=source_install.project_version(),
        venv_dir=repo_paths.venv_dir,
        python=repo_paths.python,
        extras=DEFAULT_EXTRAS,
        chromium=ChromiumStatus.FAILED,
        launcher=tmp_path / "Silentfrog.lnk",
        run_hint="run_silentfrog.bat" if source_install.is_windows() else "./run_silentfrog.sh",
    )
    assert out[banner:] == render_install_summary(expected)
    assert any(f"Step {total}/{total}" in line for line in out[:banner])
    assert "Install FAILED" not in "\n".join(out)


def test_main_fail_hard_step_prints_reason_and_returns_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_runs(monkeypatch, fail_at=2)
    _stub_main_side_effects(monkeypatch, None)

    assert source_install.main([]) == 7

    out = capsys.readouterr().out
    assert "[install] Install FAILED: command exited with code 7." in out
    assert "Install complete" not in out

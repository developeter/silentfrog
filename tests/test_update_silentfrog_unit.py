from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.update_silentfrog import (  # noqa: E402
    _ensure_executable_launchers,
    _install_runtime_deps,
    _refresh_install,
    _runtime_dep_specs,
    _sync_site_packages,
    _venv_site_packages,
)


def _make_user_install(root: Path) -> None:
    """Create the minimal directory layout the updater expects."""
    src_pkg = root / "src" / "silentfrog"
    src_pkg.mkdir(parents=True)
    (src_pkg / "gui.py").write_text("# new gui\n", encoding="utf-8")
    (src_pkg / "updater.py").write_text("# new updater\n", encoding="utf-8")
    sub = src_pkg / "exporters"
    sub.mkdir()
    (sub / "action_workbook.py").write_text("# new workbook\n", encoding="utf-8")
    # Synthesise the windows-style site-packages so the helper can find it
    # without requiring an actual .venv on disk.
    target_pkg = root / ".venv" / "Lib" / "site-packages" / "silentfrog"
    target_pkg.mkdir(parents=True)
    (target_pkg / "gui.py").write_text("# old gui\n", encoding="utf-8")
    (target_pkg / "updater.py").write_text("# old updater\n", encoding="utf-8")
    (target_pkg / "exporters").mkdir()
    (target_pkg / "exporters" / "action_workbook.py").write_text("# old workbook\n", encoding="utf-8")


def test_sync_site_packages_overwrites_installed_files(tmp_path: Path, monkeypatch) -> None:
    """Regression: replaces ``pip install . --no-deps`` which was
    failing on Windows when the GUI was still running. Pure file copy
    leaves the package importable even on partial failure.
    """
    monkeypatch.setattr(
        "tools.update_silentfrog._venv_site_packages",
        lambda root: tmp_path / ".venv" / "Lib" / "site-packages",
    )
    _make_user_install(tmp_path)
    exit_code = _sync_site_packages(tmp_path)
    assert exit_code == 0
    sp = tmp_path / ".venv" / "Lib" / "site-packages" / "silentfrog"
    assert (sp / "gui.py").read_text(encoding="utf-8") == "# new gui\n"
    assert (sp / "updater.py").read_text(encoding="utf-8") == "# new updater\n"
    assert (sp / "exporters" / "action_workbook.py").read_text(encoding="utf-8") == "# new workbook\n"


def test_sync_site_packages_skips_pycache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.update_silentfrog._venv_site_packages",
        lambda root: tmp_path / ".venv" / "Lib" / "site-packages",
    )
    _make_user_install(tmp_path)
    pycache = tmp_path / "src" / "silentfrog" / "__pycache__"
    pycache.mkdir()
    (pycache / "gui.cpython-312.pyc").write_bytes(b"old-bytecode")
    exit_code = _sync_site_packages(tmp_path)
    assert exit_code == 0
    target_pycache = tmp_path / ".venv" / "Lib" / "site-packages" / "silentfrog" / "__pycache__"
    assert not target_pycache.exists(), "__pycache__ must not be copied"


def test_sync_site_packages_fails_clearly_when_source_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "tools.update_silentfrog._venv_site_packages",
        lambda root: tmp_path / ".venv" / "Lib" / "site-packages",
    )
    (tmp_path / ".venv" / "Lib" / "site-packages" / "silentfrog").mkdir(parents=True)
    exit_code = _sync_site_packages(tmp_path)
    assert exit_code == 1
    assert "source package missing" in capsys.readouterr().out


def test_sync_site_packages_fails_clearly_when_target_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "tools.update_silentfrog._venv_site_packages",
        lambda root: tmp_path / ".venv" / "Lib" / "site-packages",
    )
    (tmp_path / "src" / "silentfrog").mkdir(parents=True)
    (tmp_path / "src" / "silentfrog" / "gui.py").write_text("x", encoding="utf-8")
    exit_code = _sync_site_packages(tmp_path)
    assert exit_code == 1
    assert "installed package missing" in capsys.readouterr().out


def test_venv_site_packages_windows_path() -> None:
    import os

    if os.name != "nt":
        pytest.skip("Windows-specific path layout")
    repo = Path("C:/users/dev/silentfrog")
    assert _venv_site_packages(repo) == repo / ".venv" / "Lib" / "site-packages"


def test_runtime_dep_specs_reads_project_dependencies(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "x"\n'
        "dependencies = [\n"
        '    "extruct (>=0.16.0,<0.17.0)",\n'
        '    "w3lib (>=2.1.0,<3.0.0)",\n'
        "]\n",
        encoding="utf-8",
    )
    assert _runtime_dep_specs(pyproject) == [
        "extruct (>=0.16.0,<0.17.0)",
        "w3lib (>=2.1.0,<3.0.0)",
    ]


def test_runtime_dep_specs_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _runtime_dep_specs(tmp_path / "missing.toml") == []


def test_install_runtime_deps_calls_pip_with_named_specs(tmp_path: Path, monkeypatch, capsys) -> None:
    """Regression for exit-code-4 file-lock failure: the deps_changed
    path must NOT run `pip install .` (which uninstalls silentfrog and
    fails on Windows when the GUI is running). It must run direct
    `pip install <spec>` which never touches the wrapper exe.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\ndependencies = ["extruct (>=0.16.0,<0.17.0)"]\n',
        encoding="utf-8",
    )
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    monkeypatch.setattr("os.name", "nt")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        captured["cwd"] = str(cwd)
        return 0

    monkeypatch.setattr("tools.update_silentfrog._run", fake_run)

    exit_code = _install_runtime_deps(tmp_path)

    assert exit_code == 0
    assert "pip" in captured["cmd"]
    assert "install" in captured["cmd"]
    assert "--upgrade" in captured["cmd"]
    # The package install spec must be present; "." must NOT be there
    # (that would rebuild silentfrog and trigger the file-lock failure).
    assert "extruct (>=0.16.0,<0.17.0)" in captured["cmd"]
    assert "." not in captured["cmd"]


def test_refresh_install_deps_changed_uses_direct_pip_not_full_reinstall(tmp_path: Path, monkeypatch) -> None:
    """Both the deps-changed and deps-unchanged paths must avoid
    `install_silentfrog.py` / `pip install .` so silentfrog.exe is never
    overwritten while the GUI is running.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = ["aiohttp"]\n', encoding="utf-8")
    _make_user_install(tmp_path)
    monkeypatch.setattr(
        "tools.update_silentfrog._venv_site_packages",
        lambda root: tmp_path / ".venv" / "Lib" / "site-packages",
    )
    monkeypatch.setattr("os.name", "nt")
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")

    calls: list[list[str]] = []
    monkeypatch.setattr("tools.update_silentfrog._run", lambda cmd, cwd: calls.append(cmd) or 0)

    exit_code = _refresh_install(tmp_path, deps_changed=True)

    assert exit_code == 0
    # Exactly one pip invocation; it targets the named dep, not ".".
    assert len(calls) == 1
    assert "install_silentfrog.py" not in calls[0]
    assert "." not in calls[0]
    assert "aiohttp" in calls[0]


def test_refresh_install_deps_unchanged_skips_pip_entirely(tmp_path: Path, monkeypatch) -> None:
    _make_user_install(tmp_path)
    monkeypatch.setattr(
        "tools.update_silentfrog._venv_site_packages",
        lambda root: tmp_path / ".venv" / "Lib" / "site-packages",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr("tools.update_silentfrog._run", lambda cmd, cwd: calls.append(cmd) or 0)

    exit_code = _refresh_install(tmp_path, deps_changed=False)

    assert exit_code == 0
    assert calls == [], "deps_changed=False must not invoke pip"


def test_ensure_executable_launchers_restores_x_bit(tmp_path: Path) -> None:
    """GitHub zip archives drop POSIX +x; the post-sync hook must restore it."""
    import os
    import stat as _stat

    if os.name == "nt":
        pytest.skip("POSIX-only permission semantics")
    # Drop a representative subset of launcher files at the install root
    # with the same `-rw-r--r--` mode the Apply step leaves behind.
    targets = {
        "run_silentfrog.sh": "#!/bin/sh\necho run\n",
        "install_silentfrog.command": "#!/bin/sh\necho install\n",
        "uninstall_silentfrog.sh": "#!/bin/sh\necho uninstall\n",
    }
    for name, body in targets.items():
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o644)
    # Files outside the executable-launchers set must be left alone.
    bat = tmp_path / "run_silentfrog.bat"
    bat.write_text("@echo off\n", encoding="utf-8")
    bat.chmod(0o644)

    _ensure_executable_launchers(tmp_path)

    bits = _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH
    for name in targets:
        mode = (tmp_path / name).stat().st_mode
        assert mode & bits == bits, name
    # .bat is in the launcher list but its suffix is not executable on macOS.
    assert (tmp_path / "run_silentfrog.bat").stat().st_mode & bits == 0

from __future__ import annotations

from pathlib import Path

from tools.package_app import PackagePaths, package_command, package_paths


def test_package_paths_uses_os_scoped_build_dir(tmp_path: Path) -> None:
    paths = package_paths(tmp_path, "Darwin")

    assert paths.entrypoint == tmp_path / "deploy" / "main.py"
    assert paths.build_dir == tmp_path / "build" / "package" / "darwin"


def test_package_command_uses_pyside6_deploy_defaults(tmp_path: Path) -> None:
    paths = PackagePaths(
        root=tmp_path,
        entrypoint=tmp_path / "deploy" / "main.py",
        build_dir=tmp_path / "build" / "package" / "windows",
    )

    command = package_command(paths, mode="standalone", dry_run=True, keep_files=True)

    assert command[:4] == ["pyside6-deploy", str(paths.entrypoint), "--force", "--name"]
    assert "Silentfrog" in command
    assert "--mode" in command
    assert "standalone" in command
    assert "--dry-run" in command
    assert "--keep-deployment-files" in command
    assert "--extra-ignore-dirs" in command

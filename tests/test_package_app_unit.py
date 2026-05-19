from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.package_app import (
    ArtifactPlan,
    IconAssets,
    PackagePaths,
    _arch_label,
    _resolve_icon,
    artifact_plan,
    build_zip,
    deployment_output_dir,
    finalize_windows_output,
    hdiutil_command,
    icon_assets,
    load_project_version,
    materialize_spec,
    nuitka_data_dir_args,
    package_command,
    package_paths,
    select_icon_for_os,
    stage_entrypoint,
    staged_entrypoint,
)


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
    assert "--icon" not in command


def test_package_command_passes_config_file_when_provided(tmp_path: Path) -> None:
    paths = PackagePaths(
        root=tmp_path,
        entrypoint=tmp_path / "deploy" / "main.py",
        build_dir=tmp_path / "build" / "package" / "darwin",
    )
    spec = tmp_path / "pysidedeploy.spec"
    command = package_command(
        paths,
        mode="standalone",
        dry_run=False,
        keep_files=False,
        config_file=spec,
    )
    assert "-c" in command
    idx = command.index("-c")
    assert command[idx + 1] == str(spec)


def test_materialize_spec_rewrites_icon(tmp_path: Path) -> None:
    template = tmp_path / "pysidedeploy.spec"
    template.write_text(
        "[app]\nicon = src/silentfrog/assets/icon.png\n[nuitka]\nmode = standalone\n",
        encoding="utf-8",
    )
    dest = tmp_path / "build" / "pysidedeploy.spec"
    icon = tmp_path / "rendered.icns"
    materialize_spec(template, dest, icon)
    text = dest.read_text(encoding="utf-8")
    assert f"icon = {icon}" in text
    assert "src/silentfrog/assets/icon.png" not in text
    assert "[nuitka]" in text


def test_materialize_spec_leaves_template_icon_when_none(tmp_path: Path) -> None:
    template = tmp_path / "pysidedeploy.spec"
    body = "[app]\nicon = original.png\n"
    template.write_text(body, encoding="utf-8")
    dest = tmp_path / "build" / "pysidedeploy.spec"
    materialize_spec(template, dest, None)
    assert dest.read_text(encoding="utf-8") == body


def test_materialize_spec_rewrites_project_dir_and_input_file(tmp_path: Path) -> None:
    template = tmp_path / "pysidedeploy.spec"
    template.write_text(
        "[app]\nproject_dir = .\ninput_file = deploy/main.py\nicon = src/icon.png\n",
        encoding="utf-8",
    )
    dest = tmp_path / "build" / "pysidedeploy.spec"
    project_dir = tmp_path / "repo"
    input_file = project_dir / "build" / "main.py"
    materialize_spec(template, dest, None, project_dir=project_dir, input_file=input_file)
    text = dest.read_text(encoding="utf-8")
    assert f"project_dir = {project_dir}" in text
    assert f"input_file = {input_file}" in text


@pytest.mark.parametrize(
    "path_text",
    [
        r"C:\Users\dev\repo\icon.ico",
        r"D:\nightly\build\main.py",
        r"E:\path\g_with_\group_ref_like_chars",
    ],
)
def test_materialize_spec_accepts_windows_style_paths(
    tmp_path: Path, path_text: str
) -> None:
    """Regression: re.sub replacement strings must not interpret backslash escapes
    (e.g. ``\\U`` from ``C:\\Users\\...``, or ``\\g`` which is a regex group ref)
    as regex backreferences.
    """
    template = tmp_path / "pysidedeploy.spec"
    template.write_text(
        "[app]\nicon = orig.png\ninput_file = deploy/main.py\n",
        encoding="utf-8",
    )
    dest = tmp_path / "build" / "pysidedeploy.spec"
    win_like = Path(path_text)
    materialize_spec(template, dest, icon=win_like, input_file=win_like)
    text = dest.read_text(encoding="utf-8")
    assert f"icon = {win_like}" in text
    assert f"input_file = {win_like}" in text


def test_stage_entrypoint_copies_main_into_build_dir(tmp_path: Path) -> None:
    paths = PackagePaths(
        root=tmp_path,
        entrypoint=tmp_path / "deploy" / "main.py",
        build_dir=tmp_path / "build" / "package" / "darwin",
    )
    paths.entrypoint.parent.mkdir(parents=True)
    paths.entrypoint.write_text("from silentfrog.gui import main\n", encoding="utf-8")
    staged = stage_entrypoint(paths)
    assert staged == staged_entrypoint(paths)
    assert staged.is_file()
    assert staged.read_text(encoding="utf-8") == paths.entrypoint.read_text(encoding="utf-8")


def test_icon_assets_resolves_default_locations(tmp_path: Path) -> None:
    assets = icon_assets(tmp_path)
    assert assets.png == tmp_path / "src" / "silentfrog" / "assets" / "icon.png"
    assert assets.ico == tmp_path / "src" / "silentfrog" / "assets" / "icon.ico"
    assert assets.icns == tmp_path / "src" / "silentfrog" / "assets" / "icon.icns"


def test_select_icon_for_os_per_platform(tmp_path: Path) -> None:
    assets = IconAssets(png=tmp_path / "a.png", ico=tmp_path / "a.ico", icns=tmp_path / "a.icns")
    assert select_icon_for_os(assets, "Darwin") == assets.icns
    assert select_icon_for_os(assets, "Windows") == assets.ico
    assert select_icon_for_os(assets, "Linux") == assets.png


def test_resolve_icon_skips_when_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.package_app.platform.system", lambda: "Linux")
    icon = _resolve_icon(tmp_path, dry_run=False, skip_icon_build=False)
    assert icon is None


def test_resolve_icon_returns_ico_on_windows_when_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.package_app.platform.system", lambda: "Windows")
    assets_dir = tmp_path / "src" / "silentfrog" / "assets"
    assets_dir.mkdir(parents=True)
    ico = assets_dir / "icon.ico"
    ico.write_bytes(b"\x00")
    icon = _resolve_icon(tmp_path, dry_run=False, skip_icon_build=False)
    assert icon == ico


def test_resolve_icon_skips_icns_build_on_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.package_app.platform.system", lambda: "Darwin")
    called = {"value": False}

    def fake_ensure(_assets):
        called["value"] = True
        raise AssertionError("ensure_macos_icns should not run during dry-run")

    monkeypatch.setattr("tools.package_app.ensure_macos_icns", fake_ensure)
    assets_dir = tmp_path / "src" / "silentfrog" / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "icon.png").write_bytes(b"")
    _resolve_icon(tmp_path, dry_run=True, skip_icon_build=False)
    assert called["value"] is False


def test_pysidedeploy_spec_present_at_repo_root() -> None:
    spec = _REPO_ROOT / "pysidedeploy.spec"
    assert spec.is_file()
    text = spec.read_text(encoding="utf-8")
    assert "Silentfrog" in text
    assert "deploy/main.py" in text
    assert "--nofollow-import-to=pyRdfa" in text


def test_load_project_version_reads_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "silentfrog"\nversion = "9.9.9"\ndependencies = []\n',
        encoding="utf-8",
    )
    assert load_project_version(pyproject) == "9.9.9"


def test_load_project_version_raises_when_missing(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = []\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"\[project\].version"):
        load_project_version(pyproject)


def test_arch_label_per_platform() -> None:
    assert _arch_label("Darwin", "arm64") == "arm64"
    assert _arch_label("Darwin", "x86_64") == "intel"
    assert _arch_label("Windows", "AMD64") == "x64"
    assert _arch_label("Linux", "x86_64") == "x86_64"


def test_artifact_plan_for_macos_apple_silicon(tmp_path: Path) -> None:
    paths = PackagePaths(
        root=tmp_path,
        entrypoint=tmp_path / "deploy" / "main.py",
        build_dir=tmp_path / "build" / "package" / "darwin",
    )
    plan = artifact_plan(paths, "Darwin", "1.2.3", machine="arm64")
    assert plan.kind == "dmg"
    assert plan.output == paths.build_dir / "Silentfrog-1.2.3-macos-arm64.dmg"
    assert plan.source == deployment_output_dir(paths) / "Silentfrog.app"
    assert plan.version == "1.2.3"


def test_artifact_plan_for_macos_intel(tmp_path: Path) -> None:
    paths = PackagePaths(
        root=tmp_path,
        entrypoint=tmp_path / "deploy" / "main.py",
        build_dir=tmp_path / "build" / "package" / "darwin",
    )
    plan = artifact_plan(paths, "Darwin", "1.0.0", machine="x86_64")
    assert plan.output.name == "Silentfrog-1.0.0-macos-intel.dmg"


def test_artifact_plan_for_windows_zip(tmp_path: Path) -> None:
    paths = PackagePaths(
        root=tmp_path,
        entrypoint=tmp_path / "deploy" / "main.py",
        build_dir=tmp_path / "build" / "package" / "windows",
    )
    plan = artifact_plan(paths, "Windows", "1.0.0", machine="AMD64")
    assert plan.kind == "zip"
    assert plan.output.name == "Silentfrog-1.0.0-windows-x64.zip"
    assert plan.source == deployment_output_dir(paths) / "Silentfrog"


def test_hdiutil_command_uses_udzo_format(tmp_path: Path) -> None:
    plan = ArtifactPlan(
        kind="dmg",
        source=tmp_path / "Silentfrog.app",
        output=tmp_path / "Silentfrog-1.0.0-macos-arm64.dmg",
        version="1.0.0",
    )
    staging = tmp_path / "staging"
    cmd = hdiutil_command(plan, staging)
    assert cmd[0] == "hdiutil"
    assert cmd[1] == "create"
    assert "-volname" in cmd and "Silentfrog" in cmd
    assert "-srcfolder" in cmd
    idx = cmd.index("-srcfolder")
    assert cmd[idx + 1] == str(staging)
    assert "-format" in cmd
    idx = cmd.index("-format")
    assert cmd[idx + 1] == "UDZO"
    assert cmd[-1] == str(plan.output)


def test_finalize_windows_output_renames_dist_to_final(tmp_path: Path) -> None:
    paths = package_paths(tmp_path, "Windows")
    paths.build_dir.mkdir(parents=True, exist_ok=True)
    dist = paths.build_dir / "Silentfrog.dist"
    dist.mkdir()
    (dist / "Silentfrog.exe").write_bytes(b"MZ\x90\x00")
    finalize_windows_output(paths, "Windows")
    final = paths.build_dir / "Silentfrog"
    assert final.is_dir()
    assert (final / "Silentfrog.exe").is_file()
    assert not dist.exists()


def test_finalize_windows_output_raises_when_no_output_produced(tmp_path: Path) -> None:
    paths = package_paths(tmp_path, "Windows")
    paths.build_dir.mkdir(parents=True, exist_ok=True)
    # Empty .dist as pyside6-deploy leaves it when Nuitka silently failed.
    (paths.build_dir / "Silentfrog.dist").mkdir()
    with pytest.raises(RuntimeError, match="did not produce a non-empty"):
        finalize_windows_output(paths, "Windows")


def test_finalize_windows_output_is_noop_on_non_windows(tmp_path: Path) -> None:
    paths = package_paths(tmp_path, "Darwin")
    # No artifacts created; non-Windows should not raise.
    finalize_windows_output(paths, "Darwin")
    finalize_windows_output(paths, "Linux")


def test_finalize_windows_output_is_idempotent_when_final_already_exists(
    tmp_path: Path,
) -> None:
    paths = package_paths(tmp_path, "Windows")
    paths.build_dir.mkdir(parents=True, exist_ok=True)
    final = paths.build_dir / "Silentfrog"
    final.mkdir()
    (final / "Silentfrog.exe").write_bytes(b"MZ\x90\x00")
    finalize_windows_output(paths, "Windows")
    assert (final / "Silentfrog.exe").is_file()


def test_build_zip_creates_archive(tmp_path: Path) -> None:
    source = tmp_path / "Silentfrog"
    source.mkdir()
    (source / "marker.txt").write_text("hello", encoding="utf-8")
    plan = ArtifactPlan(
        kind="zip",
        source=source,
        output=tmp_path / "Silentfrog-1.0.0-linux-x86_64.zip",
        version="1.0.0",
    )
    result = build_zip(plan)
    assert result == plan.output
    assert plan.output.is_file()
    assert plan.output.stat().st_size > 0


def test_nuitka_data_dir_args_includes_assets_and_resources(tmp_path: Path) -> None:
    (tmp_path / "src" / "silentfrog" / "assets").mkdir(parents=True)
    (tmp_path / "src" / "silentfrog" / "resources").mkdir(parents=True)
    args = nuitka_data_dir_args(tmp_path)
    joined = " ".join(args)
    assets_src = (tmp_path / "src" / "silentfrog" / "assets").resolve().as_posix()
    resources_src = (tmp_path / "src" / "silentfrog" / "resources").resolve().as_posix()
    # pyside6-deploy shlex-splits extra_args (POSIX mode), so:
    #  (a) emitted paths must not contain backslashes even on Windows, and
    #  (b) round-tripping through shlex.split must reconstruct the original args.
    assert "\\" not in joined
    import shlex as _shlex

    parsed = _shlex.split(joined)
    assert f"--include-data-dir={assets_src}=silentfrog/assets" in parsed
    assert f"--include-data-dir={resources_src}=silentfrog/resources" in parsed


def test_nuitka_data_dir_args_survives_space_in_project_path(tmp_path: Path) -> None:
    """A repo path like ``C:\\Users\\dev\\silentfrog 2`` must survive
    pyside6-deploy's POSIX shlex.split of extra_args.
    """
    project = tmp_path / "silentfrog 2"
    (project / "src" / "silentfrog" / "assets").mkdir(parents=True)
    (project / "src" / "silentfrog" / "resources").mkdir(parents=True)
    args = nuitka_data_dir_args(project)
    joined = " ".join(args)
    import shlex as _shlex

    parsed = _shlex.split(joined)
    assets_src = (project / "src" / "silentfrog" / "assets").resolve().as_posix()
    resources_src = (project / "src" / "silentfrog" / "resources").resolve().as_posix()
    assert f"--include-data-dir={assets_src}=silentfrog/assets" in parsed
    assert f"--include-data-dir={resources_src}=silentfrog/resources" in parsed


def test_materialize_spec_appends_data_dir_args(tmp_path: Path) -> None:
    template = tmp_path / "pysidedeploy.spec"
    template.write_text(
        "[app]\nproject_dir = .\ninput_file = main.py\nicon = src/icon.png\n"
        "[nuitka]\nextra_args = --quiet --nofollow-import-to=pyRdfa\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "silentfrog" / "assets").mkdir(parents=True)
    (tmp_path / "src" / "silentfrog" / "resources").mkdir(parents=True)
    dest = tmp_path / "build" / "pysidedeploy.spec"
    materialize_spec(template, dest, None, project_dir=tmp_path, input_file=tmp_path / "main.py")
    text = dest.read_text(encoding="utf-8")
    assert "--quiet --nofollow-import-to=pyRdfa" in text
    assert "--include-data-dir=" in text
    assert "silentfrog/assets" in text
    assert "silentfrog/resources" in text


def test_build_zip_dry_run_does_not_create_archive(tmp_path: Path) -> None:
    source = tmp_path / "Silentfrog"
    source.mkdir()
    plan = ArtifactPlan(
        kind="zip",
        source=source,
        output=tmp_path / "Silentfrog-1.0.0.zip",
        version="1.0.0",
    )
    build_zip(plan, dry_run=True)
    assert not plan.output.exists()

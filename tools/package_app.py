from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


_APP_BUNDLE_NAME = "Silentfrog.app"
_WINDOWS_DIST_NAME = "Silentfrog"

# Data directories under src/silentfrog/ that ship via importlib.resources at
# runtime. Nuitka's --follow-imports walks only .py files, so each non-Python
# data tree must be passed explicitly via --include-data-dir.
_BUNDLED_DATA_DIRS = (
    ("src/silentfrog/assets", "silentfrog/assets"),
    ("src/silentfrog/resources", "silentfrog/resources"),
)


_ICONSET_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


@dataclass(frozen=True)
class PackagePaths:
    root: Path
    entrypoint: Path
    build_dir: Path


@dataclass(frozen=True)
class IconAssets:
    png: Path
    ico: Path
    icns: Path


@dataclass(frozen=True)
class ArtifactPlan:
    kind: str
    source: Path
    output: Path
    version: str


def load_project_version(pyproject: Path) -> str:
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    project = data.get("project")
    if not isinstance(project, dict):
        raise RuntimeError(f"pyproject.toml has no [project] table: {pyproject}")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"pyproject.toml has no [project].version: {pyproject}")
    return version


def deployment_output_dir(paths: "PackagePaths") -> Path:
    """Where pyside6-deploy lands the finalized app bundle / dist folder.

    Nuitka's intermediate output goes under build_dir/deployment, but
    pyside6-deploy renames the final artifact into build_dir itself.
    """
    return paths.build_dir


def _arch_label(system_name: str, machine: str | None = None) -> str:
    name = system_name.lower()
    if name == "darwin":
        cpu = (machine or platform.machine()).lower()
        if cpu in ("arm64", "aarch64"):
            return "arm64"
        return "intel"
    if name.startswith("win"):
        return "x64"
    return (machine or platform.machine()).lower()


def artifact_plan(
    paths: "PackagePaths",
    system_name: str,
    version: str,
    machine: str | None = None,
) -> ArtifactPlan:
    name = system_name.lower()
    deployment = deployment_output_dir(paths)
    arch = _arch_label(system_name, machine)
    if name == "darwin":
        return ArtifactPlan(
            kind="dmg",
            source=deployment / _APP_BUNDLE_NAME,
            output=paths.build_dir / f"Silentfrog-{version}-macos-{arch}.dmg",
            version=version,
        )
    if name.startswith("win"):
        return ArtifactPlan(
            kind="zip",
            source=deployment / _WINDOWS_DIST_NAME,
            output=paths.build_dir / f"Silentfrog-{version}-windows-{arch}.zip",
            version=version,
        )
    return ArtifactPlan(
        kind="zip",
        source=deployment / _WINDOWS_DIST_NAME,
        output=paths.build_dir / f"Silentfrog-{version}-linux-{arch}.zip",
        version=version,
    )


def hdiutil_command(plan: ArtifactPlan, staging: Path) -> list[str]:
    return [
        "hdiutil",
        "create",
        "-volname",
        "Silentfrog",
        "-srcfolder",
        str(staging),
        "-ov",
        "-format",
        "UDZO",
        str(plan.output),
    ]


def build_dmg(plan: ArtifactPlan, dry_run: bool = False) -> Path:
    staging = plan.output.parent / f"_dmg_staging_{plan.version}"
    if not dry_run:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        shutil.copytree(plan.source, staging / _APP_BUNDLE_NAME)
        applications_link = staging / "Applications"
        if not applications_link.exists():
            applications_link.symlink_to("/Applications")
    cmd = hdiutil_command(plan, staging)
    print(f"[package] {' '.join(cmd)}")
    if not dry_run:
        subprocess.run(cmd, check=True)
        shutil.rmtree(staging, ignore_errors=True)
    return plan.output


def build_zip(plan: ArtifactPlan, dry_run: bool = False) -> Path:
    base = plan.output.with_suffix("")
    print(f"[package] make_archive zip {plan.source} -> {plan.output}")
    if dry_run:
        return plan.output
    if plan.output.exists():
        plan.output.unlink()
    shutil.make_archive(str(base), "zip", root_dir=str(plan.source.parent), base_dir=plan.source.name)
    return plan.output


def build_artifact(plan: ArtifactPlan, dry_run: bool = False) -> Path:
    if plan.kind == "dmg":
        return build_dmg(plan, dry_run=dry_run)
    if plan.kind == "zip":
        return build_zip(plan, dry_run=dry_run)
    raise RuntimeError(f"Unknown artifact kind: {plan.kind}")


def package_paths(root: Path, system_name: str | None = None) -> PackagePaths:
    target = (system_name or platform.system()).lower()
    return PackagePaths(
        root=root,
        entrypoint=root / "deploy" / "main.py",
        build_dir=root / "build" / "package" / target,
    )


def staged_entrypoint(paths: PackagePaths) -> Path:
    return paths.build_dir / "main.py"


def icon_assets(root: Path) -> IconAssets:
    assets = root / "src" / "silentfrog" / "assets"
    return IconAssets(
        png=assets / "icon.png",
        ico=assets / "icon.ico",
        icns=assets / "icon.icns",
    )


def select_icon_for_os(assets: IconAssets, system_name: str | None = None) -> Path:
    name = (system_name or platform.system()).lower()
    if name == "darwin":
        return assets.icns
    if name.startswith("win"):
        return assets.ico
    return assets.png


def ensure_macos_icns(assets: IconAssets) -> Path:
    if assets.icns.is_file() and assets.icns.stat().st_mtime >= assets.png.stat().st_mtime:
        return assets.icns
    iconset_dir = assets.png.parent / "icon.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True, exist_ok=True)
    try:
        for filename, size in _ICONSET_SIZES:
            target = iconset_dir / filename
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(assets.png), "--out", str(target)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(assets.icns)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        shutil.rmtree(iconset_dir, ignore_errors=True)
    return assets.icns


def package_command(
    paths: PackagePaths,
    mode: str,
    dry_run: bool,
    keep_files: bool,
    icon: Path | None = None,
    config_file: Path | None = None,
) -> list[str]:
    command = [
        "pyside6-deploy",
        str(paths.entrypoint),
        "--force",
        "--name",
        "Silentfrog",
        "--mode",
        mode,
        "--extra-ignore-dirs",
        ".git,.github,.venv,build,dist,docs,tests,__pycache__",
    ]
    if config_file is not None:
        command.extend(["-c", str(config_file)])
    if keep_files:
        command.append("--keep-deployment-files")
    if dry_run:
        command.append("--dry-run")
    return command


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package Silentfrog with pyside6-deploy")
    parser.add_argument("--mode", choices=("onefile", "standalone"), default="standalone")
    parser.add_argument("--dry-run", action="store_true", help="Print the pyside6-deploy commands without building")
    parser.add_argument(
        "--keep-deployment-files",
        action="store_true",
        help="Preserve intermediate deployment files generated by pyside6-deploy",
    )
    parser.add_argument(
        "--skip-icon-build",
        action="store_true",
        help="Skip macOS icon.icns regeneration even on Darwin",
    )
    parser.add_argument(
        "--skip-artifact",
        action="store_true",
        help="Build the packaged app but do not produce the DMG/ZIP artifact",
    )
    parser.add_argument(
        "--artifact-only",
        action="store_true",
        help="Assume the packaged app already exists in build/package/<os>/deployment and only build the DMG/ZIP",
    )
    return parser.parse_args(argv)


def _resolve_icon(root: Path, dry_run: bool, skip_icon_build: bool) -> Path | None:
    assets = icon_assets(root)
    system = platform.system()
    if system.lower() == "darwin" and not skip_icon_build and not dry_run:
        try:
            ensure_macos_icns(assets)
        except subprocess.CalledProcessError as exc:
            print(f"[package] icon.icns generation failed: {exc}; falling back to icon.png")
    icon = select_icon_for_os(assets, system)
    if icon.is_file():
        return icon
    return assets.png if assets.png.is_file() else None


def nuitka_data_dir_args(project_dir: Path) -> tuple[str, ...]:
    return tuple(
        f"--include-data-dir={(project_dir / src).resolve()}={dest}"
        for src, dest in _BUNDLED_DATA_DIRS
    )


def materialize_spec(
    template: Path,
    dest: Path,
    icon: Path | None,
    project_dir: Path | None = None,
    input_file: Path | None = None,
) -> Path:
    text = template.read_text(encoding="utf-8")
    if icon is not None:
        text = re.sub(r"(?m)^icon\s*=.*$", f"icon = {icon}", text, count=1)
    if project_dir is not None:
        text = re.sub(r"(?m)^project_dir\s*=.*$", f"project_dir = {project_dir}", text, count=1)
        data_args = " ".join(nuitka_data_dir_args(project_dir))
        text = re.sub(
            r"(?m)^(extra_args\s*=.*)$",
            lambda m: f"{m.group(1)} {data_args}",
            text,
            count=1,
        )
    if input_file is not None:
        text = re.sub(r"(?m)^input_file\s*=.*$", f"input_file = {input_file}", text, count=1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    return dest


def stage_entrypoint(paths: PackagePaths) -> Path:
    target = staged_entrypoint(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.entrypoint, target)
    return target


def _run_pyside_deploy(root: Path, paths: PackagePaths, args: argparse.Namespace) -> None:
    env = os.environ.copy()
    env.setdefault("QT_API", "pyside6")
    icon = _resolve_icon(root, args.dry_run, args.skip_icon_build)
    staged = stage_entrypoint(paths)
    spec = materialize_spec(
        root / "pysidedeploy.spec",
        paths.build_dir / "pysidedeploy.spec",
        icon,
        project_dir=root,
        input_file=staged,
    )
    staged_paths = PackagePaths(root=paths.root, entrypoint=staged, build_dir=paths.build_dir)
    command = package_command(
        staged_paths,
        args.mode,
        args.dry_run,
        args.keep_deployment_files,
        icon=icon,
        config_file=spec,
    )
    subprocess.run(command, cwd=paths.build_dir, env=env, check=True)


def _run_artifact_build(root: Path, paths: PackagePaths, dry_run: bool) -> Path:
    version = load_project_version(root / "pyproject.toml")
    plan = artifact_plan(paths, platform.system(), version)
    return build_artifact(plan, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    paths = package_paths(root)
    paths.build_dir.mkdir(parents=True, exist_ok=True)
    if not args.artifact_only:
        _run_pyside_deploy(root, paths, args)
    if args.skip_artifact:
        return 0
    output = _run_artifact_build(root, paths, args.dry_run)
    print(f"[package] artifact ready: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

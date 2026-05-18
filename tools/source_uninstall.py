from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.source_install import UninstallTargets, uninstall_targets


@dataclass(frozen=True)
class UninstallOutcome:
    removed: tuple[Path, ...]
    skipped: tuple[Path, ...]


def _remove_path(path: Path) -> bool:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def run_uninstall(targets: UninstallTargets, current_script: Path | None = None, purge: bool = False) -> UninstallOutcome:
    removed: list[Path] = []
    skipped: list[Path] = []
    candidates: list[Path] = [targets.venv_dir, targets.desktop_lnk, targets.desktop_command]
    candidates.extend(
        path for path in targets.launcher_scripts
        if current_script is None or path.resolve() != current_script.resolve()
    )
    if purge:
        candidates.append(targets.user_data_dir)
    for path in candidates:
        if _remove_path(path):
            removed.append(path)
            continue
        skipped.append(path)
    return UninstallOutcome(removed=tuple(removed), skipped=tuple(skipped))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Uninstall Silentfrog's local .venv and launchers")
    parser.add_argument("--purge", action="store_true", help="Also delete local crawl history under the user data directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    targets = uninstall_targets(root)
    outcome = run_uninstall(targets, current_script=Path(__file__), purge=args.purge)
    for path in outcome.removed:
        print(f"[uninstall] removed {path}")
    for path in outcome.skipped:
        print(f"[uninstall] skipped (not present) {path}")
    if args.purge:
        print("[uninstall] Local crawl history removed.")
    else:
        print("[uninstall] Local crawl history preserved. Use --purge to remove it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

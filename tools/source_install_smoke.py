from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.source_install import installer_paths

SMOKE_CODE = """
import os
os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import silentfrog
from qtpy import API_NAME
from qtpy.QtWidgets import QApplication
from silentfrog.gui import HomeWindow
app = QApplication([])
window = HomeWindow()
assert window.windowTitle() == "Silentfrog"
print(API_NAME)
"""


def main() -> int:
    paths = installer_paths(Path.cwd())
    if not paths.launcher.exists():
        print(f"[install-smoke] Missing launcher: {paths.launcher}")
        return 1

    env = os.environ.copy()
    env.setdefault("QT_API", "pyside6")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    subprocess.run([str(paths.python), "-c", SMOKE_CODE], env=env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

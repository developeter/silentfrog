from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# PR-0/E0: tests must exercise the working tree under src/, not a stale
# non-editable copy installed in .venv/site-packages. Prepend src/ so
# `import silentfrog` resolves here — which also lets `--cov=src/silentfrog`
# attribute real coverage to these files instead of reporting 0%.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir():
    # Force position 0: a stray editable install appends src/ *after*
    # site-packages via a .pth, so a "not in sys.path" guard would no-op and
    # silently hand the stale installed copy to the suite (coverage → 0%).
    while str(_SRC) in sys.path:
        sys.path.remove(str(_SRC))
    sys.path.insert(0, str(_SRC))

# Let test modules import shared, non-fixture helpers by bare name (e.g.
# ``import minisign_fixture``) regardless of pytest's import mode.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SILENTFROG_DATA_DIR", tempfile.mkdtemp(prefix="silentfrog-tests-"))

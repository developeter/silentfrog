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
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SILENTFROG_DATA_DIR", tempfile.mkdtemp(prefix="silentfrog-tests-"))

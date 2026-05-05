from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SILENTFROG_DATA_DIR", tempfile.mkdtemp(prefix="silentfrog-tests-"))

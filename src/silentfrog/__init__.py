from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

os.environ.setdefault("QT_API", "pyside6")


def _read_version() -> str:
    try:
        return version("silentfrog")
    except PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _read_version()
__all__ = ["__version__"]

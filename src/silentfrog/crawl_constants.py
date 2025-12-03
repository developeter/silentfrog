from __future__ import annotations

import os
from typing import Set

from nltk.corpus import stopwords

_ACCEPT_DEFAULT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_ACCEPT_LANGUAGE_DEFAULT = "en-US,en;q=0.9"

STOP: Set[str] = set()
for lang in ("english", "italian", "spanish", "french"):
    try:
        STOP.update(stopwords.words(lang))
    except LookupError:
        import nltk

        nltk.download("stopwords")
        STOP.update(stopwords.words(lang))


def _keyword_density_threshold() -> float:
    raw = os.environ.get("SILENTFROG_KEYWORD_WARN_DENSITY", "").strip()
    if not raw:
        return 4.0
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return 4.0
    return max(value, 0.0)


__all__ = [
    "_ACCEPT_DEFAULT",
    "_ACCEPT_LANGUAGE_DEFAULT",
    "STOP",
    "_keyword_density_threshold",
]

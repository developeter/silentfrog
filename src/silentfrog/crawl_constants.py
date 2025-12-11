from __future__ import annotations

import os
from typing import Set

import importlib.resources

_ACCEPT_DEFAULT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_ACCEPT_LANGUAGE_DEFAULT = "en-US,en;q=0.9"

STOP: Set[str] = set()
_STOPWORD_FILES = {
    "english": "stopwords_en.txt",
    "italian": "stopwords_it.txt",
    "spanish": "stopwords_es.txt",
    "french": "stopwords_fr.txt",
}


def _load_stopwords() -> None:
    for lang, filename in _STOPWORD_FILES.items():
        try:
            data = importlib.resources.files("silentfrog.resources").joinpath(filename).read_text(encoding="utf-8")
            STOP.update(word.strip() for word in data.splitlines() if word.strip())
            continue
        except FileNotFoundError:
            pass
        try:
            from nltk.corpus import stopwords

            STOP.update(stopwords.words(lang))
        except Exception:
            continue


_load_stopwords()


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

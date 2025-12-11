from __future__ import annotations

import importlib.resources


def test_stopword_files_exist() -> None:
    for filename in (
        "stopwords_en.txt",
        "stopwords_it.txt",
        "stopwords_es.txt",
        "stopwords_fr.txt",
    ):
        data = importlib.resources.files("silentfrog.resources").joinpath(filename).read_text(encoding="utf-8")
        assert data.strip(), f"{filename} should not be empty"

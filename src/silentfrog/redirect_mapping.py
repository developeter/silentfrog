"""Semantic redirect mapping (v3 G13).

For a site migration, suggests old -> new URL redirects: pages from the
PREVIOUS crawl that are missing or gone (404/410) in the CURRENT crawl are
matched against the current crawl's live, indexable pages. Cosine similarity
on the stored G5 topic-embedding vector (``embeddings/topic.py``) is tried
first when both sides have one; a stdlib ``difflib`` ratio on path + title is
the fallback otherwise. Output feeds the EXISTING Redirect checker
(``redirect.py`` / ``redirect_gui.py`` read an Old URL/New URL mapping) via a
CSV the GUI writes -- this module stays pure derivation: no Qt, no I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse

_DEFAULT_MIN_SEMANTIC = 0.60
_DEFAULT_MIN_TEXT = 0.55
_DEFAULT_MAX_SUGGESTIONS = 500

# HTTP statuses that mean "the old URL is gone" -- a stronger migration
# signal than a generic error, and distinct from "still alive, no redirect
# needed" (any other status, including a fresh 2xx at the same URL).
_GONE_STATUS_CODES = frozenset({404, 410})


@dataclass(frozen=True, slots=True)
class PageRef:
    """One crawled page, as much as redirect matching needs -- a typed stand-in
    for the ``(url, title, vector, status, indexability)`` tuple so callers
    never pass bare positional tuples across this module's boundary."""

    url: str
    title: str = ""
    vector: tuple[float, ...] = ()
    status: str = ""
    indexability: str = ""


@dataclass(frozen=True, slots=True)
class RedirectSuggestion:
    old_url: str
    new_url: str
    score: float
    method: str  # "semantic" | "text"


@dataclass(frozen=True, slots=True)
class RedirectMap:
    suggestions: tuple[RedirectSuggestion, ...]
    unmatched: tuple[str, ...]
    measured: bool
    reason: str = ""


def _unmeasured(reason: str) -> RedirectMap:
    return RedirectMap(suggestions=(), unmatched=(), measured=False, reason=reason)


def _status_code(value: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _is_gone(url: str, current_by_url: dict[str, PageRef]) -> bool:
    current = current_by_url.get(url)
    if current is None:
        return True
    return _status_code(current.status) in _GONE_STATUS_CODES


def _is_live_indexable(page: PageRef) -> bool:
    code = _status_code(page.status)
    return 200 <= code < 300 and "Indexable" in page.indexability


def select_migration_candidates(
    previous_pages: Sequence[PageRef],
    current_pages: Sequence[PageRef],
) -> tuple[tuple[PageRef, ...], tuple[PageRef, ...]]:
    """(old_candidates, new_candidates): previous-crawl pages absent or gone
    (404/410) in the current crawl, paired with current-crawl pages that are
    live (2xx) and indexable -- the two pools ``build_redirect_map`` matches.
    A previous-crawl URL still alive (any other current status) is excluded:
    no redirect is needed for it."""
    current_by_url = {page.url: page for page in current_pages}
    old = tuple(page for page in previous_pages if _is_gone(page.url, current_by_url))
    new = tuple(page for page in current_pages if _is_live_indexable(page))
    return old, new


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product only: stored topic vectors are already L2-normalized
    (``embeddings/topic.py::_mean_vector``), so cosine similarity reduces to
    a plain dot product -- no norm division needed."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def _text_key(page: PageRef) -> str:
    return f"{urlparse(page.url).path} {page.title}".strip()


def _text_similarity(old: PageRef, new: PageRef) -> float:
    return SequenceMatcher(None, _text_key(old), _text_key(new)).ratio()


def _best_by(candidates: Sequence[PageRef], score: Callable[[PageRef], float]) -> tuple[PageRef, float] | None:
    """Highest-scoring candidate, ties broken by ``new_url`` for determinism."""
    if not candidates:
        return None
    best = min(candidates, key=lambda c: (-score(c), c.url))
    return best, score(best)


def _best_semantic(old: PageRef, new_items: Sequence[PageRef]) -> tuple[PageRef, float] | None:
    if not old.vector:
        return None
    vectored = [candidate for candidate in new_items if candidate.vector]
    return _best_by(vectored, lambda candidate: _cosine(old.vector, candidate.vector))


def _best_text(old: PageRef, new_items: Sequence[PageRef]) -> tuple[PageRef, float] | None:
    return _best_by(new_items, lambda candidate: _text_similarity(old, candidate))


def _best_match(
    old: PageRef,
    new_items: Sequence[PageRef],
    *,
    min_semantic: float,
    min_text: float,
) -> RedirectSuggestion | None:
    """Semantic match first (when both sides have a vector and it clears
    ``min_semantic``), else a text fallback on path + title. Below both
    thresholds -> no suggestion for this old URL."""
    semantic = _best_semantic(old, new_items)
    if semantic is not None and semantic[1] >= min_semantic:
        candidate, score = semantic
        return RedirectSuggestion(old.url, candidate.url, round(score, 4), "semantic")
    text = _best_text(old, new_items)
    if text is not None and text[1] >= min_text:
        candidate, score = text
        return RedirectSuggestion(old.url, candidate.url, round(score, 4), "text")
    return None


def build_redirect_map(
    old_items: Sequence[PageRef],
    new_items: Sequence[PageRef],
    *,
    min_semantic: float = _DEFAULT_MIN_SEMANTIC,
    min_text: float = _DEFAULT_MIN_TEXT,
    max_suggestions: int = _DEFAULT_MAX_SUGGESTIONS,
) -> RedirectMap:
    """Best old -> new redirect suggestion per old page.

    ``old_items``/``new_items`` are already the migration-candidate pools
    (see :func:`select_migration_candidates`) -- this function only matches,
    it does not re-derive "missing/gone" or "live/indexable". Deterministic:
    suggestions sort by old_url, ties by score desc then new_url. Never
    raises: an empty side degrades to an unmeasured map with a reason.
    """
    if not old_items:
        return _unmeasured("No pages from the previous crawl are missing or gone in the current crawl")
    if not new_items:
        return _unmeasured("No live, indexable pages in the current crawl to redirect to")
    suggestions: list[RedirectSuggestion] = []
    unmatched: list[str] = []
    for old in old_items:
        match = _best_match(old, new_items, min_semantic=min_semantic, min_text=min_text)
        if match is None:
            unmatched.append(old.url)
        else:
            suggestions.append(match)
    ordered = tuple(sorted(suggestions, key=lambda s: (s.old_url, -s.score, s.new_url))[:max_suggestions])
    return RedirectMap(suggestions=ordered, unmatched=tuple(sorted(unmatched)), measured=True)


__all__ = [
    "PageRef",
    "RedirectMap",
    "RedirectSuggestion",
    "build_redirect_map",
    "select_migration_candidates",
]

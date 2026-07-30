"""Unit tests for the v3 G13 semantic redirect mapping."""

from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import urlparse

from silentfrog.redirect_mapping import (
    PageRef,
    build_redirect_map,
    select_migration_candidates,
)

_V_A = (1.0, 0.0, 0.0)
_V_A_CLOSE = (0.99, 0.14, 0.0)  # cosine ~0.99 with _V_A
_V_FAR = (0.0, 1.0, 0.0)  # orthogonal -> cosine 0.0 with _V_A


def _text_ratio(a: PageRef, b: PageRef) -> float:
    """Standalone re-derivation of the module's path+title text key, used
    only to assert a genuine tie precondition -- not a private-helper import."""
    key_a = f"{urlparse(a.url).path} {a.title}".strip()
    key_b = f"{urlparse(b.url).path} {b.title}".strip()
    return SequenceMatcher(None, key_a, key_b).ratio()


def _old(url: str, title: str = "", vector: tuple[float, ...] = ()) -> PageRef:
    return PageRef(url=url, title=title, vector=vector)


def _new(url: str, title: str = "", vector: tuple[float, ...] = (), status: str = "200") -> PageRef:
    return PageRef(url=url, title=title, vector=vector, status=status, indexability="Indexable")


def test_semantic_match_wins_over_text_when_vectors_present() -> None:
    # The text-similar candidate ("old-page") is a poor vector match; the
    # vector-similar candidate ("unrelated-slug") is a poor text match. The
    # semantic method must win because both sides carry a vector.
    old = [_old("https://e.com/old-page", title="Old Page", vector=_V_A)]
    new = [
        _new("https://e.com/old-page-2", title="Old Page", vector=_V_FAR),
        _new("https://e.com/unrelated-slug", title="Unrelated", vector=_V_A_CLOSE),
    ]
    result = build_redirect_map(old, new)

    assert result.measured is True
    assert len(result.suggestions) == 1
    suggestion = result.suggestions[0]
    assert suggestion.old_url == "https://e.com/old-page"
    assert suggestion.new_url == "https://e.com/unrelated-slug"
    assert suggestion.method == "semantic"
    assert suggestion.score >= 0.60


def test_text_fallback_used_when_vectors_absent() -> None:
    old = [_old("https://e.com/blue-widgets", title="Blue Widgets")]
    new = [
        _new("https://e.com/red-gadgets", title="Red Gadgets"),
        _new("https://e.com/blue-widgets-new", title="Blue Widgets"),
    ]
    result = build_redirect_map(old, new)

    assert result.measured is True
    assert len(result.suggestions) == 1
    suggestion = result.suggestions[0]
    assert suggestion.new_url == "https://e.com/blue-widgets-new"
    assert suggestion.method == "text"


def test_below_both_thresholds_is_unmatched() -> None:
    old = [_old("https://e.com/totally-unrelated-topic-xyz", title="Zzz Qqq Nothing Alike")]
    new = [_new("https://e.com/completely-different", title="Abc Def Ghi Whatever")]
    result = build_redirect_map(old, new, min_semantic=0.60, min_text=0.55)

    assert result.measured is True
    assert result.suggestions == ()
    assert result.unmatched == ("https://e.com/totally-unrelated-topic-xyz",)


def test_deterministic_across_repeated_calls() -> None:
    old = [
        _old("https://e.com/b", title="B page", vector=_V_A),
        _old("https://e.com/a", title="A page", vector=_V_A),
    ]
    new = [_new("https://e.com/n", title="N page", vector=_V_A_CLOSE)]

    first = build_redirect_map(old, new)
    second = build_redirect_map(old, new)

    assert first == second
    # stable sort by old_url
    assert [s.old_url for s in first.suggestions] == ["https://e.com/a", "https://e.com/b"]


def test_tie_break_by_new_url_when_scores_equal() -> None:
    # Two candidates whose path differs from the old URL by one, equally
    # mismatched, trailing character -> identical SequenceMatcher ratio. The
    # lexically smaller new_url must win the tie, deterministically.
    old = [_old("https://e.com/same", title="Same Title")]
    new = [
        _new("https://e.com/samg", title="Same Title"),
        _new("https://e.com/samf", title="Same Title"),
    ]
    assert _text_ratio(old[0], new[0]) == _text_ratio(old[0], new[1])  # tie precondition

    result = build_redirect_map(old, new)

    assert len(result.suggestions) == 1
    assert result.suggestions[0].new_url == "https://e.com/samf"


def test_candidate_selection_missing_vs_gone_vs_still_alive() -> None:
    previous = [
        PageRef(url="https://e.com/missing", title="Missing"),
        PageRef(url="https://e.com/gone-404", title="Gone 404"),
        PageRef(url="https://e.com/gone-410", title="Gone 410"),
        PageRef(url="https://e.com/still-alive", title="Still Alive"),
    ]
    current = [
        _new("https://e.com/gone-404", status="404"),
        _new("https://e.com/gone-410", status="410"),
        _new("https://e.com/still-alive", status="200"),
        _new("https://e.com/current-page", status="200"),
    ]
    old_candidates, new_candidates = select_migration_candidates(previous, current)

    old_urls = {page.url for page in old_candidates}
    assert old_urls == {"https://e.com/missing", "https://e.com/gone-404", "https://e.com/gone-410"}
    assert "https://e.com/still-alive" not in old_urls

    new_urls = {page.url for page in new_candidates}
    assert new_urls == {"https://e.com/still-alive", "https://e.com/current-page"}


def test_candidate_selection_excludes_non_indexable_and_non_2xx_current_pages() -> None:
    current = [
        PageRef(url="https://e.com/redirect", status="301", indexability="Indexable"),
        PageRef(url="https://e.com/noindex", status="200", indexability="Non-indexable: noindex"),
        PageRef(url="https://e.com/ok", status="200", indexability="Indexable"),
    ]
    _, new_candidates = select_migration_candidates([], current)

    assert [page.url for page in new_candidates] == ["https://e.com/ok"]


def test_empty_old_side_is_unmeasured_with_reason() -> None:
    result = build_redirect_map([], [_new("https://e.com/a")])
    assert result.measured is False
    assert result.suggestions == ()
    assert result.unmatched == ()
    assert result.reason


def test_empty_new_side_is_unmeasured_with_reason() -> None:
    result = build_redirect_map([_old("https://e.com/a")], [])
    assert result.measured is False
    assert result.reason


def test_max_suggestions_caps_output_deterministically() -> None:
    old = [_old(f"https://e.com/old-{i}", title=f"Old {i}") for i in range(5)]
    new = [_new(f"https://e.com/old-{i}", title=f"Old {i}") for i in range(5)]
    result = build_redirect_map(old, new, max_suggestions=2)

    assert len(result.suggestions) == 2
    assert [s.old_url for s in result.suggestions] == ["https://e.com/old-0", "https://e.com/old-1"]

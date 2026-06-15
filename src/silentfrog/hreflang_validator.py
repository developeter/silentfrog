"""Hreflang depth validator (v2.0 V16).

Turns the 5-column hreflang rows that the crawler already produces
(``[lang, href, status, valid_format, self_reference]``) into three
explainable AI-Visibility checks under a new "Hreflang" area.

The §1.5 grading rule applies: a *not-required* signal that is merely
absent degrades to ``info`` (folds into ``good`` for scoring), and only a
genuine in-set defect (a broken return tag confirmed by a cluster, a
duplicate lang code, or a malformed lang) is ever a ``warning``. When no
cluster of alternate pages is supplied (the V16 default), reciprocity is
unconfirmable, so the return-tag and cluster checks lean on the page's own
self-declared signals and NEVER warn for something they cannot prove.

Pure and typed; never raises — ragged or malformed rows degrade to empty.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .crawl_types import AiVisibilityCheck

_X_DEFAULT = "x-default"


def _cell(cells: list[str], index: int) -> str:
    return str(cells[index]).strip() if len(cells) > index else ""


@dataclass(frozen=True)
class HreflangEntry:
    lang: str
    href: str
    status: str
    valid_format: bool
    self_ref: bool

    @classmethod
    def from_row(cls, row: Sequence[str]) -> HreflangEntry:
        cells = list(row)
        return cls(
            lang=_cell(cells, 0).lower(),
            href=_cell(cells, 1),
            status=_cell(cells, 2),
            valid_format=_cell(cells, 3).lower() == "yes",
            self_ref=_cell(cells, 4).lower() == "yes",
        )


@dataclass(frozen=True)
class HreflangValidation:
    entry_count: int
    distinct_langs: tuple[str, ...]
    has_x_default: bool
    multiple_languages: bool  # >= 2 distinct non-x-default langs
    self_referenced: bool
    return_tag_complete: bool
    missing_return_langs: tuple[str, ...]
    x_default_required: bool  # == multiple_languages
    cluster_consistent: bool
    cluster_mismatch_note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_count": self.entry_count,
            "distinct_langs": list(self.distinct_langs),
            "has_x_default": self.has_x_default,
            "multiple_languages": self.multiple_languages,
            "self_referenced": self.self_referenced,
            "return_tag_complete": self.return_tag_complete,
            "missing_return_langs": list(self.missing_return_langs),
            "x_default_required": self.x_default_required,
            "cluster_consistent": self.cluster_consistent,
            "cluster_mismatch_note": self.cluster_mismatch_note,
        }


def _is_row(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def parse_hreflang_entries(rows: object) -> list[HreflangEntry]:
    """Coerce raw hreflang rows into entries, tolerating ragged input."""
    if not _is_row(rows):
        return []
    return [HreflangEntry.from_row(row) for row in rows if _is_row(row)]


def _distinct_langs(entries: list[HreflangEntry]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(entry.lang for entry in entries if entry.lang))


def _non_default_langs(langs: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(lang for lang in langs if lang != _X_DEFAULT)


def _has_duplicate_langs(entries: list[HreflangEntry]) -> bool:
    langs = [entry.lang for entry in entries if entry.lang]
    return len(langs) != len(set(langs))


def _has_malformed_lang(entries: list[HreflangEntry]) -> bool:
    return any(entry.lang and not entry.valid_format for entry in entries)


def _self_set_hard_defect(entries: list[HreflangEntry]) -> bool:
    # A hard, warning-worthy defect: duplicate lang codes or a malformed code.
    # Missing self-reference is NOT a hard defect — it degrades to info.
    return _has_duplicate_langs(entries) or _has_malformed_lang(entries)


def _self_set_consistent(entries: list[HreflangEntry], self_referenced: bool) -> bool:
    # A page's own hreflang set is "good" when it self-references and carries
    # no hard defect; otherwise the caller decides info (indeterminate) vs
    # warning (hard defect).
    return self_referenced and not _self_set_hard_defect(entries)


def _hard_defect_note(entries: list[HreflangEntry]) -> str:
    notes = {
        "duplicate language codes": _has_duplicate_langs(entries),
        "malformed language code": _has_malformed_lang(entries),
    }
    found = [label for label, present in notes.items() if present]
    return f"Self-set defect: {', '.join(found)}" if found else ""


def _cluster_diff(
    page_url: str,
    entries: list[HreflangEntry],
    cluster: Mapping[str, list[list[str]]],
) -> tuple[bool, tuple[str, ...], str]:
    """Compare the page's alternates against each alternate's own hreflang set.

    Returns ``(consistent, missing_return_langs, note)``. An alternate is
    reciprocal when its own rows (looked up by href in ``cluster``) declare a
    hreflang pointing back to ``page_url``.
    """
    missing = [
        entry.lang
        for entry in _checkable_alternates(page_url, entries, cluster)
        if not _links_back(cluster[entry.href], page_url)
    ]
    note = "" if not missing else f"Alternates not linking back: {', '.join(missing)}"
    return (not missing), tuple(missing), note


def _checkable_alternates(
    page_url: str,
    entries: list[HreflangEntry],
    cluster: Mapping[str, list[list[str]]],
) -> list[HreflangEntry]:
    # Only alternates the cluster actually carries rows for are checkable; a
    # page's own self-reference is excluded so it never counts against itself.
    target = page_url.rstrip("/")
    return [entry for entry in entries if entry.href in cluster and entry.href.rstrip("/") != target]


def _links_back(alt_rows: object, page_url: str) -> bool:
    target = page_url.rstrip("/")
    return any(entry.href.rstrip("/") == target for entry in parse_hreflang_entries(alt_rows))


def validate_hreflang(
    page_url: str,
    rows: object,
    cluster: Mapping[str, list[list[str]]] | None = None,
) -> HreflangValidation:
    """Validate a page's hreflang set, optionally against a cluster of alternates.

    With ``cluster=None`` (the V16 default) reciprocity and cluster symmetry
    are unconfirmable, so they degrade to the self-declared signal and never
    flag a problem. Never raises.
    """
    entries = parse_hreflang_entries(rows)
    distinct = _distinct_langs(entries)
    non_default = _non_default_langs(distinct)
    multiple = len(non_default) >= 2
    self_referenced = any(entry.self_ref for entry in entries)
    return _assemble_validation(page_url, entries, distinct, multiple, self_referenced, cluster)


def _assemble_validation(
    page_url: str,
    entries: list[HreflangEntry],
    distinct: tuple[str, ...],
    multiple: bool,
    self_referenced: bool,
    cluster: Mapping[str, list[list[str]]] | None,
) -> HreflangValidation:
    self_ok = _self_set_consistent(entries, self_referenced)
    if cluster is None:
        # The note doubles as the warning trigger: a hard defect (dup/malformed
        # lang) sets it so the cluster check warns; a merely unconfirmed set
        # leaves it empty and degrades to info.
        defect_note = _hard_defect_note(entries)
        return_complete, missing, consistent, note = self_referenced, (), self_ok, defect_note
    else:
        consistent, missing, note = _cluster_diff(page_url, entries, cluster)
        return_complete = consistent
    return HreflangValidation(
        entry_count=len(entries),
        distinct_langs=distinct,
        has_x_default=_X_DEFAULT in distinct,
        multiple_languages=multiple,
        self_referenced=self_referenced,
        return_tag_complete=return_complete,
        missing_return_langs=missing,
        x_default_required=multiple,
        cluster_consistent=consistent,
        cluster_mismatch_note=note,
    )


_HREFLANG_MESSAGES = {
    "hreflang_return_tag_complete": (
        "Hreflang return tags are reciprocal",
        "Every alternate must link back to this page with a matching hreflang. "
        "Confirm reciprocity by crawling the alternate URLs as a cluster.",
    ),
    "hreflang_x_default_present": (
        "An x-default hreflang is declared",
        "When a page targets two or more languages, declare an x-default alternate "
        "for unmatched locales. Recommended, not strictly required.",
    ),
    "hreflang_cluster_consistent": (
        "The hreflang cluster is internally consistent",
        "Keep the hreflang set free of duplicate language codes and malformed values, "
        "and ensure alternates point at each other symmetrically.",
    ),
}


def _hreflang_check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    title, recommendation = _HREFLANG_MESSAGES[key]
    return AiVisibilityCheck(
        area="Hreflang",
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def _yes(flag: bool) -> str:
    return "Yes" if flag else "No"


def _return_tag_status(result: HreflangValidation, cluster_present: bool) -> str:
    # Without a cluster, reciprocity is unconfirmable: good when the page
    # self-references, else info — never warning. With a cluster, a non-empty
    # missing-return set is a genuine defect.
    if not cluster_present:
        return "good" if result.self_referenced else "info"
    return "good" if result.return_tag_complete else "warning"


def _x_default_status(result: HreflangValidation) -> str:
    # x-default is recommended, never required: present or single-language => good,
    # multi-language without it => info. Never a warning.
    if result.has_x_default or not result.multiple_languages:
        return "good"
    return "info"


def _cluster_status(result: HreflangValidation) -> str:
    # Good when the set qualifies (symmetric cluster, or self-referenced and
    # defect-free). Otherwise the note distinguishes a genuine defect (warning)
    # from a merely unconfirmable set (info) — empty note means indeterminate.
    if result.cluster_consistent:
        return "good"
    return "warning" if result.cluster_mismatch_note else "info"


def _return_tag_detail(result: HreflangValidation, cluster_present: bool) -> str:
    return (
        f"Self-referenced: {_yes(result.self_referenced)}; Cluster checked: {_yes(cluster_present)}; "
        f"Missing return langs: {', '.join(result.missing_return_langs) or '-'}."
    )


def _x_default_detail(result: HreflangValidation) -> str:
    return (
        f"x-default declared: {_yes(result.has_x_default)}; Multiple languages: "
        f"{_yes(result.multiple_languages)}; Languages: {len(_non_default_langs(result.distinct_langs))}."
    )


def _cluster_detail(result: HreflangValidation) -> str:
    return (
        f"Distinct langs: {len(result.distinct_langs)}; Consistent: {_yes(result.cluster_consistent)}; "
        f"Note: {result.cluster_mismatch_note or '-'}."
    )


def build_hreflang_checks(
    page_url: str,
    rows: object,
    cluster: Mapping[str, list[list[str]]] | None = None,
) -> list[AiVisibilityCheck]:
    """Build the three Hreflang checks; empty when the page declares no hreflang.

    Single-locale sites (no hreflang rows) stay clean — they get no rows at
    all rather than green noise.
    """
    entries = parse_hreflang_entries(rows)
    if not entries:
        return []
    result = validate_hreflang(page_url, rows, cluster)
    cluster_present = cluster is not None
    return [
        _hreflang_check(
            "hreflang_return_tag_complete",
            _return_tag_status(result, cluster_present),
            _return_tag_detail(result, cluster_present),
        ),
        _hreflang_check(
            "hreflang_x_default_present",
            _x_default_status(result),
            _x_default_detail(result),
        ),
        _hreflang_check(
            "hreflang_cluster_consistent",
            _cluster_status(result),
            _cluster_detail(result),
        ),
    ]


__all__ = [
    "HreflangEntry",
    "HreflangValidation",
    "build_hreflang_checks",
    "parse_hreflang_entries",
    "validate_hreflang",
]

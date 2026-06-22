from __future__ import annotations

from silentfrog.indexability import build_indexability_rows  # type: ignore[reportMissingImports]


def _rows_for(
    *,
    final_status: str = "200",
    hops: int = 0,
    meta_robots: str = "index, follow",
    canonical_target: str = "",
    canonical_self: bool = True,
    canonical_status: str = "200",
    canonical_multiple: bool = False,
    robots_map: dict[str, list[tuple[str, str]]] | None = None,
) -> list[list[str]]:
    redirect = {"chain": ["https://example.com/page"], "final_status": final_status, "hops": hops}
    canonical = {
        "target": canonical_target,
        "self": canonical_self,
        "status": canonical_status,
        "multiple": canonical_multiple,
    }
    return build_indexability_rows(redirect, canonical, meta_robots, robots_map or {})


def _verdict_value(rows: list[list[str]]) -> str:
    return next(value for key, value in rows if key == "Overall verdict")


def test_indexability_verdict_variants() -> None:
    assert _verdict_value(_rows_for()) == "Indexable"
    assert _verdict_value(_rows_for(final_status="404")) == "Not indexable"
    assert _verdict_value(_rows_for(robots_map={"*": [("Disallow", "/page")]})) == "Blocked by robots.txt"
    assert _verdict_value(_rows_for(meta_robots="noindex")) == "Noindex"
    assert _verdict_value(_rows_for(hops=1)) == "Redirected"
    assert (
        _verdict_value(_rows_for(canonical_target="https://example.com/other", canonical_self=False))
        == "Canonicalized elsewhere"
    )
    assert (
        _verdict_value(_rows_for(canonical_target="https://example.com/page", canonical_status="500"))
        == "Indexable with warnings"
    )
    assert _verdict_value(_rows_for(canonical_multiple=True)) == "Indexable with warnings"


def test_indexability_honors_robots_wildcard_after_unification() -> None:
    # H3 follow-up: the "*" robots check shares the RFC 9309 engine, so a
    # wildcard/anchor rule blocks /page — the old prefix matcher missed it.
    rows = _rows_for(robots_map={"*": [("Disallow", "/*age$")]})
    assert _verdict_value(rows) == "Blocked by robots.txt"

"""Unit tests for v2.0 V14 rich-result eligibility (schema + GSC)."""

from __future__ import annotations

from silentfrog.integrations.google.rich_results import (
    RichResultsReport,
    derive_from_schema,
    from_url_inspection,
)


def _schema(rows: list[dict]) -> dict:
    return {"eligibility": rows}


def test_derive_from_schema_buckets_rows() -> None:
    report = derive_from_schema(
        _schema(
            [
                {"type": "Product", "eligibility": "Eligible", "warnings": []},
                {"type": "BreadcrumbList", "eligibility": "Incomplete", "warnings": ["1 block needs fixes"]},
                {"type": "Article", "eligibility": "Not detected", "warnings": []},
            ]
        )
    )
    assert report.measured
    assert report.source == "schema"
    assert "Product" in report.eligible_types
    assert "BreadcrumbList" in report.ineligible_types
    assert "Article" not in report.eligible_types
    assert "Article" not in report.ineligible_types
    assert report.warnings


def test_derive_from_schema_empty_is_unmeasured() -> None:
    assert derive_from_schema(_schema([])).measured is False
    assert derive_from_schema({}).measured is False
    assert derive_from_schema("garbage").measured is False
    only_absent = _schema([{"type": "Product", "eligibility": "Not detected"}])
    assert derive_from_schema(only_absent).measured is False


def test_derive_falls_back_to_blocks_when_no_eligibility() -> None:
    blocks = [{"@type": "Organization", "name": "X", "url": "https://x", "logo": "https://x/l.png"}]
    report = derive_from_schema({"blocks": blocks})
    assert report.measured
    assert "Organization" in report.eligible_types


def test_from_url_inspection_parses_detected_items() -> None:
    inspection = {
        "inspectionResult": {
            "richResultsResult": {
                "detectedItems": [
                    {
                        "richResultType": "Breadcrumbs",
                        "items": [
                            {
                                "issues": [
                                    {"issueMessage": "Missing field id", "severity": "ERROR"},
                                    {"issueMessage": "minor", "severity": "WARNING"},
                                ]
                            }
                        ],
                    },
                    {"richResultType": "Products", "items": []},
                ]
            }
        }
    }
    report = from_url_inspection(inspection)
    assert report.measured and report.source == "gsc"
    assert "Breadcrumbs" in report.eligible_types
    assert "Products" in report.eligible_types
    # only ERROR severity becomes a warning
    assert len(report.warnings) == 1
    assert "Missing field id" in report.warnings[0]


def test_from_url_inspection_garbage_never_raises() -> None:
    assert from_url_inspection({}).measured is False
    assert from_url_inspection("nope").measured is False
    assert from_url_inspection({"inspectionResult": {}}).measured is False


def test_roundtrip() -> None:
    report = RichResultsReport(
        eligible_types=("Product",),
        ineligible_types=("Article",),
        warnings=("w",),
        source="gsc",
        measured=True,
    )
    assert RichResultsReport.from_dict(report.to_dict()) == report
    assert RichResultsReport.from_dict("garbage").measured is False

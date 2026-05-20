from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Tuple, Type, cast

import pytest
from qtpy import QtCore, QtGui, QtWidgets
from silentfrog.theme import apply_theme  # type: ignore[reportMissingImports]

from silentfrog.audit_issues import IssueSeverity  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.crawl_options import CrawlOptions  # type: ignore[reportMissingImports]
from silentfrog.image_diagnostics import (
    ACTUAL_HEIGHT_COL,
    ACTUAL_WIDTH_COL,
    CACHE_COL,
    DECLARED_HEIGHT_COL,
    DECLARED_WIDTH_COL,
    DIAGNOSTIC_COL,
    FETCH_PRIORITY_COL,
    IMAGE_HEADERS,
    LOADING_COL,
    SIZE_COL,
    normalize_image_row,
)
from silentfrog.settings_dialog import CrawlSettingsDialog  # type: ignore[reportMissingImports]
from silentfrog.seo_gui import WebpageSeoWindow  # type: ignore[reportMissingImports]
from silentfrog.tabs import (  # type: ignore[reportMissingImports]
    AiTab,
    AiVisibilityTab,
    CanonicalTab,
    ContentQualityTab,
    HeadersTab,
    ImagesTab,
    IndexabilityTab,
    HreflangTab,
    KeywordsTab,
    PerformanceTab,
    LinksTab,
    MetaTab,
    RedirectTab,
    RobotsTab,
    SchemaTab,
    SerpTab,
    SocialTab,
)

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")
SERP_SNAPSHOT = SNAPSHOT_DIR / "serp_preview.html"

@pytest.fixture(autouse=True)
def _restore_palette():
    app = QtWidgets.QApplication.instance()
    original = QtGui.QPalette(cast(QtWidgets.QApplication, app).palette()) if app is not None else None
    yield
    if app is not None and original is not None:
        cast(QtWidgets.QApplication, app).setPalette(original)


def _normalize_html(html: str) -> str:
    cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", html, flags=re.IGNORECASE)
    cleaned = re.sub(r"<head>.*?</head>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<body[^>]*>", "<body>", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"font-weight:\d+(\.\d+)?", "font-weight:500", cleaned)
    cleaned = cleaned.replace("\xa0", "&nbsp;")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _set_base(widget: QtWidgets.QWidget, value: int) -> None:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    apply_theme(cast(QtWidgets.QApplication, app), value < 128)
    widget.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))

def _configure_settings(tmp_path: Path) -> None:
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.Scope.UserScope, str(tmp_path))
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.setOrganizationName("SilentfrogTests")
        app.setApplicationName("SilentfrogTests")


def _row_count(view: QtWidgets.QTableView) -> int:
    model = view.model()
    assert model is not None
    return model.rowCount()


def _recap_item_containing(win: WebpageSeoWindow, text: str) -> QtWidgets.QListWidgetItem:
    for row in range(win.recap_tab.action_list.count()):
        item = win.recap_tab.action_list.item(row)
        if text in item.text():
            return item
    raise AssertionError(f"Missing recap item containing {text!r}")


def _sample_payload() -> CrawlPayload:
    raw = {
        "meta": [
            ["title", "Example Title", "13"],
            ["description", "Foo", "120"],
            ["robots", "index, follow", "12"],
            ["viewport", "width=device-width, initial-scale=1", "40"],
            ["charset", "utf-8", "5"],
        ],
        "headers": [["h1", "Title"]],
        "images": [
            normalize_image_row([
                "https://example.com/logo.png",
                "Alt",
                "Title",
                "image/png",
                "100",
                "200",
                "10 KB",
                "2h",
                "Yes",
                "High",
                "100",
                "200",
                "",
                "",
                "",
                "",
            ])
        ],
        "links": [
            [
                "https://example.com",
                "Example anchor",
                "Interno",
                "follow",
                "200",
                "OK",
                "Navigation",
                "Header",
                "com",
            ]
        ],
        "schema": {
            "summary": {
                "total": 1,
                "by_syntax": {"json-ld": 1},
                "by_type": {"WebPage": 1},
                "errors": []
            },
            "eligibility": [
                {
                    "type": "Product",
                    "detected": True,
                    "count": 1,
                    "eligibility": "Incomplete",
                    "missing_fields": ["missing offers.price", "missing offers.priceCurrency"],
                    "warnings": ["Missing required fields"],
                }
            ],
            "blocks": [
                {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": "Example Page",
                    "url": "https://example.com/page",
                    "_extracted_via": "json-ld"
                }
            ],
            "issues": [],
            "fallback_raw": []
        },
        "canonical": {
            "target": "https://example.com",
            "self": True,
            "multiple": False,
            "status": "200",
        },
        "redirect": {
            "chain": ["https://example.com"],
            "hops": 0,
            "final_status": "200",
            "loop": False,
        },
        "robots": {"*": [("Allow", "/"), ("Disallow", "/tmp")]},
        "meta_robots": "index, follow",
        "hreflang": [["en", "https://example.com", "200", "Yes", "Yes"]],
        "ai_crawl": [[
            "GPTBot",
            "gptbot",
            "Yes",
            "-",
            "-",
            "Allowed",
            "No explicit AI restrictions detected",
        ]],
        "content_quality": {
            "language": "Italian (it-IT)",
            "word_count": 420,
            "paragraph_count": 6,
            "substantial_paragraph_count": 4,
            "average_words_per_paragraph": 26.5,
            "title_present": True,
            "meta_description_present": True,
            "h1_count": 1,
            "h2_h6_count": 3,
            "title_h1_alignment": "Aligned",
            "intro_paragraph": "Present",
            "thin_content_risk": "Low",
            "heading_structure": "Good",
            "verdict": "Strong",
        },
        "ai_visibility": {
            "summary": {
                "verdict": "Needs work",
                "good_count": 6,
                "warning_count": 2,
                "critical_count": 0,
            },
            "checks": [
                {
                    "area": "Access",
                    "check": "Audited AI and search agents can access the page",
                    "status": "good",
                    "details": "Allowed: GPTBot; Limited: -; Blocked: -.",
                    "recommendation": "Keep robots.txt open for the official AI and search agents you want to allow.",
                    "key": "access_agents",
                },
                {
                    "area": "Citation readiness",
                    "check": "Cross-surface metadata is present",
                    "status": "warning",
                    "details": "OpenGraph title/description: Yes; Twitter title/description: No.",
                    "recommendation": "Keep OpenGraph and Twitter metadata complete so the page is consistently represented outside the page body.",
                    "key": "citation_social",
                },
            ],
        },
        "serp": {
            "title": "Example Title",
            "description": "Example description",
            "url": "https://example.com",
            "site_name": "Example",
            "breadcrumb": "example.com > page",
            "favicon": "data:image/png;base64,abc",
        },
        "serp_audit": {
            "too_long": "No",
            "too_short": "No",
            "px_over": "No",
            "px_under": "No",
            "equals_h1": "No",
            "missing": "No",
            "px_len": "100",
            "char_len": "10",
        },
        "performance": {
            "nav_ttfb_ms": 120.0,
            "nav_total_ms": 450.0,
            "transfer_size": 180000,
            "status": 200,
            "resource_summary": {
                "css": {"count": 4, "bytes": 42000},
                "js": {"count": 6, "bytes": 88000},
                "img": {"count": 10, "bytes": 220000},
                "font": {"count": 1, "bytes": 16000},
            },
            "top_offenders": [
                {"type": "js", "url": "https://example.com/app.js", "bytes": 88000, "blocking": True},
                {"type": "img", "url": "https://example.com/photo.jpg", "bytes": 220000, "blocking": False},
            ],
            "scripts": {
                "blocking": {"count": 2, "bytes": 90000},
                "async": {"count": 4, "bytes": 118000},
            },
            "opportunity_details": [
                {"message": "Enable compression for hero.jpg", "severity": "warning"},
            ],
        },
        "keywords": [
            {
                "term": "example",
                "length": 1,
                "frequency": 5,
                "density": 3.2,
                "density_threshold": 4.0,
                "density_warning": False,
                "in_title": True,
                "in_description": True,
                "heading_count": 1,
                "first_position": 0,
            },
            {
                "term": "sample page",
                "length": 2,
                "frequency": 2,
                "density": 1.0,
                "density_threshold": 4.0,
                "density_warning": False,
                "in_title": False,
                "in_description": False,
                "heading_count": 1,
                "first_position": 5,
            },
        ],
        "performance": {
            "nav_ttfb_ms": 120.0,
            "nav_total_ms": 450.0,
            "transfer_size": 180000,
            "status": 200,
            "resource_summary": {
                "css": {"count": 4, "bytes": 42000},
                "js": {"count": 6, "bytes": 88000},
                "img": {"count": 10, "bytes": 220000},
            },
            "opportunities": ["Enable compression for hero.jpg"],
        },
    }
    return CrawlPayload.from_raw(raw)


TABLE_TAB_CASES: Tuple[
    Tuple[Type[QtWidgets.QWidget], Tuple[object, ...], Dict[int, QtWidgets.QHeaderView.ResizeMode]],
    ...,
] = (
    (
        MetaTab,
        ([["description", "Example description", "150"]],),
        {},
    ),
    (
        HeadersTab,
        ([["h1", "Heading"]],),
        {},
    ),
    (
        ImagesTab,
        (
            [
                normalize_image_row([
                    "https://example.com/img.png",
                    "Alt",
                    "Title",
                    "image/png",
                    "640",
                    "480",
                    "18 KB",
                    "2h",
                    "Yes",
                    "High",
                    "640",
                    "480",
                    "",
                    "",
                    "",
                    "",
                ])
            ],
        ),
        {0: QtWidgets.QHeaderView.Interactive},
    ),
    (
        SocialTab,
        (
            {
                "open_graph": {
                    "title": "OG Title",
                    "description": "OG Desc",
                    "image": "https://example.com/og.png",
                    "site_name": "Example",
                    "url": "https://example.com",
                    "card": "",
                    "issues": ["Missing description"],
                },
                "twitter": {
                    "title": "TW Title",
                    "description": "TW Desc",
                    "image": "https://example.com/tw.png",
                    "site_name": "Example",
                    "url": "https://example.com",
                    "card": "summary_large_image",
                    "issues": [],
                },
            },
        ),
        {},
    ),
    (
        LinksTab,
        (
            [
                [
                    "https://example.com",
                    "Example anchor",
                    "Interno",
                    "follow",
                    "200",
                    "OK",
                    "Navigation",
                    "Header",
                    "com",
                ]
            ],
        ),
        {0: QtWidgets.QHeaderView.Stretch},
    ),
    (
        RedirectTab,
        (
            {
                "chain": ["https://example.com", "https://example.com/about"],
                "hops": 2,
                "final_status": "301",
                "loop": False,
            },
        ),
        {1: QtWidgets.QHeaderView.Stretch},
    ),
    (
        CanonicalTab,
        (
            {
                "target": "https://example.com",
                "self": True,
                "multiple": False,
                "status": "200",
            },
        ),
        {},
    ),
    (
        IndexabilityTab,
        (
            {
                "chain": ["https://example.com"],
                "hops": 0,
                "final_status": "200",
                "loop": False,
            },
            {
                "target": "https://example.com",
                "self": True,
                "multiple": False,
                "status": "200",
            },
            "index, follow",
            {"*": [("Allow", "/"), ("Disallow", "/tmp")]},
        ),
        {1: QtWidgets.QHeaderView.Stretch},
    ),
    (
        ContentQualityTab,
        (
            {
                "language": "Italian (it-IT)",
                "word_count": 420,
                "paragraph_count": 6,
                "substantial_paragraph_count": 4,
                "average_words_per_paragraph": 26.5,
                "title_present": True,
                "meta_description_present": True,
                "h1_count": 1,
                "h2_h6_count": 3,
                "title_h1_alignment": "Aligned",
                "intro_paragraph": "Present",
                "thin_content_risk": "Low",
                "heading_structure": "Good",
                "verdict": "Strong",
            },
        ),
        {1: QtWidgets.QHeaderView.Stretch},
    ),
    (
        RobotsTab,
        (
            "noindex",
            {"*": [("Allow", "/"), ("Disallow", "/tmp")]},
        ),
        {1: QtWidgets.QHeaderView.Stretch},
    ),
    (
        HreflangTab,
        ([["en", "https://example.com", "200", "Yes", "Yes"]],),
        {1: QtWidgets.QHeaderView.Stretch},
    ),
    (
        AiTab,
        ([["Crawler", "crawler", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"]],),
        {
            0: QtWidgets.QHeaderView.ResizeToContents,
            5: QtWidgets.QHeaderView.ResizeToContents,
            6: QtWidgets.QHeaderView.Stretch,
        },
    ),
    (
        AiVisibilityTab,
        (
            {
                "summary": {
                    "verdict": "Needs work",
                    "good_count": 1,
                    "warning_count": 1,
                    "critical_count": 0,
                },
                "checks": [
                    {
                        "area": "Access",
                        "check": "Audited AI and search agents can access the page",
                        "status": "good",
                        "details": "Allowed: GPTBot; Limited: -; Blocked: -.",
                        "recommendation": "Keep robots.txt open for the official AI and search agents you want to allow.",
                        "key": "access_agents",
                    },
                    {
                        "area": "Entity clarity",
                        "check": "Entity-supporting markup is present",
                        "status": "warning",
                        "details": "Detected entity schema: -; Eligible entity schema: -.",
                        "recommendation": "Add Organization, Product, or Article markup when relevant.",
                        "key": "entity_schema",
                    },
                ],
            },
        ),
        {
            0: QtWidgets.QHeaderView.ResizeToContents,
            1: QtWidgets.QHeaderView.Stretch,
            2: QtWidgets.QHeaderView.ResizeToContents,
            3: QtWidgets.QHeaderView.Stretch,
            4: QtWidgets.QHeaderView.Stretch,
        },
    ),
    (
        KeywordsTab,
        (
            [
                {
                    "term": "python",
                    "length": 1,
                    "frequency": 4,
                    "density": 2.5,
                    "density_threshold": 4.0,
                    "density_warning": False,
                    "in_title": False,
                    "in_description": True,
                    "heading_count": 1,
                    "first_position": 3,
                }
            ],
        ),
        {
            0: QtWidgets.QHeaderView.Stretch,
            3: QtWidgets.QHeaderView.ResizeToContents,
        },
    ),
    (
        PerformanceTab,
        (
            {
                "nav_ttfb_ms": 120.0,
                "nav_total_ms": 450.0,
                "transfer_size": 180000,
                "status": 200,
                "resource_summary": {
                    "css": {"count": 4, "bytes": 42000},
                    "js": {"count": 6, "bytes": 88000},
                    "img": {"count": 10, "bytes": 220000},
                },
                "opportunities": ["Enable compression for hero.jpg"],
            },
        ),
        {0: QtWidgets.QHeaderView.Stretch},
    ),
)

def test_seo_window_exposes_expected_tabs(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win.show()

    assert win.tabs.count() == 18
    labels = [win.tabs.tabText(index) for index in range(win.tabs.count())]
    assert labels == [
        "Recap",
        "Meta tag",
        "Header H1-H6",
        "Images",
        "Social",
        "Link",
        "Redirect",
        "Canonical",
        "Indexability",
        "Robots",
        "Hreflang",
        "Structured data",
        "Content quality",
        "Keywords",
        "AI crawl",
        "AI Visibility",
        "Performance",
        "SERP",
    ]

def test_recent_urls_persisted_and_ordered(qtbot, tmp_path: Path) -> None:
    _configure_settings(tmp_path)
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._remember_url("https://example.com/one")
    win._remember_url("https://example.com/two")
    win._remember_url("https://example.com/one")
    win._settings.sync()

    assert win.url_edit.itemText(0) == "https://example.com/one"
    assert win.url_edit.itemText(1) == "https://example.com/two"
    assert win.url_edit.count() == 2

    win2 = WebpageSeoWindow()
    qtbot.addWidget(win2)
    assert win2.url_edit.itemText(0) == "https://example.com/one"
    assert win2.url_edit.itemText(1) == "https://example.com/two"
    assert win2.url_edit.count() == 2


def test_seo_window_primary_controls_exist(qtbot) -> None:
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    assert win.windowTitle() == "Silentfrog - Single Page SEO Check"
    assert win.btn_go.text() == "Analyze"
    assert win.btn_export.text() == "Export Excel"
    assert win.btn_img_dl.text() == "Analyze images"
    assert win.btn_settings.text() == "Crawl settings..."


def test_seo_window_configures_scrollable_tabs(qtbot) -> None:
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    assert win.tabs.usesScrollButtons() is True
    assert win.tabs.elideMode() == QtCore.Qt.TextElideMode.ElideRight
    assert win.tabs.tabBar().expanding() is False
    assert "min-width: 0px" in win.tabs.styleSheet()
    assert win.body_stack.currentWidget() is win._intro_panel


def test_seo_window_url_combo_does_not_overflow_screen(qtbot) -> None:
    """Regression: url_edit was sizing to ~1880px because no
    SizeAdjustPolicy was set, pushing the window past the screen
    width on smaller displays.
    """
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    assert (
        win.url_edit.sizeAdjustPolicy()
        == QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    assert win.url_edit.minimumContentsLength() == 40
    assert win.url_edit.sizeHint().width() < 800

def test_recent_url_remove_click(qtbot, tmp_path: Path) -> None:
    _configure_settings(tmp_path)
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._remember_url("https://example.com/one")
    win._remember_url("https://example.com/two")
    win.show()

    win.url_edit.showPopup()
    qtbot.wait(50)
    view = win._recent_view
    model = view.model()
    assert model is not None
    index = model.index(0, 0)
    rect = view.visualRect(index)
    click_pos = QtCore.QPoint(rect.right() - 8, rect.center().y())
    qtbot.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=click_pos)

    assert win.url_edit.count() == 1
    assert win.url_edit.itemText(0) == "https://example.com/one"


def test_indexability_tab_flags_noindex(qtbot) -> None:
    tab = IndexabilityTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "chain": ["https://example.com"],
            "hops": 0,
            "final_status": "200",
            "loop": False,
        },
        {
            "target": "https://example.com",
            "self": True,
            "multiple": False,
            "status": "200",
        },
        "noindex, nofollow",
        {"*": [("Allow", "/")]},
    )

    model = tab.view.model()
    assert model is not None
    rows = {
        model.index(row, 0).data(): model.index(row, 1).data()
        for row in range(model.rowCount())
    }
    assert rows["Index directive"] == "Noindex"
    assert rows["Follow directive"] == "Nofollow"
    assert rows["Overall verdict"] == "Noindex"


def test_content_quality_tab_shows_strong_page(qtbot) -> None:
    tab = ContentQualityTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "language": "Spanish (es-ES)",
            "word_count": 380,
            "paragraph_count": 5,
            "substantial_paragraph_count": 4,
            "average_words_per_paragraph": 22.4,
            "title_present": True,
            "meta_description_present": True,
            "h1_count": 1,
            "h2_h6_count": 2,
            "title_h1_alignment": "Aligned",
            "intro_paragraph": "Present",
            "thin_content_risk": "Low",
            "heading_structure": "Good",
            "verdict": "Strong",
        }
    )

    model = tab.view.model()
    assert model is not None
    rows = {
        model.index(row, 0).data(): model.index(row, 1).data()
        for row in range(model.rowCount())
    }
    assert rows["Page language"] == "Spanish (es-ES)"
    assert rows["Thin-content risk"] == "Low"
    assert rows["Overall verdict"] == "Strong"

    tooltip_row = next(
        row for row in range(model.rowCount()) if model.index(row, 0).data() == "Page language"
    )
    tooltip = model.data(model.index(tooltip_row, 0), QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(tooltip, str)
    assert "Best practice" in tooltip
    assert "<html lang>" in tooltip


def test_ai_tab_shows_access_summary(qtbot) -> None:
    tab = AiTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            ["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"],
            ["Google-Extended", "google-extended", "No", "-", "-", "Blocked", "Blocked by robots.txt: /private"],
            ["Googlebot", "googlebot", "Yes", "-", "nosnippet", "Limited", "Google search controls: nosnippet"],
        ]
    )

    assert "Allowed 1" in tab._summary.text()
    assert "Limited 1" in tab._summary.text()
    assert "Blocked 1" in tab._summary.text()
    model = tab.view.model()
    assert model is not None
    tooltip = model.headerData(3, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(tooltip, str)
    assert "Nonstandard AI directives" in tooltip


def test_ai_tab_headers_and_empty_state_are_stable(qtbot) -> None:
    tab = AiTab()
    qtbot.addWidget(tab)
    tab.update([])

    assert "Allowed 0" in tab._summary.text()
    assert "Limited 0" in tab._summary.text()
    assert "Blocked 0" in tab._summary.text()
    model = tab.view.model()
    assert model is not None
    headers = [
        model.headerData(column, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole)
        for column in range(model.columnCount())
    ]
    assert headers == [
        "Agent",
        "Token",
        "Robots.txt OK",
        "Nonstandard directive",
        "Google controls",
        "Verdict",
        "Notes",
    ]
    assert model.rowCount() == 0


def test_ai_tab_header_tooltip_event(qtbot, monkeypatch) -> None:
    tab = AiTab()
    qtbot.addWidget(tab)
    tab.update([["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"]])
    tab.show()
    qtbot.waitExposed(tab)

    header = tab.view.horizontalHeader()
    shown: dict[str, str] = {}

    def _fake_show_text(pos, text, widget=None, rect=None, msec_display_time=-1):
        shown["text"] = text

    monkeypatch.setattr(QtWidgets.QToolTip, "showText", _fake_show_text)
    section = 3
    position = QtCore.QPoint(header.sectionViewportPosition(section) + 8, max(header.height() // 2, 1))
    event = QtGui.QHelpEvent(
        QtCore.QEvent.Type.ToolTip,
        position,
        header.viewport().mapToGlobal(position),
    )

    assert header.event(event) is True
    assert "noai" in shown["text"]


def test_ai_visibility_tab_renders_summary_and_rows(qtbot) -> None:
    tab = AiVisibilityTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "summary": {
                "verdict": "Needs work",
                "good_count": 3,
                "warning_count": 2,
                "critical_count": 0,
            },
            "checks": [
                {
                    "area": "Access",
                    "check": "Audited AI and search agents can access the page",
                    "status": "good",
                    "details": "Allowed: GPTBot, Google-Extended; Limited: -; Blocked: -.",
                    "recommendation": "Keep robots.txt open for the official AI and search agents you want to allow.",
                    "key": "access_agents",
                },
                {
                    "area": "Answerability",
                    "check": "The page answers the topic early",
                    "status": "warning",
                    "details": "Intro paragraph: Weak or missing; Overall content verdict: Needs work.",
                    "recommendation": "Add a concise opening summary paragraph.",
                    "key": "answer_intro",
                },
                {
                    "area": "Citation readiness",
                    "check": "The page is a stable canonical source",
                    "status": "critical",
                    "details": "Redirect hops: 2; Canonical self-reference: No; Multiple canonicals: No; Meta robots: noindex.",
                    "recommendation": "Keep the page indexable, self-canonical, and free from unnecessary redirects.",
                    "key": "citation_stability",
                },
            ],
        }
    )

    assert "Verdict:</b> Needs work" in tab._summary.text()
    assert "Warnings:</b> 2" in tab._summary.text()
    assert "Strong" in tab._summary.toolTip()
    assert "Weak" in tab._summary.toolTip()
    assert tab.view.wordWrap() is True
    assert tab.view.textElideMode() == QtCore.Qt.TextElideMode.ElideNone
    assert tab.view.verticalHeader().sectionResizeMode(0) == QtWidgets.QHeaderView.ResizeToContents
    model = tab.view.model()
    assert model is not None
    rows = [
        [model.index(row, column).data() for column in range(model.columnCount())]
        for row in range(model.rowCount())
    ]
    assert any(row[0] == "Access" and row[2] == "Good" for row in rows)
    assert any(row[0] == "Answerability" and row[2] == "Warning" for row in rows)
    assert any(row[0] == "Citation readiness" and row[2] == "Critical" for row in rows)
    headers = [
        model.headerData(column, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole)
        for column in range(model.columnCount())
    ]
    assert headers == ["Area", "Check", "Status", "Details", "Recommendation"]
    tooltip_row = next(
        row for row in range(model.rowCount()) if model.index(row, 0).data() == "Access"
    )
    tooltip = model.data(model.index(tooltip_row, 0), QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(tooltip, str)
    assert "robots.txt" in tooltip
    header_tooltip = model.headerData(2, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(header_tooltip, str)
    assert "Good, Warning, or Critical" in header_tooltip
    good_row = next(row for row in range(model.rowCount()) if model.index(row, 2).data() == "Good")
    warning_row = next(row for row in range(model.rowCount()) if model.index(row, 2).data() == "Warning")
    critical_row = next(row for row in range(model.rowCount()) if model.index(row, 2).data() == "Critical")
    assert model.data(model.index(good_row, 2), QtCore.Qt.ItemDataRole.BackgroundRole) is not None
    assert model.data(model.index(warning_row, 2), QtCore.Qt.ItemDataRole.BackgroundRole) is not None
    assert model.data(model.index(critical_row, 2), QtCore.Qt.ItemDataRole.BackgroundRole) is not None


def test_ai_visibility_tab_empty_state_is_stable(qtbot) -> None:
    tab = AiVisibilityTab()
    qtbot.addWidget(tab)
    tab.update({})

    assert "Verdict:</b> -" in tab._summary.text()
    model = tab.view.model()
    assert model is not None
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Info"
    assert model.data(model.index(0, 1)) == "No AI visibility data yet"
    assert model.data(model.index(0, 3)) == "Run an analysis to populate this tab."


def test_ai_visibility_tab_resizes_rows_when_first_shown(qtbot, monkeypatch) -> None:
    container = QtWidgets.QTabWidget()
    intro = QtWidgets.QWidget()
    tab = AiVisibilityTab()
    container.addTab(intro, "Intro")
    container.addTab(tab, "AI Visibility")
    container.setCurrentWidget(intro)
    qtbot.addWidget(container)

    resize_calls: list[int] = []
    original_apply = tab._apply_row_resize

    def _tracked_apply() -> None:
        resize_calls.append(tab.view.viewport().width())
        original_apply()

    monkeypatch.setattr(tab, "_apply_row_resize", _tracked_apply)

    tab.update(
        {
            "summary": {
                "verdict": "Needs work",
                "good_count": 1,
                "warning_count": 1,
                "critical_count": 0,
            },
            "checks": [
                {
                    "area": "Answerability",
                    "check": "The page answers the topic early",
                    "status": "warning",
                    "details": "This is deliberately long so the wrapped row height depends on the final visible width of the table.",
                    "recommendation": "Add a concise opening summary paragraph near the top of the page.",
                    "key": "answer_intro",
                }
            ],
        }
    )

    container.resize(900, 400)
    container.show()
    qtbot.waitExposed(container)
    container.setCurrentWidget(tab)
    qtbot.wait(50)

    assert resize_calls
    assert any(width > 0 for width in resize_calls)


def test_ai_visibility_tab_viewport_tooltip_event(qtbot, monkeypatch) -> None:
    tab = AiVisibilityTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "summary": {
                "verdict": "Needs work",
                "good_count": 1,
                "warning_count": 1,
                "critical_count": 0,
            },
            "checks": [
                {
                    "area": "Access",
                    "check": "Audited AI and search agents can access the page",
                    "status": "good",
                    "details": "Allowed: GPTBot; Limited: -; Blocked: -.",
                    "recommendation": "Keep robots.txt open for the official AI and search agents you want to allow.",
                    "key": "access_agents",
                }
            ],
        }
    )
    tab.show()
    qtbot.waitExposed(tab)

    model = tab.view.model()
    assert model is not None
    index = model.index(0, 0)
    rect = tab.view.visualRect(index)
    shown: dict[str, str] = {}

    def _fake_show_text(pos, text, widget=None, rect=None, msec_display_time=-1):
        shown["text"] = text

    monkeypatch.setattr(QtWidgets.QToolTip, "showText", _fake_show_text)
    event = QtGui.QHelpEvent(
        QtCore.QEvent.Type.ToolTip,
        rect.center(),
        tab.view.viewport().mapToGlobal(rect.center()),
    )

    assert tab.view.viewportEvent(event) is True
    assert "robots.txt" in shown["text"]


def test_content_quality_tab_viewport_tooltip_event(qtbot, monkeypatch) -> None:
    tab = ContentQualityTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "language": "English (en-US)",
            "word_count": 520,
            "paragraph_count": 8,
            "substantial_paragraph_count": 6,
            "average_words_per_paragraph": 24.5,
            "title_present": True,
            "meta_description_present": True,
            "h1_count": 1,
            "h2_h6_count": 3,
            "title_h1_alignment": "Aligned",
            "intro_paragraph": "Present",
            "thin_content_risk": "Low",
            "heading_structure": "Good",
            "verdict": "Strong",
        }
    )
    tab.show()
    qtbot.waitExposed(tab)

    model = tab.view.model()
    assert model is not None
    tooltip_row = next(
        row for row in range(model.rowCount()) if model.index(row, 0).data() == "Page language"
    )
    index = model.index(tooltip_row, 0)
    rect = tab.view.visualRect(index)
    shown: dict[str, str] = {}

    def _fake_show_text(pos, text, widget=None, rect=None, msec_display_time=-1):
        shown["text"] = text

    monkeypatch.setattr(QtWidgets.QToolTip, "showText", _fake_show_text)
    event = QtGui.QHelpEvent(
        QtCore.QEvent.Type.ToolTip,
        rect.center(),
        tab.view.viewport().mapToGlobal(rect.center()),
    )

    assert tab.view.viewportEvent(event) is True
    assert "Best practice" in shown["text"]


def test_seo_window_shows_placeholder_before_first_crawl(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    assert win.is_showing_placeholder() is True
    assert win.btn_export.isEnabled() is False
    assert win.btn_img_dl.isEnabled() is False


def test_seo_window_reveals_tabs_after_data(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    payload = _sample_payload()

    win._populate_tables(payload.to_mapping())

    assert win.is_showing_placeholder() is False
    assert win.btn_export.isEnabled() is True
    assert win.btn_img_dl.isEnabled() is True
    assert win.tabs.currentWidget() is win.recap_tab
    assert "Warnings found" in win.recap_tab.health_text()
    assert win.recap_tab.count_text(IssueSeverity.CRITICAL) == "Critical: 0"


def test_recap_issue_activation_opens_matching_detail_tab(qtbot) -> None:
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    data = _sample_payload().to_mapping()
    data["meta"] = [["title", "", "0"], ["description", "", "0"]]

    win._populate_tables(data)
    item = _recap_item_containing(win, "title tag")
    win.recap_tab.action_list.itemActivated.emit(item)

    assert win.tabs.tabText(win.tabs.currentIndex()) == "Meta tag"


@pytest.mark.parametrize(("tab_cls", "args", "resize_modes"), TABLE_TAB_CASES)
def test_table_tab_update_sets_model_and_resizing(
    tab_cls: Type[QtWidgets.QWidget],
    args: Tuple[object, ...],
    resize_modes: Dict[int, QtWidgets.QHeaderView.ResizeMode],
    qtbot,
) -> None:
    tab = tab_cls()
    qtbot.addWidget(tab)
    tab.update(*args)

    model = tab.view.model()
    assert model is not None
    assert model.rowCount() > 0
    assert tab.view.isSortingEnabled()

    header = tab.view.horizontalHeader()
    assert isinstance(header, QtWidgets.QHeaderView)
    assert header.sectionsClickable() is True
    assert header.isSortIndicatorShown() is True
    for section, expected_mode in resize_modes.items():
        assert header.sectionResizeMode(section) == expected_mode


def test_meta_tab_sorting_reorders_rows(qtbot) -> None:
    tab = MetaTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            ["title", "Short title", "11"],
            ["description", "Longer description", "120"],
            ["robots", "index, follow", "13"],
        ]
    )

    tab.view.sortByColumn(2, QtCore.Qt.SortOrder.DescendingOrder)
    QtWidgets.QApplication.processEvents()

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 0)) == "description"
    assert model.data(model.index(1, 0)) == "robots"


def test_meta_tab_header_click_sorts_rows(qtbot) -> None:
    tab = MetaTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            ["title", "Short title", "11"],
            ["description", "Longer description", "120"],
            ["robots", "index, follow", "13"],
        ]
    )
    tab.show()
    qtbot.waitExposed(tab)

    header = tab.view.horizontalHeader()
    section = 2
    position = QtCore.QPoint(header.sectionViewportPosition(section) + 8, max(header.height() // 2, 1))

    qtbot.mouseClick(header.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=position)
    qtbot.mouseClick(header.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=position)

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 0)) == "description"
    assert header.sortIndicatorSection() == 2


def test_headers_tab_sorting_reorders_rows(qtbot) -> None:
    tab = HeadersTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            ["h2", "Alpha section"],
            ["h1", "Zulu topic"],
            ["h3", "Middle section"],
        ]
    )

    tab.view.sortByColumn(1, QtCore.Qt.SortOrder.DescendingOrder)
    QtWidgets.QApplication.processEvents()

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 1)) == "Zulu topic"
    assert model.data(model.index(1, 1)) == "Middle section"


def test_images_tab_sorting_reorders_rows_and_keeps_diagnostics(qtbot) -> None:
    tab = ImagesTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            normalize_image_row(
                ["https://example.com/light.png", "Alt", "Title", "image/png", "", "", "10 KB", "1h", "Lazy", "Low"]
            ),
            normalize_image_row(
                ["https://example.com/heavy.png", "Alt", "Title", "image/png", "", "", "250 KB", "1h", "Lazy", "Low"]
            ),
        ]
    )

    tab.view.sortByColumn(SIZE_COL, QtCore.Qt.SortOrder.DescendingOrder)
    QtWidgets.QApplication.processEvents()

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 0)) == "https://example.com/heavy.png"
    assert model.data(model.index(1, 0)) == "https://example.com/light.png"
    assert model.data(model.index(0, SIZE_COL), QtCore.Qt.ItemDataRole.BackgroundRole) is not None


def test_images_tab_header_click_sorts_size_desc(qtbot) -> None:
    tab = ImagesTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            normalize_image_row(
                ["https://example.com/light.png", "Alt", "Title", "image/png", "", "", "10 KB", "1h", "Lazy", "Low"]
            ),
            normalize_image_row(
                ["https://example.com/heavy.png", "Alt", "Title", "image/png", "", "", "250 KB", "1h", "Lazy", "Low"]
            ),
        ]
    )
    tab.show()
    qtbot.waitExposed(tab)

    header = tab.view.horizontalHeader()
    position = QtCore.QPoint(header.sectionViewportPosition(SIZE_COL) + 8, max(header.height() // 2, 1))

    qtbot.mouseClick(header.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=position)
    qtbot.mouseClick(header.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=position)

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 0)) == "https://example.com/heavy.png"
    assert header.sortIndicatorSection() == SIZE_COL


def test_schema_tab_theme_toggle(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    payload = [
        {
            "_schema_summary": {
                "total": 1,
                "by_syntax": {"json-ld": 1},
                "by_type": {"WebPage": 1},
                "errors": [],
            }
        },
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "_extracted_via": "json-ld",
        },
    ]
    dark_palette = tab.palette()
    dark_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 30, 30))
    tab.setPalette(dark_palette)
    tab.update(payload)
    assert "#1e1e1e" in tab.styleSheet()

    light_palette = tab.palette()
    light_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
    tab.setPalette(light_palette)
    tab.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
    assert "#ffffff" in tab.styleSheet()

    dark_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 30, 30))
    tab.setPalette(dark_palette)
    tab.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
    assert "#1e1e1e" in tab.styleSheet()


def test_keywords_tab_theme_toggle(qtbot):
    tab = KeywordsTab()
    qtbot.addWidget(tab)
    payload = [
        {
            "term": "example",
            "length": 1,
            "frequency": 5,
            "density": 3.2,
            "density_threshold": 4.0,
            "density_warning": False,
            "in_title": True,
            "in_description": False,
            "heading_count": 1,
            "first_position": 0,
        }
    ]
    dark_palette = tab.palette()
    dark_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 30, 30))
    tab.setPalette(dark_palette)
    tab.update(payload)
    assert "#1e1e1e" in tab.view.styleSheet()

    light_palette = tab.palette()
    light_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
    tab.setPalette(light_palette)
    tab.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
    assert "#ffffff" in tab.view.styleSheet()

    dark_palette.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 30, 30))
    tab.setPalette(dark_palette)
    tab.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
    assert "#1e1e1e" in tab.view.styleSheet()


def test_performance_tab_renders_summary_and_opportunities(qtbot):
    tab = PerformanceTab()
    qtbot.addWidget(tab)

    payload = {
        "status": 200,
        "nav_ttfb_ms": 135.0,
        "nav_total_ms": 780.0,
        "transfer_size": 512000,
        "resource_summary": {
            "js": {"count": 5, "bytes": 40960},
            "img": {"count": 2, "bytes": 81920},
        },
        "summary": {
            "transfer_size": 512000,
            "total_resource_bytes": 122880,
            "total_page_bytes": 634880,
            "total_resource_count": 7,
            "third_party_bytes": 20480,
            "third_party_count": 2,
            "critical_issue_count": 1,
            "warning_issue_count": 1,
            "info_issue_count": 0,
            "verdict": "High performance risk",
        },
        "issues": [
            {
                "key": "blocking_js",
                "severity": "critical",
                "message": "Blocking JavaScript was detected in the page source.",
                "evidence": "2 blocking script(s), 43.9 KB total.",
                "recommendation": "Move non-critical scripts to defer/async and reduce blocking script weight.",
            },
            {
                "key": "image_weight",
                "severity": "warning",
                "message": "Image payload is heavier than ideal.",
                "evidence": "Measured image weight is 80.0 KB.",
                "recommendation": "Compress large images and review responsive delivery.",
            },
        ],
        "opportunity_details": [
            {"message": "Bundle JavaScript files", "severity": "warning"},
            {"message": "Review resource weight", "severity": "critical"},
        ],
        "top_offenders": [
            {"type": "js", "url": "https://example.com/app.js", "bytes": 40960, "blocking": True},
            {"type": "img", "url": "https://example.com/photo.jpg", "bytes": 81920, "blocking": False},
        ],
        "scripts": {
            "blocking": {"count": 2, "bytes": 45000},
            "async": {"count": 3, "bytes": 10240},
        },
    }

    tab.update(payload)

    summary_text = tab._summary.text()
    assert "Verdict:" in summary_text
    assert "Status:" in summary_text
    assert "TTFB:" in summary_text
    assert "Transfer:" in summary_text
    assert "Page weight:" in summary_text
    assert "Third-party:" in summary_text
    assert "620.0 KB" in summary_text
    assert "Third-party" in tab._summary.toolTip()

    scripts_text = tab._scripts.text()
    assert "Blocking JS" in scripts_text
    assert "Async/Deferred JS" in scripts_text
    assert "Images:" in scripts_text
    assert "Resource breakdown" in tab._scripts.toolTip()

    model = tab.view.model()
    assert model is not None
    assert model.rowCount() == 2
    header = tab.view.horizontalHeader()
    assert isinstance(header, QtWidgets.QHeaderView)
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.Stretch
    rows = [
        [
            model.data(model.index(row, column))
            for column in range(model.columnCount())
        ]
        for row in range(model.rowCount())
    ]
    assert any(row[1] == "Critical" and "Blocking JavaScript" in row[0] for row in rows)
    assert any("defer/async" in row[3] for row in rows)
    critical_row = next(
        row
        for row in range(model.rowCount())
        if model.data(model.index(row, 1)) == "Critical"
        and "Blocking JavaScript" in str(model.data(model.index(row, 0)) or "")
    )
    assert model.data(model.index(critical_row, 1), QtCore.Qt.ItemDataRole.BackgroundRole) is not None
    tooltip = model.data(model.index(critical_row, 0), QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(tooltip, str)
    assert "defer or async" in tooltip.lower()

    opp_html = tab._opportunities.text()
    assert "Bundle JavaScript files" in opp_html
    assert "Review resource weight" in opp_html
    assert "Critical" in opp_html
    assert "Warning" in opp_html

    offender_model = tab._offender_view.model()
    assert offender_model is not None
    assert offender_model.rowCount() == 2
    assert offender_model.data(offender_model.index(0, 0)) == "JS"
    assert offender_model.data(offender_model.index(0, 2)) == "Blocking"
    assert offender_model.data(offender_model.index(0, 3)) == "40.0 KB"
    assert offender_model.data(offender_model.index(1, 2)) == "Async"
    assert offender_model.data(offender_model.index(1, 3)) == "80.0 KB"


def test_performance_tab_empty_state_is_stable(qtbot) -> None:
    tab = PerformanceTab()
    qtbot.addWidget(tab)
    tab.update({})

    assert "Verdict:" in tab._summary.text()
    assert "Resources:" in tab._summary.text()
    assert "No issues detected" in tab._opportunities.text()
    model = tab.view.model()
    assert model is not None
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "No major performance issues detected"
    assert model.data(model.index(0, 1)) == "OK"
    offender_model = tab._offender_view.model()
    assert offender_model is not None
    assert offender_model.rowCount() == 1
    assert offender_model.data(offender_model.index(0, 0)) == "-"
    assert offender_model.data(offender_model.index(0, 1)) == "-"


def test_robots_tab_appends_empty_state(qtbot):
    tab = RobotsTab()
    qtbot.addWidget(tab)
    tab.update("", {})

    model = tab.view.model()
    assert model is not None
    rows = [
        (model.index(row, 0).data(), model.index(row, 1).data())
        for row in range(model.rowCount())
    ]
    assert ("robots.txt", "Not fetched or empty") in rows


def test_images_tab_merges_worker_results(qtbot):
    tab = ImagesTab()
    qtbot.addWidget(tab)
    initial_rows = [
        normalize_image_row(["https://example.com/img.png", "Alt", "Title", "-", "", "", "", "", "No", ""])
    ]
    tab.update(initial_rows)

    worker_rows = [["https://example.com/img.png", 640, 480, "18 KB", "image/png", "1h"]]
    tab.update(worker_rows)

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 3)) == "image/png"
    assert model.data(model.index(0, ACTUAL_WIDTH_COL)) == "640"
    assert model.data(model.index(0, SIZE_COL)) == "18 KB"
    assert model.data(model.index(0, CACHE_COL)) == "1h"
    assert tab.rows()[0][ACTUAL_WIDTH_COL] == "640"
    assert tab.rows()[0][SIZE_COL] == "18 KB"
    header = tab.view.horizontalHeader()
    assert isinstance(header, QtWidgets.QHeaderView)
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive


def test_images_tab_header_order_keeps_analysis_columns_visible(qtbot):
    tab = ImagesTab()
    qtbot.addWidget(tab)
    tab.update(
        [
            normalize_image_row(
                ["https://example.com/img.png", "Alt", "Title", "image/png", "", "", "", "", "Lazy", "High"]
            )
        ]
    )

    model = tab.view.model()
    assert model is not None

    headers = [
        model.headerData(column, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole)
        for column in range(model.columnCount())
    ]
    assert headers == IMAGE_HEADERS
    assert headers[:8] == ["Src", "Alt", "Title", "Type", "W", "H", "Size", "Cache TTL"]


def test_schema_tab_dark_palette(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    _set_base(tab, 16)
    app = QtWidgets.QApplication.instance()
    assert app is not None
    assert app.property("silentfrog_theme") == "dark"
    items = [{"@context": "https://schema.org", "_extracted_via": "json-ld"}]
    tab.update(items)

    assert "background:#1e1e1e; color:#f0f0f0;" in tab.styleSheet()
    html = tab.toHtml()
    assert "background-color:#262626;" in html
    assert "color:#f0f0f0;" in html


def test_schema_tab_light_palette(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    _set_base(tab, 255)
    app = QtWidgets.QApplication.instance()
    assert app is not None
    assert app.property("silentfrog_theme") == "light"
    items = [{"@context": "https://schema.org", "_extracted_via": "json-ld"}]
    tab.update(items)

    assert "background:#ffffff; color:#202124;" in tab.styleSheet()
    html = tab.toHtml()
    assert "background-color:#f7f7f7;" in html
    assert "color:#202124;" in html


def test_schema_tab_handles_missing_items(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    tab.update([])

    assert "Structured data not found" in tab.toHtml()


def test_schema_tab_renders_eligibility_summary(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "summary": {
                "total": 1,
                "by_syntax": {"json-ld": 1},
                "by_type": {"Product": 1},
                "errors": ["Block #1 (Product) via json-ld: missing offers.price"],
            },
            "eligibility": [
                {
                    "type": "Product",
                    "detected": True,
                    "count": 1,
                    "eligibility": "Incomplete",
                    "missing_fields": ["missing offers.price", "missing offers.priceCurrency"],
                    "warnings": ["Missing required fields"],
                }
            ],
            "blocks": [
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "_extracted_via": "json-ld",
                    "_schema_errors": ["missing offers.price", "missing offers.priceCurrency"],
                }
            ],
        }
    )

    html = tab.toHtml()
    assert "Eligibility summary" in html
    assert "Product" in html
    assert "Incomplete" in html
    assert "missing offers.price" in html


def test_schema_tab_displays_block_errors(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    items = [
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "_extracted_via": "json-ld",
            "itemListElement": [{"@type": "ListItem", "name": "Home"}],
            "_schema_errors": [
                "itemListElement[1] missing position",
                "itemListElement[1] missing item url",
            ],
        },
        {
            "_schema_issues": [
                "Block #1 (BreadcrumbList) via json-ld: itemListElement[1] missing position",
                "Block #1 (BreadcrumbList) via json-ld: itemListElement[1] missing item url",
            ]
        },
    ]

    tab.update(items)
    html = tab.toHtml()
    assert "Block #1 (BreadcrumbList) via json-ld" in html
    assert "itemListElement[1] missing position" in html
    assert "<ul" in html


def test_serp_tab_snapshot(qtbot):
    tab = SerpTab()
    qtbot.addWidget(tab)
    serp = {
        "title": "Example Title",
        "description": "Example description for preview.",
        "url": "https://example.com/page",
        "site_name": "Example",
        "breadcrumb": "example.com > page",
        "favicon": "https://example.com/favicon.png",
    }
    audit = {
        "char_len": "20",
        "px_len": "144",
        "too_long": "No",
        "too_short": "No",
        "px_over": "No",
        "px_under": "No",
        "equals_h1": "No",
        "missing": "No",
    }
    tab.update(serp, audit)

    assert tab.preview.styleSheet() == "background:#ffffff;color:#202124;border:1px solid #d0d0d0;"
    model = tab.table.model()
    assert model is not None
    assert model.rowCount() == 8
    header = tab.table.horizontalHeader()
    assert isinstance(header, QtWidgets.QHeaderView)
    assert header.sectionResizeMode(1) == QtWidgets.QHeaderView.ResizeToContents

    normalized_html = _normalize_html(tab.preview.toHtml())
    expected_html = _normalize_html(SERP_SNAPSHOT.read_text(encoding="utf-8"))
    plain_text = tab.preview.toPlainText()
    assert "Example Title" in plain_text
    assert "Example description for preview." in plain_text
    assert "example.com > page" in plain_text
    assert "favicon.png" in normalized_html
    assert "favicon.png" in expected_html
    assert "example.com/page" in normalized_html
    assert "example.com/page" in expected_html


def test_export_excel_triggers_save_dialog(qtbot, monkeypatch, tmp_path: Path):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._latest_payload = _sample_payload()  # type: ignore[attr-defined]
    win.btn_export.setEnabled(True)

    target = tmp_path / "report"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), ""),
    )

    captured: Dict[str, Any] = {}

    def fake_export(payload: CrawlPayload, path: Path) -> None:
        captured["payload"] = payload
        captured["path"] = path

    monkeypatch.setattr("silentfrog.seo_gui.export_page_analysis", fake_export)
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None)

    win._export_excel()

    payload_value = captured.get("payload")
    path_value = captured.get("path")
    assert isinstance(payload_value, CrawlPayload)
    assert isinstance(path_value, Path)
    assert payload_value is win._latest_payload
    assert path_value == target.with_suffix(".xlsx")
    assert QtWidgets.QApplication.overrideCursor() is None


def test_export_excel_without_payload_shows_warning(qtbot, monkeypatch):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._latest_payload = None  # type: ignore[attr-defined]

    flagged = {}

    def fake_info(*args, **kwargs):
        flagged["called"] = True

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", fake_info)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))

    win._export_excel()

    assert flagged.get("called") is True


def test_image_analysis_updates_payload_rows(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    payload = _sample_payload()
    win._populate_tables(payload.to_mapping())

    update_rows = [[payload.images[0][0], 640, 320, "42 KB", "image/png", "30m"]]
    win._populate_tables({"img_update": update_rows})

    assert win._latest_payload is not None
    image_row = win._latest_payload.images[0]
    assert image_row[0] == payload.images[0][0]
    assert image_row[1] == "Alt"
    assert image_row[2] == "Title"
    assert image_row[3] == "image/png"
    assert image_row[DECLARED_WIDTH_COL] == "100"
    assert image_row[DECLARED_HEIGHT_COL] == "200"
    assert image_row[ACTUAL_WIDTH_COL] == "640"
    assert image_row[ACTUAL_HEIGHT_COL] == "320"
    assert image_row[SIZE_COL] == "42 KB"
    assert image_row[CACHE_COL] == "30m"
    assert image_row[LOADING_COL] == payload.images[0][LOADING_COL]
    assert image_row[FETCH_PRIORITY_COL] == payload.images[0][FETCH_PRIORITY_COL]
    assert image_row[DIAGNOSTIC_COL]


def test_image_analysis_updates_visible_columns_in_images_tab(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    payload = _sample_payload()
    win._populate_tables(payload.to_mapping())
    win._populate_tables({"img_update": [[payload.images[0][0], 640, 320, "42 KB", "image/png", "30m"]]})

    model = win.images_tab.view.model()
    assert model is not None

    assert model.headerData(ACTUAL_WIDTH_COL, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole) == "W"
    assert model.headerData(ACTUAL_HEIGHT_COL, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole) == "H"
    assert model.headerData(SIZE_COL, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole) == "Size"
    assert model.headerData(CACHE_COL, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole) == "Cache TTL"

    assert model.data(model.index(0, ACTUAL_WIDTH_COL)) == "640"
    assert model.data(model.index(0, ACTUAL_HEIGHT_COL)) == "320"
    assert model.data(model.index(0, SIZE_COL)) == "42 KB"
    assert model.data(model.index(0, CACHE_COL)) == "30m"


def test_seo_window_populates_ai_visibility_tab(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)

    payload = _sample_payload()
    win._populate_tables(payload.to_mapping())

    model = win.ai_visibility_tab.view.model()
    assert model is not None
    assert win.ai_visibility_tab._summary.text().find("Needs work") != -1
    rows = [
        [model.index(row, column).data() for column in range(model.columnCount())]
        for row in range(model.rowCount())
    ]
    assert any(row[0] == "Access" and row[2] == "Good" for row in rows)
    assert any(row[0] == "Citation readiness" and row[2] == "Warning" for row in rows)


def test_crawl_settings_dialog_roundtrip(qtbot):
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.chk_gentle.isChecked() is False
    assert dialog.spin_parallel.value() == 4

    dialog.btn_preset_gentle.setChecked(True)
    assert dialog.spin_parallel.value() == 2
    dialog.btn_preset_standard.setChecked(True)
    assert dialog.spin_parallel.value() == 4
    dialog.btn_preset_custom.setChecked(True)

    dialog.chk_gentle.setChecked(True)
    dialog.spin_parallel.setValue(3)
    dialog.txt_headers.setPlainText("Authorization: Token 123")
    dialog.edit_cookies.setText("session=abc")

    options = dialog.options()
    assert options.gentle_mode is True
    assert options.max_concurrent_per_host == 3
    assert options.extra_headers["Authorization"] == "Token 123"
    assert options.extra_headers["Cookie"] == "session=abc"


def test_crawl_settings_toggle_reset_to_standard(qtbot):
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.chk_gentle.setChecked(True)
    dialog.spin_parallel.setValue(1)
    dialog.chk_gentle.setChecked(False)
    assert dialog.btn_preset_standard.isChecked()
    assert dialog.spin_parallel.value() == 4


def test_crawl_settings_spin_triggers_custom(qtbot):
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.chk_gentle.setChecked(True)
    dialog.spin_parallel.setValue(3)
    assert dialog.btn_preset_custom.isChecked()


def test_window_applies_dialog_options(qtbot, monkeypatch):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    assert win._crawl_options.gentle_mode is False

    desired = CrawlOptions.from_ui(
        gentle_mode=True,
        max_parallel=2,
        header_text="X-Test: 1",
    )

    class DummyDialog:
        def __init__(self, current, parent) -> None:
            self._current = current

        def exec(self) -> int:
            return QtWidgets.QDialog.Accepted

        def options(self) -> CrawlOptions:
            return desired

    monkeypatch.setattr("silentfrog.seo_gui.CrawlSettingsDialog", DummyDialog)
    win._open_crawl_settings()

    assert win._crawl_options.gentle_mode is True
    assert win._crawl_options.extra_headers["X-Test"] == "1"


def test_populate_tables_reenables_controls(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    payload = _sample_payload()

    win.bar.setVisible(True)

    win._populate_tables(payload.to_mapping())

    assert not win.bar.isVisible()


def test_clear_results_resets_tabs(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    payload = _sample_payload()

    win._populate_tables(payload.to_mapping())

    assert _row_count(win.meta_tab.view) > 0

    win._clear_results()

    assert _row_count(win.meta_tab.view) == 0
    assert _row_count(win.headers_tab.view) == 0
    assert _row_count(win.images_tab.view) == 0
    assert _row_count(win.links_tab.view) == 0
    assert win.btn_export.isEnabled() is False
    assert win.recap_tab.health_text().startswith("<b>Ready</b>")

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Tuple, Type, cast

import pytest
from PyQt5 import QtCore, QtGui, QtWidgets

from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.crawl_options import CrawlOptions  # type: ignore[reportMissingImports]
from silentfrog.settings_dialog import CrawlSettingsDialog  # type: ignore[reportMissingImports]
from silentfrog.seo_gui import WebpageSeoWindow  # type: ignore[reportMissingImports]
from silentfrog.tabs import (  # type: ignore[reportMissingImports]
    AiTab,
    CanonicalTab,
    HeadersTab,
    ImagesTab,
    HreflangTab,
    KeywordsTab,
    PerformanceTab,
    LinksTab,
    MetaTab,
    RedirectTab,
    RobotsTab,
    SchemaTab,
    SerpTab,
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
    color = QtGui.QColor(value, value, value)
    palette = QtGui.QPalette(cast(QtWidgets.QApplication, app).palette())
    palette.setColor(QtGui.QPalette.Base, color)
    palette.setColor(QtGui.QPalette.Window, color)
    text = QtGui.QColor(240, 240, 240) if value < 128 else QtGui.QColor(32, 33, 36)
    palette.setColor(QtGui.QPalette.Text, text)
    palette.setColor(QtGui.QPalette.WindowText, text)
    cast(QtWidgets.QApplication, app).setPalette(palette)
    cast(QtWidgets.QApplication, app).setProperty("silentfrog_theme", "dark" if value < 128 else "light")


def _row_count(view: QtWidgets.QTableView) -> int:
    model = view.model()
    assert model is not None
    return model.rowCount()

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
            ["https://example.com/logo.png", "Alt", "Title", "image/png", "100", "200", "10 KB", "Yes", "High"]
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
        "ai_crawl": [["GPTBot", "Yes", "No", "Allowed"]],
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
        ([["https://example.com/img.png", "Alt", "Title", "640", "480", "18 KB"]],),
        {0: QtWidgets.QHeaderView.Interactive},
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
        ([["Crawler", "Yes", "No", "Allowed"]],),
        {
            0: QtWidgets.QHeaderView.ResizeToContents,
            3: QtWidgets.QHeaderView.ResizeToContents,
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

    assert win.tabs.count() == 13
    labels = [win.tabs.tabText(index) for index in range(win.tabs.count())]
    assert labels == [
        "Meta tag",
        "Header H1-H6",
        "Images",
        "Link",
        "Redirect",
        "Canonical",
        "Robots",
        "Hreflang",
        "Structured data",
        "Keywords",
        "AI crawl",
        "Performance",
        "SERP",
    ]


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
    for section, expected_mode in resize_modes.items():
        assert header.sectionResizeMode(section) == expected_mode


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
    assert "Status:" in summary_text
    assert "TTFB:" in summary_text
    assert "Transfer:" in summary_text
    assert "Page weight:" in summary_text
    assert "620.0 KB" in summary_text

    scripts_text = tab._scripts.text()
    assert "Blocking JS" in scripts_text
    assert "Async/Deferred JS" in scripts_text

    model = tab.view.model()
    assert model is not None
    assert model.rowCount() == 2
    header = tab.view.horizontalHeader()
    assert isinstance(header, QtWidgets.QHeaderView)
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.Stretch
    assert model.data(model.index(0, 2)) == "40.0 KB"

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
        ["https://example.com/img.png", "Alt", "Title", "-", "", "", "", "No", ""]
    ]
    tab.update(initial_rows)

    worker_rows = [["https://example.com/img.png", 640, 480, "18 KB", "image/png"]]
    tab.update(worker_rows)

    model = tab.view.model()
    assert model is not None
    assert model.data(model.index(0, 3)) == "image/png"
    assert model.data(model.index(0, 4)) == "640"
    assert model.data(model.index(0, 6)) == "18 KB"
    assert tab.rows()[0][4] == "640"
    assert tab.rows()[0][6] == "18 KB"
    header = tab.view.horizontalHeader()
    assert isinstance(header, QtWidgets.QHeaderView)
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive


def test_schema_tab_dark_palette(qtbot):
    tab = SchemaTab()
    qtbot.addWidget(tab)
    _set_base(tab, 16)
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
    assert normalized_html == expected_html


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

    update_rows = [[payload.images[0][0], 640, 320, "42 KB", "image/png"]]
    win._populate_tables({"img_update": update_rows})

    assert win._latest_payload is not None
    image_row = win._latest_payload.images[0]
    assert image_row[0] == payload.images[0][0]
    assert image_row[1] == "Alt"
    assert image_row[2] == "Title"
    assert image_row[3] == "image/png"
    assert image_row[4] == "640"
    assert image_row[5] == "320"
    assert image_row[6] == "42 KB"
    assert image_row[7] == "Yes"
    assert image_row[8] == payload.images[0][8]


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

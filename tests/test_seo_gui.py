from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Tuple, Type

import pytest
from PyQt5 import QtGui, QtWidgets

from silentfrog.crawl_types import CrawlPayload
from silentfrog.seo_gui import WebpageSeoWindow
from silentfrog.tabs import (
    AiTab,
    CanonicalTab,
    HeadersTab,
    ImagesTab,
    HreflangTab,
    KeywordsTab,
    LinksTab,
    MetaTab,
    RedirectTab,
    RobotsTab,
    SchemaTab,
    SerpTab,
)

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")
SERP_SNAPSHOT = SNAPSHOT_DIR / "serp_preview.html"


def _normalize_html(html: str) -> str:
    cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", html, flags=re.IGNORECASE)
    cleaned = re.sub(r"<head>.*?</head>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.replace("\xa0", "&nbsp;")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _set_base(widget: QtWidgets.QWidget, value: int) -> None:
    palette = widget.palette()
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(value, value, value))
    widget.setPalette(palette)


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
        "images": [["https://example.com/logo.png", "Alt", "Title", "image/png", "100", "200", "10 KB", "Yes"]],
        "links": [["https://example.com", "Example", "Follow", "200"]],
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
        "keywords": [["keyword", "5"]],
    }
    return CrawlPayload.from_raw(raw)


def test_seo_window_exposes_expected_tabs(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win.show()

    assert win.tabs.count() == 12
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
        "SERP",
    ]


TABLE_TAB_CASES: Tuple[
    Tuple[Type[QtWidgets.QWidget], Tuple[object, ...], Dict[int, QtWidgets.QHeaderView.ResizeMode]],
    ...,
] = (
    (MetaTab, ([["description", "Example description", "150"]],), {}),
    (HeadersTab, ([["h1", "Heading"]],), {}),
    (
        ImagesTab,
        ([["https://example.com/img.png", "Alt", "Title", "640", "480", "18 KB"]],),
        {0: QtWidgets.QHeaderView.Interactive},
    ),
    (
        LinksTab,
        ([["https://example.com", "Example", "Follow", "200"]],),
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
        ({"target": "https://example.com", "self": True, "multiple": False, "status": "200"},),
        {},
    ),
    (
        RobotsTab,
        ("noindex", {"*": [("Allow", "/"), ("Disallow", "/tmp")]}),
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
    (KeywordsTab, ([["python", "4"]],), {}),
)


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
        ["https://example.com/img.png", "Alt", "Title", "-", "", "", "", "No"]
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
    assert "background-color:#2a2a2a;" in html
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
    expected_html = SERP_SNAPSHOT.read_text(encoding="utf-8").strip()
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


def test_populate_tables_reenables_controls(qtbot):
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    payload = _sample_payload()

    win.btn_go.setEnabled(False)
    win.bar.setVisible(True)

    win._populate_tables(payload.to_mapping())

    assert win.btn_go.isEnabled()
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

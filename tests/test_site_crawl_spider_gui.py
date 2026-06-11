"""v2.0 V3.1 — Site Crawl GUI drives the spider (crawl-mode controls)."""

from __future__ import annotations

from silentfrog.crawl_mode import CrawlMode
from silentfrog.site_crawl_gui import SiteCrawlWindow


def test_crawl_mode_combo_has_all_modes(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    labels = [win.crawl_mode_combo.itemText(i) for i in range(win.crawl_mode_combo.count())]
    assert "Auto (recommended)" in labels[0]
    datas = [win.crawl_mode_combo.itemData(i) for i in range(win.crawl_mode_combo.count())]
    assert datas[0] is None  # Auto
    # Stored as string values; round-tripped via CrawlMode.from_value.
    modes = {CrawlMode.from_value(d) for d in datas if d is not None}
    assert modes == {CrawlMode.HYBRID, CrawlMode.SPIDER, CrawlMode.SITEMAP, CrawlMode.LIST}


def test_defaults_max_urls_raised_and_robots_on(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    assert win.limit_spin.maximum() == 1_000_000
    assert win.respect_robots_check.isChecked() is True
    assert win.follow_subdomains_check.isChecked() is False
    assert win.depth_spin.value() == 10
    assert win.politeness_spin.value() == 200


def test_auto_mode_hybrid_for_base_url_only(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.base_url.setText("https://example.com")
    win.crawl_mode_combo.setCurrentIndex(0)  # Auto
    config = win._config_from_ui()
    assert config.spider.mode is CrawlMode.HYBRID


def test_auto_mode_list_for_url_list(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.base_url.setText("https://example.com")
    win.url_list.setPlainText("https://example.com/a\nhttps://example.com/b")
    win.crawl_mode_combo.setCurrentIndex(0)  # Auto
    assert win._config_from_ui().spider.mode is CrawlMode.LIST


def test_explicit_spider_mode_honours_all_fields(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.base_url.setText("https://example.com")
    spider_index = next(
        i for i in range(win.crawl_mode_combo.count()) if win.crawl_mode_combo.itemData(i) == CrawlMode.SPIDER.value
    )
    win.crawl_mode_combo.setCurrentIndex(spider_index)
    win.depth_spin.setValue(3)
    win.politeness_spin.setValue(500)
    win.respect_robots_check.setChecked(False)
    win.follow_subdomains_check.setChecked(True)
    spider = win._config_from_ui().spider
    assert spider.mode is CrawlMode.SPIDER
    assert spider.max_depth == 3
    assert spider.politeness_delay_ms == 500
    assert spider.respect_robots is False
    assert spider.follow_subdomains is True

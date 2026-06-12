"""SchemaTab groups nested component types under their parent (hotfix)."""

from __future__ import annotations

from silentfrog.schema_extractor import _extract_schema_all
from silentfrog.tabs import SchemaTab

_HTML = (
    "<html><head>"
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"LocalBusiness","name":"Acme",'
    '"address":{"@type":"PostalAddress","streetAddress":"Via Roma 1","addressLocality":"Milano"}}'
    "</script>"
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":'
    '[{"@type":"ListItem","position":1,"item":{"@id":"https://e.com/","name":"Home"}}]}'
    "</script>"
    "</head><body>x</body></html>"
)


def test_schema_tab_header_separates_primary_and_nested(qtbot) -> None:
    tab = SchemaTab()
    qtbot.addWidget(tab)
    tab.update(_extract_schema_all(_HTML, "https://e.com/p"))
    html = tab.toHtml()
    # 2 primary (LocalBusiness + BreadcrumbList), 2 nested (PostalAddress + ListItem).
    assert "2 items" in html
    assert "nested component" in html


def test_schema_tab_labels_nested_with_parent(qtbot) -> None:
    tab = SchemaTab()
    qtbot.addWidget(tab)
    tab.update(_extract_schema_all(_HTML, "https://e.com/p"))
    html = tab.toHtml()
    # PostalAddress is shown but labelled as a component "in LocalBusiness".
    assert "PostalAddress" in html
    assert "in LocalBusiness" in html


def test_schema_block_models_carry_roles(qtbot) -> None:
    tab = SchemaTab()
    qtbot.addWidget(tab)
    tab.update(_extract_schema_all(_HTML, "https://e.com/p"))
    roles = {b.type_hint: b.role for b in tab._state["blocks"]}
    assert roles["LocalBusiness"] == "primary"
    assert roles["PostalAddress"] == "nested"

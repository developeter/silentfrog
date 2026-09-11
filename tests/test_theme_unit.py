from __future__ import annotations

import re

from silentfrog.theme import (  # type: ignore[reportMissingImports]
    DARK_STYLESHEET,
    LIGHT_STYLESHEET,
)

_DOWN_ARROW_RULE = re.compile(r"QComboBox::down-arrow\s*\{[^}]*\bimage:\s*url\(([^)]+)\)")
_DOWN_ARROW_DISABLED_RULE = re.compile(r"QComboBox::down-arrow:disabled\s*\{[^}]*\bimage:\s*url\(([^)]+)\)")


def test_combobox_down_arrow_visible_in_both_themes() -> None:
    """Regression for the invisible dropdown arrow: styling ::drop-down
    suppresses Qt's native arrow, and (as verified by manual rendering) a
    plain CSS border-triangle is NOT honoured by QComboBox::down-arrow under
    this app's native styles — it paints as a solid block, not a chevron.
    An explicit image-backed ::down-arrow rule is required or the combo
    boxes that hold past-scan history look like plain text fields with no
    indication they are dropdowns."""
    for name, stylesheet in (("dark", DARK_STYLESHEET), ("light", LIGHT_STYLESHEET)):
        match = _DOWN_ARROW_RULE.search(stylesheet)
        assert match, f"{name} stylesheet has no QComboBox::down-arrow image rule"
        url = match.group(1).strip()
        assert url, f"{name} stylesheet's down-arrow image url() is empty"


def test_combobox_down_arrow_has_muted_disabled_variant() -> None:
    for name, stylesheet in (("dark", DARK_STYLESHEET), ("light", LIGHT_STYLESHEET)):
        match = _DOWN_ARROW_DISABLED_RULE.search(stylesheet)
        assert match, f"{name} stylesheet has no muted QComboBox::down-arrow:disabled rule"
        enabled_url = _DOWN_ARROW_RULE.search(stylesheet).group(1).strip()  # type: ignore[union-attr]
        disabled_url = match.group(1).strip()
        assert disabled_url != enabled_url, f"{name} stylesheet reuses the enabled arrow image for the disabled state"

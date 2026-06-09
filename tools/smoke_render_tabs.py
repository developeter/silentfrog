"""Render the v1.1 N5a-fix tabs to PNGs so a human can visually
confirm the heatmap + badge row landed correctly.

Run: poetry run python tools/smoke_render_tabs.py [out_dir]
Output: <out_dir>/bot_matrix.png and <out_dir>/ai_visibility.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from qtpy import QtCore, QtWidgets

from silentfrog.tabs import AiVisibilityTab, BotMatrixTab
from silentfrog.theme import apply_theme

# Realistic payload — 6 of the 19 bots, varying robots.txt verdicts,
# llms.txt present, render diff = warning so the chips show variety.
_SAMPLE_PAYLOAD = {
    "ai_crawl": [
        ["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"],
        ["ChatGPT-User", "chatgpt-user", "Yes", "-", "-", "Allowed", "Allowed"],
        ["ClaudeBot", "claudebot", "Yes", "-", "-", "Allowed", "Allowed"],
        ["PerplexityBot", "perplexitybot", "No", "-", "-", "Blocked", "Disallow: /"],
        ["Googlebot", "googlebot", "Yes", "-", "nosnippet", "Limited", "Google: nosnippet"],
        ["Google-Extended", "google-extended", "No", "noai", "-", "Blocked", "Disallow + noai"],
    ],
    "discovery": {
        "llms_txt": {"present": True},
        "well_known_ai_json": {"present": False},
    },
    "render": {"status": "warning", "reason": "Headings drift after JS hydration."},
}

_AI_VISIBILITY_SAMPLE = {
    "summary": {
        "verdict": "Needs work",
        "score": 72,
        "good_count": 12,
        "warning_count": 4,
        "critical_count": 1,
    },
    "checks": [
        {
            "area": "Access",
            "check": "robots.txt access",
            "status": "good",
            "details": "Allowed",
            "recommendation": "-",
            "key": "access_robots_txt",
        },
        {
            "area": "Performance",
            "check": "Largest Contentful Paint (lab)",
            "status": "good",
            "details": "2.1s",
            "recommendation": "-",
            "key": "perf_lcp",
        },
        {
            "area": "Performance",
            "check": "Interaction to Next Paint (lab)",
            "status": "warning",
            "details": "260ms",
            "recommendation": "Reduce main-thread work.",
            "key": "perf_inp",
        },
        {
            "area": "Performance",
            "check": "CrUX P75 LCP",
            "status": "info",
            "details": "Not measured",
            "recommendation": "Set SILENTFROG_PSI_ENABLE=1",
            "key": "perf_crux_lcp",
        },
        {
            "area": "AI Citations",
            "check": "Brave indexes the URL",
            "status": "info",
            "details": "Not measured",
            "recommendation": "Set SILENTFROG_AI_CITATIONS_ENABLE=1",
            "key": "ai_citations_brave",
        },
        {
            "area": "Access",
            "check": "SSR parity",
            "status": "warning",
            "details": "Headings drift after JS hydration.",
            "recommendation": "Server-render headings.",
            "key": "access_ssr_parity",
        },
    ],
}


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("./tmp_smoke_render")
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    apply_theme(app, dark=True)

    bot_tab = BotMatrixTab()
    bot_tab.resize(1100, 560)
    bot_tab.update(_SAMPLE_PAYLOAD)
    bot_tab.show()
    QtWidgets.QApplication.processEvents()
    bot_tab.view.resizeRowsToContents()
    QtWidgets.QApplication.processEvents()
    bot_path = out_dir / "bot_matrix.png"
    bot_tab.grab().save(str(bot_path))

    vis_tab = AiVisibilityTab()
    vis_tab.resize(1100, 560)
    vis_tab.update(_AI_VISIBILITY_SAMPLE)
    vis_tab.show()
    QtWidgets.QApplication.processEvents()
    vis_tab.set_score_history([78, 74, 76, 70, 72])
    QtWidgets.QApplication.processEvents()
    vis_path = out_dir / "ai_visibility.png"
    vis_tab.grab().save(str(vis_path))

    QtCore.QTimer.singleShot(50, app.quit)
    app.exec()
    print(f"wrote {bot_path}")
    print(f"wrote {vis_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

from __future__ import annotations

import json
from pathlib import Path

from tools.code_shape_guard import (
    ShapeViolation,
    collect_functions,
    collect_violations,
    load_baseline,
    unexpected_violations,
    write_baseline,
)


def test_code_shape_guard_flags_branchy_function(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    target = pkg / "sample.py"
    target.write_text(
        "\n".join(
            [
                "def branchy(value):",
                "    if value == 0:",
                "        return 0",
                "    elif value == 1:",
                "        return 1",
                "    elif value == 2:",
                "        return 2",
                "    elif value == 3:",
                "        return 3",
                "    return 4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    functions = collect_functions([pkg])
    violations = collect_violations(functions)

    assert any(item.metric == "elifs" for item in violations)


def test_code_shape_guard_filters_baselined_violation(tmp_path: Path) -> None:
    violation = ShapeViolation(
        key="src/silentfrog/example.py:demo",
        metric="branches",
        actual=15,
        limit=12,
        path="src/silentfrog/example.py",
        qualname="demo",
        line=10,
    )
    baseline_path = tmp_path / "baseline.json"
    write_baseline(baseline_path, [violation])

    baseline_ids = load_baseline(baseline_path)
    failures = unexpected_violations([violation], baseline_ids)

    assert failures == []
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert payload["allowed"][0]["id"] == "src/silentfrog/example.py:demo|branches"

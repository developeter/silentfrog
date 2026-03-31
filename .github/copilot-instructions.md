# Silentfrog repository instructions

- Write all code and explanations in English unless the user explicitly asks for another language.
- Keep code human-readable first. Prefer fewer branches, small helpers, and explicit names over clever abstractions.
- Use guard clauses instead of deep nesting.
- Avoid long `if/elif` chains for status or string dispatch when a constant map, helper, or typed strategy is clearer.
- Do not mix parsing, business logic, orchestration, and UI rendering in one function.
- Avoid boolean-heavy APIs. If behavior splits, introduce a named helper or a typed configuration object.
- Prefer typed dataclasses/models over loose dicts when data moves across modules.
- Keep imports minimal and remove dead code in the same task.
- Use the shared theme helpers for GUI styling; do not add ad-hoc palette logic in widgets.
- Every bug fix needs a regression test.
- For GUI regressions, test the real user path when possible: clicks, sorting, tooltips, visible table data, and empty states.
- Before finishing a non-trivial change, run:
  - `poetry run python tools/doctor.py --quick`
  - focused tests for touched areas
  - `poetry run python tools/doctor.py`
- Do not weaken the code-shape guard or grow its baseline casually. Refactor first.

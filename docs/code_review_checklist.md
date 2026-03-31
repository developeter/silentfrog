# Silentfrog Code Review Checklist

Use this checklist before closing any non-trivial code change.

## Shape

- Is the happy path obvious within a few lines?
- Did I use guard clauses instead of stacking nested conditionals?
- Can any `if/elif` chain become a constant map, helper, or typed strategy?
- Does any function now do more than one job?
- Did I add boolean flags where a named helper or typed config would be clearer?

## Boundaries

- Is parsing separate from derivation logic?
- Is UI rendering separate from payload/business logic?
- Did I keep typed models/dataclasses where data crosses module boundaries?
- Did I avoid passing around new loose dict shapes without a clear reason?

## Readability

- Would a human maintainer understand this code in about 30 seconds?
- Are names explicit enough that comments are mostly unnecessary?
- Do comments explain intent/tradeoffs instead of restating the code?
- Did I remove dead branches, unused imports, and copy-paste leftovers?

## Tests

- Does the change have the smallest useful regression test?
- For GUI changes, did I test the real user path if behavior depends on clicks, sorting, tooltips, visible columns, or empty states?
- Did I avoid changing stable integration expectations unless behavior intentionally changed?

## Finish

- `poetry run python tools/doctor.py --quick`
- Focused tests for the touched area
- `poetry run python tools/doctor.py`

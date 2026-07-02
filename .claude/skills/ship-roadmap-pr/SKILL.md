---
name: ship-roadmap-pr
description: Implement one Silentfrog roadmap PR end-to-end with scoped tests, conditional adversarial review, anti-bloat controls, one final quality gate, and a concise handoff. Use when asked to start, continue, implement, or ship a numbered roadmap PR or milestone.
---

# Ship one roadmap PR

Work on exactly one requested PR. Do not begin the next PR.

## Loop

1. Read `CLAUDE.md`, `AGENTS.md`, the active roadmap acceptance criteria,
   `git status`, and the relevant production/tests code.
2. State the exact scope and explicit non-goals. Preserve unrelated changes.
3. Implement the smallest coherent change that satisfies the acceptance criteria.
4. Run focused tests, Ruff/format on touched files, and code-shape checks.
5. Classify risk:
   - **High:** persistence/schema, concurrency/cancellation, networking/TLS/SSRF,
     updater/installer, data loss, scoring, large-scale memory/paging, or mutable
     GUI state used as identity.
   - **Normal:** local deterministic changes without those boundaries.
6. For high-risk changes, invoke `lean-adversarial-reviewer` once with the raw
   diff and acceptance criteria. Do not leak suspected answers.
7. Fix only reproducible current-scope blockers. If production behavior changed
   because of review, allow one final targeted reviewer pass. Stop after two
   passes and report unresolved blockers rather than looping.
8. Run the full doctor only after implementation/review stabilizes. Do not run
   it again unless the failed gate required a code change.
9. Run `docs/code_review_checklist.md`.
10. Stop with a Caveman-style report: outcome, files, focused/full verification,
    known later-scope items, and commit readiness.

## Test economy

- Every new regression test must fail when the verified defect is reintroduced.
- Prefer extending or parametrizing an existing test.
- Test observable behavior, not private implementation details, when possible.
- Do not duplicate coverage already provided by a stronger integration test.
- Do not add a test for speculative behavior that production cannot produce.

## Code economy

- No unrelated cleanup, bonus refactor, compatibility shim, or future-proof layer.
- No new abstraction without a current production consumer or locked roadmap contract.
- No new dependency unless required by acceptance criteria.
- Prefer deletion/simplification over parallel code paths.
- Keep backward compatibility only where the roadmap or current callers require it.

## Commit

Default: stop before committing. If the user's initial request explicitly
authorizes commit, use `caveman-commit` only after all blockers and gates are
clear. Never include unrelated or explicitly excluded files.

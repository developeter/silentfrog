# Contributing to Silentfrog

Thanks for your interest in improving Silentfrog! The project is still young and mostly maintained by a single developer, so the workflow is intentionally lightweight. This guide explains how to contribute code while keeping the repo stable and easy to maintain.

## Getting Started

1. **Fork the repository** and clone your fork locally.
2. **Install dependencies** with `poetry install` (Python 3.12).
3. **Run the test suite** with `poetry run pytest` to ensure the baseline is green before you change anything.

## Coding Guidelines

- Follow **PEP 8** and type hints where practical.
- Keep patches focused; prefer small, well-scoped pull requests.
- Avoid introducing new heavy dependencies unless there is a strong justification.
- Keep async code non-blocking and respect the existing architecture (crawler, GUI tabs, workers).
- Update or add tests for every behavior change.

## Development Workflow

1. Create a feature branch off `dev` (e.g., `git checkout -b feature/performance-tab`). The maintainer pushes directly to `dev`, but external contributors should still use topic branches and open pull requests. The `main` branch only holds tagged releases.
2. Make your changes and update any relevant documentation.
3. Run the test suite locally (`poetry run pytest`). For GUI-heavy work, run targeted tests (e.g., `tests/test_seo_gui.py`) and do a quick manual smoke test if possible.
4. Commit with a clear message describing the change.
5. Open a pull request against `main` with:
   - A summary of what changed and why.
   - Any new tests or important verification steps.
   - Screenshots/GIFs for UI changes if relevant.

## Reporting Bugs or Requesting Features

Even if you do not plan to send code, filing issues is helpful. Please include:

- Silentfrog version and OS.
- Steps to reproduce (for bugs).
- Desired behavior and rationale (for features).

## Need Help?

If something is unclear or you have questions about the development process, open an issue and describe what you’re trying to do. The maintainer will respond as soon as possible.

Thanks again for helping grow Silentfrog! Even small improvements—bug fixes, copy tweaks, or additional tests—make the tool better for everyone.

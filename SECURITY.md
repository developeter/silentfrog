# Security Policy

## Supported Versions

Security fixes are only provided for the latest tagged release (the version on `main`) and the `dev` branch. Older releases are not maintained.

## Reporting a Vulnerability

If you discover a security issue, please open a **public GitHub issue** with the `security` label. The project is fully open source and handled transparently, so please describe the problem openly (redact sensitive data as needed). Include:

1. Affected version (latest release or `dev` commit).
2. Reproduction steps and expected vs. actual behavior.
3. Any logs or crash output that illustrates the risk.

Expect an initial response within 72 hours; we aim to release a fix as soon as practical.

## Scope

Silentfrog is a desktop SEO crawler, so security issues are mostly related to:

- Remote code execution or arbitrary file writes triggered by untrusted pages.
- Leaking credentials or local files when crawling user-specified URLs.
- Denial-of-service vectors (infinite recursion, resource exhaustion) caused by malformed input.

UI bugs or general crashes without a security impact should be reported via standard bug issues.

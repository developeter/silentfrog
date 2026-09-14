# Security Policy

## Supported Versions

Silentfrog does not yet publish separately tagged releases; development
happens on the `dev` integration branch (with v2.0 hardening currently on
`feature/v2.0`). Security fixes are applied to the active development line.

| Version | Supported |
|---|---|
| `dev` (current development line) | ✅ |
| Latest signed release, once published | ✅ |
| Older branches / forks | ❌ |

When signed releases are published, the in-app updater installs only a
release whose signed manifest verifies against the pinned maintainer key
(see *Security model* below), so staying current keeps you on a
signature-verified build.

## Reporting a Vulnerability

**Please do not open a public issue for security problems.** Public issues
are visible to everyone and can expose users before a fix is available.

Report privately through GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab and click **Report a
   vulnerability**, or go directly to
   <https://github.com/developeter/silentfrog/security/advisories/new>.
2. This opens a private security advisory visible only to you and the
   maintainers. Nothing is disclosed publicly unless and until an advisory
   is published.

GitHub private reporting requires a GitHub account. If you do not have one,
please still avoid posting vulnerability details publicly; open a minimal,
non-sensitive issue asking a maintainer to make private contact, and share
the details privately once they reach out.

### What to include

1. Affected version — the `dev` commit SHA (or release tag, once releases
   exist).
2. Reproduction steps and expected vs. actual behavior.
3. The impact or attack scenario you believe is possible.
4. Any logs, crash output, or proof-of-concept that illustrates the risk
   (redact your own secrets).

### How reports are handled

Silentfrog is a small open-source project maintained on a best-effort
basis. A maintainer will review the advisory and work with you in the same
private thread on confirmation, a fix, and a coordinated disclosure
timeline. Please allow reasonable time for a fix to ship before disclosing
publicly. There is no bug-bounty program and no guaranteed response time.

## Security model (what is already hardened)

Silentfrog is a desktop SEO/GEO crawler. The v2.0 hardening work
established the defaults below; reports that bypass any of them are in
scope.

- **TLS verification is on by default.** Crawler fetches use a verified TLS
  context (the bundled `certifi` CA set, hostname checking, certificate
  required, OpenSSL security level ≥ 2). Disabling certificate verification
  is an explicit, off-by-default per-crawl opt-in intended only for trusted
  self-signed / intranet hosts.
- **SSRF protection is on by default.** Every crawled address is resolved
  and vetted; loopback, private, link-local (including cloud-metadata), and
  reserved destinations are rejected. The connection is pinned to the vetted
  IP (anti-rebinding) while the original hostname is preserved for the Host
  header, SNI, and certificate verification, and redirects are re-validated.
  Reaching private / intranet hosts is an explicit, off-by-default per-crawl
  opt-in.
- **The in-app updater verifies signatures.** "Check for Updates" installs a
  GitHub Release only when its `manifest.json` is minisign-signed by the
  maintainer's pinned public key, and the downloaded archive matches the
  SHA-256 committed in that signed manifest. Verification **fails closed** —
  a missing, wrong, unsigned, or tampered asset is refused and nothing is
  swapped. Updates target signed-tag releases, never an unsigned `dev`
  commit.
- **Built-in Google OAuth client.** Silentfrog embeds a maintainer-owned
  Google OAuth *Desktop app* client id and secret
  (`src/silentfrog/integrations/google/app_client.py`) so connecting Search
  Console / Analytics 4 doesn't require every user to create their own
  Google Cloud project. Per Google's own OAuth documentation and RFC 8252
  §8.5, a "Desktop app" (installed-application) client secret is explicitly
  **not a confidential credential** — it only identifies the app to Google,
  the same way a public client id does, and by itself it cannot grant
  access to any account's data. Every connection still requires the end
  user's own consent in their browser (loopback OAuth flow, RFC 8252), the
  scopes requested are read-only (`webmasters.readonly`,
  `analytics.readonly`), and the resulting token is stored only in that
  user's own OS keychain. Data flows directly from Google to the user's
  machine; the maintainer never receives tokens or audit data. Bringing
  your own client (`client_secret.json`, Desktop app type) remains
  supported and overrides the built-in one. This note describes what is
  embedded and why; it makes no claim about the app's Google verification
  status.

### Known limitation (later-scope)

The one-click **bootstrap installers** (`bootstrap/Get-Silentfrog.*`) used
for first-time setup currently download the latest `dev` source archive
over HTTPS **without** minisign signature verification. Signature
verification of the bootstrap path is planned but not yet implemented; until
then, first-time bootstrap installs rely on transport (HTTPS) security
alone. The signature-verifying in-app updater described above governs every
subsequent update.

## Out of scope

Non-security UI bugs, general crashes without a security impact, and feature
requests belong in normal public issues, not private reports. Typical
*in-scope* security issues include:

- Remote code execution or arbitrary file writes triggered by untrusted
  crawled pages.
- Leaking credentials or local files while crawling user-specified URLs.
- Denial-of-service vectors (infinite recursion, resource exhaustion) caused
  by malformed input.
- Bypassing the TLS, SSRF, or update-signature protections described above.

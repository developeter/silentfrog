# Releasing a signed Silentfrog update

This is the procedure for a maintainer to make the in-app updater
(`Help → Check for Updates…`) actually work. It only applies **once a
real minisign keypair exists** — until then, `PINNED_PUBLIC_KEY` in
`src/silentfrog/update_trust.py` stays `""` and the updater fails closed
on purpose (see `docs/v2_0_release_roadmap.md` §2, "Decision: unpin the
orphaned signing key").

Nothing here runs in CI. `.github/workflows/release-bootstrap.yml` only
attaches the three bootstrap launcher files
(`Get-Silentfrog.{ps1,bat,command}`) to a release; it never builds an
archive, a manifest, or a signature, and the signing key must never
touch CI. Everything below is a manual, offline maintainer procedure.

## 0. One-time: generate and pin a keypair

1. Install [minisign](https://jedisct1.github.io/minisign/) on your own
   machine (never in CI).
2. Generate a keypair:

   ```bash
   minisign -G -p silentfrog.pub -s silentfrog.key
   ```

   `silentfrog.key` is the **private** key — keep it offline (a password
   manager, an encrypted USB drive, a hardware token). It must never be
   committed, uploaded, or pasted into an issue/PR/CI log. `silentfrog.pub`
   is safe to keep alongside it; only its *content* gets pinned, not the
   file itself.
3. `silentfrog.pub` looks like:

   ```
   untrusted comment: minisign public key <key id>
   RW............................................
   ```

   Copy the **second line** (the base64 blob, not the comment) into
   `PINNED_PUBLIC_KEY` in `src/silentfrog/update_trust.py`, replacing the
   empty string:

   ```python
   PINNED_PUBLIC_KEY = "RW...."  # paste the second line of silentfrog.pub
   ```

   Update the comment above it with the new key id (minisign prints the
   key id when it signs; it's also the first 8 raw bytes after the `RW`
   algorithm prefix once base64-decoded).
4. Commit that change on its own — it's a real, reviewable behaviour
   change (fail-closed → fail-open-once-signed), not part of a release.

**Rotating** an existing key later: ship a release signed by the
*current* key that updates `PINNED_PUBLIC_KEY` to the new one, then start
signing with the new key. Never overwrite a trusted key silently.

## 1. Every release: build and sign

Run these from the repo root, on the tag you're about to publish (so
`pyproject.toml`'s version and the tag agree — see
`docs/v2_0_release_roadmap.md` §7 item 1, `pyproject.toml:3` is the only
version literal).

### 1.1 Tag

```bash
git tag -a v<version> -m "v<version>"
git push origin v<version>
```

Pushing the tag fires `release-bootstrap.yml`, which creates a **draft**
release (default; see the `workflow_dispatch` `draft` input added in
v2.0 if you ever need to publish immediately instead — see
`docs/v2_0_release_roadmap.md` §2 for why draft is the safe default) and
attaches the three bootstrap files. Everything below adds to that same
draft release.

### 1.2 Build the source archive

The archive must unzip to **exactly one top-level directory** containing
a `pyproject.toml` with `name = "silentfrog"` in it — that's what
`tools/source_update.py::extract_archive`/`validate_archive` require on
the receiving end. `git archive` on the tag produces exactly that shape:

```bash
git archive --format=zip --prefix=silentfrog-<version>/ \
    -o silentfrog-<version>.zip v<version>
```

Pick whatever `<name>.zip` you like — the manifest below records the
exact filename, and that's what the updater asks for by name (it never
guesses).

### 1.3 Compute hashes

```bash
sha256sum silentfrog-<version>.zip
```

You'll also need the SHA-256 of the pinned Python installer the
bootstrap scripts download (`bootstrap/Get-Silentfrog.ps1` /
`.command`, currently `python-3.12.7-amd64.exe` / `-macos11.pkg` from
python.org) — python.org publishes per-file SHA-256 sums next to each
download. This field is part of the manifest schema
(`update_trust.parse_manifest` requires it, so it's part of what the
signature commits to) even though today's swap-only update flow
(`tools/update_silentfrog.py`) does not itself reinstall Python — it
exists for forward compatibility. Point it at the same installer the
bootstrap scripts already trust rather than inventing a new one.

### 1.4 Write `manifest.json`

Exact shape required by `update_trust.parse_manifest` (format **1** —
any other value, or a missing field below, raises `TrustError` and the
updater refuses the release):

```json
{
  "format": 1,
  "tag": "v<version>",
  "source": {
    "name": "silentfrog-<version>.zip",
    "sha256": "<sha256 of the zip, lowercase hex>"
  },
  "python_installer": {
    "url": "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe",
    "sha256": "<sha256 of that installer, lowercase hex>"
  }
}
```

Notes tied directly to the parser (`src/silentfrog/update_trust.py`):

- `format` must be the integer `1`.
- `tag` must be the exact release tag (e.g. `v2.0.0`) — this is what
  `write_revision_file` records into `.silentfrog_revision` on a
  successful update, and what `src/silentfrog/updater.py::compare()`
  string-matches against on the next check.
- `source.name` must be the **exact filename** you attach to the
  release as an asset (see step 1.6) — `tools/source_update.py`'s
  `release_asset_url()` builds
  `https://github.com/{owner}/{repo}/releases/download/{tag}/{name}`
  from it and downloads only that URL, never anything the GitHub API
  merely lists.
- `source.sha256` / `python_installer.sha256` are lowercase hex SHA-256
  (`ensure_archive_matches` lowercases before comparing, but write them
  lowercase to begin with).

### 1.5 Sign the manifest

```bash
minisign -S -s silentfrog.key -m manifest.json -x manifest.json.minisig
```

This produces `manifest.json.minisig`, a 4-line minisign detached
signature. `update_trust.verify_manifest` requires: a well-formed
signature blob, a key id matching the pinned key exactly, a `trusted
comment:` line, and a valid **global signature** binding the signature
to that trusted comment — plain `minisign -S` already produces all of
this; nothing needs hand-editing.

The private key (`silentfrog.key`) never leaves your machine for this
step — do it offline, not in any CI runner or shared shell.

### 1.6 Attach the assets to the draft release

Upload exactly these three files as **release assets** (via the GitHub
UI, or `gh release upload v<version> <files>`) on top of the three
bootstrap files CI already attached:

- `silentfrog-<version>.zip` (or whatever `source.name` says)
- `manifest.json`
- `manifest.json.minisig`

The filenames must match `manifest.json`'s `source.name` and the
constants in `tools/source_update.py`
(`MANIFEST_NAME = "manifest.json"`,
`MANIFEST_SIGNATURE_NAME = "manifest.json.minisig"`) exactly — the
updater fetches these by name, not by browsing the release.

### 1.7 Verify locally before publishing (recommended)

Point a scratch install at the draft release's assets and confirm it
verifies and applies cleanly:

```bash
poetry run python -m tools.update_silentfrog --revision v<version>
```

Expect exit code `0` (`EXIT_OK`). A `5` (`EXIT_UNVERIFIED`) means the
signature, key id, or a hash didn't match — fix the mismatch before
publishing, never by weakening the check. `3`/`4` mean a download or
install-side problem unrelated to signing.

### 1.8 Publish

Publish the draft release (GitHub UI, or re-run
`release-bootstrap.yml` via `workflow_dispatch` with `draft: false` if
you'd rather not touch the UI). Once published, `GET /releases/latest`
starts returning it — that's what both
`src/silentfrog/updater.py::fetch_remote_revision` (the GUI's "Check for
Updates" poll) and the `bootstrap/Get-Silentfrog.{ps1,command}` scripts'
release-tracking check.

## Reference: what each moving part expects

| Piece | Lives in | Expects |
| --- | --- | --- |
| Pinned public key | `src/silentfrog/update_trust.py:PINNED_PUBLIC_KEY` | The base64 blob line of `silentfrog.pub`, or `""` to fail closed |
| Manifest schema | `update_trust.parse_manifest` | `format=1`, `tag`, `source.name`, `source.sha256`, `python_installer.url`, `python_installer.sha256` |
| Manifest signature | `update_trust.verify_manifest` / `verify_detached` | A minisign detached signature whose key id matches the pinned key, with a valid trusted-comment global signature |
| Asset URLs | `tools/source_update.py:release_asset_url` | `https://github.com/{owner}/{repo}/releases/download/{tag}/{name}` — never the GitHub API's asset listing |
| Archive shape | `tools/source_update.py:extract_archive` / `validate_archive` | Exactly one top-level directory, containing a `pyproject.toml` with `name = "silentfrog"` |
| Applied by | `tools/update_silentfrog.py` (`python -m tools.update_silentfrog --revision <tag>`) | Refuses on developer clones (`.git` present); exits `EXIT_UNVERIFIED (5)` on any verification failure, `EXIT_OK (0)` only after signature + hash both check out |

For the test fixtures that exercise this same format end-to-end with a
throwaway (non-production) key, see `tests/minisign_fixture.py` and
`tests/test_update_trust.py` — regenerate the real-signature regression
fixture there (`_REAL_MINISIGN_SIG` / `_REAL_MINISIGN_KEY_ID`) the next
time a key is rotated, following the same pattern.

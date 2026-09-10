# v2.0 release roadmap

> **Working document.** Delete it when 2.0.0 ships, or keep it as history.
> Written 2026-09-10 on `feature/v2.0`. Self-contained: a fresh session should be
> able to pick up any R-item below without re-deriving the analysis.

---

## 0. Start here (for a new session)

1. Read `CLAUDE.md`, then `AGENTS.md` (the operating contract), then this file.
2. **The repo is the NESTED `silentfrog/` subdir**, not the outer workspace.
3. Before touching anything, open `docs/PLAYBOOKS.md` and follow the matching recipe
   literally — P1 (new AI Visibility check), P3 (opt-in feature), P6 (GUI styling), P7
   (ship a PR + the risk table).
4. Gates: `poetry run python tools/doctor.py --quick` while working, full
   `poetry run python tools/doctor.py` (7 gates, ~3 min) once before closing.
5. Pick ONE R-item. They are ordered but R1, R4 and R5 are independent of R2/R3.

**Traps that have already cost time in this repo** (all in `CLAUDE.md`, repeated because
they bite every session):

- Tests run against `src/`, but the *app* runs `.venv/Lib/site-packages/silentfrog`. After
  editing, the launched app is stale until you reinstall.
- `pip install --no-deps --upgrade .` **fails if the app is running** (`silentfrog.exe` is
  locked) and pip deletes the package *before* it notices, without rolling back. Close the
  app first. If it happens anyway: `cp -r src/silentfrog/* .venv/Lib/site-packages/silentfrog/`
  restores it, then reinstall properly once the app is closed.
- A bare `git commit` is denied by a PreToolUse hook — use `-m` or `-F <file>`.
- `git push` runs the full doctor as a pre-push hook (~5–8 min). That is the gate, not a hang.
- `lean-adversarial-reviewer` usually truncates before printing findings; resume it via
  SendMessage and it completes.

---

## 1. Why this exists

`CLAUDE.md` claims "v2.0 roadmap V1..V20: complete". A four-scope audit verified each
milestone **against the code rather than the docs** and found that claim is optimistic in one
specific way: three milestones have working, tested code with **no way for a user to reach it**.

The sharpest example — `src/silentfrog/integrations/google/checks.py:49` tells the user:

> "Settings → Connect Google Search Console."

That menu was never built. `run_loopback_flow` and `save_token` (`integrations/google/oauth.py`)
have **zero callers** — verified by grep, they appear only in their own `__all__`. No user can
ever produce a token, so the GSC/GA4 checks are permanently stuck on "Not connected". The app
instructs users to click something that does not exist.

### What is genuinely fine

Do not re-litigate these; they were verified:

- **All 15 v3 G-items are shipped** — module + user surface + tests, no doc-only items. The fake
  `ai_citations_perplexity` proxy really is gone.
- 16/20 V-items fully wired. **V19 Stage B (QML) is NOT a gap** — the roadmap scoped V19 to
  Stage A for v2.0.
- Zero TODO/FIXME/HACK in `src/`; the 8 `NotImplementedError` are Protocol stubs with real
  subclasses; 133 test files / 153 modules; 89% coverage; doctor wired into CI.

### The verified gaps

| Item | Gap | Evidence |
|---|---|---|
| **V7** GSC/GA4 | OAuth flow unreachable; app points at a non-existent menu | `oauth.py` `run_loopback_flow`/`save_token` have no callers; `checks.py:49,99` |
| **V1** stealth | No GUI path sets `use_stealth`; only an undocumented env var | `settings_dialog.py` `options()` never passes it; `seo_crawler.py:114` |
| **V16** robots simulator | `simulate_robots` has zero callers | `robots_simulator.py:418` (only `__all__`) |
| **M6** log GUI | No GUI file imports `log_analysis`; CLI-only | parser half landed in `1ef0dac` |
| **M8** remote sync | `remote_sync.py` imported only by its own test | out of scope, see §8 |
| release | `version = "1.0.0"`, CHANGELOG stale since 2026-05-19, **zero git tags** | `pyproject.toml:3` |

---

## 2. Decisions already made — do not reopen

From the user, plus three I was asked to decide.

| Decision | Value |
|---|---|
| V1 + V16 | **Expose in Settings** (deliver what the roadmap promised) |
| M6 GUI log window | **In scope** |
| M8 remote sync | **Out of scope** |
| Version | **2.0.0** |
| Tag | Create and push `v2.0.0` |
| Google credentials | **BYO `client_secret.json`** — user's own Cloud project |
| Release draft/published | **Keep `draft: true`** — decided, see below |
| Pinned signing key | **Set to `""`** — decided, see below |

### Decision: keep releases as drafts

The user asked to flip `release-bootstrap.yml` from `draft: true` to published. **Do not.**

The updater polls `/releases/latest`, which never returns drafts. Today that fails gracefully —
no release, no update offered. If we publish a v2.0.0 with no `manifest.json` +
`manifest.json.minisig`, `tools/update_silentfrog.py` downloads the manifest, gets a 404, and
returns `EXIT_UNVERIFIED = 5`. Every user who clicks "Check for updates" gets a hard failure.

A draft is the *safe* state when a release cannot be signed, not a bug. R5 adds a
`workflow_dispatch` input so it can be flipped deliberately once signing is possible.

### Decision: unpin the orphaned signing key

`update_trust.py:38` pins `PINNED_PUBLIC_KEY = "RWTwmgvci/k/s0YtnM0nBg/MOCf7aMn9aHe3y1MprEeMnghlphnMCvUn"`.

Verified: that string appears **only** in `update_trust.py`. There is no `silentfrog.pub` in the
repo or the user's home, no minisign material anywhere, and `tests/minisign_fixture.py` uses its
own self-contained generated `TEST_SEED` — not this key. The user confirms they never generated
or downloaded a key.

So a public key is pinned whose private half nobody controls. Two consequences:

1. No signed release is possible — the auto-update path cannot work as designed.
2. Its provenance is unknown. If that private key exists anywhere, its holder can sign updates
   that this app will trust. That is a supply-chain risk with no upside.

**Set `PINNED_PUBLIC_KEY = ""`.** The module's own docstring says empty is the fail-closed safe
default: *"While it is empty the updater verifies nothing and therefore refuses every update."*
That is exactly the true state, stated honestly. Safe to do precisely because **zero releases
exist and zero users trust the old key**, so there is nothing to rotate from.

When the user wants working auto-update: generate a minisign keypair, keep the private half
offline, pin the new public half, then ship a signed release. Write that up in
`docs/RELEASING.md` (R5) rather than blocking 2.0.0 on it.

---

## 3. R1 — Reach the orphaned V1 / V16 code · small

**Closes:** V1 stealth toggle, V16 robots simulator. Independent — good first PR.

`use_stealth` is already wired end-to-end. **Only the checkbox and one keyword are missing:**

- `crawl_options.py:119` field · `:160` default · `:183` `from_ui` kwarg · `:209` forward
- consumer `seo_crawler.py:114` `_stealth_enabled()` → `:131` `FetchStrategy(...)`

### Changes

**`settings_dialog.py`**
- Add `_scrapling_available()` next to `_playwright_available()` / `_embeddings_available()`
  (lines 24–39), using `importlib.util.find_spec("scrapling")` as
  `fetchers/scrapling_backend.py:72` already does.
- Add `chk_stealth` to the **Advanced** group (`_build_advanced_group`, 64 lines — has room).
  ⚠ **Do not add it to `_build_geo_group`: that is 79 lines against the 80-line cap** in
  `tools/code_shape_guard.py` and will fail the gate.
- Follow the optional-extra pattern exactly, all three parts:
  1. build: `setEnabled(False)` + **append** to the tooltip (never replace) with the literal
     `pip install silentfrog[stealth]`
  2. `_initialize_options`: `chk.setChecked(chk.isEnabled() and options.use_stealth)`
  3. `options()`: `use_stealth=bool(chk.isEnabled() and chk.isChecked())`
- Add a "Test a URL against robots.txt…" button opening the new dialog.

**NEW `robots_sim_dialog.py`** — small modal over the already-tested
`robots_simulator.simulate_robots()`: robots.txt body (paste, or fetch from a URL), target URL,
user-agent → allowed/blocked plus the matching rule. Pure view over existing logic; no new
parsing.

**`docs/v2_beat_screaming_frog_roadmap.md`** — mark both surfaces delivered.

### Tests
- Stealth roundtrip: mirror `tests/test_audit_profile_settings.py:39`
  (`test_settings_dialog_insecure_tls_opt_in_roundtrips`).
- Extra-missing: mirror `tests/test_tech_stack_unit.py:100` (asserts `isEnabled() is False`,
  then forces `setChecked(True)` and asserts `options()` still returns `False`).
- One pytest-qt test that the robots dialog renders a verdict for a known-blocked path.

### Optional sub-task
The roadmap also promised an `access_fetch_backend` info check. That is a **P1-playbook** item
(tooltip + `CHECK_EVIDENCE` + fixture, all guard-tested) for a purely diagnostic row. If the P1
overhead outweighs the value, **drop the promise from the roadmap doc instead** — do not
half-implement it, the H6 guard tests will fail.

---

## 4. R2 — Google connect: pure layer · medium

**Closes the V7 lie.** After R2 `from_env()` is reachable from stored config; no UI yet. Ships
independently of R3.

**Key finding — a token alone does nothing.** `connection.from_env()` requires **all** of:
`SILENTFROG_GOOGLE_ENABLE` truthy **and** a keyring token **and** `SILENTFROG_GSC_SITE_URL` /
`SILENTFROG_GA4_PROPERTY_ID`. A Connect button by itself would not make a single check pass.

### Changes

**NEW `integrations/google/config.py`**
```python
@dataclass(frozen=True, slots=True)
class GoogleConfig:
    enabled: bool = False
    gsc_site_url: str = ""
    ga4_property_id: str = ""
    client_secrets_path: str = ""

def load_config() -> GoogleConfig   # never raises; missing/corrupt -> defaults
def save_config(config: GoogleConfig) -> None
```
JSON under `_data_dir()`, reusing the exact shape of `integrations/semrush/budget.py:24`
(`SILENTFROG_DATA_DIR` override + platform branches).

> **Not QSettings.** It would drag Qt into the pure layer, breaking `silentfrog-cli` and
> `silentfrog-mcp`. The repo already has that bug and it is instructive: `settings_dialog.py:554`
> writes `semrush/max_calls` to QSettings while `seo_crawler.py:550` reads the env var
> `SILENTFROG_SEMRUSH_MAX_CALLS`. Verified — that spinbox round-trips onto itself and has **no
> effect on behaviour**. Do not reproduce the pattern.

**NEW `integrations/google/connect.py`**
- `load_client_secrets(path)` → typed result, never raises. Must reject a `{"web": ...}` client
  with an explicit *"needs an OAuth client of type 'Desktop app'"* message — the most common BYO
  mistake, and the raw `from_client_config` failure is opaque.
- `connect_account(account, secrets, *, flow=run_loopback_flow)` — **flow injected as a default
  arg**; this is the primary test seam and does not exist today.
- `disconnect_account(account)` — delete token **and** clear the matching config field.

**`oauth.py`**
- Add `has_token`, `delete_token`.
- Wrap `run_loopback_flow` in a real `try/except` — it currently has **none**, so a missing extra
  leaks `ModuleNotFoundError` to the caller.
- Add `timeout_seconds` (~180), `prompt="consent"` (so reconnect can switch account), and
  `host="localhost"`/`bind_addr="127.0.0.1"` to reduce the Windows firewall prompt.
- Store **only the path** to `client_secret.json` — `Credentials.to_json()` already embeds
  `client_id`/`client_secret`/`refresh_token`, so refresh works without the file. Verify this
  stays true if the token format changes.

**`connection.py`** — two small changes:
- `_enabled()` = env truthy **or** `load_config().enabled`
- `from_env()` falls back to config for site URL / property id
- **Env wins over config** so headless/CI is unchanged. Keep the name `from_env` (3 callers plus
  a monkeypatch at `tests/test_v14_adversarial.py:101`); just update the docstring.

**`gsc_client.py`** — add `list_sites()` for R3's property picker; `None` service → `[]`.

**`checks.py:49,99`** and **`ai_visibility.py:426`** — make the recommendation strings name the
real path instead of a menu that doesn't exist.

### Tests
- **NEW `test_google_config_unit.py`** — roundtrip; missing file → defaults; corrupt JSON →
  defaults without raising; `SILENTFROG_DATA_DIR` respected (`conftest.py:29` already isolates it).
- **NEW `test_google_connect_unit.py`** — fake flow → `save_token` called with the right account;
  `ModuleNotFoundError` → `ok=False` carrying the `pip install silentfrog[google]` message;
  timeout → no token written; disconnect clears token **and** config field; `{"web":...}` rejected.
  Fake-keyring pattern: `tests/test_alert_transport_unit.py:197`.
- **Extend `test_google_integration_unit.py`** with the `from_env` matrix — currently **zero**
  coverage. Cover: nothing set → `None`; env path (regression); **config-only path** (the new
  behaviour); token but empty site URL → `None` (documents the trap); env overrides config;
  keyring raising → `None`.

---

## 5. R3 — Google connect: the dialog · large

**NEW `google_connect_dialog.py`**, launched from a ~20-line `_build_google_group` in
`settings_dialog.py` — a two-widget launcher row, **not** an 8-row group inside the already
five-deep scroll area.

Contents: `client_secret.json` file picker · Connect/Disconnect per account · **editable combo**
for the GSC property populated from `list_sites()` · GA4 property-id field · `Use Google data in
audits` checkbox **unchecked by default** (preserves the default-OFF invariant).

The editable combo earns its keep: GSC property strings must match exactly
(`sc-domain:example.com` vs `https://example.com/`), and free text fails silently — producing
exactly the "connected but no data" state this feature exists to remove.

### Threading — deliberately different from the existing precedent

`run_loopback_flow` blocks for **minutes** waiting on a human in a browser.

`_on_semrush_test` (`settings_dialog.py:581`) marshals results back with
`QMetaObject.invokeMethod(label, ...)`. If the modal is closed mid-flow the `QLabel` is destroyed
and that is a use-after-free. It is a ~15s window there; OAuth widens it to minutes, turning a
theoretical crash into a likely one.

**Use a daemon worker writing to a holder + a dialog-owned `QTimer` poll (200 ms).** The timer
dies with the dialog; the orphaned worker finishes into a discarded holder and touches no Qt
object. Add an inline comment explaining the deviation. File the latent `_on_semrush_test` bug
separately — **do not fix it here**.

Missing `google` extra — three layers: launcher disabled with the `pip install silentfrog[google]`
tooltip append; `run_loopback_flow`'s new `try/except`; `connect_account` returning a typed
failure. Never a traceback.

### UI copy that must be there
A consent screen left in **Testing** issues refresh tokens that **expire after 7 days**. Without
a warning, users connect, see data, and silently lose it a week later. Say "set your consent
screen to *In production*", and surface a failed refresh as "Reconnect", not silent
`measured=False`.

Status uses text glyphs `✓`/`✗` like `_on_semrush_test`, **not colour** — sidesteps playbook P6
entirely. Include a "Test connection" button: presence-of-token alone will lie after the 7-day
expiry.

### Tests
**NEW `test_google_settings_gui.py`** — extra-missing disables the launcher with the right
tooltip; accept path writes `GoogleConfig`; checkbox default-off; layout guard mirroring
`tests/test_audit_profile_settings.py:111` (asserts a `QScrollArea` exists, the dialog fits on
screen, and the button box is parented outside the scroll area).

⚠ Add `@staticmethod` seams (`_load_google_status`, `_run_connect`) mirroring `_load_semrush_key`
— **without them every existing settings-dialog test will hit the real OS keychain.**

---

## 6. R4 — Server-log analysis window (M6) · medium

Verified: `log_analysis.py` is complete and CLI-reachable (`silentfrog-cli logs`), but **no GUI
file imports it**. The parser-unification half of M6 landed in commit `1ef0dac`; this closes the
other half. Independent of R2/R3.

**NEW `log_gui.py`** — `LogWindow` mirroring `redirect_gui.py`'s shape: file picker, optional
*known URLs* file for orphan detection, worker `QThread`, progress, results table via the
existing `GenericModel`, findings from `issues_for_log_report`. Reuses `analyse_log_file` /
`LogAnalysisConfig` — **no new analysis logic**.

**`gui.py`** — 4th home button. The fixed `420x500` shrank when v3 retired the Multi-URL
Dashboard (see the comment at `gui.py:33`); restore the taller height. Keep `_spawn_child` so the
Python reference is retained — dropping it segfaults PySide6.

### Tests
`test_log_gui.py` — window builds; a sample log produces rows; an empty/garbage file degrades
without raising. Extend `test_home_gui.py` for the 4th action (it already asserts the three
button labels).

---

## 7. R5 — Release 2.0.0 · small

1. **`pyproject.toml:3`** → `version = "2.0.0"`. **This is the only version literal.**
   `__version__` derives via `importlib.metadata`; `tools/source_install.py:375` reads pyproject
   for the macOS plist. No test asserts the version. Requires a reinstall for the About dialog to
   show it.
2. **`update_trust.py:38`** → `PINNED_PUBLIC_KEY = ""` (see §2). Check the surrounding tests still
   pass — they use their own generated key, so they should be unaffected.
3. **`CHANGELOG.md`** — promote `## Unreleased` to `## 2.0.0`, add the V1–V20 / G1–G15 waves and
   the redirect-checker rewrite. Keep the house style (H3 themes, H4 categories, no dates, no `v`
   prefix). Add a **Known limitations** section: in-app update needs a signed release and is not
   yet active; server-log analysis got a GUI in 2.0 but remote sync (M8) is not wired.
4. **`README.md`** — document the shipped-but-undocumented features: Topic map
   (`content_clusters.py`), semantic redirect mapping (`redirect_mapping.py`), accessibility audit
   (`accessibility_audit.py`), log analytics (`log_analysis.py`), llms.txt generator
   (`exporters/llms_txt.py`), AI citation SoV (`ai_citations.py`), GSC/GA4 + the new BYO setup
   steps. Fix `README.md:309` ("No tagged releases are published yet").
5. **`bootstrap/Get-Silentfrog.{ps1,command}`** — track the latest published `v*` release,
   **falling back to the `dev` branch when none exists**. Without the fallback, new installs break
   until a release is published. This fixes the permanent false "update available": bootstrap
   records a commit SHA (`ps1:131`) while `updater.compare()` string-matches a tag name.
6. **`.github/workflows/release-bootstrap.yml`** — add a `workflow_dispatch` input for
   draft/published instead of hardcoding, with a comment pointing at §2.
7. **NEW `docs/RELEASING.md`** — the signed-release procedure for when a key exists: generate a
   minisign keypair, keep the private half offline, pin the public half, build the archive, write
   `manifest.json` (format 1: `tag`, `source.name`, `source.sha256`, `python_installer.url`,
   `python_installer.sha256`), sign it, attach archive + `.minisig` + bootstrap files, publish.
8. **`CLAUDE.md` / `HANDOFF.md`** — correct the status block. `CLAUDE.md` currently overstates
   V1..V20; say what is actually true.
9. **Tag:** `git tag -a v2.0.0` + push → fires `release-bootstrap.yml` → **draft** release with the
   three bootstrap files. Do not publish it.

---

## 8. Explicitly out of scope

- **M8 remote sync** — `remote_sync.py` (310 lines) is imported only by its own test. Leave it
  unwired and say so in the changelog. Do not delete it; do not ship it as a feature.
- **V12 Common Crawl backlinks** — dropped in favour of Semrush. Correct the roadmap's claim
  rather than build it.
- **V6 custom-extraction results tab** — rules configure via Settings and results reach the LLM
  export. The promised dedicated tab is a nice-to-have; reword the roadmap.
- **GA4 property dropdown** (Admin API `accountSummaries.list`) — a third service builder for
  polish. Ship validated free text.
- **Remote OAuth revocation** — point at `myaccount.google.com/permissions` in the disconnect copy.
- **`_on_semrush_test` use-after-free** and the **dead `semrush/max_calls` spinbox** — both real,
  both pre-existing, both separate tickets. Don't fix in these PRs; don't copy them either.

---

## 9. Verification

Per PR: quick doctor while working, focused tests, full doctor once before closing.

**R2 and R3 touch networking + credentials → HIGH risk** per the `docs/PLAYBOOKS.md` §P7 table →
one `lean-adversarial-reviewer` pass with the raw diff and acceptance criteria.

Manual checks no test can cover:

- **R1** — Settings → Advanced shows the stealth box; it is disabled with the right tooltip when
  `scrapling` is absent. The robots dialog returns a verdict for a known-blocked path.
- **R3** — a **real** BYO round-trip: create a Desktop-app OAuth client in a Google Cloud project,
  connect, confirm the GSC checks flip from "Not connected" to real rows, then Disconnect and
  confirm they revert.
- **R4** — run a real access log through the window and cross-check the counts against
  `silentfrog-cli logs` on the same file.
- **R5** — after a reinstall (app closed), Help → About shows **2.0.0**.

## 10. Status

| PR | Scope | Effort | Done |
|---|---|---|---|
| R1 | V1 stealth checkbox + V16 robots dialog | small | ☑ |
| R2 | Google connect — pure layer | medium | ☐ |
| R3 | Google connect — dialog | large | ☐ |
| R4 | Server-log analysis window (M6) | medium | ☐ |
| R5 | Version, changelog, README, bootstrap, tag | small | ☐ |

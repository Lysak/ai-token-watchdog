# CodexBar Keychain Auto-Refresh

> **Disabled legacy subsystem.** Watchdog now reads usage and costs only via
> CodexBar CLI. The scripts in `launchd/codexbar-keychain/` exit without
> accessing Keychain, refreshing tokens, or installing a LaunchAgent. The
> remainder of this document is historical context only.

This document describes how `watchdog.py` and a supporting background
system keep [CodexBar](https://github.com/steipete/codexbar/) able to read
Claude's local credentials without ever popping a macOS password prompt.
It exists because `watchdog.py --reset-check` shells out to `codexbar` every
10 minutes (see `launchd/com.ai-token-watchdog.reset-check.plist`), and if
CodexBar can't read its credentials silently, that cron-like job effectively
breaks.

> **tl;dr — the fix that actually matters (2026-07-29):** `watchdog.py`'s
> `get_usage_data()` always re-fetches the `claude` provider via
> `codexbar usage --provider claude --source web`, instead of trusting
> whatever source CodexBar's "auto" mode picks. This sidesteps CodexBar's
> buggy internal OAuth Keychain cache entirely — see
> ["The real fix" section](#the-real-fix-stop-using-the-oauth-source-2026-07-29)
> below. Everything above that section is prior, partial troubleshooting
> (ACL/partition-list, prompt-mode experiments) kept for history — none of
> it was the actual root cause of the "OAuth credentials not found" /
> "OAuth token expired" errors.

> **Source of truth is this repo.** The scripts and plist are tracked at
> `launchd/codexbar-keychain/` and installed (templated) into
> `~/.codexbar-keychain/` and `~/Library/LaunchAgents/` by
> `launchd/codexbar-keychain/install.sh`. Only the runtime state
> (`.last-mdat`, `.fail-count`, `agent.log`) and the login-password keychain
> item stay outside git, on-machine only.

## Why CodexBar needs a keychain fix at all

CodexBar reads Claude credentials from the macOS login keychain item
`"Claude Code-credentials"`. Reading a keychain item without a GUI prompt
requires the reading app's Team ID to be present in that item's **partition
list** (an ACL). Whenever the Claude Code CLI itself rewrites that keychain
item (e.g. on token refresh or re-login), macOS resets the partition list to
only the app that just wrote it — silently dropping CodexBar's Team ID
(`Y5PE65HELJ`). The next time CodexBar tries to read it, macOS shows an
interactive "Allow access?" / password dialog instead of just working.

This system detects that rewrite and re-adds CodexBar's Team ID to the
partition list automatically, before the next `codexbar` call happens.

## Which credential store each provider actually uses (audited 2026-07-27)

Not every provider is exposed to this problem — only one keychain item is:

| Provider | Credential store | Needs an ACL fix? |
|---|---|---|
| **Codex** | Plain file `~/.codex/auth.json` (mode `600`) | **No.** Filesystem permissions, not Keychain ACLs — any process running as this user can read it. Structurally can never hit the "password prompt" problem. |
| **Claude Code** | macOS Keychain item, service `"Claude Code-credentials"`, account = `$(whoami)` | **Yes.** This is the one item `refresh-partition.sh` manages. |

Other Claude/Codex-related keychain items exist but are irrelevant here —
they're all self-owned by the app that created them, so there's no
cross-app ACL to lose:
- `cookie.claude`, `cookie.codex` (service `com.steipete.codexbar.cache`) — CodexBar's own cached web-session cookies, written and read only by CodexBar itself.
- `"Claude Safe Storage"` / `"Codex Safe Storage"` — Electron app local-storage encryption keys for the Claude/Codex desktop apps, unrelated to CLI auth.

So "one for Codex, one for Claude Code" resolves to: **zero** ACL-managed
items for Codex, **one** (`Claude Code-credentials`) for Claude Code. No
other item needs to be added to `refresh-partition.sh`.

## Logging every `codexbar` call (added 2026-07-27)

`watchdog.py`'s `get_usage_data()` now appends one JSON line per call to
`logs/codexbar-calls.jsonl`, with a per-provider status so recurring
failures can be traced by interval/cause over time:

```json
{"ts": "2026-07-27T20:25:24+03:00", "duration_ms": 2186, "returncode": 0,
 "providers": {"codex": {"status": "ok"}, "claude": {"status": "ok"}}}
```

On a provider-level error (e.g. the Claude OAuth failure seen today), the
provider's entry becomes:

```json
"claude": {"status": "error", "message": "Claude OAuth credentials not found. Run `claude` to authenticate.", "code": 3}
```

On a total `codexbar` subprocess failure (timeout, crash, empty output),
`providers` is empty and a top-level `call_error` field holds the detail.

To inspect later:
```bash
# All Claude errors, most recent last
jq 'select(.providers.claude.status=="error")' logs/codexbar-calls.jsonl

# How often codexbar was actually called (one line per watchdog run)
wc -l logs/codexbar-calls.jsonl
```

This is separate from `~/.codexbar-keychain/agent.log`, which logs the
*repair* side (when `refresh-partition.sh` fixed or failed to fix the ACL).
Cross-referencing the two — a `provider_error` here followed shortly by an
`ERROR` in `agent.log` — is how to confirm the keychain fix is the actual
cause of a given failure, versus something else (e.g. today's case, which
turned out to be a stale CodexBar-side cookie/session state, not an ACL
problem — see git history for the incident).

## Components

| File | Tracked? | Role |
|---|---|---|
| `launchd/codexbar-keychain/refresh-partition.sh` | ✅ repo | Template. Repair logic — `__PROJECT_DIR__`/`__STATE_DIR__` filled in at install time. |
| `launchd/codexbar-keychain/setup.sh` | ✅ repo | Template. One-time interactive bootstrap. |
| `launchd/codexbar-keychain/com.codexbar-keychain.plist` | ✅ repo | Template. LaunchAgent definition. |
| `launchd/codexbar-keychain/install.sh` | ✅ repo | Renders the templates above into `~/.codexbar-keychain/` and `~/Library/LaunchAgents/`, (re)loads the LaunchAgent. |
| `~/Library/LaunchAgents/com.dmytrii.codexbar-keychain.plist` | ❌ machine-local (generated) | Installed LaunchAgent. `WatchPaths` on `~/Library/Keychains/login.keychain-db` — fires on **any** write to the login keychain (not just the target item). |
| `~/.codexbar-keychain/refresh-partition.sh`, `setup.sh` | ❌ machine-local (generated) | Installed copies of the templates above, with real paths substituted. Don't edit directly — edit the repo template and re-run `install.sh`. |
| `~/.codexbar-keychain/agent.log` | ❌ machine-local (state) | Combined stdout+stderr log of every `refresh-partition.sh` run. |
| `~/.codexbar-keychain/.last-mdat` | ❌ machine-local (state) | The keychain item's `mdat` (modified date) as of the last successful repair. Used to break the trigger loop (see below). |
| `~/.codexbar-keychain/.fail-count` | ❌ machine-local (state) | Consecutive-failure counter, used to throttle Telegram alerts. |
| `"codexbar-login-helper"` (keychain item, not a file) | ❌ machine-local (secret) | Holds the macOS login password, created by `setup.sh`. ACL restricts read access to the `/usr/bin/security` binary only (`-T /usr/bin/security`) — no ordinary script or app can read it directly, only via that fixed binary path. |

## Flow

```
Claude Code CLI rewrites "Claude Code-credentials"
        │  (partition list reset by macOS, CodexBar's Team ID dropped)
        ▼
any write to login.keychain-db
        │
        ▼
launchd WatchPaths fires → runs refresh-partition.sh
        │
        ├─ reads "Claude Code-credentials" mdat (no password needed)
        ├─ mdat unchanged since last repair? → exit 0 (nothing to do,
        │      also breaks the loop caused by our own repair writing mdat)
        │
        ├─ mdat changed → reads login password from "codexbar-login-helper"
        │      via `security find-generic-password -w` (no prompt: this
        │      binary is the authorized reader)
        │
        ├─ password missing/unreadable → notify_failure(), exit 1
        │
        ├─ runs `security set-generic-password-partition-list`
        │      to re-add teamid:Y5PE65HELJ to the target item's ACL
        │
        ├─ success → save new mdat to .last-mdat, reset .fail-count to 0
        └─ failure → notify_failure()
```

`notify_failure()` increments `.fail-count`; once it reaches **3 consecutive
failures**, it sends one Telegram alert (reusing `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` from **this project's** `.env`, read via `grep`/`cut` —
not sourced) and resets the counter, so a persistent failure alerts once
every 3 triggers instead of on every single one.

## Security model

- The login password is stored **once**, encrypted, inside a keychain item
  scoped so only `/usr/bin/security` can read it (`-T /usr/bin/security -U`).
  It is never written to disk in plaintext, never logged, and `setup.sh`
  `unset`s its in-memory copy after use.
- `refresh-partition.sh` only ever *reads* that one keychain item and only
  ever *modifies the ACL* (partition list) of `"Claude Code-credentials"` —
  it does not touch the credential value itself.
- No process can obtain the password non-interactively except by invoking
  `/usr/bin/security` as the same macOS user — which is the same trust
  boundary the OS itself uses for every other keychain-backed credential.

## Install / update (after cloning or editing the templates)

```bash
bash launchd/codexbar-keychain/install.sh
```

Renders the tracked templates into `~/.codexbar-keychain/` and
`~/Library/LaunchAgents/`, then reloads the LaunchAgent — no password
needed if `codexbar-login-helper` already exists. Run this again any time
`refresh-partition.sh`, `setup.sh`, or the plist template changes in this
repo.

```bash
bash launchd/codexbar-keychain/install.sh --uninstall
```

Unloads and removes the LaunchAgent plist. Leaves state files and the
keychain secret in place (printed instructions to remove the secret too).

## Setup / re-setup (one-time, interactive)

Must be run by hand in Terminal.app (not by an agent or script) — needed on
first install, and again only if the `codexbar-login-helper` keychain item
is ever deleted (e.g. keychain reset, migration to a new Mac, manual
cleanup):

```bash
bash ~/.codexbar-keychain/setup.sh
```

This: verifies the password, (re)creates the `codexbar-login-helper` item,
verifies non-interactive read works, runs `refresh-partition.sh` once
immediately, and (re)bootstraps the LaunchAgent.

## Verification (run 2026-07-27)

Checked after today's `setup.sh` run:

- [x] `codexbar-login-helper` readable non-interactively (`security
      find-generic-password -w` succeeds).
- [x] LaunchAgent loaded, last exit status `0` (`launchctl list | grep
      codexbar-keychain`).
- [x] `agent.log` shows two successful repairs today (`12:57:03`, `17:07:58`)
      after a string of `ERROR: не зміг прочитати пароль-помічник` earlier —
      confirms the fix took effect.
- [x] `.fail-count` is `0` (alert throttle correctly reset on success).
- [x] `.last-mdat` matches the target item's current `mdat` — the loop-
      breaker is working, no repeated re-triggering.

Everything is currently working end-to-end.

## The real root cause of the recurring prompt (found 2026-07-27, via CodexBar's own GitHub issues)

`refresh-partition.sh` adds `teamid:Y5PE65HELJ` to the partition list — this
only ever grants access to the **signed** `/Applications/CodexBar.app`
(GUI). The CLI binary `watchdog.py` actually calls
(`/opt/homebrew/bin/codexbar` → `CodexBarCLI` from the Homebrew *formula*,
not the app bundle) is **unsigned** (`codesign -dv` → "code object is not
signed at all") and therefore has no Team ID to match against any partition
entry — our script structurally could never grant it access. The one-off
password + "Always Allow" click on 2026-07-27 worked only because macOS
manually trusted that exact binary file; a `brew upgrade codexbar` replaces
the file and can invalidate that grant at any time, with no automated
recovery.

This exact class of bug is extensively reported upstream — see
[#243](https://github.com/steipete/CodexBar/issues/243),
[#1991](https://github.com/steipete/CodexBar/issues/1991),
[#2115](https://github.com/steipete/CodexBar/issues/2115) ("Always Allow"
doesn't persist), and [#458](https://github.com/steipete/CodexBar/issues/458)
(the fix). CodexBar ships an official switch for it:
`claudeOAuthKeychainReadStrategy`. The default, `securityFramework`, is the
strict code-signature-checked native Keychain API (what fails for unsigned
CLIs). `securityCLIExperimental` makes CodexBar shell out to
`/usr/bin/security` internally instead — a path already trusted via our
`apple-tool:` partition entry — so **both** the GUI and the unsigned CLI get
access without any prompt, no per-binary "Always Allow" needed.

**Applied 2026-07-27:**
```bash
defaults write com.steipete.codexbar claudeOAuthKeychainReadStrategy securityCLIExperimental
```
(`claudeOAuthKeychainPromptMode` was `onlyOnUserAction` at the time — later
changed to `always`, see below.)
Verified immediately after: both `codexbar usage --provider claude` (CLI)
and `watchdog.get_usage_data()` returned `error: None` with no prompt.

Trade-off (disclosed to and accepted by the user before applying): this
setting name references weakening CodexBar's XARA-style code-signature
verification for Keychain reads — a deliberate security-for-convenience
choice, not a free fix. If this Mac is ever exposed to untrusted local
software, re-evaluate.

This is a Homebrew-managed app preference (`defaults`), not a repo file —
it doesn't survive a fresh machine setup and isn't tracked by git. Anyone
reproducing this setup on a new Mac needs to re-run the `defaults write`
above (documented here for that reason).

## A second, independent root cause (found 2026-07-28): CodexBar's own stale internal cache

The `securityCLIExperimental` fix above addresses the ACL/partition-list gap
for the unsigned CLI. It does **not** address a second, unrelated bug found
the next morning, when the 10:00 Telegram report showed Claude
`⚠️ Auth required` again even though `securityCLIExperimental` was still
active.

Investigation (`codexbar usage --provider claude --source oauth -v
--log-level trace`) showed the live `"Claude Code-credentials"` item was
fine (fresh `expiresAt`), but CodexBar's read came back
`source=cacheKeychain` with a **stale, already-expired** `expiresAtMs` —
CodexBar maintains its own persistent OAuth cache in the Keychain, separate
from the live credential: service `com.steipete.codexbar.cache`, account
`oauth.claude` (siblings: `cookie.claude`, `cookie.codex`,
`cookie.perplexity`). That cache can go stale independently of the live
item, and reverting `claudeOAuthKeychainReadStrategy` back to
`securityFramework` did **not** change this error — confirming the read
strategy was not the cause of this particular failure.

Deleting the stale `oauth.claude` item outright made things temporarily
*worse*: the CLI then reported "OAuth credentials not found" instead, with
no `cacheKeychain` trace line at all — the headless CLI
(`allowKeychainPrompt=false`) cannot rebuild this cache from a cold/missing
state by itself. Only the GUI app, which is allowed to prompt/interact, can
repopulate it. This matches an open upstream bug,
[#1823](https://github.com/steipete/CodexBar/issues/1823) ("Claude
constantly looses token for access"), reported by multiple users across
roughly ten CodexBar versions including this one (0.45.2).

**Manual recovery procedure (current, in effect):** open the CodexBar
menu-bar app and click **Refresh** on the Claude panel. This triggers a
native macOS "Allow access?" dialog for the signed GUI app — **not a
password prompt** — clicking Allow rebuilds `oauth.claude` from the live,
valid credential.

### Tried and reverted: `claudeOAuthKeychainPromptMode = always` (2026-07-28)

CodexBar's GUI app runs a background process that *can* proactively repair
a stale `oauth.claude` cache with no user click at all — but only if
allowed to show its confirmation dialog unprompted. The default,
`onlyOnUserAction`, blocks exactly this; a CLI error message made the
reason explicit: *"Claude OAuth token expired, but background repair is
suppressed when Keychain prompt policy is set to only prompt on user
action."* Switching to `always` fixed that: the first hours after applying
it, the background process repaired the cache silently, with no dialog at
all.

**However, ~4.5 hours later this had a serious side effect:** the headless
`--reset-check` `launchd` job (runs every 10 min, no interactive session)
timed out at 30s, and macOS's system log confirmed why —
`SecurityAgent`/`SFAuthenticationWindow` (the **real macOS login-password
authentication dialog**, not an "Allow access?" confirmation) opened at
that exact moment and sat waiting on-screen until the user noticed and
entered their password. `always` apparently lets the same "background
repair" logic run **inside the plain CLI invocation too**, and when that
happens outside of any interactive session, macOS falls back to its
strongest prompt (full password) instead of a lightweight Allow dialog —
exactly the failure mode this whole system exists to prevent.

**Reverted the same day:**
```bash
defaults write com.steipete.codexbar claudeOAuthKeychainPromptMode onlyOnUserAction
osascript -e 'tell application "CodexBar" to quit'
open -g /Applications/CodexBar.app
```

**Conclusion:** `always` is **not safe to use** with a headless cron-driven
CLI like `watchdog.py --reset-check` — it trades "occasional manual Refresh
click" for "occasional surprise system password prompt," which is strictly
worse for this project's goal. Stick with `onlyOnUserAction` and rely on
the manual Refresh-click recovery + the Telegram auth-error alert (below)
to know when it's needed.

## Known gaps

- ~~Not version-controlled~~ — fixed 2026-07-27: scripts + plist are now
  templated under `launchd/codexbar-keychain/` and installed via
  `install.sh` (see above). Only the state files and the
  `codexbar-login-helper` secret remain machine-local, by design.
- **`securityCLIExperimental` is explicitly labeled experimental** by
  upstream and has had at least one prior regression
  ([#458](https://github.com/steipete/CodexBar/issues/458), fixed on
  `main` before this was applied). Watch `logs/codexbar-calls.jsonl` for
  a regression after any future `brew upgrade codexbar`.
- **No monitoring of the LaunchAgent's own health**, only of
  `refresh-partition.sh`'s logic inside it. If `launchctl` unloads the agent
  entirely (e.g. after a macOS update resets LaunchAgents), there's no
  script failure to alert on — it just silently stops firing. Nothing in
  this repo or `~/.codexbar-keychain/` currently checks
  `launchctl list | grep com.dmytrii.codexbar-keychain` on a schedule.
- **`WatchPaths` fires on any write to the whole login keychain**, not just
  the target item — mostly harmless (the `mdat` gate makes unrelated writes
  a no-op exit 0), but means `refresh-partition.sh` runs more often than
  strictly necessary.
- **Telegram alerting is untested against a real 3-failure streak** — it was
  added today and the only failures logged since were before the code
  existed. Worth confirming once (e.g. by temporarily renaming the
  `codexbar-login-helper` item) that the alert actually fires at failure #3.
- **CodexBar's own `oauth.claude` cache can go stale independently of the
  ACL fix** (see previous section) — an open upstream bug
  ([#1823](https://github.com/steipete/CodexBar/issues/1823)), not something
  this repo's scripts can fully prevent. Recovery is still manual (a GUI
  Refresh click), but as of 2026-07-28 `watchdog.py`'s `--reset-check` run
  (every 10 min) alerts distinctly for this: `detect_auth_errors()` in
  `watchdog.py` is **edge-triggered** — it fires a `🔑 Auth error` Telegram
  message (with the "click Refresh in CodexBar" hint) once, the moment a
  provider's `error` field first appears, then stays silent on every
  subsequent 10-minute run while the error persists (tracked via
  `authErrorActive` in `logs/reset_state.json`, per provider). The flag
  clears on the next successful run, so a *later, separate* incident alerts
  again. This avoids spamming one alert every 10 minutes for a single
  ongoing outage while still catching the case where the user isn't at the
  computer when it starts.
  A possible future improvement (not yet implemented): trying
  `open -g /Applications/CodexBar.app` to silently wake the GUI process and
  see if that alone is enough to trigger a self-heal, removing the manual
  click entirely.

## The real fix: stop using the `oauth` source (2026-07-29)

Every earlier attempt in this doc (ACL/partition-list repair,
`securityCLIExperimental`, `claudeOAuthKeychainPromptMode = always`) treated
the symptom — CodexBar's Claude `oauth` source depending on a
Keychain-cached token (`com.steipete.codexbar.cache`/`oauth.claude`) that
goes stale independently of the live, always-valid
`"Claude Code-credentials"` item (upstream bug
[#1823](https://github.com/steipete/CodexBar/issues/1823), still open and
under active maintainer triage as of this writing). `always` mode even made
things *worse*: it let the same background-repair logic run inside a
headless CLI call and fall back to a real macOS **login-password** dialog —
see the section above — so it was reverted.

`codexbar usage` has a `--source <auto|web|cli|oauth|api>` flag. For Claude:
- `--source oauth` — the buggy one. Depends on the stale internal cache.
- `--source cli` — reads `"Claude Code-credentials"` directly (no cache),
  but returns oddly-formatted `resetDescription` strings (e.g.
  `"Resets7pm(Europe\/Kiev)"` — a display bug in that code path).
- `--source web` — hits claude.ai directly through a *separate* cookie
  cache (`cookie.claude`) that has never shown this staleness bug in our
  logs, and returns data in the same shape/formatting as the (working)
  `oauth` source used to.

`codexbar usage --format json` (no `--provider`, used to fetch every
enabled provider in one call) picks `oauth` for Claude by default — that
choice lives inside CodexBar itself and isn't exposed as a persistent
per-provider setting in `defaults` or any config file we could find. So the
fix lives in `watchdog.py` instead: `get_usage_data()`
(`watchdog.py:_refetch_claude_via_web`) always issues a second, explicit
call — `codexbar usage --provider claude --source web --format json` — and
replaces the primary call's `claude` entry with that result, *unless* the
web fetch itself errors or fails, in which case the original (possibly
errored) entry is kept so a genuine outage still surfaces rather than being
silently swallowed. Codex is untouched — it keeps its own default/auto
source, which is where `codexResetCredits` and other Codex-specific fields
come from; forcing `--source web` globally would have dropped those.

Verified 2026-07-29: with `claudeOAuthKeychainPromptMode` back at
`onlyOnUserAction` (the safe setting) and the live `oauth` source actively
erroring ("Claude OAuth credentials not found"), `get_usage_data()`
consistently returned `error: None` for Claude via the `web` source — no
Keychain prompt, no GUI click, no dependency on CodexBar's internal cache
at all. Tests: `tests/test_get_usage_data.py` covers both the
happy-path replacement and the "web also fails, keep the original error"
fallback.

**This is expected to make the whole class of "Claude OAuth
credentials/token ..." errors structurally not happen anymore**, since
`watchdog.py` no longer routes through the one code path
(`com.steipete.codexbar.cache`/`oauth.claude`) that's actually buggy. The
ACL/partition-list system (`launchd/codexbar-keychain/`) and the
edge-triggered auth-error Telegram alert both stay in place as defense in
depth — for the GUI app itself (which still defaults to `oauth` for its
menu-bar display) and for any other provider/scenario not covered by this
workaround.

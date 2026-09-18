# CodexBar snapshot mirror — reading usage data with no subprocess, no prompts

`watchdog.py`'s `get_usage_data()` no longer shells out to `codexbar usage`. Instead it
reads a local mirror of CodexBar's own `widget-snapshot.json` — the file the
always-running CodexBar menu-bar app already writes for its WidgetKit widgets,
already fetched on CodexBar's own refresh cycle. This removes the whole class
of Keychain/OAuth confirmation-prompt problems that `codexbar usage` under
`launchd` could hit (see `docs/codexbar-keychain.md` for that history).

## Architecture

1. **Source** (CodexBar-owned, protected): `~/Library/Group Containers/Y5PE65HELJ.com.steipete.codexbar/widget-snapshot.json`.
   Written by CodexBar itself. Reading it from an arbitrary process fails with
   `Operation not permitted` — it's inside a macOS App Group container.
2. **`tools/read-codexbar-snapshot`** (compiled from `tools/read-codexbar-snapshot.c`):
   a tiny, single-purpose C binary. Its only job is to copy that one file
   somewhere readable. Granted **Full Disk Access** in System Settings —
   scoped to exactly this binary, not to Python/uv (see pitfall below).
3. **LaunchAgent `com.ai-token-watchdog.codexbar-snapshot`** (`launchd/com.ai-token-watchdog.codexbar-snapshot.plist`):
   runs that binary as a **direct child of `launchd`**, copying the source
   into `logs/codexbar-snapshot.json` (an ordinary, unprotected file) via
   `WatchPaths` on the source — fires whenever CodexBar writes a fresh snapshot.
4. **`watchdog.py`**: reads `logs/codexbar-snapshot.json` with a plain
   `open()`/`json.load()`. No subprocess, no elevated permission needed here
   at all — by the time this process runs, the data is just a normal file.

Only the LaunchAgent in step 3 ever touches the protected source path. This
is deliberate — see the pitfall below for why.

## Diagnostic finding: `uv` / uv-managed Python break Full Disk Access for a child binary

**Symptom:** `read-codexbar-snapshot` was granted Full Disk Access and worked
fine when run directly (as a bare `launchctl load` job, or as a child of the
Apple-signed `/usr/bin/python3`). But it failed with `Operation not permitted`
whenever its parent process was `uv run ...` — including `uv run python3 -c
"...subprocess.run(['read-codexbar-snapshot', ...])"` — **even though the
grant itself was correct and even under a clean `launchd` job with no
Terminal/IDE in the process tree.**

**Root cause:** `uv` and uv-managed Python builds
(`~/.local/share/uv/python/cpython-*`) are **ad hoc-signed**
(`codesign -dv` → `flags=0x20002(adhoc,linker-signed)`, no Team ID), unlike
Apple's own `/usr/bin/python3` (a properly platform-signed binary). Empirically,
when an ad hoc-signed process spawns a child, macOS's TCC "responsible
process" attribution does **not** treat the child as its own responsible
process — the check gets attributed up the chain instead, past a grant scoped
to the child binary itself. A properly signed intermediary (Apple's
`/usr/bin/python3`, or `launchd` itself) does not have this problem.

**Practical consequence — this is why the architecture above has a dedicated
LaunchAgent:** never invoke a Full-Disk-Access-scoped helper binary from
inside the `uv run watchdog.py` process (or from any `uv`/venv-python
subprocess). Give it its **own LaunchAgent job**, with the helper binary as
the direct `ProgramArguments[0]`, and have it write to a plain file that the
`uv`-run process reads normally afterward.

## Rebuilding the binary: you must re-grant Full Disk Access, and restart `tccd`

Recompiling `tools/read-codexbar-snapshot.c` produces a **new ad hoc code
signature** (the hash changes every build). The previous Full Disk Access
grant, which is tied to that signature, stops matching — even though the file
path is unchanged.

After any rebuild:
```bash
xcrun clang -O2 -o tools/read-codexbar-snapshot tools/read-codexbar-snapshot.c
```
1. Remove the old entry in **System Settings → Privacy & Security → Full Disk
   Access** and re-add the (new) binary at the same path.
2. **This alone was not enough in testing** — the new grant did not take
   effect until also running:
   ```bash
   sudo killall tccd
   ```
   (`tccd` is the system daemon that caches Full Disk Access decisions; it
   did not pick up the updated grant for this bare, non-`.app` binary without
   being restarted.)
3. Re-verify with a throwaway `launchctl load` test (direct binary as
   `ProgramArguments[0]`, not through `uv`) before trusting the real
   LaunchAgent.

`launchd/install.sh` deliberately does **not** auto-recompile an existing
binary for this reason — it only compiles it if missing, and otherwise warns
if the `.c` source is newer than the built binary.

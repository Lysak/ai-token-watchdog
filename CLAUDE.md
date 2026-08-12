# ai-token-watchdog — project rules

## Stack & conventions

- Python 3.14, `uv` only (no pip, no virtualenv)
- No classes — flat functions only
- All user-facing text in English
- macOS launchd for scheduling (not cron)
- Providers auto-discovered via `PROVIDER_{NAME}_ENABLED=true` env vars

## Legacy reset detection (disabled)

The reset-check launchd agent and `--reset-check` path are retained only as
commented legacy code. They must not be installed or scheduled: frequent
CodexBar calls can trigger a macOS Keychain password prompt. Active monitor
messages already show each limit window's next reset time via `↻`.

### Codex — weekly limit reset

When the 7-day window resets, **`resetsAt` advances to a new future date**.
Detection: compare stored `resetsAt` vs current — if current is later, a new cycle started.

### Claude — weekly limit reset

When the 7-day window resets, **`resetsAt` does NOT change**.
Only `usedPercent` drops (e.g. 5% → 0%).

Detection: track `maxUsedPercent` (high-water mark) across runs.
A reset fires when `current usedPercent < maxUsedPercent`.
After a detected reset, `maxUsedPercent` resets to 0 for the next cycle.

**Do NOT use `resetsAt` changes to detect Claude resets** — the value can jitter
by 1–2 seconds between API calls and produce false positives.

## State file (`logs/reset_state.json`)

Fields per provider:
- `usedPercent` — last seen secondary window usage %
- `maxUsedPercent` — peak usage % seen in the current cycle (Claude reset detection)
- `resetsAt` — last seen reset timestamp (used for Codex cycle detection only)
- `lastNotifiedAt` — when we last sent a reset alert (cooldown anchor)

A top-level `_error` key (not a provider) tracks the error-alert cooldown:
`{"lastNotifiedAt": "<iso timestamp>"}`. On any run failure (e.g. `codexbar`
timing out), an alert fires only if `ERROR_COOLDOWN_HOURS` (default 1) has
elapsed since the last one — this stops a persistent failure, hit every run
by a scheduled monitor run, from spamming an alert each time.
The marker is cleared as soon as a run succeeds again.

# Disable Reset Polling Design

## Goal

Stop the 10-minute `codexbar usage` polling that checks for limit resets, while retaining the normal monitor and daily reports.

## Design

- `launchd/install.sh` installs only the monitor and daily launchd agents.
- On installation or uninstallation, it also unloads and removes a previously installed `com.ai-token-watchdog.reset-check.plist`, so an existing 10-minute job cannot continue running.
- The reset-check plist and Python reset-detection path remain in the repository as clearly marked, commented legacy code; they are not active or installed.
- Normal monitor messages keep the existing `resetsAt` rendering for primary and secondary limit windows, which shows the next reset time. Daily cost reports remain unchanged.
- Documentation describes two active agents and removes the password/keychain workaround that only existed for the frequent reset-check job.

## Verification

- Add a focused installer test or static check proving the active plist list excludes reset-check while legacy cleanup remains.
- Run the existing Python test suite and shell syntax validation for the installer.
- Confirm the monitor-message test covers the next-reset line.

## Constraints

- Preserve the current dirty-worktree edits.
- Do not add dependencies or new scheduling/configuration.
- Do not commit without an explicit user instruction.

# Disable Reset Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop installation of the 10-minute reset polling job while retaining usage and reset-time reporting.

**Architecture:** Keep the monitor and daily launchd agents active. The installer removes any legacy reset-check launch agent; its plist and Python detection code stay in the repository as disabled legacy functionality.

**Tech Stack:** Python 3.14, Bash, macOS launchd, unittest.

## Global Constraints

- Preserve existing dirty-worktree changes.
- Do not add dependencies.
- Do not commit without an explicit user instruction.

---

### Task 1: Disable legacy reset polling

**Files:**
- Modify: `launchd/install.sh`
- Modify: `launchd/com.ai-token-watchdog.reset-check.plist`
- Modify: `watchdog.py`

- [ ] Remove reset-check from the installer active plist list.
- [ ] Unload and remove its previously installed user LaunchAgent during install and uninstall.
- [ ] Mark the reset-check plist and `--reset-check` execution branch as disabled legacy code.

### Task 2: Keep reports and documentation accurate

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] Document only monitor and daily agents.
- [ ] State that monitor usage lines show the next reset.
- [ ] Remove active reset-polling and password-workaround guidance.

### Task 3: Verify

**Files:**
- Test: `tests/test_*.py`

- [ ] Run the existing unit tests.
- [ ] Run shell syntax validation and inspect the generated active-agent list.
- [ ] Run `git diff --check`.

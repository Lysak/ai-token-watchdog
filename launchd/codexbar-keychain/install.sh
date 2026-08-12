#!/usr/bin/env bash
# Disabled legacy subsystem: watchdog reads data only through CodexBar CLI.
# This script intentionally never installs, reloads, or accesses Keychain data.
echo "codexbar-keychain is disabled; watchdog does not manage Keychain access."
exit 0

: <<'LEGACY_KEYCHAIN_INSTALL'
# Installs the CodexBar keychain auto-refresh system (see ../../docs/codexbar-keychain.md).
# This is a separate system from the watchdog launchd agents (../install.sh) —
# it keeps CodexBar's keychain access refreshed so it never has to prompt
# for the macOS login password.
#
# Run once after cloning:
#   bash launchd/codexbar-keychain/install.sh
#
# Then, if this is the first install (no "codexbar-login-helper" keychain
# item yet), run the one-time interactive step it prints at the end:
#   bash ~/.codexbar-keychain/setup.sh
#
# To uninstall:
#   bash launchd/codexbar-keychain/install.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_DIR="${CODEXBAR_KEYCHAIN_DIR:-$HOME/.codexbar-keychain}"
LABEL="${CODEXBAR_KEYCHAIN_LABEL:-com.dmytrii.codexbar-keychain}"
PLIST_TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST_TARGET"
    echo "Unloaded and removed: $LABEL.plist"
    echo "Left in place (untracked state/secrets): $STATE_DIR"
    echo "To also remove the stored login password: security delete-generic-password -s codexbar-login-helper -a \"\$(whoami)\""
    exit 0
fi
LEGACY_KEYCHAIN_INSTALL

mkdir -p "$STATE_DIR"

sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__STATE_DIR__|$STATE_DIR|g" \
    "$SCRIPT_DIR/refresh-partition.sh" > "$STATE_DIR/refresh-partition.sh"
chmod +x "$STATE_DIR/refresh-partition.sh"

sed -e "s|__STATE_DIR__|$STATE_DIR|g" -e "s|__LABEL__|$LABEL|g" \
    "$SCRIPT_DIR/setup.sh" > "$STATE_DIR/setup.sh"
chmod +x "$STATE_DIR/setup.sh"

sed -e "s|__STATE_DIR__|$STATE_DIR|g" -e "s|__LABEL__|$LABEL|g" -e "s|__HOME__|$HOME|g" \
    "$SCRIPT_DIR/com.codexbar-keychain.plist" > "$PLIST_TARGET"

echo "Installed scripts to: $STATE_DIR"
echo "Installed plist to:   $PLIST_TARGET"

if security find-generic-password -s "codexbar-login-helper" -a "$(whoami)" -w >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
    echo "✅ codexbar-login-helper already present — reloaded LaunchAgent ($LABEL)."
else
    echo ""
    echo "⚠️  No 'codexbar-login-helper' keychain item found yet."
    echo "    Run this once, interactively, in Terminal.app:"
    echo "      bash $STATE_DIR/setup.sh"
fi

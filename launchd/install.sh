#!/usr/bin/env bash
# Installs launchd agents for ai-token-watchdog.
# Run once after cloning and configuring .env:
#   bash launchd/install.sh
#
# To uninstall:
#   bash launchd/install.sh --uninstall

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
ENV_FILE="$PROJECT_DIR/.env"
UV_PATH="$(which uv 2>/dev/null || echo "")"
WATCHDOG_PATH="$PROJECT_DIR/watchdog.py"

READER_PATH="$PROJECT_DIR/tools/read-codexbar-snapshot"
READER_SRC="$PROJECT_DIR/tools/read-codexbar-snapshot.c"
SNAPSHOT_SOURCE="$HOME/Library/Group Containers/Y5PE65HELJ.com.steipete.codexbar/widget-snapshot.json"
SNAPSHOT_DEST="$PROJECT_DIR/logs/codexbar-snapshot.json"

PLISTS=(
    "com.ai-token-watchdog.monitor.plist"
    "com.ai-token-watchdog.daily.plist"
    "com.ai-token-watchdog.codexbar-snapshot.plist"
)
LEGACY_RESET_CHECK_PLIST="com.ai-token-watchdog.reset-check.plist"

if [[ -z "$UV_PATH" ]]; then
    echo "ERROR: uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env not found at $ENV_FILE"
    echo "       Run: cp .env.example .env  and fill in your values."
    exit 1
fi

# Read values from .env (ignore comments and blank lines)
_env_get() {
    grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

MONITOR_HOURS="$(_env_get MONITOR_HOURS)"
DAILY_REPORT_HOUR="$(_env_get DAILY_REPORT_HOUR)"
MONITOR_HOURS="${MONITOR_HOURS:-10,14,16,20}"
DAILY_REPORT_HOUR="${DAILY_REPORT_HOUR:-18}"

build_monitor_hours_xml() {
    local input="$1"
    local IFS=','
    read -r -a hours <<< "$input"

    if [[ "${#hours[@]}" -eq 0 ]]; then
        echo "ERROR: MONITOR_HOURS is empty"
        exit 1
    fi

    local xml=""
    local raw=""
    local hour=""
    for raw in "${hours[@]}"; do
        hour="$(echo "$raw" | xargs)"
        if [[ ! "$hour" =~ ^([01]?[0-9]|2[0-3])$ ]]; then
            echo "ERROR: invalid MONITOR_HOURS value: $hour"
            echo "       Expected comma-separated local hours like: 10,14,16,20"
            exit 1
        fi
        xml+="        <dict>\n"
        xml+="            <key>Hour</key>\n"
        xml+="            <integer>${hour}</integer>\n"
        xml+="            <key>Minute</key>\n"
        xml+="            <integer>0</integer>\n"
        xml+="        </dict>\n"
    done

    printf '%b' "$xml"
}

MONITOR_HOURS_XML="$(build_monitor_hours_xml "$MONITOR_HOURS")"

mkdir -p "$PROJECT_DIR/logs"

# Legacy reset polling ran `codexbar usage` every 10 minutes. Remove a prior
# installation so it cannot keep prompting for Keychain access in the background.
remove_legacy_reset_check() {
    local target="$LAUNCHD_DIR/$LEGACY_RESET_CHECK_PLIST"
    if [[ -f "$target" ]]; then
        launchctl unload "$target" 2>/dev/null || true
        rm "$target"
        echo "Unloaded and removed legacy: $LEGACY_RESET_CHECK_PLIST"
    fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
    for plist in "${PLISTS[@]}"; do
        target="$LAUNCHD_DIR/$plist"
        if [[ -f "$target" ]]; then
            launchctl unload "$target" 2>/dev/null || true
            rm "$target"
            echo "Unloaded and removed: $plist"
        fi
    done
    remove_legacy_reset_check
    echo "Done. Agents uninstalled."
    exit 0
fi

remove_legacy_reset_check

# read-codexbar-snapshot mirrors CodexBar's App-Group-protected
# widget-snapshot.json into $SNAPSHOT_DEST — see docs/codexbar-keychain.md.
# Only compile it if missing: recompiling an existing binary changes its ad
# hoc code signature and invalidates any Full Disk Access grant already made
# for it in System Settings.
if [[ ! -x "$READER_PATH" ]]; then
    echo "Compiling read-codexbar-snapshot..."
    xcrun clang -O2 -o "$READER_PATH" "$READER_SRC"
    echo "⚠️  New binary — grant it Full Disk Access:"
    echo "    System Settings → Privacy & Security → Full Disk Access → + → $READER_PATH"
elif [[ "$READER_SRC" -nt "$READER_PATH" ]]; then
    echo "⚠️  $READER_SRC changed since the last build — NOT auto-recompiling"
    echo "    (would invalidate the existing Full Disk Access grant)."
    echo "    Rebuild manually, then remove + re-add it in Full Disk Access:"
    echo "    xcrun clang -O2 -o \"$READER_PATH\" \"$READER_SRC\""
fi

for plist in "${PLISTS[@]}"; do
    src="$PROJECT_DIR/launchd/$plist"
    target="$LAUNCHD_DIR/$plist"

    launchctl unload "$target" 2>/dev/null || true

    sed \
        -e "s|__UV_PATH__|$UV_PATH|g" \
        -e "s|__WATCHDOG_PATH__|$WATCHDOG_PATH|g" \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__READER_PATH__|$READER_PATH|g" \
        -e "s|__SNAPSHOT_SOURCE__|$SNAPSHOT_SOURCE|g" \
        -e "s|__SNAPSHOT_DEST__|$SNAPSHOT_DEST|g" \
        -e "/__MONITOR_HOURS_XML__/{
r /dev/stdin
d
}" \
        -e "s|__DAILY_REPORT_HOUR__|$DAILY_REPORT_HOUR|g" \
        "$src" > "$target" <<< "$MONITOR_HOURS_XML"
    launchctl load "$target"
    echo "Loaded: $plist"
done

echo ""
echo "Agents installed successfully."
echo "  Monitor runs at local hours: ${MONITOR_HOURS}."
echo "  Daily report runs at ${DAILY_REPORT_HOUR}:00."
echo "  CodexBar snapshot mirror runs on load + whenever CodexBar updates its snapshot."
echo ""
echo "Verify:  launchctl list | grep watchdog"
echo "Logs in: $PROJECT_DIR/logs/"

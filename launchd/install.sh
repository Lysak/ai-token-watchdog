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

PLISTS=(
    "com.ai-token-watchdog.monitor.plist"
    "com.ai-token-watchdog.daily.plist"
    "com.ai-token-watchdog.reset-check.plist"
)

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

if [[ "${1:-}" == "--uninstall" ]]; then
    for plist in "${PLISTS[@]}"; do
        target="$LAUNCHD_DIR/$plist"
        if [[ -f "$target" ]]; then
            launchctl unload "$target" 2>/dev/null || true
            rm "$target"
            echo "Unloaded and removed: $plist"
        fi
    done
    echo "Done. Agents uninstalled."
    exit 0
fi

for plist in "${PLISTS[@]}"; do
    src="$PROJECT_DIR/launchd/$plist"
    target="$LAUNCHD_DIR/$plist"

    launchctl unload "$target" 2>/dev/null || true

    sed \
        -e "s|__UV_PATH__|$UV_PATH|g" \
        -e "s|__WATCHDOG_PATH__|$WATCHDOG_PATH|g" \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "/__MONITOR_HOURS_XML__/{
r /dev/stdin
d
}" \
        -e "s|__DAILY_REPORT_HOUR__|$DAILY_REPORT_HOUR|g" \
        "$src" > "$target" <<< "$MONITOR_HOURS_XML"
    # reset-check plist has no placeholders beyond the common ones — sed above handles it

    launchctl load "$target"
    echo "Loaded: $plist"
done

echo ""
echo "Agents installed successfully."
echo "  Monitor runs at local hours: ${MONITOR_HOURS}."
echo "  Daily report runs at ${DAILY_REPORT_HOUR}:00."
echo "  Reset-check runs every 30 min (state saved to logs/reset_state.json)."
echo ""
echo "Verify:  launchctl list | grep watchdog"
echo "Logs in: $PROJECT_DIR/logs/"

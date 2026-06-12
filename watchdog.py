#!/usr/bin/env python3
"""AI Token Watchdog — monitors usage limits and sends Telegram notifications.

Usage:
    uv run watchdog.py           # usage % monitor + pacing advice (run every N hours)
    uv run watchdog.py --daily   # daily credit cost report (run once at DAILY_REPORT_HOUR)
"""

import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

CODEXBAR = "/opt/homebrew/bin/codexbar"
BUNX = os.getenv("BUNX_PATH", "/opt/homebrew/bin/bunx")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Kyiv"))
WORK_START = int(os.getenv("WORK_START_HOUR", "8"))
WORK_END = int(os.getenv("WORK_END_HOUR", "22"))

PROVIDER_ICONS = {
    "codex": "🟢",
    "claude": "🟣",
    "perplexity": "🔵",
}

# Map watchdog provider names → ccusage agent names (None = not tracked by ccusage)
CCUSAGE_AGENT_MAP: dict[str, str | None] = {
    "codex": "codex",
    "claude": "claude",
    "perplexity": None,
}


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def get_enabled_providers() -> set[str]:
    enabled = set()
    for key, val in os.environ.items():
        m = re.fullmatch(r"PROVIDER_([A-Z]+)_ENABLED", key)
        if m and val.lower() == "true":
            enabled.add(m.group(1).lower())
    return enabled


def get_usage_data() -> list[dict]:
    result = subprocess.run(
        [CODEXBAR, "usage", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codexbar exited {result.returncode}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def find_provider(data: list[dict], name: str) -> dict | None:
    return next((p for p in data if p.get("provider") == name), None)


def get_ccusage_costs(agent: str) -> dict[str, float]:
    """Return {date_str: cost_usd} for the last ~2 days via ccusage CLI.

    Returns empty dict if ccusage is unavailable or the agent isn't tracked.
    """
    try:
        result = subprocess.run(
            [BUNX, "ccusage", agent, "daily", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {}
        entries = json.loads(result.stdout).get("daily", [])
        costs: dict[str, float] = {}
        for entry in entries:
            date = entry.get("date") or entry.get("period")
            cost = entry.get("totalCost") or entry.get("costUSD")
            if date is not None and cost is not None:
                costs[date] = float(cost)
        return costs
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def alert_emoji(pct: int | float | None) -> str:
    if pct is None:
        return "❓"
    if pct >= 90:
        return "🚨"
    if pct >= 80:
        return "⚠️"
    return "✅"


def format_bar(pct: int | float | None) -> str:
    if pct is None:
        return "[??????????] ?%"
    filled = round((pct / 100) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {pct}%"


def _limit_line(label: str, limit: dict) -> str:
    pct = limit.get("usedPercent")
    reset = limit.get("resetDescription", "?")
    return f"  {label}: {alert_emoji(pct)} {format_bar(pct)}  ↻ {reset}"


# ---------------------------------------------------------------------------
# Pacing calculation
# ---------------------------------------------------------------------------

def _working_minutes_until(end: datetime, now: datetime) -> int:
    """Count working minutes (WORK_START..WORK_END) between now and end, in user's TZ."""
    if end <= now:
        return 0

    total = 0
    current = now.astimezone(TZ)
    finish = end.astimezone(TZ)

    while current < finish:
        next_day = (current + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = min(next_day, finish)

        work_start_dt = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
        work_end_dt = current.replace(hour=WORK_END, minute=0, second=0, microsecond=0)

        overlap_start = max(current, work_start_dt)
        overlap_end = min(day_end, work_end_dt)

        if overlap_end > overlap_start:
            total += int((overlap_end - overlap_start).total_seconds() / 60)

        current = next_day

    return total


def pacing_advice(secondary: dict, primary: dict) -> str | None:
    """Return a one-line pacing recommendation based on weekly budget and remaining windows."""
    resets_at_str = secondary.get("resetsAt")
    window_minutes = primary.get("windowMinutes")
    secondary_used = secondary.get("usedPercent")

    if not resets_at_str or not window_minutes or secondary_used is None:
        return None

    reset_dt = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    working_mins = _working_minutes_until(reset_dt, now)
    remaining_windows = max(1, working_mins // window_minutes)

    remaining_pct = 100 - secondary_used
    target_per_window = remaining_pct / remaining_windows

    window_hours = window_minutes // 60
    window_label = f"{window_hours}h" if window_minutes % 60 == 0 else f"{window_minutes}m"

    if remaining_windows == 1:
        urgency = "🔥 Last window before reset!"
    elif target_per_window > 40:
        urgency = "⚡ Heavy usage needed to spend budget"
    elif target_per_window < 5:
        urgency = "🧊 Slow down — budget nearly spent"
    else:
        urgency = "📈 On track"

    return (
        f"  Pacing ({window_label} windows): {remaining_windows} left before reset  "
        f"→ target ~{target_per_window:.0f}%/window  {urgency}"
    )


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def build_monitor_message(data: list[dict], enabled: set[str]) -> str:
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"🤖 *AI Token Watchdog* — {now}\n"]

    for name in ["codex", "claude", "perplexity"]:
        if name not in enabled:
            continue
        provider = find_provider(data, name)
        if not provider:
            continue

        usage = provider.get("usage", {})
        primary = usage.get("primary", {})
        secondary = usage.get("secondary", {})
        icon = PROVIDER_ICONS.get(name, "⚪")
        login = usage.get("loginMethod") or provider.get("openaiDashboard", {}).get("accountPlan", "")
        title = f"{icon} *{name.capitalize()}{f' ({login})' if login else ''}*"

        lines.append(title)
        if primary:
            lines.append(_limit_line("5h ", primary))
        if secondary:
            lines.append(_limit_line("7d ", secondary))

        for extra in usage.get("extraRateWindows", []):
            w = extra.get("window", {})
            t = extra.get("title", "Extra")
            lines.append(_limit_line(t, w))

        if usage.get("tertiary"):
            lines.append(_limit_line("3  ", usage["tertiary"]))

        # Pacing advice when both primary and secondary windows are present
        if primary and secondary:
            advice = pacing_advice(secondary, primary)
            if advice:
                lines.append(advice)

        lines.append("")

    return "\n".join(lines).rstrip()


def build_daily_message(data: list[dict], enabled: set[str]) -> str:
    now_tz = datetime.now(TZ)
    today = now_tz.strftime("%Y-%m-%d")
    yesterday = (now_tz - timedelta(days=1)).strftime("%Y-%m-%d")
    lines = [f"📊 *Daily Report* — {today}\n"]

    total_today = 0.0
    total_yesterday = 0.0
    has_cost_data = False

    for name in ["codex", "claude", "perplexity"]:
        if name not in enabled:
            continue
        provider = find_provider(data, name)
        if not provider:
            continue

        icon = PROVIDER_ICONS.get(name, "⚪")
        usage = provider.get("usage", {})

        # --- Try ccusage first (real dollar costs from local logs) ---
        ccusage_agent = CCUSAGE_AGENT_MAP.get(name)
        today_val: float | None = None
        yesterday_val: float | None = None

        if ccusage_agent:
            costs = get_ccusage_costs(ccusage_agent)
            today_val = costs.get(today)
            yesterday_val = costs.get(yesterday)

        # --- Fallback: CodexBar openaiDashboard breakdown (Codex only) ---
        if today_val is None:
            breakdown = (
                provider.get("openaiDashboard", {}).get("usageBreakdown")
                or usage.get("usageBreakdown")
                or []
            )
            breakdown_sorted = sorted(breakdown, key=lambda x: x.get("day", ""), reverse=True)
            cb_today = breakdown_sorted[0].get("totalCreditsUsed") if breakdown_sorted else None
            cb_yesterday = breakdown_sorted[1].get("totalCreditsUsed") if len(breakdown_sorted) > 1 else None
            today_val = cb_today
            yesterday_val = cb_yesterday

        if today_val is not None:
            total_today += today_val
            has_cost_data = True
            source = "ccusage" if ccusage_agent else "API-equiv"
            lines.append(f"{icon} *{name.capitalize()}* today: `${today_val:.2f}` ({source})")
            if yesterday_val is not None:
                total_yesterday += yesterday_val
        else:
            primary_pct = usage.get("primary", {}).get("usedPercent")
            weekly_pct = usage.get("secondary", {}).get("usedPercent")
            pct_info = ""
            if primary_pct is not None:
                pct_info = f"  5h: {primary_pct}%"
            if weekly_pct is not None:
                pct_info += f"  7d: {weekly_pct}%"
            lines.append(f"{icon} *{name.capitalize()}*: subscription plan (no cost data){pct_info}")

    lines.append("")
    if has_cost_data:
        lines.append(f"💰 *Total today:* `${total_today:.2f}`")
        if total_yesterday > 0:
            lines.append(f"📅 Yesterday: `${total_yesterday:.2f}`")
        lines.append("_Costs are API-equivalent — actual charge is your flat subscription fee._")
    else:
        lines.append("_All active providers are subscription plans — no per-token cost data available._")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env", file=sys.stderr)
        sys.exit(1)

    daily = "--daily" in sys.argv

    try:
        data = get_usage_data()
        enabled = get_enabled_providers()
        if not enabled:
            print("WARNING: No providers enabled. Set PROVIDER_*_ENABLED=true in .env", file=sys.stderr)
        message = build_daily_message(data, enabled) if daily else build_monitor_message(data, enabled)
    except FileNotFoundError:
        message = f"🚨 *AI Token Watchdog ERROR*\ncodexbar not found at `{CODEXBAR}`"
    except Exception as e:
        message = f"🚨 *AI Token Watchdog ERROR*\n`{type(e).__name__}: {e}`"

    try:
        send_telegram(message)
        mode = "daily report" if daily else "monitor"
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Sent {mode} to Telegram.")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

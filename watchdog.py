#!/usr/bin/env python3
"""AI Token Watchdog — monitors usage limits and sends Telegram notifications.

Usage:
    uv run watchdog.py           # usage % monitor + pacing advice (run every N hours)
    uv run watchdog.py --daily   # daily credit cost report (run once at DAILY_REPORT_HOUR)
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

CODEXBAR = os.getenv("CODEXBAR_PATH", "/opt/homebrew/bin/codexbar")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Kyiv"))
WORK_START = int(os.getenv("WORK_START_HOUR", "8"))
WORK_END = int(os.getenv("WORK_END_HOUR", "22"))

RESET_CREDIT_WARN_DAYS = int(os.getenv("RESET_CREDIT_WARN_DAYS", "14"))
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "reset_state.json")
SENT_LOG = Path(os.path.dirname(os.path.abspath(__file__))) / "logs" / "sent.log"
RESET_COOLDOWN_HOURS = int(os.getenv("RESET_COOLDOWN_HOURS", "2"))

PROVIDER_ICONS = {
    "codex": "🟢",
    "claude": "🟣",
    "perplexity": "🔵",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


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
    stdout = result.stdout.strip()
    if stdout:
        return json.loads(stdout)

    detail = result.stderr.strip() or "no stdout or stderr output"
    raise RuntimeError(f"codexbar exited {result.returncode}: {detail}")


def find_provider(data: list[dict], name: str) -> dict | None:
    return next((p for p in data if p.get("provider") == name), None)


def get_codexbar_costs(provider: str) -> dict:
    """Return cost data for a provider via `codexbar cost --format json`.

    Keys: today_cost, yesterday_cost, today_tokens, today_models,
          last_30d_cost, last_30d_tokens, cache_pct (Claude only).
    Returns empty dict if unavailable.
    """
    try:
        result = subprocess.run(
            [CODEXBAR, "cost", "--format", "json", "--provider", provider],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        data = json.loads(result.stdout)
        if not data:
            return {}
        p = data[0]
        now_tz = datetime.now(TZ)
        today = now_tz.strftime("%Y-%m-%d")
        yesterday = (now_tz - timedelta(days=1)).strftime("%Y-%m-%d")
        daily = p.get("daily", [])
        today_e = next((d for d in daily if d.get("date") == today), None)
        yest_e = next((d for d in daily if d.get("date") == yesterday), None)

        out: dict = {
            "today_cost": today_e.get("totalCost") if today_e else None,
            "today_tokens": today_e.get("totalTokens") if today_e else None,
            "today_models": today_e.get("modelsUsed", []) if today_e else [],
            "yesterday_cost": yest_e.get("totalCost") if yest_e else None,
            "last_30d_cost": p.get("last30DaysCostUSD"),
            "last_30d_tokens": p.get("last30DaysTokens"),
        }
        # Cache-read ratio for Claude (cache reads dominate cost profile)
        if today_e:
            total = today_e.get("totalTokens") or 0
            cache_r = today_e.get("cacheReadTokens") or 0
            if total > 0:
                out["cache_pct"] = cache_r / total * 100
        return out
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


def _codex_reset_credits_line(usage: dict) -> str | None:
    """Return a warning line when any Codex reset credit expires within RESET_CREDIT_WARN_DAYS days."""
    credits_data = usage.get("codexResetCredits")
    if not credits_data:
        return None

    now = datetime.now(timezone.utc)
    warn_cutoff = now + timedelta(days=RESET_CREDIT_WARN_DAYS)

    available = [
        c for c in credits_data.get("credits", [])
        if c.get("status") == "available"
    ]
    if not available:
        return None

    expiring_soon = sorted(
        (
            (_parse_dt(c.get("expires_at")), c)
            for c in available
            if _parse_dt(c.get("expires_at")) is not None
              and _parse_dt(c.get("expires_at")) <= warn_cutoff
        ),
        key=lambda x: x[0],
    )

    if not expiring_soon:
        return None

    count = len(available)
    credit_word = "reset" if count == 1 else "resets"
    parts = []
    for expires_dt, _ in expiring_soon:
        days_left = (expires_dt - now).days
        date_label = expires_dt.astimezone(TZ).strftime("%b %d")
        if days_left <= 0:
            parts.append(f"{date_label} (today!)")
        elif days_left == 1:
            parts.append(f"{date_label} (tomorrow)")
        else:
            parts.append(f"{date_label} (in {days_left}d)")

    expiry_str = ", ".join(parts)
    return f"  ⏳ Reset credits: {count} {credit_word} available — expires {expiry_str}"


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

        if provider.get("error"):
            lines.append("  ⚠️ Auth required — run `codexbar` and sign in")
            lines.append("")
            continue

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

        # Codex reset credits expiry warning (shown ≤ RESET_CREDIT_WARN_DAYS before expiry)
        if name == "codex":
            credit_line = _codex_reset_credits_line(usage)
            if credit_line:
                lines.append(credit_line)

        # Cost summary (codex + claude only — perplexity has no local logs)
        if name in ("codex", "claude"):
            costs = get_codexbar_costs(name)
            if costs:
                parts = []
                if costs.get("today_cost") is not None:
                    parts.append(f"Today: `${costs['today_cost']:.2f}`")
                if costs.get("last_30d_cost") is not None:
                    parts.append(f"30d: `${costs['last_30d_cost']:,.0f}`")
                if parts:
                    lines.append(f"  💰 {' | '.join(parts)}")

        lines.append("")

    return "\n".join(lines).rstrip()


def build_daily_message(data: list[dict], enabled: set[str]) -> str:
    now_tz = datetime.now(TZ)
    today = now_tz.strftime("%Y-%m-%d")
    lines = [f"📊 *Daily Report* — {today}\n"]

    total_today = 0.0
    total_30d = 0.0
    has_cost_data = False

    for name in ["codex", "claude", "perplexity"]:
        if name not in enabled:
            continue
        provider = find_provider(data, name)
        if not provider:
            continue

        icon = PROVIDER_ICONS.get(name, "⚪")
        usage = provider.get("usage", {})

        if name not in ("codex", "claude"):
            # Perplexity — no local logs, show usage % only
            primary_pct = usage.get("primary", {}).get("usedPercent")
            weekly_pct = usage.get("secondary", {}).get("usedPercent")
            pct = f"  5h: {primary_pct}%  7d: {weekly_pct}%" if primary_pct is not None else ""
            lines.append(f"{icon} *{name.capitalize()}*: subscription — no cost data{pct}")
            lines.append("")
            continue

        costs = get_codexbar_costs(name)
        today_cost = costs.get("today_cost")
        yest_cost = costs.get("yesterday_cost")
        last_30d = costs.get("last_30d_cost")
        last_30d_tok = costs.get("last_30d_tokens")
        models = costs.get("today_models", [])
        cache_pct = costs.get("cache_pct")

        login = usage.get("loginMethod") or provider.get("openaiDashboard", {}).get("accountPlan", "")
        lines.append(f"{icon} *{name.capitalize()}{f' ({login})' if login else ''}*")

        if today_cost is not None:
            model_str = f"  _{', '.join(models)}_" if models else ""
            lines.append(f"  Today: `${today_cost:.2f}`{model_str}")
            total_today += today_cost
            has_cost_data = True
        else:
            lines.append("  Today: no data yet")

        if yest_cost is not None:
            lines.append(f"  Yesterday: `${yest_cost:.2f}`")

        if last_30d is not None:
            tok_str = f"  ({last_30d_tok / 1e9:.2f}B tokens)" if last_30d_tok else ""
            lines.append(f"  30d: `${last_30d:,.0f}`{tok_str}")
            total_30d += last_30d

        if cache_pct is not None and name == "claude":
            lines.append(f"  Cache reads: {cache_pct:.0f}% of tokens")

        lines.append("")

    if has_cost_data:
        lines.append(f"💰 *Total today:* `${total_today:.2f}`")
        if total_30d > 0:
            lines.append(f"📅 *30d API-equiv:* `${total_30d:,.0f}`")
    lines.append("_API-equivalent costs — actual charge is your flat subscription fee._")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reset detection
# ---------------------------------------------------------------------------

def load_reset_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_reset_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def detect_resets(
    data: list[dict], enabled: set[str], old_state: dict
) -> tuple[list[tuple[str, str, dict, dict]], dict]:
    """Detect weekly (7d) limit resets for Codex and Claude.

    A reset/recalculation is detected only when usedPercent drops below the
    prior high-water mark for that provider.

    This intentionally ignores resetsAt drift for Codex. In practice, CodexBar
    can move that timestamp forward even when usage is unchanged, which creates
    false weekly reset notifications like 0% -> 0% or 8% -> 8%.

    Includes a cooldown so a single reset event doesn't produce duplicate alerts.
    Returns (resets, new_state).
    """
    resets: list[tuple[str, str, dict, dict]] = []
    new_state: dict = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    for name in ["codex", "claude"]:
        if name not in enabled:
            continue
        provider = find_provider(data, name)
        if not provider:
            continue

        window = provider.get("usage", {}).get("secondary")
        if not window:
            continue

        new_pct = window.get("usedPercent")
        new_resets_at = window.get("resetsAt")
        prev = old_state.get(name, {})
        old_max_pct = prev.get("maxUsedPercent") or prev.get("usedPercent") or 0
        new_max_pct = max(new_pct or 0, old_max_pct)

        new_state[name] = {
            "usedPercent": new_pct,
            "maxUsedPercent": new_max_pct,
            "resetsAt": new_resets_at,
            "lastNotifiedAt": prev.get("lastNotifiedAt"),
        }

        # Signal: usedPercent dropped below the high-water mark
        pct_reset = new_pct is not None and new_pct < old_max_pct

        if not pct_reset:
            continue

        reason = "usedPercent drop"
        last_notified = prev.get("lastNotifiedAt")
        if last_notified:
            last_dt = datetime.fromisoformat(last_notified)
            elapsed_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if elapsed_h < RESET_COOLDOWN_HOURS:
                print(
                    f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"{name}: reset detected ({reason}) but cooldown active "
                    f"({elapsed_h:.1f}h < {RESET_COOLDOWN_HOURS}h) — skipping."
                )
                continue

        resets.append((name, "secondary", {"usedPercent": old_max_pct}, window))
        new_state[name]["lastNotifiedAt"] = now_iso
        # Reset the high-water mark so the next cycle starts fresh
        new_state[name]["maxUsedPercent"] = new_pct or 0

    return resets, new_state


def build_reset_message(resets: list[tuple[str, str, dict, dict]]) -> str:
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"🔄 *Limit Reset!* — {now}\n"]

    for name, _window_key, old_window, new_window in resets:
        icon = PROVIDER_ICONS.get(name, "⚪")
        old_pct = old_window.get("usedPercent", "?")
        new_pct = new_window.get("usedPercent", "?")
        reset_desc = new_window.get("resetDescription", "")

        lines.append(f"{icon} *{name.capitalize()}* — weekly (7d) limit reset")
        lines.append(f"  Was: {old_pct}% used → Now: {new_pct}% used")
        if reset_desc:
            lines.append(f"  Next reset: {reset_desc}")
        lines.append("")

    return "\n".join(lines).rstrip()


def check_resets(data: list[dict], enabled: set[str]) -> None:
    old_state = load_reset_state()
    resets, new_state = detect_resets(data, enabled, old_state)

    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    if resets:
        msg = build_reset_message(resets)
        # Save state AFTER successful send so a Telegram failure allows retry next run.
        send_telegram(msg, mode="reset")
        save_reset_state(new_state)
        names = ", ".join(name for name, *_ in resets)
        print(f"[{ts}] Sent reset notification ({len(resets)} reset(s): {names}).")
    else:
        save_reset_state(new_state)
        print(f"[{ts}] No resets detected.")


# ---------------------------------------------------------------------------
# Sent-message log
# ---------------------------------------------------------------------------

def log_sent(mode: str, text: str) -> None:
    """Append a one-line entry to sent.log so every outgoing message is auditable."""
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    first_line = text.split("\n")[0].replace("*", "").replace("`", "").strip()
    entry = f"[{ts}] [{mode}] {first_line}\n"
    try:
        SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SENT_LOG.open("a") as f:
            f.write(entry)
    except Exception as e:
        print(f"Warning: could not write sent.log: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(text: str, mode: str = "message") -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()
    log_sent(mode, text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env", file=sys.stderr)
        sys.exit(1)

    daily = "--daily" in sys.argv
    reset_check = "--reset-check" in sys.argv

    try:
        data = get_usage_data()
        enabled = get_enabled_providers()
        if not enabled:
            print("WARNING: No providers enabled. Set PROVIDER_*_ENABLED=true in .env", file=sys.stderr)

        if reset_check:
            check_resets(data, enabled)
            return

        message = build_daily_message(data, enabled) if daily else build_monitor_message(data, enabled)
    except FileNotFoundError:
        message = f"🚨 *AI Token Watchdog ERROR*\ncodexbar not found at `{CODEXBAR}`"
    except Exception as e:
        message = f"🚨 *AI Token Watchdog ERROR*\n`{type(e).__name__}: {e}`"

    try:
        mode = "daily" if daily else "monitor"
        send_telegram(message, mode=mode)
        print(f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}] Sent {mode} to Telegram.")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

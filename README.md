# AI Token Watchdog

A local macOS script that monitors AI subscription usage (Claude, Codex, Perplexity) via [CodexBar](https://github.com/steipete/codexbar/) and sends Telegram notifications with **smart pacing advice** — so you can spread usage more evenly across your working hours.

**Two modes:**
- **Monitor** — runs at fixed local hours, reports usage % + pacing advice + today's API-equivalent cost per provider
- **Daily report** — runs once at configured hour, reports costs, token counts, and 30-day totals

## Prerequisites

- macOS
- [CodexBar](https://github.com/steipete/codexbar/) installed at `/opt/homebrew/bin/codexbar`
- [uv](https://docs.astral.sh/uv/) — `brew install uv`
- A Telegram bot (create via [@BotFather](https://t.me/BotFather))

## Install CodexBar

```bash
# CodexBar (macOS 14+)
brew install --cask codexbar

# Verify
/opt/homebrew/bin/codexbar --version
/opt/homebrew/bin/codexbar usage --format json | python3 -m json.tool | head -20
```

After installing, open CodexBar and sign in to each provider (Codex, Claude) so usage data is available via the CLI.

## Setup

```bash
git clone https://github.com/your-username/ai-token-watchdog.git
cd ai-token-watchdog

# Install dependencies
uv sync

# Configure
cp .env.example .env
# Edit .env — fill in your Telegram credentials and preferences

# Test run
uv run watchdog.py           # monitor message
uv run watchdog.py --daily   # daily report message
```

### Getting your Telegram Chat ID

1. Start a chat with your bot on Telegram (send any message)
2. Open: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Copy the value at `result[0].message.chat.id`

## Installing launchd Agents (macOS)

```bash
bash launchd/install.sh
```

This reads `MONITOR_HOURS`, `DAILY_REPORT_HOUR` from your `.env` and installs three launchd agents to `~/Library/LaunchAgents/`:

| Agent | Schedule |
|---|---|
| `com.ai-token-watchdog.monitor` | Daily at each hour listed in `MONITOR_HOURS` |
| `com.ai-token-watchdog.daily` | Daily at `DAILY_REPORT_HOUR:00` |
| `com.ai-token-watchdog.reset-check` | Every 30 minutes (limit reset detector) |

```bash
# Verify agents are running
launchctl list | grep watchdog

# View logs
tail -f logs/monitor.log
tail -f logs/daily.log
tail -f logs/reset-check.log

# Uninstall
bash launchd/install.sh --uninstall
```

> **Note:** After changing `MONITOR_HOURS` or `DAILY_REPORT_HOUR` in `.env`, re-run `bash launchd/install.sh` to apply changes.

## Configuration

All settings live in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | — | Your Telegram chat ID |
| `MONITOR_HOURS` | `10,14,16,20` | Comma-separated local hours when monitor notifications are sent |
| `DAILY_REPORT_HOUR` | `18` | Hour for daily credit report (0–23, local time) |
| `TIMEZONE` | `Europe/Kyiv` | Your timezone ([IANA name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)) |
| `WORK_START_HOUR` | `8` | Working day start hour (for pacing calculation) |
| `WORK_END_HOUR` | `22` | Working day end hour (for pacing calculation) |
| `CODEXBAR_PATH` | `/opt/homebrew/bin/codexbar` | Path to `codexbar` CLI |
| `RESET_DROP_THRESHOLD` | `40` | Min % drop in Claude usage to detect a limit reset |
| `RESET_CREDIT_WARN_DAYS` | `14` | Days before Codex reset-credit expiry to start showing warnings |
| `PROVIDER_CODEX_ENABLED` | `true` | Enable/disable Codex monitoring |
| `PROVIDER_CLAUDE_ENABLED` | `true` | Enable/disable Claude monitoring |
| `PROVIDER_PERPLEXITY_ENABLED` | `true` | Enable/disable Perplexity monitoring |

## Adding a New Provider

Adding a new provider is a two-step process:

**Step 1 — Configure it in CodexBar**

Sign in to the new provider inside CodexBar (via its menu bar UI). Once connected, verify it appears in the JSON output and note the exact `provider` field value:

```bash
/opt/homebrew/bin/codexbar usage --format json | python3 -m json.tool | grep '"provider"'
```

Example output: `"provider": "grok"` → use `GROK` (uppercase) in the next step.

**Step 2 — Enable it in `.env`**

Add one line following the pattern `PROVIDER_{NAME}_ENABLED=true`:

```dotenv
PROVIDER_GROK_ENABLED=true
```

No code changes to `watchdog.py` needed. New providers default to a ⚪ icon.

> **Note:** If the name in `.env` doesn't match CodexBar's `provider` field exactly, the provider is silently skipped. Always verify via the `grep` command above.

## How Pacing Works

For each provider, the script calculates:

1. **Remaining weekly budget** — `100% - weekly_used%`
2. **Remaining working windows** — how many primary rate-limit windows (5h or 12h) fit in working hours (`WORK_START_HOUR`–`WORK_END_HOUR`) between now and the weekly reset
3. **Target per window** — `remaining_budget / remaining_windows`

**Example:** Weekly limit resets in 2 days. You have 63% remaining. Working hours 8:00–22:00 = 14h/day. Primary window = 5h → ~2 windows/day → 4 windows total.  
→ Target: `63% / 4 = ~16% per 5h window`.

## Example Notifications

**Monitor (fixed local hours):**
```
🤖 AI Token Watchdog — 2026-07-12 10:00

🟢 Codex (plus)
  5h : ✅ [█████░░░░░] 54%  ↻ 3:09 PM
  7d : ✅ [██████░░░░] 58%  ↻ Jul 18 at 9:04 AM
  Pacing (5h windows): 16 left before reset  → target ~3%/window  🧊 Slow down — budget nearly spent
  ⏳ Reset credits: 3 resets available — expires Jul 18 (in 5d)
  💰 Today: $8.34 | 30d: $316

🟣 Claude (Claude Pro)
  5h : ✅ [█░░░░░░░░░] 12%  ↻ Jul 12 at 3:09PM
  7d : ✅ [░░░░░░░░░░] 6%   ↻ Jul 17 at 5:59PM
  Pacing (5h windows): 16 left before reset  → target ~6%/window  📈 On track
  💰 Today: $3.18 | 30d: $584
```

**Daily report (18:00):**
```
📊 Daily Report — 2026-07-12

🟢 Codex (plus)
  Today: $8.34  gpt-5.6-sol
  Yesterday: $62.65
  30d: $316  (0.59B tokens)

🟣 Claude (Claude Pro)
  Today: $3.18  claude-sonnet-4-6
  Yesterday: $5.31
  30d: $584  (1.05B tokens)
  Cache reads: 98% of tokens

💰 Total today: $11.53
📅 30d API-equiv: $900
API-equivalent costs — actual charge is your flat subscription fee.
```

**Limit reset notification (every 30 min check):**
```
🔄 Limit Reset! — 2026-07-12 15:09

🟢 Codex — 5h window reset
  Was: 100% used → Now: 3% used
  Next reset: 8:09 PM
```

> **About cost data:** All dollar costs come from `codexbar cost`, which reads local CLI logs and calculates API-equivalent spend. Perplexity is a flat subscription with no per-token data — usage % is shown instead.

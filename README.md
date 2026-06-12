# AI Token Watchdog

A local macOS script that monitors AI subscription usage (Claude, Codex, Perplexity) via [CodexBar](https://github.com/steipete/codexbar/) and sends Telegram notifications with **smart pacing advice** — so you can spread usage more evenly across your working hours.

**Two modes:**
- **Monitor** — runs at fixed local hours, reports usage % + pacing advice per provider
- **Daily report** — runs once at configured hour, reports credit costs for the day

## Prerequisites

- macOS
- [CodexBar](https://github.com/steipete/codexbar/) installed at `/opt/homebrew/bin/codexbar`
- [ccusage](https://github.com/ryoppippi/ccusage/) available via `bunx ccusage` for local cost data
- [Bun](https://bun.sh/) installed first (required because `ccusage` is run via `bunx`)
- [uv](https://docs.astral.sh/uv/) — `brew install uv`
- A Telegram bot (create via [@BotFather](https://t.me/BotFather))

## Install CodexBar and ccusage

If you do not already have `CodexBar` and `ccusage` on your machine:

```bash
# CodexBar (macOS 14+)
brew install --cask codexbar

# Install Bun first (required for bunx ccusage)
curl -fsSL https://bun.sh/install | bash

# Verify Bun / bunx
~/.bun/bin/bun --version
~/.bun/bin/bunx --version

# Quick smoke tests
/opt/homebrew/bin/codexbar --help
~/.bun/bin/bunx ccusage --help
```

If you prefer a globally installed `ccusage` command instead of `bunx ccusage`:

```bash
~/.bun/bin/bun install -g ccusage
ccusage --help
```

If your Bun binary is not at `~/.bun/bin/bunx`, set `BUNX_PATH` in `.env` to the actual path from:

```bash
which bunx
```

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

This reads `MONITOR_HOURS` and `DAILY_REPORT_HOUR` from your `.env` and installs two launchd agents to `~/Library/LaunchAgents/`:

| Agent | Schedule (from .env) |
|---|---|
| `com.ai-token-watchdog.monitor` | Daily at each hour listed in `MONITOR_HOURS` |
| `com.ai-token-watchdog.daily` | Daily at `DAILY_REPORT_HOUR:00` |

```bash
# Verify agents are running
launchctl list | grep watchdog

# View logs
tail -f logs/monitor.log
tail -f logs/daily.log

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
| `BUNX_PATH` | `/opt/homebrew/bin/bunx` | Path to `bunx` (used for ccusage cost data) |
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
🤖 AI Token Watchdog — 2026-06-12 23:01

🟢 Codex (Plus)
  5h : ✅ [██░░░░░░░░] 17%  ↻ Jun 13, 3:33 AM
  7d : ✅ [████░░░░░░] 37%  ↻ Jun 18, 9:03 AM
  Pacing (5h windows): 8 left before reset → target ~8%/window  📈 On track

🟣 Claude (Claude Pro)
  5h : ✅ [██░░░░░░░░] 16%  ↻ Jun 12 at 11:29PM
  7d : ✅ [░░░░░░░░░░] 2%   ↻ Jun 19 at 5:59PM
  Pacing (5h windows): 16 left before reset → target ~6%/window  📈 On track

🔵 Perplexity
  5h : 🚨 [██████████] 100%  0/0 credits
```

**Daily report (18:00):**
```
📊 Daily Report — 2026-06-12

🟢 Codex today: $17.94 (ccusage)
🟣 Claude today: $53.36 (ccusage)
🔵 Perplexity: subscription plan (no cost data)  5h: 100%  7d: 100%

💰 Total today: $71.30
📅 Yesterday: $29.52
Costs are API-equivalent — actual charge is your flat subscription fee.
```

> **About cost data:** Claude and Codex dollar costs come from [ccusage](https://github.com/ryoppippi/ccusage), which reads local CLI logs and calculates API-equivalent spend. Perplexity is a flat subscription with no per-token data — usage % is shown instead.

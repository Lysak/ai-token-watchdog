#!/bin/bash
# Disabled legacy subsystem: no Keychain reads, writes, or token refreshes.
echo "codexbar-keychain is disabled; watchdog does not manage Keychain access."
exit 0

: <<'LEGACY_KEYCHAIN_REFRESH'
# Відновлює partition list для елемента "Claude Code-credentials",
# щоб CodexBar (team Y5PE65HELJ) читав його без запиту пароля.
# Гейт по mdat: реагує лише на РЕАЛЬНУ зміну елемента, ігнорує власні записи.
#
# Templated by install.sh — __PROJECT_DIR__ and __STATE_DIR__ are substituted
# at install time. Do not edit the installed copy in __STATE_DIR__ directly;
# edit this file and re-run install.sh.

USER_NAME="$(whoami)"
HELPER_SVC="codexbar-login-helper"
TARGET="Claude Code-credentials"
STATE="__STATE_DIR__/.last-mdat"
FAIL_COUNT_FILE="__STATE_DIR__/.fail-count"
WATCHDOG_ENV="__PROJECT_DIR__/.env"
FAIL_ALERT_THRESHOLD=3

# Сповіщає в Telegram (той самий бот/чат, що й ai-token-watchdog) і скидає лічильник,
# щоб не спамити при кожному наступному тригері WatchPaths.
notify_failure() {
  local reason="$1"
  local count
  count="$(($(cat "$FAIL_COUNT_FILE" 2>/dev/null || echo 0) + 1))"
  echo "$count" > "$FAIL_COUNT_FILE"
  [ "$count" -lt "$FAIL_ALERT_THRESHOLD" ] && return 0
  [ -f "$WATCHDOG_ENV" ] || return 0

  local token chat_id
  token="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$WATCHDOG_ENV" | cut -d= -f2-)"
  chat_id="$(grep -E '^TELEGRAM_CHAT_ID=' "$WATCHDOG_ENV" | cut -d= -f2-)"
  [ -z "$token" ] || [ -z "$chat_id" ] && return 0

  curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    -d chat_id="$chat_id" \
    -d text="🚨 codexbar-keychain: refresh-partition.sh fails repeatedly (${count}x) — ${reason}. CodexBar may start prompting for your login password again." \
    >/dev/null 2>&1
  echo "0" > "$FAIL_COUNT_FILE"
}

# Читання атрибутів (у т.ч. mdat) НЕ потребує пароля.
CUR="$(security find-generic-password -s "$TARGET" -a "$USER_NAME" 2>/dev/null | grep '"mdat"' || true)"

# Елемент відсутній (напр. під час ре-логіну) — нічого не робимо.
[ -z "$CUR" ] && exit 0

# Нічого не змінилось з моменту останнього застосування — вихід (розриває цикл).
[ -f "$STATE" ] && [ "$CUR" = "$(cat "$STATE")" ] && exit 0

# Пароль читає лише авторизований /usr/bin/security, без GUI-запиту.
LOGIN_PW="$(security find-generic-password -s "$HELPER_SVC" -a "$USER_NAME" -w 2>/dev/null)"
if [ -z "$LOGIN_PW" ]; then
  echo "$(date '+%F %T') ERROR: не зміг прочитати пароль-помічник"
  notify_failure "helper keychain item '$HELPER_SVC' missing or unreadable"
  exit 1
fi

if security set-generic-password-partition-list -a "$USER_NAME" -s "$TARGET" \
     -S "apple-tool:,apple:,teamid:Y5PE65HELJ" -k "$LOGIN_PW" >/dev/null 2>&1; then
  # Запам'ятовуємо mdat ПІСЛЯ нашої зміни, щоб наступний тригер (від нашого ж запису) ігнорувати.
  security find-generic-password -s "$TARGET" -a "$USER_NAME" 2>/dev/null | grep '"mdat"' > "$STATE"
  echo "0" > "$FAIL_COUNT_FILE"
  echo "$(date '+%F %T') OK: partition list оновлено для CodexBar (Y5PE65HELJ)"
else
  echo "$(date '+%F %T') ERROR: set-generic-password-partition-list не вдалось"
  notify_failure "set-generic-password-partition-list failed"
fi
LEGACY_KEYCHAIN_REFRESH

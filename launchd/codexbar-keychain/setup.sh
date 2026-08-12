#!/bin/bash
# Disabled legacy subsystem: no Keychain reads, writes, or password prompts.
echo "codexbar-keychain is disabled; watchdog does not manage Keychain access."
exit 0

: <<'LEGACY_KEYCHAIN_SETUP'
# Одноразове налаштування (запускати в Terminal.app — спитає пароль від входу).
#
# Templated by install.sh — __STATE_DIR__ and __LABEL__ are substituted at
# install time. Do not edit the installed copy in __STATE_DIR__ directly;
# edit this file and re-run install.sh, then re-run the installed setup.sh.
set -euo pipefail

DIR="__STATE_DIR__"
USER_NAME="$(whoami)"
HELPER_SVC="codexbar-login-helper"
LABEL="__LABEL__"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "== Налаштування автооновлення keychain-доступу для CodexBar =="
read -rs -p "Пароль від входу в macOS (login keychain): " LOGIN_PW; echo

# 0. Перевірка пароля
if ! security unlock-keychain -p "$LOGIN_PW" "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null; then
  echo "❌ Пароль невірний."; exit 1
fi

# 1. Зберегти пароль у окремому keychain-елементі; читати дозволено лише /usr/bin/security
security delete-generic-password -s "$HELPER_SVC" -a "$USER_NAME" >/dev/null 2>&1 || true
security add-generic-password -s "$HELPER_SVC" -a "$USER_NAME" -w "$LOGIN_PW" \
  -D "CodexBar keychain helper" -T /usr/bin/security -U
security set-generic-password-partition-list -s "$HELPER_SVC" -a "$USER_NAME" \
  -S "apple-tool:,apple:" -k "$LOGIN_PW" >/dev/null

# 2. Перевірити неінтерактивне читання
if [ -z "$(security find-generic-password -s "$HELPER_SVC" -a "$USER_NAME" -w 2>/dev/null)" ]; then
  echo "❌ Не вдалося налаштувати неінтерактивне читання пароля."; exit 1
fi
echo "✅ Пароль збережено в keychain (зашифровано; читає лише /usr/bin/security)."
unset LOGIN_PW

# 3. Застосувати одразу
rm -f "$DIR/.last-mdat"
bash "$DIR/refresh-partition.sh" || true

# 4. (Пере)завантажити LaunchAgent
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "✅ LaunchAgent завантажено ($LABEL)."
echo "Готово. Лог: $DIR/agent.log"
LEGACY_KEYCHAIN_SETUP

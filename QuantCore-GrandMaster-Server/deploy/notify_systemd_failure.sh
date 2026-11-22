#!/usr/bin/env bash
# ==============================================================================
# Dead-Man's Switch: зовнішнє сповіщення systemd OnFailure при краші / OOM сервісу
# ==============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ -f "$ENV_FILE" ]; then
    # Безпечне зчитування TELEGRAM_TOKEN та TELEGRAM_CHAT_ID із .env
    TELEGRAM_TOKEN="$(grep -E '^TELEGRAM_TOKEN=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'")"
    TELEGRAM_CHAT_ID="$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'")"
fi

if [ -z "${TELEGRAM_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    exit 0
fi

HOST_NAME="$(hostname)"
TS_UTC="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
LAST_LOGS="$(journalctl -u trading_bot.service -n 8 --no-pager 2>/dev/null | tail -c 600)"

MSG="🚨 [DEAD-MAN SWITCH: SYSTEMD ONFAILURE]
• Host: ${HOST_NAME} (${TS_UTC})
• Service trading_bot.service exited abnormally (OOM / Crash / Preflight Stop)!
• Біржові STOP_MARKET ордери залишаються активними на Binance.
• Останні рядки журналу:
${LAST_LOGS}"

curl -sS --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${MSG}" >/dev/null 2>&1 || true

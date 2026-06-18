#!/usr/bin/env bash
# Запускает все три бота в одном контейнере (один сервис = дешевле).
# Токены приходят из переменных окружения площадки (не из .env — его в проде нет).
set -euo pipefail
cd "$(dirname "$0")"

echo "▶️  Старт трёх ботов…"

BOT_TOKEN="${REMINDER_TOKEN:?нет REMINDER_TOKEN}" python -u reminder-bot/bot.py &
BOT_TOKEN="${PRICE_TOKEN:?нет PRICE_TOKEN}" CHECK_EVERY_MIN="${CHECK_EVERY_MIN:-30}" python -u price-tracker-bot/bot.py &
BOT_TOKEN="${FAQ_TOKEN:?нет FAQ_TOKEN}" ADMIN_CHAT_ID="${ADMIN_CHAT_ID:-}" python -u faq-bot/bot.py &

# Если любой из ботов упал — гасим контейнер, площадка перезапустит всё заново.
wait -n
echo "⛔ Один из ботов остановился — выходим, чтобы площадка перезапустила."
exit 1

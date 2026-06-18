<div align="center">

# ⏰ Напоминалка

**Telegram-бот, который не даст ничего забыть.**

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0?logo=telegram&logoColor=white)

</div>

---

## Возможности

| | Команда | Что делает |
|---|---|---|
| ⏱ | `/remind 10m купить хлеб` | разовое напоминание через 10 минут |
| 🕐 | `/remind 2h позвонить маме` | единицы: `m` мин, `h` часы, `d` дни |
| 📅 | `/daily 09:00 выпить воды` | каждый день в указанное время |
| 📋 | `/list` | список активных + удаление кнопкой 🗑 |

- Напоминания **переживают перезапуск** (хранятся в `reminders.json`).
- Ежедневные срабатывают раз в сутки, без дублей.

## Запуск

```bash
pip install -r requirements.txt
BOT_TOKEN=ваш_токен python bot.py
```

Токен берётся у [@BotFather](https://t.me/BotFather) → `/newbot`.

## Под заказ

Допиливается под клиента: напоминания по будням, привязка к Google Календарю,
напоминания команде в группе, кнопка «отложить на 10 минут». Пишите — настрою.

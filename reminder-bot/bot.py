# -*- coding: utf-8 -*-
"""
⏰ Напоминалка — Telegram-бот напоминаний.

Что умеет:
  • разовые напоминания:  /remind 10m купить хлеб
  • поддержка единиц: m (мин), h (часы), d (дни)  →  /remind 2h позвонить маме
  • ежедневные напоминания в нужное время:  /daily 09:00 выпить воды
  • список и удаление активных напоминаний (кнопками)
  • переживает перезапуск — всё хранится в reminders.json

Стек: pyTelegramBotAPI. Запуск: BOT_TOKEN=xxx python bot.py
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

import telebot
from dotenv import load_dotenv
from telebot import types

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = os.path.join(os.path.dirname(__file__), "reminders.json")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ---------------------------------------------------------------- хранилище
_lock = threading.Lock()


def load() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save(items: list) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add_reminder(item: dict) -> None:
    with _lock:
        items = load()
        items.append(item)
        save(items)


# ---------------------------------------------------------------- разбор времени
UNITS = {"m": 60, "h": 3600, "d": 86400, "м": 60, "ч": 3600, "д": 86400}


def parse_delay(token: str):
    """'10m' -> 600 секунд. Вернёт None, если не распознал."""
    match = re.fullmatch(r"(\d+)\s*([mhdмчд])", token.lower())
    if not match:
        return None
    return int(match.group(1)) * UNITS[match.group(2)]


def parse_time(token: str):
    """'09:00' -> (9, 0). Вернёт None, если не время."""
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", token)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


# ---------------------------------------------------------------- команды
WELCOME = (
    "⏰ <b>Напоминалка</b>\n\n"
    "Я не дам тебе ничего забыть.\n\n"
    "<b>Разовое напоминание:</b>\n"
    "<code>/remind 10m купить хлеб</code>\n"
    "<code>/remind 2h позвонить маме</code>\n"
    "Единицы: <code>m</code> минуты, <code>h</code> часы, <code>d</code> дни.\n\n"
    "<b>Каждый день в нужное время:</b>\n"
    "<code>/daily 09:00 выпить воды</code>\n\n"
    "<b>Список:</b> /list — посмотреть и удалить активные."
)


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    bot.reply_to(message, WELCOME)


@bot.message_handler(commands=["remind"])
def cmd_remind(message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Формат: <code>/remind 10m текст</code>")
        return
    delay = parse_delay(parts[1])
    if delay is None:
        bot.reply_to(message, "Не понял время. Примеры: <code>10m</code>, <code>2h</code>, <code>1d</code>.")
        return
    fire_at = time.time() + delay
    add_reminder({
        "chat_id": message.chat.id,
        "text": parts[2],
        "fire_at": fire_at,
        "kind": "once",
    })
    when = datetime.fromtimestamp(fire_at).strftime("%d.%m %H:%M")
    bot.reply_to(message, f"✅ Напомню <b>{when}</b>:\n«{parts[2]}»")


@bot.message_handler(commands=["daily"])
def cmd_daily(message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Формат: <code>/daily 09:00 текст</code>")
        return
    hm = parse_time(parts[1])
    if hm is None:
        bot.reply_to(message, "Не понял время. Формат ЧЧ:ММ, например <code>09:00</code>.")
        return
    add_reminder({
        "chat_id": message.chat.id,
        "text": parts[2],
        "hour": hm[0],
        "minute": hm[1],
        "kind": "daily",
        "last_date": "",
    })
    bot.reply_to(message, f"✅ Каждый день в <b>{parts[1]}</b>:\n«{parts[2]}»")


@bot.message_handler(commands=["list"])
def cmd_list(message):
    items = [(i, r) for i, r in enumerate(load()) if r["chat_id"] == message.chat.id]
    if not items:
        bot.reply_to(message, "Активных напоминаний нет.")
        return
    markup = types.InlineKeyboardMarkup()
    lines = ["<b>Твои напоминания:</b>\n"]
    for idx, r in items:
        if r["kind"] == "once":
            label = datetime.fromtimestamp(r["fire_at"]).strftime("%d.%m %H:%M")
        else:
            label = f"ежедневно {r['hour']:02d}:{r['minute']:02d}"
        lines.append(f"• <b>{label}</b> — {r['text']}")
        markup.add(types.InlineKeyboardButton(f"🗑 {label} — {r['text'][:20]}", callback_data=f"del:{idx}"))
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def cb_delete(call):
    idx = int(call.data.split(":")[1])
    with _lock:
        items = load()
        if 0 <= idx < len(items) and items[idx]["chat_id"] == call.message.chat.id:
            removed = items.pop(idx)
            save(items)
            bot.answer_callback_query(call.id, "Удалено")
            bot.edit_message_text(f"🗑 Удалено: «{removed['text']}»", call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Уже неактуально")


# ---------------------------------------------------------------- фоновый проверяльщик
def checker():
    while True:
        now = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        with _lock:
            items = load()
            keep = []
            fired = []
            for r in items:
                if r["kind"] == "once":
                    if now >= r["fire_at"]:
                        fired.append(r)
                    else:
                        keep.append(r)
                else:  # daily
                    nowdt = datetime.now()
                    if r.get("last_date") != today and (nowdt.hour, nowdt.minute) >= (r["hour"], r["minute"]):
                        r["last_date"] = today
                        fired.append(r)
                    keep.append(r)
            if fired:
                save(keep)
        for r in fired:
            try:
                bot.send_message(r["chat_id"], f"⏰ <b>Напоминание</b>\n{r['text']}")
            except Exception as exc:  # noqa: BLE001
                print("send failed:", exc)
        time.sleep(15)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("Задай токен: BOT_TOKEN=xxx python bot.py")
    threading.Thread(target=checker, daemon=True).start()
    print("⏰ Напоминалка запущена")
    while True:
        try:
            bot.infinity_polling(skip_pending=False, timeout=30)
        except Exception as exc:  # noqa: BLE001 — никогда не падаем из-за поллинга
            print("polling restart:", exc)
            time.sleep(3)

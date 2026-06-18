# -*- coding: utf-8 -*-
"""
💰 Парсер цен — Telegram-бот отслеживания цены товара.

Что умеет:
  • кидаешь ссылку на товар — бот сам находит цену (без CSS-селектора)
  • проверяет раз в N минут и пишет, когда цена изменилась (выросла/упала)
  • /list — что отслеживаю, /stop — удалить
  • переживает перезапуск (watches.json)

Стек: pyTelegramBotAPI + requests + beautifulsoup4 + lxml.
Запуск: BOT_TOKEN=xxx python bot.py
"""

import json
import os
import threading
import time

import requests
import telebot
from dotenv import load_dotenv
from telebot import types

from price import extract_price

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHECK_EVERY = int(os.environ.get("CHECK_EVERY_MIN", "30")) * 60  # секунды
DATA_FILE = os.path.join(os.path.dirname(__file__), "watches.json")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
_lock = threading.Lock()


# ---------------------------------------------------------------- хранилище
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


# ---------------------------------------------------------------- фетч цены
def fetch_price(url: str):
    """Вернёт (amount, raw, currency) или бросит понятную строку-ошибку."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except requests.Timeout:
        raise RuntimeError("сайт не ответил за 15 секунд")
    except requests.RequestException:
        raise RuntimeError("не удалось открыть ссылку")
    if resp.status_code in (401, 403):
        raise RuntimeError("сайт блокирует автопроверки (нужен другой магазин)")
    if resp.status_code == 404:
        raise RuntimeError("страница не найдена (404)")
    if resp.status_code >= 500:
        raise RuntimeError(f"сайт временно недоступен ({resp.status_code})")
    amount, raw, currency = extract_price(resp.text)
    if amount is None:
        raise RuntimeError("не нашёл цену (возможно, она грузится скриптом)")
    return amount, raw, currency


def fmt(amount: float, currency: str | None) -> str:
    money = f"{amount:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    return f"{money} {currency}" if currency else money


# ---------------------------------------------------------------- команды
WELCOME = (
    "💰 <b>Парсер цен</b>\n\n"
    "Пришли ссылку на товар — я найду цену сам и буду следить за ней.\n"
    "Как только цена изменится — напишу.\n\n"
    "📋 /list — что отслеживаю\n"
    "🛑 /stop — удалить отслеживание\n\n"
    "<i>Работает на «лёгких» магазинах (Shopify, нишевые и западные шопы). "
    "Крупные маркетплейсы часто прячут цену за скриптами.</i>"
)


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    bot.reply_to(message, WELCOME)


@bot.message_handler(commands=["list"])
def cmd_list(message):
    items = [(i, w) for i, w in enumerate(load()) if w["chat_id"] == message.chat.id]
    if not items:
        bot.reply_to(message, "Пока ничего не отслеживаю. Пришли ссылку на товар.")
        return
    lines = ["<b>Отслеживаю:</b>\n"]
    for _, w in items:
        last = fmt(w["last"], w.get("currency")) if w.get("last") is not None else "—"
        lines.append(f"• {last} — {w['url']}")
    bot.send_message(message.chat.id, "\n".join(lines), disable_web_page_preview=True)


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    items = [(i, w) for i, w in enumerate(load()) if w["chat_id"] == message.chat.id]
    if not items:
        bot.reply_to(message, "Нечего удалять.")
        return
    markup = types.InlineKeyboardMarkup()
    for idx, w in items:
        markup.add(types.InlineKeyboardButton(f"🗑 {w['url'][:40]}", callback_data=f"del:{idx}"))
    bot.send_message(message.chat.id, "Что удалить?", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def cb_delete(call):
    idx = int(call.data.split(":")[1])
    with _lock:
        items = load()
        if 0 <= idx < len(items) and items[idx]["chat_id"] == call.message.chat.id:
            removed = items.pop(idx)
            save(items)
            bot.answer_callback_query(call.id, "Удалено")
            bot.edit_message_text(f"🗑 Больше не слежу за:\n{removed['url']}",
                                  call.message.chat.id, call.message.message_id,
                                  disable_web_page_preview=True)
        else:
            bot.answer_callback_query(call.id, "Уже неактуально")


@bot.message_handler(func=lambda m: m.text and m.text.startswith("http"))
def on_url(message):
    url = message.text.strip()
    wait = bot.reply_to(message, "🔎 Ищу цену…")
    try:
        amount, _, currency = fetch_price(url)
    except RuntimeError as exc:
        bot.edit_message_text(f"⚠️ {exc}", message.chat.id, wait.message_id)
        return
    with _lock:
        items = load()
        items.append({"chat_id": message.chat.id, "url": url, "last": amount, "currency": currency})
        save(items)
    bot.edit_message_text(
        f"✅ Слежу за ценой.\nСейчас: <b>{fmt(amount, currency)}</b>\n"
        f"Проверяю каждые {CHECK_EVERY // 60} мин — напишу при изменении.",
        message.chat.id, wait.message_id,
    )


@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.reply_to(message, "Пришли <b>ссылку на товар</b> (начинается с http), и я начну следить за ценой.")


# ---------------------------------------------------------------- фоновый чек
def checker():
    while True:
        time.sleep(CHECK_EVERY)
        with _lock:
            items = load()
        changed = False
        for w in items:
            try:
                amount, _, currency = fetch_price(w["url"])
            except RuntimeError:
                continue  # временная ошибка — попробуем в следующий раз
            old = w.get("last")
            if old is not None and amount != old:
                arrow = "📉 упала" if amount < old else "📈 выросла"
                try:
                    bot.send_message(
                        w["chat_id"],
                        f"{arrow}!\n<s>{fmt(old, currency)}</s> → <b>{fmt(amount, currency)}</b>\n{w['url']}",
                        disable_web_page_preview=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    print("send failed:", exc)
            if amount != old:
                w["last"] = amount
                w["currency"] = currency
                changed = True
        if changed:
            with _lock:
                save(items)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("Задай токен: BOT_TOKEN=xxx python bot.py")
    threading.Thread(target=checker, daemon=True).start()
    print("💰 Парсер цен запущен")
    while True:
        try:
            bot.infinity_polling(skip_pending=False, timeout=30)
        except Exception as exc:  # noqa: BLE001 — никогда не падаем из-за поллинга
            print("polling restart:", exc)
            time.sleep(3)

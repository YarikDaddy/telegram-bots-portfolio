# -*- coding: utf-8 -*-
"""
💬 FAQ-автоответчик для бизнеса — Telegram-бот первой линии поддержки.

Что умеет:
  • меню кнопками: Услуги / Цены / Контакты / Оставить заявку
  • отвечает на частые вопросы по ключевым словам (доставка, оплата, гарантия…)
  • «Оставить заявку» — собирает имя + телефон + сообщение и шлёт владельцу в ЛС
  • авто-приписка о нерабочем времени

Весь контент бизнеса вынесен в content.py — клиент правит его без кода.
Стек: pyTelegramBotAPI. Запуск: BOT_TOKEN=xxx ADMIN_CHAT_ID=123 python bot.py
"""

import os
import time
from datetime import datetime

import telebot
from dotenv import load_dotenv
from telebot import types

import content as C

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")  # куда слать заявки

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# простое состояние «заполняет заявку»: chat_id -> {step, data}
leads: dict = {}


# ---------------------------------------------------------------- клавиатуры
def main_menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🛠 Услуги", "💵 Цены")
    kb.row("📞 Контакты", "📝 Оставить заявку")
    return kb


def is_working_hours() -> bool:
    hour = datetime.now().hour
    return C.WORK_FROM <= hour < C.WORK_TO


def with_hours_note(text: str) -> str:
    if not is_working_hours():
        return text + "\n\n🌙 <i>Сейчас нерабочее время — ответим в " \
                      f"{C.WORK_FROM:02d}:00–{C.WORK_TO:02d}:00.</i>"
    return text


# ---------------------------------------------------------------- команды/меню
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    leads.pop(message.chat.id, None)
    bot.send_message(message.chat.id, with_hours_note(C.GREETING), reply_markup=main_menu())


@bot.message_handler(func=lambda m: m.text == "🛠 Услуги")
def m_services(message):
    bot.send_message(message.chat.id, C.SERVICES, reply_markup=main_menu())


@bot.message_handler(func=lambda m: m.text == "💵 Цены")
def m_prices(message):
    bot.send_message(message.chat.id, C.PRICES, reply_markup=main_menu())


@bot.message_handler(func=lambda m: m.text == "📞 Контакты")
def m_contacts(message):
    bot.send_message(message.chat.id, C.CONTACTS, reply_markup=main_menu(),
                     disable_web_page_preview=True)


# ---------------------------------------------------------------- заявка (3 шага)
@bot.message_handler(func=lambda m: m.text == "📝 Оставить заявку")
def lead_start(message):
    leads[message.chat.id] = {"step": "name", "data": {}}
    cancel = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel.row("✖️ Отмена")
    bot.send_message(message.chat.id, "Как вас зовут?", reply_markup=cancel)


@bot.message_handler(func=lambda m: m.chat.id in leads)
def lead_flow(message):
    if message.text == "✖️ Отмена":
        leads.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Отменено.", reply_markup=main_menu())
        return

    state = leads[message.chat.id]
    if state["step"] == "name":
        state["data"]["name"] = message.text
        state["step"] = "phone"
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add(types.KeyboardButton("📲 Отправить мой номер", request_contact=True))
        kb.row("✖️ Отмена")
        bot.send_message(message.chat.id, "Ваш телефон? (или нажмите кнопку ниже)", reply_markup=kb)
    elif state["step"] == "phone":
        phone = message.contact.phone_number if message.contact else message.text
        state["data"]["phone"] = phone
        state["step"] = "msg"
        cancel = types.ReplyKeyboardMarkup(resize_keyboard=True)
        cancel.row("✖️ Отмена")
        bot.send_message(message.chat.id, "Опишите задачу одним сообщением:", reply_markup=cancel)
    elif state["step"] == "msg":
        state["data"]["msg"] = message.text
        finish_lead(message, state["data"])


def finish_lead(message, data):
    leads.pop(message.chat.id, None)
    user = message.from_user
    username = f"@{user.username}" if user.username else f"id{user.id}"
    card = (
        "🔔 <b>Новая заявка</b>\n\n"
        f"👤 Имя: {data['name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"💬 Задача: {data['msg']}\n"
        f"🔗 Контакт: {username}"
    )
    if ADMIN_CHAT_ID:
        try:
            bot.send_message(ADMIN_CHAT_ID, card)
        except Exception as exc:  # noqa: BLE001
            print("admin notify failed:", exc)
    bot.send_message(message.chat.id, with_hours_note(C.LEAD_THANKS), reply_markup=main_menu())


# ---------------------------------------------------------------- FAQ по ключевым словам
@bot.message_handler(func=lambda m: True)
def faq(message):
    text = (message.text or "").lower()
    for keywords, answer in C.FAQ:
        if any(k in text for k in keywords):
            bot.send_message(message.chat.id, answer, reply_markup=main_menu())
            return
    bot.send_message(message.chat.id, with_hours_note(C.FALLBACK), reply_markup=main_menu())


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("Задай токен: BOT_TOKEN=xxx ADMIN_CHAT_ID=твой_id python bot.py")
    if not ADMIN_CHAT_ID:
        print("⚠️  ADMIN_CHAT_ID не задан — заявки не будут пересылаться владельцу.")
    print("💬 FAQ-бот запущен")
    while True:
        try:
            bot.infinity_polling(skip_pending=False, timeout=30)
        except Exception as exc:  # noqa: BLE001 — никогда не падаем из-за поллинга
            print("polling restart:", exc)
            time.sleep(3)

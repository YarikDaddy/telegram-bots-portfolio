# -*- coding: utf-8 -*-
"""
📅 Бот-запись для салона / барбершопа — онлайн-запись с напоминаниями.

Что умеет:
  • запись в пару тапов: услуга → день → свободное время → имя → телефон
  • показывает только свободные слоты (занятые скрыты, прошедшее время — тоже)
  • «📋 Мои записи» — посмотреть и отменить свою запись
  • напоминает клиенту за день и за 2 часа до визита (меньше неявок)
  • каждая запись прилетает владельцу в ЛС
  • переживает перезапуск — всё хранится в bookings.json

Весь контент салона вынесен в content.py — клиент правит без кода.
Стек: pyTelegramBotAPI. Запуск: BOT_TOKEN=xxx ADMIN_CHAT_ID=123 python bot.py
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

import telebot
from dotenv import load_dotenv
from telebot import types

import content as C

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")  # куда слать новые записи
DATA_FILE = os.path.join(os.path.dirname(__file__), "bookings.json")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# состояние «оформляет запись»: chat_id -> {step, service, date, time, name}
pending: dict = {}


# ---------------------------------------------------------------- хранилище
_lock = threading.Lock()


def load() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save(items: list) -> None:
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def add_booking(b: dict) -> None:
    with _lock:
        items = load()
        items.append(b)
        save(items)


def taken_times(date: str) -> set:
    """Занятые времена на дату (активные записи)."""
    return {b["time"] for b in load() if b["date"] == date and b.get("status") == "active"}


# ---------------------------------------------------------------- хелперы
def service_by_id(sid: str) -> dict | None:
    return next((s for s in C.SERVICES if s["id"] == sid), None)


def grid_times() -> list:
    """Все времена сетки от WORK_FROM до WORK_TO с шагом SLOT_STEP_MIN."""
    out, t = [], datetime(2000, 1, 1, C.WORK_FROM, 0)
    end = datetime(2000, 1, 1, C.WORK_TO, 0)
    while t < end:
        out.append(t.strftime("%H:%M"))
        t += timedelta(minutes=C.SLOT_STEP_MIN)
    return out


def free_times(date: str) -> list:
    """Свободные времена на дату: сетка минус занятые минус прошедшие (если сегодня)."""
    taken = taken_times(date)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    res = []
    for t in grid_times():
        if t in taken:
            continue
        if date == today and datetime.strptime(f"{date} {t}", "%Y-%m-%d %H:%M") <= now:
            continue
        res.append(t)
    return res


def human_date(date: str) -> str:
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{d.strftime('%d.%m')} ({days[d.weekday()]})"


def main_menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📅 Записаться")
    kb.row("📋 Мои записи", "📍 Адрес и контакты")
    return kb


# ---------------------------------------------------------------- команды/меню
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    pending.pop(message.chat.id, None)
    bot.send_message(message.chat.id, C.GREETING, reply_markup=main_menu())


@bot.message_handler(func=lambda m: m.text == "📍 Адрес и контакты")
def m_contacts(message):
    bot.send_message(message.chat.id, C.CONTACTS, reply_markup=main_menu())


# ---------------------------------------------------------------- запись: шаг 1 — услуга
@bot.message_handler(func=lambda m: m.text == "📅 Записаться")
def book_start(message):
    pending.pop(message.chat.id, None)
    kb = types.InlineKeyboardMarkup()
    for s in C.SERVICES:
        kb.add(types.InlineKeyboardButton(
            f"{s['title']} — {s['price']}", callback_data=f"svc:{s['id']}"))
    bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("svc:"))
def cb_service(call):
    sid = call.data.split(":", 1)[1]
    service = service_by_id(sid)
    if not service:
        bot.answer_callback_query(call.id, "Услуга не найдена")
        return
    pending[call.message.chat.id] = {"step": "day", "service": sid}
    kb = types.InlineKeyboardMarkup()
    today = datetime.now()
    for i in range(C.DAYS_AHEAD):
        d = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        label = "Сегодня" if i == 0 else ("Завтра" if i == 1 else human_date(d))
        kb.add(types.InlineKeyboardButton(label, callback_data=f"day:{d}"))
    bot.edit_message_text(f"💈 {service['title']}\n\nВыберите день:",
                          call.message.chat.id, call.message.message_id, reply_markup=kb)


# ---------------------------------------------------------------- запись: шаг 2 — день
@bot.callback_query_handler(func=lambda c: c.data.startswith("day:"))
def cb_day(call):
    date = call.data.split(":", 1)[1]
    state = pending.get(call.message.chat.id)
    if not state:
        bot.answer_callback_query(call.id, "Начните заново: «📅 Записаться»")
        return
    state["date"] = date
    state["step"] = "time"
    slots = free_times(date)
    if not slots:
        bot.answer_callback_query(call.id, "На этот день мест нет — выберите другой")
        return
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(*[types.InlineKeyboardButton(t, callback_data=f"tm:{t}") for t in slots])
    bot.edit_message_text(f"📅 {human_date(date)}\n\nСвободное время:",
                          call.message.chat.id, call.message.message_id, reply_markup=kb)


# ---------------------------------------------------------------- запись: шаг 3 — время
@bot.callback_query_handler(func=lambda c: c.data.startswith("tm:"))
def cb_time(call):
    t = call.data.split(":", 1)[1]
    state = pending.get(call.message.chat.id)
    if not state or "date" not in state:
        bot.answer_callback_query(call.id, "Начните заново: «📅 Записаться»")
        return
    # перепроверяем, что слот ещё свободен (вдруг кто-то успел занять)
    if t not in free_times(state["date"]):
        bot.answer_callback_query(call.id, "Упс, время только что заняли — выберите другое")
        cb_day(call)  # перерисуем доступные слоты
        return
    state["time"] = t
    state["step"] = "name"
    bot.edit_message_text(
        f"✅ {human_date(state['date'])} в {t}\n\nКак вас зовут?",
        call.message.chat.id, call.message.message_id)


# ---------------------------------------------------------------- запись: шаг 4-5 — имя/телефон
@bot.message_handler(func=lambda m: pending.get(m.chat.id, {}).get("step") == "name")
def step_name(message):
    state = pending[message.chat.id]
    state["name"] = message.text.strip()
    state["step"] = "phone"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📲 Отправить мой номер", request_contact=True))
    kb.row("✖️ Отмена")
    bot.send_message(message.chat.id, "Ваш телефон? (или нажмите кнопку ниже)", reply_markup=kb)


@bot.message_handler(content_types=["contact"],
                     func=lambda m: pending.get(m.chat.id, {}).get("step") == "phone")
def step_phone_contact(message):
    _finish(message, message.contact.phone_number)


@bot.message_handler(func=lambda m: pending.get(m.chat.id, {}).get("step") == "phone")
def step_phone_text(message):
    if message.text == "✖️ Отмена":
        pending.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Запись отменена.", reply_markup=main_menu())
        return
    _finish(message, message.text.strip())


def _finish(message, phone: str):
    state = pending.pop(message.chat.id, None)
    if not state:
        return
    service = service_by_id(state["service"])
    # финальная проверка занятости
    if state["time"] not in free_times(state["date"]):
        bot.send_message(message.chat.id,
                         "К сожалению, это время только что заняли. Начните заново: «📅 Записаться».",
                         reply_markup=main_menu())
        return
    user = message.from_user
    booking = {
        "id": uuid.uuid4().hex[:8],
        "chat_id": message.chat.id,
        "service": service["title"],
        "price": service["price"],
        "date": state["date"],
        "time": state["time"],
        "name": state["name"],
        "phone": phone,
        "username": f"@{user.username}" if user.username else f"id{user.id}",
        "status": "active",
        "remind_day": False,
        "remind_soon": False,
    }
    add_booking(booking)

    bot.send_message(
        message.chat.id,
        f"✅ <b>Вы записаны!</b>\n\n"
        f"💈 {service['title']} — {service['price']}\n"
        f"📅 {human_date(state['date'])} в {state['time']}\n"
        f"📍 {C.SALON_NAME}\n\n"
        f"Я напомню о визите заранее. Посмотреть/отменить — «📋 Мои записи».",
        reply_markup=main_menu())

    if ADMIN_CHAT_ID:
        try:
            bot.send_message(
                ADMIN_CHAT_ID,
                f"🔔 <b>Новая запись</b>\n\n"
                f"💈 {service['title']} — {service['price']}\n"
                f"📅 {human_date(state['date'])} в {state['time']}\n"
                f"👤 {booking['name']}\n"
                f"📞 {booking['phone']}\n"
                f"🔗 {booking['username']}")
        except Exception as exc:  # noqa: BLE001
            print("admin notify failed:", exc)


# ---------------------------------------------------------------- мои записи / отмена
@bot.message_handler(func=lambda m: m.text == "📋 Мои записи")
def m_my(message):
    now = datetime.now()
    mine = [b for b in load()
            if b["chat_id"] == message.chat.id and b.get("status") == "active"
            and datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M") >= now]
    if not mine:
        bot.send_message(message.chat.id, "У вас нет активных записей.", reply_markup=main_menu())
        return
    mine.sort(key=lambda b: (b["date"], b["time"]))
    for b in mine:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel:{b['id']}"))
        bot.send_message(
            message.chat.id,
            f"💈 {b['service']}\n📅 {human_date(b['date'])} в {b['time']}",
            reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel:"))
def cb_cancel(call):
    bid = call.data.split(":", 1)[1]
    with _lock:
        items = load()
        target = next((b for b in items if b["id"] == bid
                       and b["chat_id"] == call.message.chat.id), None)
        if not target or target.get("status") != "active":
            bot.answer_callback_query(call.id, "Запись уже отменена")
            return
        target["status"] = "cancelled"
        save(items)
    bot.answer_callback_query(call.id, "Запись отменена")
    bot.edit_message_text(
        f"❌ Отменено: {target['service']}, {human_date(target['date'])} в {target['time']}",
        call.message.chat.id, call.message.message_id)
    if ADMIN_CHAT_ID:
        try:
            bot.send_message(ADMIN_CHAT_ID,
                             f"❌ <b>Отмена записи</b>\n{target['service']} — "
                             f"{human_date(target['date'])} в {target['time']} ({target['name']})")
        except Exception as exc:  # noqa: BLE001
            print("admin notify failed:", exc)


# ---------------------------------------------------------------- напоминания (фон)
def reminder_loop():
    while True:
        try:
            now = datetime.now()
            changed = False
            with _lock:
                items = load()
                for b in items:
                    if b.get("status") != "active":
                        continue
                    when = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
                    delta = when - now
                    # за день (между 23 и 25 часами до визита)
                    if not b.get("remind_day") and timedelta(hours=23) <= delta <= timedelta(hours=25):
                        _safe_send(b["chat_id"], C.REMIND_DAY.format(
                            salon=C.SALON_NAME, service=b["service"],
                            date=human_date(b["date"]), time=b["time"]))
                        b["remind_day"] = True
                        changed = True
                    # за ~2 часа (между 1 и 2 часами до визита)
                    if not b.get("remind_soon") and timedelta(hours=1) <= delta <= timedelta(hours=2):
                        _safe_send(b["chat_id"], C.REMIND_SOON.format(
                            salon=C.SALON_NAME, service=b["service"], time=b["time"]))
                        b["remind_soon"] = True
                        changed = True
                if changed:
                    save(items)
        except Exception as exc:  # noqa: BLE001
            print("reminder loop error:", exc)
        time.sleep(60)


def _safe_send(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except Exception as exc:  # noqa: BLE001
        print("reminder send failed:", exc)


# ---------------------------------------------------------------- запуск
if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("Задай токен: BOT_TOKEN=xxx ADMIN_CHAT_ID=твой_id python bot.py")
    if not ADMIN_CHAT_ID:
        print("⚠️  ADMIN_CHAT_ID не задан — записи не будут пересылаться владельцу.")
    threading.Thread(target=reminder_loop, daemon=True).start()
    print("📅 Бот-запись запущен")
    while True:
        try:
            bot.infinity_polling(skip_pending=False, timeout=30)
        except Exception as exc:  # noqa: BLE001 — никогда не падаем из-за поллинга
            print("polling restart:", exc)
            time.sleep(3)

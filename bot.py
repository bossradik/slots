import os
import random
import sqlite3
import asyncio
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


TOKEN = os.getenv("BOT_TOKEN")
DB = "slots.db"

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]

MULTI = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30
}

BETS = [10, 25, 50, 100]


# =========================
# DATABASE
# =========================

def con():
    return sqlite3.connect(DB)


def init_db():
    c = con()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        name TEXT,
        balance INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best INTEGER DEFAULT 0,
        bet INTEGER DEFAULT 10,
        bonus TEXT DEFAULT '',
        wheel TEXT DEFAULT ''
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS jackpot(
        id INTEGER PRIMARY KEY,
        money INTEGER DEFAULT 5000
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS duels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator INTEGER,
        opponent INTEGER DEFAULT 0,
        bet INTEGER,
        status TEXT DEFAULT 'waiting',
        winner INTEGER DEFAULT 0
    )
    """)

    c.execute(
        "INSERT OR IGNORE INTO jackpot(id,money) VALUES(1,5000)"
    )

    c.commit()
    c.close()


def register(u):
    c = con()

    c.execute(
        "INSERT OR IGNORE INTO users(id,name) VALUES(?,?)",
        (u.id, u.full_name or "Игрок")
    )

    c.execute(
        "UPDATE users SET name=? WHERE id=?",
        (u.full_name or "Игрок", u.id)
    )

    c.commit()
    c.close()


def user(uid):
    c = con()
    r = c.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()
    c.close()
    return r


def update(uid, field, value):
    allowed = {
        "balance",
        "xp",
        "spins",
        "wins",
        "best",
        "bet",
        "bonus",
        "wheel"
    }

    if field not in allowed:
        return

    c = con()

    c.execute(
        f"UPDATE users SET {field}=? WHERE id=?",
        (value, uid)
    )

    c.commit()
    c.close()


def level(uid):
    u = user(uid)
    return u[3] // 100 + 1


def get_jackpot():
    c = con()

    r = c.execute(
        "SELECT money FROM jackpot WHERE id=1"
    ).fetchone()

    c.close()

    return r[0]


def add_jackpot(value):
    c = con()

    c.execute(
        "UPDATE jackpot SET money=money+? WHERE id=1",
        (value,)
    )

    c.commit()
    c.close()


def reset_jackpot():
    c = con()

    c.execute(
        "UPDATE jackpot SET money=5000 WHERE id=1"
    )

    c.commit()
    c.close()


# =========================
# MENUS
# =========================

def menu():
    k = InlineKeyboardBuilder()

    items = [
        ("🎰 Слоты", "game"),
        ("👤 Профиль", "profile"),
        ("🎁 Бонус", "bonus"),
        ("🏆 Топ", "top"),
        ("🔢 Комбинации", "combos"),
        ("⚔️ Дуэли", "duel"),
        ("🎡 Колесо", "wheel"),
        ("📊 Статистика", "stats"),
        ("❓ Помощь", "help")
    ]

    for text, data in items:
        k.button(text=text, callback_data=data)

    k.adjust(2)

    return k.as_markup()


def game_menu(uid):
    u = user(uid)
    bet = u[7]

    k = InlineKeyboardBuilder()

    k.button(
        text=f"🎰 КРУТИТЬ • {bet} 💰",
        callback_data="spin"
    )

    for b in BETS:
        k.button(
            text=f"💰 {b}",
            callback_data=f"bet:{b}"
        )

    k.button(
        text="🔙 Меню",
        callback_data="menu"
    )

    k.adjust(1, 4, 1)

    return k.as_markup()


def duel_menu():
    k = InlineKeyboardBuilder()

    k.button(
        text="⚔️ Создать дуэль",
        callback_data="duel_create"
    )

    k.button(
        text="🔎 Найти соперника",
        callback_data="duel_find"
    )

    k.button(
        text="🔙 Меню",
        callback_data="menu"
    )

    k.adjust(1)

    return k.as_markup()


def duel_bets():
    k = InlineKeyboardBuilder()

    for b in BETS:
        k.button(
            text=f"💰 {b}",
            callback_data=f"duel_bet:{b}"
        )

    k.button(
        text="🔙 Назад",
        callback_data="duel"
    )

    k.adjust(2, 1)

    return k.as_markup()


# =========================
# START / COMMANDS
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    register(message.from_user)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Добро пожаловать!\n\n"
        "💰 Стартовый баланс: 1000\n"
        "⭐ Получай XP за каждую крутку\n"
        "💎 Лови джекпот на 7️⃣7️⃣7️⃣\n"
        "⚔️ Сражайся с другими игроками\n\n"
        "👇 Выбирай:",
        reply_markup=menu()
    )


@dp.message(Command("slots"))
async def slots(message: Message):
    register(message.from_user)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 💰",
        reply_markup=game_menu(message.from_user.id)
    )


@dp.message(Command("balance"))
async def balance(message: Message):
    register(message.from_user)

    u = user(message.from_user.id)

    await message.answer(
        f"💰 Баланс: <b>{u[2]}</b>\n"
        f"⭐ Уровень: <b>{level(u[0])}</b>\n"
        f"✨ XP: <b>{u[3]}</b>"
    )


@dp.message(Command("bonus"))
async def bonus_command(message: Message):
    register(message.from_user)

    uid = message.from_user.id
    u = user(uid)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if u[8] == today:
        await message.answer(
            "🎁 Бонус уже получен сегодня!"
        )
        return

    reward = 100 + level(uid) * 25

    update(
        uid,
        "balance",
        u[2] + reward
    )

    update(
        uid,
        "bonus",
        today
    )

    await message.answer(
        f"🎁 Получено <b>+{reward} 💰</b>"
    )


# =========================
# MAIN MENU
# =========================

@dp.callback_query(F.data == "menu")
async def menu_button(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    await call.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "👇 Выбирай:",
        reply_markup=menu()
    )


@dp.callback_query(F.data == "game")
async def game_button(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    await call.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"🎯 Ставка: <b>{user(call.from_user.id)[7]}</b> 💰\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 💰",
        reply_markup=game_menu(call.from_user.id)
    )


# =========================
# BET
# =========================

@dp.callback_query(F.data.startswith("bet:"))
async def bet_button(call: CallbackQuery):
    register(call.from_user)

    value = int(
        call.data.split(":")[1]
    )

    update(
        call.from_user.id,
        "bet",
        value
    )

    await call.answer(
        f"Ставка {value} 💰"
    )

    await call.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"🎯 Ставка: <b>{value}</b> 💰\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 💰",
        reply_markup=game_menu(call.from_user.id)
    )


# =========================
# SPIN
# =========================

@dp.callback_query(F.data == "spin")
async def spin(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)
    bet = u[7]

    if u[2] < bet:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    update(
        uid,
        "balance",
        u[2] - bet
    )

    update(
        uid,
        "spins",
        u[4] + 1
    )

    update(
        uid,
        "xp",
        u[3] + 10
    )

    await call.answer()

    await call.message.edit_text(
        "🎰 <b>КРУТИМ...</b>\n\n"
        "❓ | ❓ | ❓"
    )

    await asyncio.sleep(0.3)

    result = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    await call.message.edit_text(
        "🎰 <b>КРУТИМ...</b>\n\n"
        f"{result[0]} | ❓ | ❓"
    )

    await asyncio.sleep(0.3)

    await call.message.edit_text(
        "🎰 <b>КРУТИМ...</b>\n\n"
        f"{result[0]} | {result[1]} | ❓"
    )

    await asyncio.sleep(0.3)

    win = 0
    jackpot_win = False

    if result[0] == result[1] == result[2] == "7️⃣":
        win = get_jackpot()
        reset_jackpot()
        jackpot_win = True

    elif result[0] == result[1] == result[2]:
        win = bet * MULTI[result[0]]

    elif (
        result[0] == result[1]
        or result[0] == result[2]
        or result[1] == result[2]
    ):
        win = bet * 2

    else:
        add_jackpot(
            max(1, bet // 10)
        )

    if win:
        now = user(uid)

        update(
            uid,
            "balance",
            now[2] + win
        )

        update(
            uid,
            "wins",
            now[5] + 1
        )

        if win > now[6]:
            update(
                uid,
                "best",
                win
            )

    now = user(uid)

    if jackpot_win:
        result_text = (
            f"💎💎💎 <b>ДЖЕКПОТ!</b>\n"
            f"💰 +{win}"
        )

    elif win:
        result_text = (
            f"🎉 <b>Выигрыш +{win} 💰</b>"
        )

    else:
        result_text = (
            f"😢 Проигрыш -{bet} 💰"
        )

    await call.message.edit_text(
        "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
        f"{result[0]} | {result[1]} | {result[2]}\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{now[2]}</b>\n"
        f"⭐ Уровень: <b>{level(uid)}</b>\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b>",
        reply_markup=game_menu(uid)
    )


# =========================
# PROFILE
# =========================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    u = user(call.from_user.id)

    await call.message.edit_text(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 {u[1]}\n"
        f"💰 Баланс: <b>{u[2]}</b>\n"
        f"⭐ Уровень: <b>{level(u[0])}</b>\n"
        f"✨ XP: <b>{u[3]}</b>\n"
        f"🎰 Круток: <b>{u[4]}</b>\n"
        f"🏆 Побед: <b>{u[5]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[6]}</b>",
        reply_markup=menu()
    )


# =========================
# BONUS
# =========================

@dp.callback_query(F.data == "bonus")
async def bonus(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if u[8] == today:
        await call.answer(
            "🎁 Бонус уже получен сегодня!",
            show_alert=True
        )
        return

    reward = 100 + level(uid) * 25

    update(
        uid,
        "balance",
        u[2] + reward
    )

    update(
        uid,
        "bonus",
        today
    )

    await call.answer(
        f"🎁 +{reward} 💰"
    )

    await call.message.edit_text(
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"💰 Получено: <b>+{reward}</b>\n\n"
        "Возвращайся завтра!",
        reply_markup=menu()
    )


# =========================
# TOP
# =========================

@dp.callback_query(F.data == "top")
async def top(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    c = con()

    rows = c.execute(
        """
        SELECT name,balance,wins
        FROM users
        ORDER BY balance DESC
        LIMIT 10
        """
    ).fetchall()

    c.close()

    text = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += (
            f"<b>{i}.</b> {row[0]} — "
            f"{row[1]} 💰 | {row[2]} 🏆\n"
        )

    await call.message.edit_text(
        text,
        reply_markup=menu()
    )


# =========================
# COMBINATIONS
# =========================

@dp.callback_query(F.data == "combos")
async def combos(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    await call.message.edit_text(
        "🔢 <b>КОМБИНАЦИИ</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — 💎 ДЖЕКПОТ\n\n"
        "Любые 2 одинаковых — x2",
        reply_markup=menu()
    )


# =========================
# STATS
# =========================

@dp.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    u = user(call.from_user.id)

    await call.message.edit_text(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎰 Круток: <b>{u[4]}</b>\n"
        f"🏆 Побед: <b>{u[5]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[6]}</b>\n"
        f"✨ XP: <b>{u[3]}</b>\n"
        f"⭐ Уровень: <b>{level(u[0])}</b>",
        reply_markup=menu()
    )


# =========================
# WHEEL
# =========================

@dp.callback_query(F.data == "wheel")
async def wheel(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if u[9] == today:
        await call.answer(
            "🎡 Колесо уже использовано сегодня!",
            show_alert=True
        )
        return

    reward = random.choice(
        [25, 50, 100, 150, 250, 500, 1000, 5000]
    )

    update(
        uid,
        "balance",
        u[2] + reward
    )

    update(
        uid,
        "wheel",
        today
    )

    await call.answer(
        f"🎡 +{reward} 💰"
    )

    await call.message.edit_text(
        "🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
        f"🎉 Ты получил <b>+{reward} 💰</b>",
        reply_markup=menu()
    )


# =========================
# ⚔️ DUELS
# =========================

@dp.callback_query(F.data == "duel")
async def duel(call: CallbackQuery):
    register(call.from_user)

    await call.answer()

    await call.message.edit_text(
        "⚔️ <b>ДУЭЛИ</b>\n\n"
        "Сразись с другим игроком за монеты!\n\n"
        "🏆 Победитель получает весь банк.\n"
        "💰 Ставки: 10 / 25 / 50 / 100\n\n"
        "Выбирай:",
        reply_markup=duel_menu()
    )


@dp.callback_query(F.data == "duel_create")
async def duel_create(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    c = con()

    active = c.execute(
        """
        SELECT id
        FROM duels
        WHERE creator=?
        AND status='waiting'
        """,
        (uid,)
    ).fetchone()

    c.close()

    if active:
        await call.answer(
            "❌ У тебя уже есть активная дуэль!",
            show_alert=True
        )
        return

    await call.answer()

    await call.message.edit_text(
        "⚔️ <b>СОЗДАНИЕ ДУЭЛИ</b>\n\n"
        f"💰 Твой баланс: <b>{u[2]}</b>\n\n"
        "Выбери ставку:",
        reply_markup=duel_bets()
    )


@dp.callback_query(F.data.startswith("duel_bet:"))
async def duel_bet(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    bet = int(call.data.split(":")[1])

    if bet not in BETS:
        await call.answer(
            "❌ Неверная ставка!",
            show_alert=True
        )
        return

    u = user(uid)

    if u[2] < bet:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    c = con()

    active = c.execute(
        """
        SELECT id
        FROM duels
        WHERE creator=?
        AND status='waiting'
        """,
        (uid,)
    ).fetchone()

    if active:
        c.close()

        await call.answer(
            "❌ У тебя уже есть дуэль!",
            show_alert=True
        )
        return

    c.execute(
        """
        INSERT INTO duels(creator,bet,status)
        VALUES(?,?,?)
        """,
        (uid, bet, "waiting")
    )

    duel_id = c.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    c.commit()
    c.close()

    update(
        uid,
        "balance",
        u[2] - bet
    )

    k = InlineKeyboardBuilder()

    k.button(
        text="🔎 Найти соперника",
        callback_data="duel_find"
    )

    k.button(
        text="❌ Отменить",
        callback_data=f"duel_cancel:{duel_id}"
    )

    k.adjust(1)

    await call.answer(
        "⚔️ Дуэль создана!"
    )

    await call.message.edit_text(
        "⚔️ <b>ДУЭЛЬ СОЗДАНА!</b>\n\n"
        f"💰 Твоя ставка: <b>{bet}</b>\n"
        "⏳ Ждём соперника...\n\n"
        "Когда другой игрок найдёт твою дуэль,\n"
        "битва начнётся автоматически.",
        reply_markup=k.as_markup()
    )


@dp.callback_query(F.data == "duel_find")
async def duel_find(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    c = con()

    d = c.execute(
        """
        SELECT id,creator,bet
        FROM duels
        WHERE status='waiting'
        AND creator!=?
        ORDER BY id ASC
        LIMIT 1
        """,
        (uid,)
    ).fetchone()

    c.close()

    if not d:
        await call.answer(
            "⏳ Сейчас нет доступных дуэлей.",
            show_alert=True
        )
        return

    duel_id = d[0]
    creator = d[1]
    bet = d[2]

    if u[2] < bet:
        await call.answer(
            f"❌ Нужно {bet} 💰",
            show_alert=True
        )
        return

    update(
        uid,
        "balance",
        u[2] - bet
    )

    c = con()

    c.execute(
        """
        UPDATE duels
        SET opponent=?,status='playing'
        WHERE id=? AND status='waiting'
        """,
        (uid, duel_id)
    )

    c.commit()
    c.close()

    winner = random.choice(
        [creator, uid]
    )

    total = bet * 2

    wu = user(winner)

    update(
        winner,
        "balance",
        wu[2] + total
    )

    c = con()

    c.execute(
        """
        UPDATE duels
        SET status='finished',winner=?
        WHERE id=?
        """,
        (winner, duel_id)
    )

    c.commit()
    c.close()

    if winner == uid:
        text = (
            "🏆 <b>ТЫ ПОБЕДИЛ!</b>\n\n"
            f"💰 Твоя ставка: {bet}\n"
            f"🏦 Банк: <b>{total} 💰</b>\n"
            f"🎉 Тебе: <b>+{total} 💰</b>"
        )
    else:
        text = (
            "💀 <b>ТЫ ПРОИГРАЛ!</b>\n\n"
            f"💰 Твоя ставка: {bet}\n"
            f"🏦 Банк: <b>{total} 💰</b>\n"
            "😢 Победил соперник."
        )

    await call.answer(
        "🏆 Победа!" if winner == uid else "💀 Поражение!",
        show_alert=True
    )

    await call.message.edit_text(
        "⚔️ <b>РЕЗУЛЬТАТ ДУЭЛИ</b>\n\n"
        f"🎲 Ставка: <b>{bet} 💰</b>\n"
        f"🏦 Банк: <b>{total} 💰</b>\n\n"
        f"{text}\n\n"
        "⚔️ Можешь сразу сыграть ещё.",
        reply_markup=duel_menu()
    )


@dp.callback_query(F.data.startswith("duel_cancel:"))
async def duel_cancel(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    duel_id = int(
        call.data.split(":")[1]
    )

    c = con()

    d = c.execute(
        """
        SELECT bet
        FROM duels
        WHERE id=? AND creator=? AND status='waiting'
        """,
        (duel_id, uid)
    ).fetchone()

    c.close()

    if not d:
        await call.answer(
            "❌ Дуэль уже недоступна.",
            show_alert=True
        )
        return

    bet = d[0]
    u = user(uid)

    update(
        uid,
        "balance",
        u[2] + bet
    

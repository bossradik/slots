import os
import sqlite3
import random
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
DB_NAME = "slots.db"

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]

MULTIPLIERS = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30,
    "7️⃣": 100
}

BETS = [10, 25, 50, 100]


def connect():
    return sqlite3.connect(DB_NAME)


def init_db():
    con = connect()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            name TEXT DEFAULT '',
            balance INTEGER DEFAULT 1000,
            xp INTEGER DEFAULT 0,
            spins INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            best_win INTEGER DEFAULT 0,
            bet INTEGER DEFAULT 10,
            bonus_day TEXT DEFAULT '',
            wheel_day TEXT DEFAULT '',
            mission_spins INTEGER DEFAULT 0,
            mission_wins INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            spins INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_users (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user1 INTEGER,
            user2 INTEGER DEFAULT 0,
            bet INTEGER,
            status TEXT DEFAULT 'waiting'
        )
    """)

    con.commit()
    con.close()


def register_user(user, chat=None):
    con = connect()
    cur = con.cursor()

    username = user.username or ""
    name = user.full_name or "Игрок"

    cur.execute(
        """
        INSERT OR IGNORE INTO users
        (id, username, name)
        VALUES (?, ?, ?)
        """,
        (user.id, username, name)
    )

    cur.execute(
        """
        UPDATE users
        SET username=?, name=?
        WHERE id=?
        """,
        (username, name, user.id)
    )

    if chat:
        cur.execute(
            """
            INSERT OR IGNORE INTO chats
            (id, title)
            VALUES (?, ?)
            """,
            (chat.id, chat.title or "Группа")
        )

        cur.execute(
            """
            INSERT OR IGNORE INTO chat_users
            (chat_id, user_id)
            VALUES (?, ?)
            """,
            (chat.id, user.id)
        )

    con.commit()
    con.close()


def get_user(user_id):
    con = connect()

    row = con.execute(
        """
        SELECT
            id,
            username,
            name,
            balance,
            xp,
            spins,
            wins,
            best_win,
            bet,
            bonus_day,
            wheel_day,
            mission_spins,
            mission_wins
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    con.close()
    return row


def set_value(user_id, field, value):
    allowed = {
        "balance",
        "xp",
        "spins",
        "wins",
        "best_win",
        "bet",
        "bonus_day",
        "wheel_day",
        "mission_spins",
        "mission_wins"
    }

    if field not in allowed:
        return

    con = connect()

    con.execute(
        f"UPDATE users SET {field}=? WHERE id=?",
        (value, user_id)
    )

    con.commit()
    con.close()


def add_value(user_id, field, amount):
    user = get_user(user_id)

    if not user:
        return

    current = user[3]

    if field == "balance":
        current = user[3]
    elif field == "xp":
        current = user[4]
    elif field == "spins":
        current = user[5]
    elif field == "wins":
        current = user[6]
    elif field == "best_win":
        current = user[7]
    elif field == "mission_spins":
        current = user[11]
    elif field == "mission_wins":
        current = user[12]
    else:
        return

    set_value(user_id, field, current + amount)


def get_level(user_id):
    user = get_user(user_id)

    if not user:
        return 1

    return user[4] // 100 + 1


def main_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🎰 Слоты",
        callback_data="game"
    )

    kb.button(
        text="👤 Профиль",
        callback_data="profile"
    )

    kb.button(
        text="🏆 Топ",
        callback_data="top"
    )

    kb.button(
        text="🔢 Комбинации",
        callback_data="combos"
    )

    kb.button(
        text="🎲 Дуэль",
        callback_data="duel"
    )

    kb.button(
        text="📋 Миссии",
        callback_data="missions"
    )

    kb.button(
        text="🎡 Колесо",
        callback_data="wheel"
    )

    kb.button(
        text="👥 Группа",
        callback_data="group"
    )

    kb.button(
        text="🏅 Достижения",
        callback_data="achievements"
    )

    kb.button(
        text="📊 Статистика",
        callback_data="stats"
    )

    kb.button(
        text="❓ Помощь",
        callback_data="help"
    )

    kb.adjust(2)

    return kb.as_markup()


def game_keyboard(user_id):
    user = get_user(user_id)

    bet = user[8] if user else 10

    kb = InlineKeyboardBuilder()

    kb.button(
        text=f"🎰 КРУТИТЬ • {bet} 💰",
        callback_data="spin"
    )

    for value in BETS:
        kb.button(
            text=f"💰 {value}",
            callback_data=f"bet:{value}"
        )

    kb.button(
        text="🔙 Меню",
        callback_data="menu"
    )

    kb.adjust(1, 4, 1)

    return kb.as_markup()


async def show_game(message, user_id):
    user = get_user(user_id)

    if not user:
        return

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{get_level(user_id)}</b>\n"
        f"✨ XP: <b>{user[4]}</b>\n"
        f"🎯 Ставка: <b>{user[8]} 💰</b>\n\n"
        "Выбери ставку или сразу крути."
    )

    await message.edit_text(
        text,
        reply_markup=game_keyboard(user_id)
    )


@dp.message(CommandStart())
async def start_handler(message: Message):
    register_user(
        message.from_user,
        message.chat
    )

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Добро пожаловать!\n"
        "Крути слоты, выигрывай монеты,\n"
        "повышай уровень и попадай в топ.\n\n"
        "👇 Выбирай действие:",
        reply_markup=main_keyboard()
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    register_user(
        message.from_user,
        message.chat
    )

    await message.answer(
        "❓ <b>ПОМОЩЬ</b>\n\n"
        "/start — главное меню\n"
        "/slots — открыть слоты\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/profile — профиль\n"
        "/top — топ игроков\n"
        "/stats — статистика\n"
        "/group — статистика группы\n"
        "/pay 100 — перевод ответом\n"
        "/duel 100 — дуэль\n"
        "/wheel — колесо\n"
        "/missions — миссии"
    )


@dp.message(Command("slots"))
async def slots_handler(message: Message):
    register_user(
        message.from_user,
        message.chat
    )

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Ставка сохраняется.\n"
        "После результата можно сразу "
        "нажать «КРУТИТЬ ЕЩЁ».",
        reply_markup=game_keyboard(
            message.from_user.id
        )
    )


@dp.message(Command("balance"))
async def balance_handler(message: Message):
    register_user(
        message.from_user,
        message.chat
    )

    user = get_user(
        message.from_user.id
    )

    await message.answer(
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{get_level(user[0])}</b>\n"
        f"✨ XP: <b>{user[4]}</b>"
    )


@dp.message(Command("profile"))
async def profile_handler(message: Message):
    register_user(
        message.from_user,
        message.chat
    )

    await send_profile(
        message,
        message.from_user.id
    )


async def send_profile(message, user_id):
    user = get_user(user_id)

    if not user:
        return

    await message.answer(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Имя: <b>{user[2]}</b>\n"
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{get_level(user_id)}</b>\n"
        f"✨ XP: <b>{user[4]}</b>\n\n"
        f"🎰 Круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>\n"
        f"🎯 Ставка: <b>{user[8]} 💰</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "menu")
async def menu_callback(call: CallbackQuery):
    register_user(
        call.from_user,
        call.message.chat
    )

    await call.answer()

    await call.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "👇 Выбирай действие:",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "game")
async def game_callback(call: CallbackQuery):
    register_user(
        call.from_user,
        call.message.chat
    )

    await call.answer()

    await show_game(
        call.message,
        call.from_user.id
    )


@dp.callback_query(F.data.startswith("bet:"))
async def bet_callback(call: CallbackQuery):
    register_user(
        call.from_user,
        call.message.chat
    )

    bet = int(
        call.data.split(":")[1]
    )

    set_value(
        call.from_user.id,
        "bet",
        bet
    )

    await call.answer(
        f"Ставка установлена: {bet} 💰"
    )

    await show_game(
        call.message,
        call.from_user.id
    )


def make_spin():
    return [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]


def calculate_win(result, bet):
    a, b, c = result

    if a == b == c:
        return bet * MULTIPLIERS[a]

    if a == b or a == c or b == c:
        return bet * 2

    return 0


async def spin_animation(message):
    frames = [
        "🎰 <b>КРУТИМ...</b>\n\n"
        "❓ | ❓ | ❓",

        "🎰 <b>КРУТИМ...</b>\n\n"
        "🍒 | ❓ | ❓",

        "🎰 <b>КРУТИМ...</b>\n\n"
        "🍒 | 🔔 | ❓",

        "🎰 <b>КРУТИМ...</b>\n\n"
        "🍒 | 🔔 | 💎"
    ]

    for frame in frames:
        try:
            await message.edit_text(frame)
        except Exception:
            pass

        await asyncio.sleep(0.25)


@dp.callback_query(F.data == "spin")
async def spin_callback(call: CallbackQuery):
    register_user(
        call.from_user,
        call.message.chat
    )

    user_id = call.from_user.id
    user = get_user(user_id)

    bet = user[8]

    if user[3] < bet:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    set_value(
        user_id,
        "balance",
        user[3] - bet
    )

    add_value(
        user_id,
        "spins",
        1
    )

    add_value(
        user_id,
        "xp",
        10
    )

    add_value(
        user_id,
        "mission_spins",
        1
    )

    await call.answer()

    await spin_animation(
        call.message
    )

    result = make_spin()
    win = calculate_win(
        result,
        bet
    )

    if win > 0:
        current = get_user(user_id)

        set_value(
            user_id,
            "balance",
            current[3] + win
        )

        add_value(
            user_id,
            "wins",
            1
        )

        add_value(
            user_id,
            "mission_wins",
            1
        )

        current = get_user(user_id)

        if win > current[7]:
            set_value(
                user_id,
                "best_win",
                win
            )

        if (
            result[0] ==
            result[1] ==
            result[2] ==
            "7️⃣"
        ):
            result_text = (
                "💎💎💎 <b>ДЖЕКПОТ!</b> 💎💎💎"
            )
        else:
            result_text = (
                f"🎉 <b>Выигрыш: +{win} 💰</b>"
            )

    else:
        result_text = (
            f"😢 Проигрыш: -{bet} 💰"
        )

    current = get_user(user_id)

    text = (
        "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
        f"{result[0]} | {result[1]} | {result[2]}\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{current[3]}</b>\n"
        f"⭐ Уровень: <b>{get_level(user_id)}</b>"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text=f"🎰 КРУТИТЬ ЕЩЁ • {bet} 💰",
        callback_data="spin"
    )

    kb.button(
        text="🎯 Изменить ставку",
        callback_data="game"
    )

    kb.button(
        text="🔙 Меню",
        callback_data="menu"
    )

    kb.adjust(1)

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )
    @dp.callback_query(F.data == "profile")
async def profile_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()
    user = get_user(call.from_user.id)

    await call.message.edit_text(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Имя: <b>{user[2]}</b>\n"
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{get_level(user[0])}</b>\n"
        f"✨ XP: <b>{user[4]}</b>\n"
        f"🎰 Круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>\n"
        f"🎯 Ставка: <b>{user[8]} 💰</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "combos")
async def combos_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    text = (
        "🔢 <b>КОМБИНАЦИИ</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — x100 💎\n\n"
        "Любые 2 одинаковых — x2"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("bonus"))
async def bonus_handler(message: Message):
    register_user(message.from_user, message.chat)

    user = get_user(message.from_user.id)
    today = datetime.now(timezone.utc).date().isoformat()

    if user[9] == today:
        await message.answer(
            "🎁 <b>Бонус уже получен сегодня!</b>\n\n"
            "Возвращайся завтра."
        )
        return

    level = get_level(message.from_user.id)
    reward = 100 + level * 25

    set_value(
        message.from_user.id,
        "balance",
        user[3] + reward
    )

    set_value(
        message.from_user.id,
        "bonus_day",
        today
    )

    await message.answer(
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"💰 Получено: <b>+{reward}</b>\n"
        f"⭐ Уровень: <b>{level}</b>"
    )


@dp.callback_query(F.data == "missions")
async def missions_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    user = get_user(call.from_user.id)

    spins = user[11]
    wins = user[12]

    text = (
        "📋 <b>МИССИИ</b>\n\n"
        f"🎰 Сделать 10 круток: "
        f"<b>{min(spins, 10)}/10</b>\n"
        f"🏆 Получить 3 победы: "
        f"<b>{min(wins, 3)}/3</b>\n\n"
        "Награды за выполнение миссий будут "
        "добавлены в следующем обновлении."
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("missions"))
async def missions_handler(message: Message):
    register_user(message.from_user, message.chat)

    user = get_user(message.from_user.id)

    await message.answer(
        "📋 <b>МИССИИ</b>\n\n"
        f"🎰 Крутки: <b>{min(user[11], 10)}/10</b>\n"
        f"🏆 Победы: <b>{min(user[12], 3)}/3</b>"
    )


@dp.callback_query(F.data == "top")
async def top_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    con = connect()

    rows = con.execute(
        """
        SELECT name, balance, wins, best_win
        FROM users
        ORDER BY balance DESC
        LIMIT 10
        """
    ).fetchall()

    con.close()

    text = "🏆 <b>ТОП ШАХТЁРОВ СЛОТОВ</b>\n\n"

    if not rows:
        text += "Пока игроков нет."
    else:
        for i, row in enumerate(rows, 1):
            name = row[0] or "Игрок"

            text += (
                f"<b>{i}.</b> {name}\n"
                f"💰 {row[1]} | 🏆 {row[2]} побед\n"
            )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("top"))
async def top_handler(message: Message):
    register_user(message.from_user, message.chat)

    con = connect()

    rows = con.execute(
        """
        SELECT name, balance, wins
        FROM users
        ORDER BY balance DESC
        LIMIT 10
        """
    ).fetchall()

    con.close()

    text = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += (
            f"{i}. {row[0] or 'Игрок'} — "
            f"{row[1]} 💰 — {row[2]} побед\n"
        )

    await message.answer(text)


@dp.callback_query(F.data == "achievements")
async def achievements_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    user = get_user(call.from_user.id)

    achievements = []

    if user[5] >= 10:
        achievements.append("🎰 10 круток")

    if user[5] >= 100:
        achievements.append("🔥 100 круток")

    if user[6] >= 10:
        achievements.append("🏆 10 побед")

    if user[7] >= 1000:
        achievements.append("💎 Выигрыш 1000+")

    if user[4] >= 1000:
        achievements.append("⭐ 1000 XP")

    if not achievements:
        achievements.append("🔒 Пока достижений нет")

    text = (
        "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"
        + "\n".join(achievements)
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "stats")
async def stats_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    user = get_user(call.from_user.id)

    text = (
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎰 Всего круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>\n"
        f"⭐ XP: <b>{user[4]}</b>\n"
        f"📈 Уровень: <b>{get_level(user[0])}</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("stats"))
async def stats_handler(message: Message):
    register_user(message.from_user, message.chat)

    user = get_user(message.from_user.id)

    await message.answer(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎰 Круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>\n"
        f"⭐ XP: <b>{user[4]}</b>\n"
        f"📈 Уровень: <b>{get_level(user[0])}</b>"
    )


@dp.callback_query(F.data == "help")
async def help_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    text = (
        "❓ <b>ПОМОЩЬ</b>\n\n"
        "🎰 Слоты — игра\n"
        "👤 Профиль — твои данные\n"
        "🏆 Топ — рейтинг игроков\n"
        "🔢 Комбинации — таблица выигрышей\n"
        "📋 Миссии — задания\n"
        "🎡 Колесо — ежедневное колесо\n"
        "👥 Группа — статистика группы\n"
        "🏅 Достижения — награды\n"
        "📊 Статистика — твоя статистика\n\n"
        "💰 Баланс сохраняется в базе данных."
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("wheel"))
async def wheel_handler(message: Message):
    register_user(message.from_user, message.chat)

    user = get_user(message.from_user.id)
    today = datetime.now(timezone.utc).date().isoformat()

    if user[10] == today:
        await message.answer(
            "🎡 <b>Колесо уже использовано сегодня!</b>"
        )
        return

    rewards = [25, 50, 100, 150, 250, 500]
    reward = random.choice(rewards)

    set_value(
        message.from_user.id,
        "balance",
        user[3] + reward
    )

    set_value(
        message.from_user.id,
        "wheel_day",
        today
    )

    await message.answer(
        "🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
        "🎰 Колесо вращается...\n"
        "⬇️\n"
        f"🎉 Тебе выпало: <b>+{reward} 💰</b>"
    )


@dp.callback_query(F.data == "wheel")
async def wheel_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    user = get_user(call.from_user.id)
    today = datetime.now(timezone.utc).date().isoformat()

    if user[10] == today:
        text = (
            "🎡 <b>КОЛЕСО</b>\n\n"
            "❌ Сегодня ты уже крутил колесо.\n"
            "Возвращайся завтра."
        )
    else:
        rewards = [25, 50, 100, 150, 250, 500]
        reward = random.choice(rewards)

        set_value(
            call.from_user.id,
            "balance",
            user[3] + reward
        )

        set_value(
            call.from_user.id,
            "wheel_day",
            today
        )

        text = (
            "🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
            "🎰 Колесо вращается...\n\n"
            f"🎉 Выпало: <b>+{reward} 💰</b>"
        )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "group")
async def group_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    chat_id = call.message.chat.id

    con = connect()

    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(u.spins), 0),
        COALESCE(SUM(u.wins), 0)
        FROM chat_users cu
        JOIN users u ON u.id = cu.user_id
        WHERE cu.chat_id=?
        """,
        (chat_id,)
    ).fetchone()

    con.close()

    members = row[0] or 0
    spins = row[1] or 0
    wins = row[2] or 0

    text = (
        "👥 <b>СТАТИСТИКА ГРУППЫ</b>\n\n"
        f"👤 Игроков: <b>{members}</b>\n"
        f"🎰 Круток: <b>{spins}</b>\n"
        f"🏆 Побед: <b>{wins}</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Меню", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("group"))
async def group_handler(message: Message):
    register_user(message.from_user, message.chat)

    chat_id = message.chat.id

    con = connect()

    row = con.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(u.spins), 0),
        COALESCE(SUM(u.wins), 0)
        FROM chat_users cu
        JOIN users u ON u.id = cu.user_id
        WHERE cu.chat_id=?
        """,
        (chat_id,)
    ).fetchone()

    con.close()

    await message.answer(
        "👥 <b>СТАТИСТИКА ГРУППЫ</b>\n\n"
        f"👤 Игроков: <b>{row[0] or 0}</b>\n"
        f"🎰 Круток: <b>{row[1] or 0}</b>\n"
        f"🏆 Побед: <b>{row[2] or 0}</b>"
    )


@dp.message(Command("pay"))
async def pay_handler(message: Message):
    register_user(message.from_user, message.chat)

    if not message.reply_to_message:
        await message.answer(
            "💰 Использование:\n"
            "<code>/pay 100</code>\n"
            "ответом на сообщение игрока."
        )
        return

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "❌ Укажи сумму.\n"
            "Пример: <code>/pay 100</code>"
        )
        return

    amount = int(parts[1])

    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше нуля.")
        return

    sender = get_user(message.from_user.id)
    receiver_id = message.reply_to_message.from_user.id

    if receiver_id == message.from_user.id:
        await message.answer("❌ Нельзя переводить самому себе.")
        return

    receiver = get_user(receiver_id)

    if not receiver:
        register_user(
            message.reply_to_message.from_user,
            message.chat
        )
        receiver = get_user(receiver_id)

    if sender[3] < amount:
        await message.answer("❌ Недостаточно монет.")
        return

    set_value(
        message.from_user.id,
        "balance",
        sender[3] - amount
    )

    set_value(
        receiver_id,
        "balance",
        receiver[3] + amount
    )

    await message.answer(
        "💸 <b>Перевод выполнен!</b>\n\n"
        f"👤 Получатель: <b>{receiver[2]}</b>\n"
        f"💰 Сумма: <b>{amount}</b>"
    )


@dp.message(Command("duel"))
async def duel_handler(message: Message):
    register_user(message.from_user, message.chat)

    if not message.reply_to_message:
        await message.answer(
            "🎲 Чтобы начать дуэль, ответь на сообщение игрока:\n"
            "<code>/duel 100</code>"
        )
        return

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "❌ Пример: <code>/duel 100</code>"
        )
        return

    bet = int(parts[1])

    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше нуля.")
        return

    user1 = get_user(message.from_user.id)
    opponent_id = message.reply_to_message.from_user.id

    if opponent_id == message.from_user.id:
        await message.answer("❌ Нельзя вызвать себя.")
        return

    user2 = get_user(opponent_id)

    if not user2:
        register_user(
            message.reply_to_message.from_user,
            message.chat
        )
        user2 = get_user(opponent_id)

    if user1[3] < bet:
        await message.answer("❌ У тебя недостаточно монет.")
        return

    if user2[3] < bet:
        await message.answer("❌ У соперника недостаточно монет.")
        return

    winner_id = random.choice(
        [message.from_user.id, opponent_id]
    )

    loser_id = (
        opponent_id
        if winner_id == message.from_user.id
        else message.from_user.id
    )

    winner = get_user(winner_id)
    loser = get_user(loser_id)

    set_value(
        winner_id,
        "balance",
        winner[3] + bet
    )

    set_value(
        loser_id,
        "balance",
        loser[3] - bet
    )

    winner_name = winner[2] or "Игрок"

    await message.answer(
        "🎲 <b>ДУЭЛЬ</b>\n\n"
        f"🏆 Победитель: <b>{winner_name}</b>\n"
        f"💰 Выигрыш: <b>+{bet}</b>"
    )


@dp.callback_query(F.data == "duel")
async def duel_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    await call.message.edit_text(
        "🎲 <b>ДУЭЛЬ</b>\n\n"
        "Чтобы вызвать игрока на дуэль,\n"
        "ответь на его сообщение командой:\n\n"
        "<code>/duel 100</code>\n\n"
        "Ставка указывается после команды.",
        reply_markup=main_keyboard()
    )


@dp.errors()
async def error_handler(event):
    try:
        print("BOT ERROR:", event.exception)
    except Exception:
        pass


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.getenv("PORT", "10000"))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(f"0.0.0.0:{port}")

    server.serve_forever()


async def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set"
        )

    init_db()

    threading.Thread(
        target=run_health_server,
        daemon=True
    ).start()

    print("BOT STARTED")

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

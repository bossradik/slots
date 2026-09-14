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

SYMBOLS = [
    "🍒",
    "🍋",
    "🍊",
    "🔔",
    "💎",
    "7️⃣"
]

MULTIPLIERS = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30
}

BETS = [10, 25, 50, 100]


def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    con = db()

    con.execute("""
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

    con.execute("""
        CREATE TABLE IF NOT EXISTS jackpot (
            id INTEGER PRIMARY KEY,
            amount INTEGER DEFAULT 5000
        )
    """)

    con.execute(
        "INSERT OR IGNORE INTO jackpot (id, amount) VALUES (1, 5000)"
    )

    con.commit()
    con.close()


def register_user(user):
    con = db()

    con.execute(
        """
        INSERT OR IGNORE INTO users
        (id, username, name)
        VALUES (?, ?, ?)
        """,
        (
            user.id,
            user.username or "",
            user.full_name or "Игрок"
        )
    )

    con.execute(
        """
        UPDATE users
        SET username=?, name=?
        WHERE id=?
        """,
        (
            user.username or "",
            user.full_name or "Игрок",
            user.id
        )
    )

    con.commit()
    con.close()


def get_user(user_id):
    con = db()

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

    con = db()

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

    indexes = {
        "balance": 3,
        "xp": 4,
        "spins": 5,
        "wins": 6,
        "best_win": 7,
        "mission_spins": 11,
        "mission_wins": 12
    }

    if field not in indexes:
        return

    current = user[indexes[field]]

    set_value(
        user_id,
        field,
        current + amount
    )


def level(user_id):
    user = get_user(user_id)

    if not user:
        return 1

    return user[4] // 100 + 1


def jackpot():
    con = db()

    row = con.execute(
        "SELECT amount FROM jackpot WHERE id=1"
    ).fetchone()

    con.close()

    return row[0]


def add_jackpot(amount):
    con = db()

    con.execute(
        """
        UPDATE jackpot
        SET amount=amount+?
        WHERE id=1
        """,
        (amount,)
    )

    con.commit()
    con.close()


def reset_jackpot():
    con = db()

    con.execute(
        "UPDATE jackpot SET amount=5000 WHERE id=1"
    )

    con.commit()
    con.close()


def main_keyboard():
    kb = InlineKeyboardBuilder()

    buttons = [
        ("🎰 Слоты", "game"),
        ("👤 Профиль", "profile"),
        ("🎁 Бонус", "bonus"),
        ("🏆 Топ", "top"),
        ("🔢 Комбинации", "combos"),
        ("🎲 Дуэль", "duel"),
        ("📋 Миссии", "missions"),
        ("🎡 Колесо", "wheel"),
        ("🏅 Достижения", "achievements"),
        ("📊 Статистика", "stats"),
        ("❓ Помощь", "help")
    ]

    for text, data in buttons:
        kb.button(
            text=text,
            callback_data=data
        )

    kb.adjust(2)

    return kb.as_markup()


def game_keyboard(user_id):
    user = get_user(user_id)

    bet = user[8]

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
        f"⭐ Уровень: <b>{level(user_id)}</b>\n"
        f"✨ XP: <b>{user[4]}</b>\n"
        f"🎯 Ставка: <b>{user[8]} 💰</b>\n"
        f"💎 Джекпот: <b>{jackpot()} 💰</b>\n\n"
        "Выбери ставку или крути."
    )

    await message.edit_text(
        text,
        reply_markup=game_keyboard(user_id)
    )


@dp.message(CommandStart())
async def start(message: Message):
    register_user(message.from_user)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Добро пожаловать!\n\n"
        "Крути слоты, выигрывай 💰,\n"
        "повышай уровень и попадай в топ.\n\n"
        "👇 Выбирай действие:",
        reply_markup=main_keyboard()
    )


@dp.message(Command("slots"))
async def slots(message: Message):
    register_user(message.from_user)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>",
        reply_markup=game_keyboard(
            message.from_user.id
        )
    )


@dp.message(Command("balance"))
async def balance(message: Message):
    register_user(message.from_user)

    user = get_user(message.from_user.id)

    await message.answer(
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{level(user[0])}</b>\n"
        f"✨ XP: <b>{user[4]}</b>"
    )


@dp.message(Command("profile"))
async def profile(message: Message):
    register_user(message.from_user)

    user = get_user(message.from_user.id)

    await message.answer(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Имя: <b>{user[2]}</b>\n"
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{level(user[0])}</b>\n"
        f"✨ XP: <b>{user[4]}</b>\n"
        f"🎰 Круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "menu")
async def menu(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    await call.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "👇 Выбирай действие:",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "game")
async def game(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    await show_game(
        call.message,
        call.from_user.id
    )


@dp.callback_query(F.data.startswith("bet:"))
async def bet(call: CallbackQuery):
    register_user(call.from_user)

    value = int(
        call.data.split(":")[1]
    )

    set_value(
        call.from_user.id,
        "bet",
        value
    )

    await call.answer(
        f"Ставка: {value} 💰"
    )

    await show_game(
        call.message,
        call.from_user.id
    )


def spin_result():
    return [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]


def win_amount(result, bet):
    a, b, c = result

    if a == "7️⃣" and b == "7️⃣" and c == "7️⃣":
        prize = jackpot()
        reset_jackpot()
        return prize, True

    if a == b == c:
        return bet * MULTIPLIERS[a], False

    if a == b or a == c or b == c:
        return bet * 2, False

    add_jackpot(max(1, bet // 10))

    return 0, False


async def animation(message):
    frames = [
        "🎰 <b>КРУТИМ...</b>\n\n❓ | ❓ | ❓",
        "🎰 <b>КРУТИМ...</b>\n\n🍒 | ❓ | ❓",
        "🎰 <b>КРУТИМ...</b>\n\n🍒 | 🔔 | ❓",
        "🎰 <b>КРУТИМ...</b>\n\n🍒 | 🔔 | 💎"
    ]

    for frame in frames:
        try:
            await message.edit_text(frame)
        except Exception:
            pass

        await asyncio.sleep(0.2)


@dp.callback_query(F.data == "spin")
async def spin(call: CallbackQuery):
    register_user(call.from_user)

    user_id = call.from_user.id
    user = get_user(user_id)

    bet_value = user[8]

    if user[3] < bet_value:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    set_value(
        user_id,
        "balance",
        user[3] - bet_value
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

    await animation(call.message)

    result = spin_result()

    win, is_jackpot = win_amount(
        result,
        bet_value
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

        if is_jackpot:
            result_text = (
                f"💎💎💎 <b>ДЖЕКПОТ!</b>\n"
                f"💰 +{win}"
            )
        else:
            result_text = (
                f"🎉 <b>Выигрыш: +{win} 💰</b>"
            )
    else:
        result_text = (
            f"😢 Проигрыш: -{bet_value} 💰"
        )

    current = get_user(user_id)

    text = (
        "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
        f"{result[0]} | {result[1]} | {result[2]}\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{current[3]}</b>\n"
        f"💎 Джекпот: <b>{jackpot()}</b>\n"
        f"⭐ Уровень: <b>{level(user_id)}</b>"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text=f"🎰 КРУТИТЬ ЕЩЁ • {bet_value} 💰",
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
async def profile_button(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    user = get_user(call.from_user.id)

    await call.message.edit_text(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Имя: <b>{user[2]}</b>\n"
        f"💰 Баланс: <b>{user[3]}</b>\n"
        f"⭐ Уровень: <b>{level(user[0])}</b>\n"
        f"✨ XP: <b>{user[4]}</b>\n"
        f"🎰 Круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "bonus")
async def bonus_button(call: CallbackQuery):
    register_user(call.from_user)

    user = get_user(call.from_user.id)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if user[9] == today:
        await call.answer(
            "🎁 Бонус уже получен сегодня!",
            show_alert=True
        )
        return

    reward = 100 + level(call.from_user.id) * 25

    set_value(
        call.from_user.id,
        "balance",
        user[3] + reward
    )

    set_value(
        call.from_user.id,
        "bonus_day",
        today
    )

    await call.answer(
        f"🎁 +{reward} 💰"
    )

    await call.message.edit_text(
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"💰 Получено: <b>+{reward}</b>\n\n"
        "Возвращайся завтра!",
        reply_markup=main_keyboard()
    )


@dp.message(Command("bonus"))
async def bonus_command(message: Message):
    register_user(message.from_user)

    user = get_user(message.from_user.id)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if user[9] == today:
        await message.answer(
            "🎁 Бонус уже получен сегодня."
        )
        return

    reward = 100 + level(message.from_user.id) * 25

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
        f"🎁 Бонус получен!\n"
        f"💰 +{reward}"
    )


@dp.callback_query(F.data == "top")
async def top_button(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    con = db()

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

    for number, row in enumerate(rows, 1):
        text += (
            f"<b>{number}.</b> "
            f"{row[0] or 'Игрок'} — "
            f"{row[1]} 💰\n"
        )

    await call.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )


@dp.message(Command("top"))
async def top_command(message: Message):
    register_user(message.from_user)

    con = db()

    rows = con.execute(
        """
        SELECT name, balance
        FROM users
        ORDER BY balance DESC
        LIMIT 10
        """
    ).fetchall()

    con.close()

    text = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"

    for number, row in enumerate(rows, 1):
        text += (
            f"{number}. {row[0] or 'Игрок'} — "
            f"{row[1]} 💰\n"
        )

    await message.answer(text)


@dp.callback_query(F.data == "combos")
async def combos(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    text = (
        "🔢 <b>КОМБИНАЦИИ</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — 💎 ДЖЕКПОТ\n\n"
        "Любые 2 одинаковых — x2"
    )

    await call.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "missions")
async def missions(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    user = get_user(call.from_user.id)

    text = (
        "📋 <b>МИССИИ</b>\n\n"
        f"🎰 10 круток: "
        f"<b>{min(user[11], 10)}/10</b>\n"
        f"🏆 3 победы: "
        f"<b>{min(user[12], 3)}/3</b>\n\n"
        "Миссии будут расширены дальше."
    )

    await call.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "wheel")
async def wheel(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    user = get_user(call.from_user.id)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if user[10] == today:
        await call.message.edit_text(
            "🎡 <b>КОЛЕСО</b>\n\n"
            "❌ Сегодня колесо уже использовано.\n"
            "Возвращайся завтра.",
            reply_markup=main_keyboard()
        )
        return

    rewards = [
        25,
        50,
        100,
        150,
        250,
        500,
        1000,
        5000
    ]

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

    await call.message.edit_text(
        "🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
        "🎰 Колесо вращается...\n\n"
        f"🎉 Выпало: <b>+{reward} 💰</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "achievements")
async def achievements(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    user = get_user(call.from_user.id)

    result = []

    if user[5] >= 10:
        result.append("🎰 10 круток")

    if user[5] >= 100:
        result.append("🔥 100 круток")

    if user[6] >= 10:
        result.append("🏆 10 побед")

    if user[7] >= 1000:
        result.append("💎 Выигрыш 1000+")

    if user[4] >= 1000:
        result.append("⭐ 1000 XP")

    if not result:
        result.append("🔒 Пока достижений нет")

    await call.message.edit_text(
        "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"
        + "\n".join(result),
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    user = get_user(call.from_user.id)

    await call.message.edit_text(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎰 Круток: <b>{user[5]}</b>\n"
        f"🏆 Побед: <b>{user[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{user[7]}</b>\n"
        f"⭐ XP: <b>{user[4]}</b>\n"
        f"📈 Уровень: <b>{level(user[0])}</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "help")
async def help_button(call: CallbackQuery):
    register_user(call.from_user)

    await call.answer()

    await call.message.edit_text(
        "❓ <b>ПОМОЩЬ</b>\n\n"
        "/start — главное меню\n"
        "/slots — слоты\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/top — рейтинг\n"
        "/profile — профиль\n"
        "/stats — статистика\n\n"
        "💰 Перевод:\n"
        "ответь на сообщение игрока:\n"
        "<code>/pay 100</code>\n\n"
        "🎲 Дуэль:\n"
        "ответь игроку:\n"
        "<code>/duel 100</code>",
        reply_markup=main_keyboard()
    )


@dp.message(Command("pay"))
async def pay(message: Message):
    register_user(message.from_user)

    if not message.reply_to_message:
        await message.answer(
            "💰 Ответь на сообщение игрока и напиши:\n"
            "<code>/pay 100</code>"
        )
        return

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "❌ Пример: <code>/pay 100</code>"
        )
        return

    amount = int(parts[1])

    if amount <= 0:
        await message.answer(
            "❌ Сумма должна быть больше нуля."
        )
        return

    receiver_id = message.reply_to_message.from_user.id

    if receiver_id == message.from_user.id:
        await message.answer(
            "❌ Нельзя переводить самому себе."
        )
        return

    sender = get_user(
        message.from_user.id
    )

    receiver = get_user(receiver_id)

    if not receiver:
        register_user(
            message.reply_to_message.from_user
        )
        receiver = get_user(receiver_id)

    if sender[3] < amount:
        await message.answer(
            "❌ Недостаточно монет."
        )
        return

    set_value(
        message.from_user.id,
        "balance",
        sender[3] - amount
    )

    set_value(
        receiver_id,
        "balance",
        receiver[3]

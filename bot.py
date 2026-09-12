import os
import asyncio
import random
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в настройках Render.")

PORT = int(os.environ.get("PORT", "10000"))

DB_FILE = "slots.db"

START_BALANCE = 1000
JACKPOT_START = 5000


# =========================
# СИМВОЛЫ СЛОТОВ
# =========================

CHERRY = "\U0001F352"
LEMON = "\U0001F34B"
ORANGE = "\U0001F34A"
BELL = "\U0001F514"
DIAMOND = "\U0001F48E"
SEVEN = "7\uFE0F\u20E3"

SYMBOLS = [
    CHERRY,
    LEMON,
    ORANGE,
    BELL,
    DIAMOND,
    SEVEN
]

MULTIPLIERS = {
    CHERRY: 5,
    LEMON: 7,
    ORANGE: 10,
    BELL: 15,
    DIAMOND: 30,
    SEVEN: 100
}


# =========================
# БАЗА ДАННЫХ
# =========================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    balance INTEGER DEFAULT 1000,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    last_bonus TEXT DEFAULT '',
    spins INTEGER DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
)
""")

db.execute(
    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
    ("jackpot", JACKPOT_START)
)

db.commit()


# =========================
# ПОЛЬЗОВАТЕЛИ
# =========================

def get_user(user_id, username=""):

    user = db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if user is None:

        db.execute(
            """
            INSERT INTO users(
                user_id,
                username,
                balance,
                xp,
                level,
                last_bonus,
                spins
            )
            VALUES(?, ?, ?, 0, 1, '', 0)
            """,
            (
                user_id,
                username,
                START_BALANCE
            )
        )

        db.commit()

        user = db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    elif username and user["username"] != username:

        db.execute(
            "UPDATE users SET username = ? WHERE user_id = ?",
            (
                username,
                user_id
            )
        )

        db.commit()

        user = db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return dict(user)


def update_user(user_id, **values):

    if not values:
        return

    parts = []
    params = []

    for key, value in values.items():

        parts.append(f"{key} = ?")
        params.append(value)

    params.append(user_id)

    db.execute(
        f"""
        UPDATE users
        SET {", ".join(parts)}
        WHERE user_id = ?
        """,
        params
    )

    db.commit()


# =========================
# УРОВЕНЬ
# =========================

def calculate_level(xp):

    return xp // 100 + 1


# =========================
# ДАТА
# =========================

def today():

    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")


# =========================
# ДЖЕКПОТ
# =========================

def get_jackpot():

    row = db.execute(
        "SELECT value FROM settings WHERE key = 'jackpot'"
    ).fetchone()

    return int(row["value"])


def set_jackpot(value):

    db.execute(
        """
        UPDATE settings
        SET value = ?
        WHERE key = 'jackpot'
        """,
        (int(value),)
    )

    db.commit()


# =========================
# КНОПКИ
# =========================

def keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎰 КРУТИТЬ 10",
                    callback_data="spin:10"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Ставка 25",
                    callback_data="spin:25"
                ),

                InlineKeyboardButton(
                    text="💰 Ставка 50",
                    callback_data="spin:50"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Ставка 100",
                    callback_data="spin:100"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🎁 Бонус",
                    callback_data="bonus"
                ),

                InlineKeyboardButton(
                    text="🏆 Топ",
                    callback_data="top"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Баланс",
                    callback_data="balance"
                )
            ]
        ]
    )


# =========================
# ГЛАВНОЕ МЕНЮ
# =========================

def menu_text(user):

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{user['balance']}</b>\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"✨ XP: <b>{user['xp']}</b>\n"
        f"🎯 Спинов: <b>{user['spins']}</b>\n\n"
        "Выбери ставку и крути!"
    )


# =========================
# ИГРА
# =========================

def play_spin(user_id, bet):

    user = get_user(user_id)

    if user["balance"] < bet:

        return (
            "❌ <b>Недостаточно монет!</b>\n\n"
            f"Твой баланс: <b>{user['balance']}</b>"
        )

    reels = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    balance = user["balance"] - bet

    xp = user["xp"] + 10

    spins = user["spins"] + 1

    jackpot = get_jackpot()

    jackpot += max(1, bet // 10)

    win = 0

    result = "😐 Ничего. Попробуй ещё!"


    # ТРИ СЕМЁРКИ

    if (
        reels[0] == SEVEN
        and reels[1] == SEVEN
        and reels[2] == SEVEN
    ):

        win = jackpot

        jackpot = JACKPOT_START

        result = (
            "🎉 <b>ДЖЕКПОТ!</b>\n"
            f"Ты выиграл <b>{win}</b> монет!"
        )


    # ТРИ ОДИНАКОВЫХ

    elif (
        reels[0] == reels[1]
        and reels[1] == reels[2]
    ):

        multiplier = MULTIPLIERS[reels[0]]

        win = bet * multiplier

        result = (
            "🔥 <b>ТРИ ОДИНАКОВЫХ!</b>\n"
            f"Множитель: x{multiplier}\n"
            f"Выигрыш: <b>{win}</b> монет!"
        )


    # ДВА ОДИНАКОВЫХ

    elif (
        reels[0] == reels[1]
        or reels[1] == reels[2]
        or reels[0] == reels[2]
    ):

        win = bet * 2

        result = (
            "✨ <b>ДВА ОДИНАКОВЫХ!</b>\n"
            f"Выигрыш: <b>{win}</b> монет!"
        )


    balance += win

    level = calculate_level(xp)

    update_user(
        user_id,
        balance=balance,
        xp=xp,
        level=level,
        spins=spins
    )

    set_jackpot(jackpot)

    user = get_user(user_id)

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n"
        f"{result}\n\n"
        f"💸 Ставка: <b>{bet}</b>\n"
        f"💰 Баланс: <b>{user['balance']}</b>\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"✨ XP: <b>{user['xp']}</b>\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b>"
    )


# =========================
# БОНУС
# =========================

def daily_bonus(user_id):

    user = get_user(user_id)

    if user["last_bonus"] == today():

        return (
            "🎁 <b>Бонус уже получен!</b>\n\n"
            "Возвращайся завтра."
        )

    reward = 100 + user["level"] * 25

    new_balance = user["balance"] + reward

    update_user(
        user_id,
        balance=new_balance,
        last_bonus=today()
    )

    return (
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n\n"
        f"Ты получил: <b>+{reward}</b> монет!\n"
        f"💰 Баланс: <b>{new_balance}</b>"
    )


# =========================
# ТОП
# =========================

def top_players():

    rows = db.execute(
        """
        SELECT username, user_id, balance, level
        FROM users
        ORDER BY balance DESC
        LIMIT 10
        """
    ).fetchall()

    if not rows:

        return "🏆 Пока игроков нет."

    text = "🏆 <b>ТОП ШАХТЁРОВ СЛОТОВ</b>\n\n"

    for index, row in enumerate(rows, 1):

        name = row["username"]

        if not name:

            name = "Игрок " + str(row["user_id"])[-4:]

        text += (
            f"{index}. {name} — "
            f"💰 {row['balance']} "
            f"⭐ {row['level']}\n"
        )

    return text


# =========================
# TELEGRAM
# =========================

dp = Dispatcher()


@dp.message(Command("start"))
async def start_command(message: Message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        menu_text(user),
        reply_markup=keyboard()
    )


@dp.message(Command("balance"))
async def balance_command(message: Message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        (
            "💰 <b>ТВОЙ БАЛАНС</b>\n\n"
            f"Монеты: <b>{user['balance']}</b>\n"
            f"⭐ Уровень: <b>{user['level']}</b>\n"
            f"✨ XP: <b>{user['xp']}</b>\n"
            f"🎯 Спинов: <b>{user['spins']}</b>"
        ),
        reply_markup=keyboard()
    )


@dp.message(Command("bonus"))
async def bonus_command(message: Message):

    await message.answer(
        daily_bonus(message.from_user.id),
        reply_markup=keyboard()
    )


@dp.message(Command("top"))
async def top_command(message: Message):

    await message.answer(
        top_players(),
        reply_markup=keyboard()
    )


@dp.callback_query(F.data.startswith("spin:"))
async def spin_callback(callback: CallbackQuery):

    bet = int(
        callback.data.split(":")[1]
    )

    text = play_spin(
        callback.from_user.id,
        bet
    )

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=keyboard()
    )


@dp.callback_query(F.data == "bonus")
async def bonus_callback(callback: CallbackQuery):

    text = daily_bonus(
        callback.from_user.id
    )

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=keyboard()
    )


@dp.callback_query(F.data == "balance")
async def balance_callback(callback: CallbackQuery):

    user = get_user(
        callback.from_user.id,
        callback.from_user.username or ""
    )

    await callback.answer()

    await callback.message.edit_text(
        (
            "💰 <b>ТВОЙ БАЛАНС</b>\n\n"
            f"Монеты: <b>{user['balance']}</b>\n"
            f"⭐ Уровень: <b>{user['level']}</b>\n"
            f"✨ XP: <b>{user['xp']}</b>\n"
            f"🎯 Спинов: <b>{user['spins']}</b>"
        ),
        reply_markup=keyboard()
    )


@dp.callback_query(F.data == "top")
async def top_callback(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        top_players(),
        reply_markup=keyboard()
    )


# =========================
# HEALTH SERVER ДЛЯ RENDER
# =========================

async def health_handler(
    reader,
    writer
):

    try:

        await reader.read(1024)

        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "Content-Length: 2\r\n"
            "Connection: close\r\n"
            "\r\n"
            "OK"
        )

        writer.write(
            response.encode()
        )

        await writer.drain()

    finally:

        writer.close()

        try:
            await writer.wait_closed()
        except Exception:
            pass


# =========================
# ЗАПУСК
# =========================

async def main():

    print("Запуск программы...")

    print(
        f"Открываем порт Render: {PORT}"
    )

    server = await asyncio.start_server(
        health_handler,
        "0.0.0.0",
        PORT
    )

    print(
        f"Health server запущен на порту {PORT}"
    )

    print("BOT_TOKEN найден.")

    bot = Bot(
        token=BOT_TOKEN
    )

    print("Telegram bot starting...")

    try:

        await dp.start_polling(
            bot
        )

    finally:

        server.close()

        await server.wait_closed()

        await bot.session.close()


if __name__ == "__main__":

    asyncio.run(
        main()
            )

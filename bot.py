import os
import asyncio
import random
import sqlite3
import threading
import html

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)


# =========================
# НАСТРОЙКИ
# =========================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Render")

PORT = int(os.getenv("PORT", "10000"))

DB_FILE = "slots.db"

START_BALANCE = 1000
JACKPOT_START = 5000

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
    "💎": 30,
    "7️⃣": 100
}

BETS = [10, 25, 50, 100]


# =========================
# БАЗА ДАННЫХ
# =========================

db_lock = threading.Lock()

conn = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

conn.row_factory = sqlite3.Row


with db_lock:

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            balance INTEGER NOT NULL DEFAULT 1000,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1,
            last_bonus TEXT DEFAULT '',
            spins INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )
    """)

    conn.execute(
        """
        INSERT OR IGNORE INTO settings(key, value)
        VALUES('jackpot', ?)
        """,
        (JACKPOT_START,)
    )

    conn.commit()


# =========================
# РАБОТА С ДАННЫМИ
# =========================

def get_user(user_id, username=""):

    with db_lock:

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

        if row is None:

            conn.execute(
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
                VALUES(
                    ?,
                    ?,
                    ?,
                    0,
                    1,
                    '',
                    0
                )
                """,
                (
                    user_id,
                    username or "",
                    START_BALANCE
                )
            )

            conn.commit()

            row = conn.execute(
                """
                SELECT *
                FROM users
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

        elif username and row["username"] != username:

            conn.execute(
                """
                UPDATE users
                SET username=?
                WHERE user_id=?
                """,
                (
                    username,
                    user_id
                )
            )

            conn.commit()

            row = conn.execute(
                """
                SELECT *
                FROM users
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

        return dict(row)


def update_user(user_id, **fields):

    allowed = {
        "username",
        "balance",
        "xp",
        "level",
        "last_bonus",
        "spins"
    }

    fields = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not fields:
        return

    columns = ", ".join(
        f"{key}=?"
        for key in fields
    )

    values = list(fields.values())
    values.append(user_id)

    with db_lock:

        conn.execute(
            f"""
            UPDATE users
            SET {columns}
            WHERE user_id=?
            """,
            values
        )

        conn.commit()


def get_jackpot():

    with db_lock:

        row = conn.execute(
            """
            SELECT value
            FROM settings
            WHERE key='jackpot'
            """
        ).fetchone()

        return int(row["value"])


def set_jackpot(value):

    with db_lock:

        conn.execute(
            """
            UPDATE settings
            SET value=?
            WHERE key='jackpot'
            """,
            (
                max(0, int(value)),
            )
        )

        conn.commit()


# =========================
# УРОВЕНЬ И XP
# =========================

def level_from_xp(xp):

    return xp // 100 + 1


def xp_to_next_level(xp):

    current_level = level_from_xp(xp)

    next_level_xp = current_level * 100

    return next_level_xp - xp


# =========================
# ДАТА
# =========================

def today():

    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")


# =========================
# КЛАВИАТУРА
# =========================

def main_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎰 КРУТИТЬ",
                    callback_data="spin:10"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Ставка 10",
                    callback_data="spin:10"
                ),

                InlineKeyboardButton(
                    text="💰 Ставка 25",
                    callback_data="spin:25"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Ставка 50",
                    callback_data="spin:50"
                ),

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
                    text="🏆 Рейтинг",
                    callback_data="top"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Баланс",
                    callback_data="balance"
                ),

                InlineKeyboardButton(
                    text="📊 Профиль",
                    callback_data="profile"
                )
            ]

        ]
    )


# =========================
# ТЕКСТ ПРОФИЛЯ
# =========================

def profile_text(user):

    need_xp = xp_to_next_level(
        user["xp"]
    )

    return (
        "👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"

        f"💰 Баланс: "
        f"<b>{user['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{user['level']}</b>\n"

        f"✨ Опыт: "
        f"<b>{user['xp']}</b> XP\n"

        f"📈 До следующего уровня: "
        f"<b>{need_xp}</b> XP\n"

        f"🎯 Спинов: "
        f"<b>{user['spins']}</b>\n\n"

        f"💎 Джекпот: "
        f"<b>{get_jackpot()}</b> 🪙"
    )


# =========================
# ПРИВЕТСТВИЕ
# =========================

def welcome_text(user):

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"

        "Добро пожаловать в игру!\n\n"

        f"💰 Баланс: "
        f"<b>{user['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{user['level']}</b>\n"

        f"✨ XP: "
        f"<b>{user['xp']}</b>\n\n"

        "Выбери ставку и крути барабаны! 🎰"
    )


# =========================
# ИГРА
# =========================

def spin_result(user_id, bet):

    user = get_user(user_id)

    if bet not in BETS:

        return "❌ Неверная ставка."

    if user["balance"] < bet:

        return (
            "❌ <b>Недостаточно монет!</b>\n\n"
            f"💰 Баланс: "
            f"<b>{user['balance']}</b> 🪙"
        )

    # Барабаны

    reels = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    # Снимаем ставку

    balance = user["balance"] - bet

    # Опыт

    xp = user["xp"] + 10

    # Спины

    spins = user["spins"] + 1

    # Джекпот постепенно растёт

    jackpot = (
        get_jackpot()
        + max(1, bet // 10)
    )

    win = 0

    result_text = (
        "😐 <b>Проигрыш</b>\n"
        "Повезёт в следующий раз!"
    )

    # =====================
    # ДЖЕКПОТ
    # =====================

    if (
        reels[0] == "7️⃣"
        and reels[1] == "7️⃣"
        and reels[2] == "7️⃣"
    ):

        win = jackpot

        jackpot = JACKPOT_START

        result_text = (
            "💥💥💥\n"
            "🎉 <b>ДЖЕКПОТ!</b>\n\n"
            f"🏆 Ты выиграл "
            f"<b>{win}</b> 🪙!"
        )

    # =====================
    # ТРИ ОДИНАКОВЫХ
    # =====================

    elif (
        reels[0]
        == reels[1]
        == reels[2]
    ):

        multiplier = MULTIPLIERS[
            reels[0]
        ]

        win = bet * multiplier

        result_text = (
            "🔥 <b>ТРИ ОДИНАКОВЫХ!</b>\n\n"
            f"🎯 Множитель: "
            f"<b>x{multiplier}</b>\n"
            f"💰 Выигрыш: "
            f"<b>{win}</b> 🪙"
        )

    # =====================
    # ДВА ОДИНАКОВЫХ
    # =====================

    elif (
        reels[0] == reels[1]
        or reels[1] == reels[2]
        or reels[0] == reels[2]
    ):

        win = bet * 2

        result_text = (
            "✨ <b>ДВА ОДИНАКОВЫХ!</b>\n\n"
            f"💰 Выигрыш: "
            f"<b>{win}</b> 🪙"
        )

    # Добавляем выигрыш

    balance += win

    new_level = level_from_xp(xp)

    update_user(
        user_id,
        balance=balance,
        xp=xp,
        level=new_level,
        spins=spins
    )

    set_jackpot(jackpot)

    new_user = get_user(user_id)

    level_up_text = ""

    if new_level > user["level"]:

        level_up_text = (
            "\n\n🎉 <b>НОВЫЙ УРОВЕНЬ!</b>\n"
            f"⭐ Теперь ты "
            f"<b>{new_level} уровня</b>!"
        )

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"

        f"┃ {reels[0]} "
        f"┃ {reels[1]} "
        f"┃ {reels[2]} ┃\n\n"

        f"{result_text}"

        f"{level_up_text}\n\n"

        f"💸 Ставка: "
        f"<b>{bet}</b> 🪙\n"

        f"💰 Баланс: "
        f"<b>{new_user['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{new_user['level']}</b>\n"

        f"✨ XP: "
        f"<b>{new_user['xp']}</b>\n"

        f"🎯 Спинов: "
        f"<b>{new_user['spins']}</b>\n"

        f"💎 Джекпот: "
        f"<b>{get_jackpot()}</b> 🪙"
    )


# =========================
# ЕЖЕДНЕВНЫЙ БОНУС
# =========================

def bonus_result(user_id):

    user = get_user(user_id)

    current_day = today()

    if user["last_bonus"] == current_day:

        return (
            "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
            "❌ Ты уже получил бонус сегодня.\n\n"
            "⏰ Возвращайся завтра!"
        )

    reward = (
        100
        + user["level"] * 25
    )

    new_balance = (
        user["balance"]
        + reward
    )

    update_user(
        user_id,
        balance=new_balance,
        last_bonus=current_day
    )

    return (
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n\n"

        f"💰 Получено: "
        f"<b>+{reward}</b> 🪙\n\n"

        f"💳 Новый баланс: "
        f"<b>{new_balance}</b> 🪙"
    )


# =========================
# РЕЙТИНГ
# =========================

def top_result():

    with db_lock:

        rows = conn.execute(
            """
            SELECT
                username,
                user_id,
                balance,
                level,
                xp,
                spins
            FROM users
            ORDER BY balance DESC
            LIMIT 10
            """
        ).fetchall()

    if not rows:

        return "🏆 Пока игроков нет."

    lines = [
        "🏆 <b>ТОП-10 ШАХТЁРОВ СЛОТОВ</b>\n"
    ]

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for i, row in enumerate(
        rows,
        1
    ):

        name = (
            row["username"]
            or f"Игрок {str(row['user_id'])[-4:]}"
        )

        name = html.escape(name)

        if i <= 3:

            prefix = medals[i - 1]

        else:

            prefix = f"<b>{i}.</b>"

        lines.append(
            f"{prefix} {name}\n"
            f"   💰 {row['balance']} 🪙"
            f" | ⭐ {row['level']}"
            f" | ✨ {row['xp']} XP"
        )

    return "\n".join(lines)


# =========================
# DISPATCHER
# =========================

dp = Dispatcher()


# =========================
# /START
# =========================

@dp.message(Command("start"))
async def cmd_start(message: Message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        welcome_text(user),
        reply_markup=main_keyboard()
    )


# =========================
# /BALANCE
# =========================

@dp.message(Command("balance"))
async def cmd_balance(message: Message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        profile_text(user),
        reply_markup=main_keyboard()
    )


# =========================
# /BONUS
# =========================

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):

    text = bonus_result(
        message.from_user.id
    )

    await message.answer(
        text,
        reply_markup=main_keyboard()
    )


# =========================
# /TOP
# =========================

@dp.message(Command("top"))
async def cmd_top(message: Message):

    await message.answer(
        top_result(),
        reply_markup=main_keyboard()
    )


# =========================
# /PROFILE
# =========================

@dp.message(Command("profile"))
async def cmd_profile(message: Message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        profile_text(user),
        reply_markup=main_keyboard()
    )


# =========================
# КНОПКА СЛОТОВ
# =========================

@dp.callback_query(
    F.data.startswith("spin:")
)
async def cb_spin(
    callback: CallbackQuery
):

    try:

        bet = int(
            callback.data.split(":")[1]
        )

    except (
        ValueError,
        IndexError
    ):

        await callback.answer(
            "❌ Ошибка ставки."
        )

        return

    text = spin_result(
        callback.from_user.id,
        bet
    )

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================
# КНОПКА БОНУСА
# =========================

@dp.callback_query(
    F.data == "bonus"
)
async def cb_bonus(
    callback: CallbackQuery
):

    text = bonus_result(
        callback.from_user.id
    )

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================
# КНОПКА БАЛАНСА
# =========================

@dp.callback_query(
    F.data == "balance"
)
async def cb_balance(
    callback: CallbackQuery
):

    user = get_user(
        callback.from_user.id,
        callback.from_user.username or ""
    )

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            profile_text(user),
            reply_markup=main_keyboard()
        )


# =========================
# КНОПКА ПРОФИЛЯ
# =========================

@dp.callback_query(
    F.data == "profile"
)
async def cb_profile(
    callback: CallbackQuery
):

    user = get_user(
        callback.from_user.id,
        callback.from_user.username or ""
    )

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            profile_text(user),
            reply_markup=main_keyboard()
        )


# =========================
# КНОПКА РЕЙТИНГА
# =========================

@dp.callback_query(
    F.data == "top"
)
async def cb_top(
    callback: CallbackQuery
):

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            top_result(),
            reply_markup=main_keyboard()
        )


# =========================
# HEALTH SERVER ДЛЯ RENDER
# =========================

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        body = b"OK"

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)

    def log_message(
        self,
        format,
        *args
    ):

        pass


def start_health_server():

    server = HTTPServer(
        (
            "0.0.0.0",
            PORT
        ),
        HealthHandler
    )

    print(
        f"HTTP server started on port {PORT}"
    )

    server.serve_forever()


# =========================
# ЗАПУСК
# =========================

async def main():

    print(
        "BOT_TOKEN найден."
    )

    print(
        f"PORT: {PORT}"
    )

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    bot = Bot(TOKEN)

    print(
        "Telegram bot started!"
    )

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())

import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Добавь BOT_TOKEN в Render -> Environment."
    )

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

VALID_BETS = (10, 25, 50, 100)


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

db_lock = threading.Lock()

conn = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

conn.row_factory = sqlite3.Row


with db_lock:

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            balance INTEGER NOT NULL DEFAULT 1000,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1,
            last_bonus TEXT DEFAULT '',
            spins INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO settings(key, value)
        VALUES('jackpot', ?)
        """,
        (JACKPOT_START,)
    )

    conn.commit()


# =========================================================
# ФУНКЦИИ БАЗЫ
# =========================================================

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
                INSERT INTO users (
                    user_id,
                    username,
                    balance,
                    xp,
                    level,
                    last_bonus,
                    spins
                )
                VALUES (?, ?, ?, 0, 1, '', 0)
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

        if row is None:
            return JACKPOT_START

        return int(row["value"])


def set_jackpot(value):

    with db_lock:

        conn.execute(
            """
            UPDATE settings
            SET value=?
            WHERE key='jackpot'
            """,
            (max(0, int(value)),)
        )

        conn.commit()


# =========================================================
# ИГРОВЫЕ ФУНКЦИИ
# =========================================================

def level_from_xp(xp):

    return xp // 100 + 1


def today():

    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")


# =========================================================
# КЛАВИАТУРА
# =========================================================

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


# =========================================================
# СТАРТОВОЕ СООБЩЕНИЕ
# =========================================================

def welcome_text(user):

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Добро пожаловать в игру!\n\n"
        f"💰 Баланс: <b>{user['balance']}</b> 🪙\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"✨ XP: <b>{user['xp']}</b>\n"
        f"🎯 Спинов: <b>{user['spins']}</b>\n\n"
        "Выбери ставку и крути барабаны! 🎰"
    )


# =========================================================
# ПРОФИЛЬ
# =========================================================

def profile_text(user):

    next_level_xp = user["level"] * 100
    current_xp = user["xp"]

    if current_xp >= next_level_xp:
        xp_text = "Готов к следующему уровню!"
    else:
        xp_text = (
            f"{current_xp} / {next_level_xp}"
        )

    username = user["username"]

    if username:
        name = "@" + escape(username)
    else:
        name = "Без username"

    return (
        "📊 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Игрок: <b>{name}</b>\n"
        f"💰 Баланс: <b>{user['balance']}</b> 🪙\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"✨ XP: <b>{xp_text}</b>\n"
        f"🎯 Всего спинов: <b>{user['spins']}</b>\n\n"
        "Чем больше играешь — тем выше уровень!"
    )


# =========================================================
# БАЛАНС
# =========================================================

def balance_text(user):

    return (
        "💰 <b>БАЛАНС</b>\n\n"
        f"🪙 Монеты: <b>{user['balance']}</b>\n"
        f"⭐ Уровень: <b>{user['level']}</b>\n"
        f"✨ XP: <b>{user['xp']}</b>\n"
        f"🎯 Спинов: <b>{user['spins']}</b>"
    )


# =========================================================
# ИГРА
# =========================================================

def spin_result(user_id, bet):

    user = get_user(user_id)

    if bet not in VALID_BETS:

        return "❌ Неверная ставка."

    if user["balance"] < bet:

        return (
            "❌ <b>Недостаточно монет!</b>\n\n"
            f"💰 Твой баланс: <b>{user['balance']}</b> 🪙"
        )

    # Барабаны
    reels = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    # Списываем ставку
    balance = user["balance"] - bet

    # XP
    xp = user["xp"] + 10

    # Спины
    spins = user["spins"] + 1

    # Джекпот увеличивается после каждой игры
    jackpot = get_jackpot()

    jackpot += max(
        1,
        bet // 10
    )

    win = 0

    result_text = (
        "😐 <b>Ничего!</b>\n"
        "Попробуй ещё раз."
    )

    # =====================================================
    # ДЖЕКПОТ
    # =====================================================

    if (
        reels[0] == "7️⃣"
        and reels[1] == "7️⃣"
        and reels[2] == "7️⃣"
    ):

        win = jackpot

        jackpot = JACKPOT_START

        result_text = (
            "🎉 <b>ДЖЕКПОТ!</b>\n\n"
            f"💎 Ты выиграл <b>{win}</b> 🪙!"
        )

    # =====================================================
    # ТРИ ОДИНАКОВЫХ
    # =====================================================

    elif (
        reels[0] == reels[1]
        and reels[1] == reels[2]
    ):

        multiplier = MULTIPLIERS[reels[0]]

        win = bet * multiplier

        result_text = (
            "🔥 <b>ТРИ ОДИНАКОВЫХ!</b>\n\n"
            f"{reels[0]} {reels[1]} {reels[2]}\n\n"
            f"💰 Выигрыш: <b>{win}</b> 🪙\n"
            f"⚡ Множитель: <b>x{multiplier}</b>"
        )

    # =====================================================
    # ДВА ОДИНАКОВЫХ
    # =====================================================

    elif (
        reels[0] == reels[1]
        or reels[1] == reels[2]
        or reels[0] == reels[2]
    ):

        win = bet * 2

        result_text = (
            "✨ <b>ДВА ОДИНАКОВЫХ!</b>\n\n"
            f"{reels[0]} {reels[1]} {reels[2]}\n\n"
            f"💰 Выигрыш: <b>{win}</b> 🪙"
        )

    # Добавляем выигрыш
    balance += win

    # Новый уровень
    level = level_from_xp(xp)

    # Сохраняем
    update_user(
        user_id,
        balance=balance,
        xp=xp,
        level=level,
        spins=spins
    )

    set_jackpot(jackpot)

    new_user = get_user(user_id)

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"┃ {reels[0]} ┃ {reels[1]} ┃ {reels[2]} ┃\n\n"
        f"{result_text}\n\n"
        f"💸 Ставка: <b>{bet}</b> 🪙\n"
        f"💰 Баланс: <b>{new_user['balance']}</b> 🪙\n"
        f"⭐ Уровень: <b>{new_user['level']}</b>\n"
        f"✨ XP: <b>{new_user['xp']}</b>\n"
        f"🎯 Спинов: <b>{new_user['spins']}</b>\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 🪙"
    )


# =========================================================
# ЕЖЕДНЕВНЫЙ БОНУС
# =========================================================

def bonus_result(user_id):

    user = get_user(user_id)

    current_day = today()

    if user["last_bonus"] == current_day:

        return (
            "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
            "❌ Ты уже получил бонус сегодня.\n\n"
            "⏰ Возвращайся завтра!"
        )

    reward = 100 + user["level"] * 25

    new_balance = user["balance"] + reward

    update_user(
        user_id,
        balance=new_balance,
        last_bonus=current_day
    )

    return (
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n\n"
        f"🎉 Ты получил <b>+{reward}</b> 🪙!\n\n"
        f"💰 Новый баланс: <b>{new_balance}</b> 🪙"
    )


# =========================================================
# РЕЙТИНГ
# =========================================================

def top_result():

    with db_lock:

        rows = conn.execute(
            """
            SELECT username, user_id, balance, level, spins
            FROM users
            ORDER BY balance DESC
            LIMIT 10
            """
        ).fetchall()

    if not rows:

        return "🏆 Пока игроков нет."

    lines = [
        "🏆 <b>ТОП-10 ШАХТЁРОВ</b>\n"
    ]

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for i, row in enumerate(rows, 1):

        username = row["username"]

        if username:

            name = "@" + escape(username)

        else:

            name = (
                f"Игрок {str(row['user_id'])[-4:]}"
            )

        if i <= 3:
            medal = medals[i - 1]
        else:
            medal = f"{i}."

        lines.append(
            f"{medal} <b>{name}</b>\n"
            f"   💰 {row['balance']} 🪙 | "
            f"⭐ Ур. {row['level']} | "
            f"🎯 {row['spins']}"
        )

    return "\n".join(lines)


# =========================================================
# TELEGRAM
# =========================================================

dp = Dispatcher()


# =========================================================
# /start
# =========================================================

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


# =========================================================
# /balance
# =========================================================

@dp.message(Command("balance"))
async def cmd_balance(message: Message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        balance_text(user),
        reply_markup=main_keyboard()
    )


# =========================================================
# /bonus
# =========================================================

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):

    text = bonus_result(
        message.from_user.id
    )

    await message.answer(
        text,
        reply_markup=main_keyboard()
    )


# =========================================================
# /top
# =========================================================

@dp.message(Command("top"))
async def cmd_top(message: Message):

    await message.answer(
        top_result(),
        reply_markup=main_keyboard()
    )


# =========================================================
# КРУТИТЬ
# =========================================================

@dp.callback_query(F.data.startswith("spin:"))
async def cb_spin(callback: CallbackQuery):

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


# =========================================================
# БОНУС
# =========================================================

@dp.callback_query(F.data == "bonus")
async def cb_bonus(callback: CallbackQuery):

    text = bonus_result(
        callback.from_user.id
    )

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================================================
# БАЛАНС
# =========================================================

@dp.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):

    user = get_user(
        callback.from_user.id,
        callback.from_user.username or ""
    )

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            balance_text(user),
            reply_markup=main_keyboard()
        )


# =========================================================
# РЕЙТИНГ
# =========================================================

@dp.callback_query(F.data == "top")
async def cb_top(callback: CallbackQuery):

    await callback.answer()

    if callback.message:

        await callback.message.edit_text(
            top_result(),
            reply_markup=main_keyboard()
        )


# =========================================================
# ПРОФИЛЬ
# =========================================================

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):

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


# =========================================================
# HEALTH SERVER ДЛЯ RENDER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path in (
            "/",
            "/healthz"
        ):

            body = b"OK"

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()

            self.wfile.write(body)

        else:

            self.send_response(404)

            self.end_headers()

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
        f"Health server started on port {PORT}"
    )

    server.serve_forever()


# =========================================================
# MAIN
# =========================================================

async def main():

    print("BOT_TOKEN найден.")

    print(
        f"PORT: {PORT}"
    )

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    print(
        "Telegram bot starting..."
    )

    await dp.start_polling(bot)


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())

import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


ENV = {str(k).strip(): str(v).strip() for k, v in os.environ.items()}
BOT_TOKEN = ENV.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. В Render -> Environment Variables "
        "нужна переменная BOT_TOKEN с токеном BotFather."
    )

PORT = int(os.environ.get("PORT", "10000"))
DB_FILE = "slots.db"

START_BALANCE = 1000
JACKPOT_START = 5000

SYMBOLS = [
    "\U0001F352",
    "\U0001F34B",
    "\U0001F34A",
    "\U0001F514",
    "\U0001F48E",
    "7\uFE0F\u20E3"
]

MULTIPLIERS = {
    "\U0001F352": 5,
    "\U0001F34B": 7,
    "\U0001F34A": 10,
    "\U0001F514": 15,
    "\U0001F48E": 30,
    "7\uFE0F\u20E3": 100,
}


db_lock = threading.Lock()

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
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
        "INSERT OR IGNORE INTO settings(key, value) VALUES('jackpot', ?)",
        (JACKPOT_START,)
    )

    conn.commit()


def get_jackpot():
    with db_lock:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='jackpot'"
        ).fetchone()

        return int(row["value"])


def set_jackpot(value):
    with db_lock:
        conn.execute(
            "UPDATE settings SET value=? WHERE key='jackpot'",
            (max(0, int(value)),)
        )

        conn.commit()


def get_user(user_id, username=""):
    with db_lock:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id=?",
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
                    level
                )
                VALUES(?, ?, ?, 0, 1)
                """,
                (
                    user_id,
                    username or "",
                    START_BALANCE
                )
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM users WHERE user_id=?",
                (user_id,)
            ).fetchone()

        elif username and row["username"] != username:
            conn.execute(
                "UPDATE users SET username=? WHERE user_id=?",
                (
                    username,
                    user_id
                )
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM users WHERE user_id=?",
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
            f"UPDATE users SET {columns} WHERE user_id=?",
            values
        )

        conn.commit()


def level_from_xp(xp):
    return xp // 100 + 1


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="\U0001F3B0 КРУТИТЬ",
                    callback_data="spin:10"
                )
            ],

            [
                InlineKeyboardButton(
                    text="\U0001F4B0 Ставка 10",
                    callback_data="spin:10"
                ),

                InlineKeyboardButton(
                    text="\U0001F4B0 Ставка 25",
                    callback_data="spin:25"
                )
            ],

            [
                InlineKeyboardButton(
                    text="\U0001F4B0 Ставка 50",
                    callback_data="spin:50"
                ),

                InlineKeyboardButton(
                    text="\U0001F4B0 Ставка 100",
                    callback_data="spin:100"
                )
            ],

            [
                InlineKeyboardButton(
                    text="\U0001F381 Бонус",
                    callback_data="bonus"
                ),

                InlineKeyboardButton(
                    text="\U0001F3C6 Топ",
                    callback_data="top"
                )
            ],

            [
                InlineKeyboardButton(
                    text="\U0001F4B0 Баланс",
                    callback_data="balance"
                )
            ]
        ]
    )


def welcome_text(user):
    return (
        "\U0001F3B0 <b>СЛОТЫ</b>\n\n"
        f"\U0001F4B0 Баланс: <b>{user['balance']}</b> \U0001FA99\n"
        f"\u2B50 Уровень: <b>{user['level']}</b>\n"
        f"\u2728 XP: <b>{user['xp']}</b>\n"
        f"\U0001F3AF Спинов: <b>{user['spins']}</b>\n\n"
        "Выбери ставку и крути барабаны!"
    )


def spin_result(user_id, bet):
    user = get_user(user_id)

    if user["balance"] < bet:
        return (
            "\u274C Недостаточно монет.\n"
            f"Твой баланс: <b>{user['balance']}</b> \U0001FA99"
        )

    reels = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    balance = user["balance"] - bet
    xp = user["xp"] + 10
    spins = user["spins"] + 1

    jackpot = get_jackpot() + max(1, bet // 10)

    win = 0

    result_text = "\U0001F610 Ничего. Попробуй ещё!"

    if (
        reels[0] == reels[1]
        and reels[1] == reels[2]
        and reels[0] == "7\uFE0F\u20E3"
    ):
        win = jackpot
        jackpot = JACKPOT_START

        result_text = (
            "\U0001F389 <b>ДЖЕКПОТ!</b> "
            f"Ты выиграл <b>{win}</b> \U0001FA99!"
        )

    elif reels[0] == reels[1] == reels[2]:
        win = bet * MULTIPLIERS[reels[0]]

        result_text = (
            "\U0001F525 <b>Три одинаковых!</b>\n"
            f"Выигрыш: <b>{win}</b> \U0001FA99"
        )

    elif (
        reels[0] == reels[1]
        or reels[1] == reels[2]
        or reels[0] == reels[2]
    ):
        win = bet * 2

        result_text = (
            "\u2728 <b>Два одинаковых!</b>\n"
            f"Выигрыш: <b>{win}</b> \U0001FA99"
        )

    balance += win

    update_user(
        user_id,
        balance=balance,
        xp=xp,
        level=level_from_xp(xp),
        spins=spins
    )

    set_jackpot(jackpot)

    new_user = get_user(user_id)

    return (
        "\U0001F3B0 <b>СЛОТЫ</b>\n\n"
        f"\u2503 {reels[0]} \u2503 {reels[1]} \u2503 {reels[2]} \u2503\n\n"
        f"{result_text}\n\n"
        f"\U0001F4B8 Ставка: <b>{bet}</b> \U0001FA99\n"
        f"\U0001F4B0 Баланс: <b>{new_user['balance']}</b> \U0001FA99\n"
        f"\u2B50 Уровень: <b>{new_user['level']}</b>\n"
        f"\U0001F3AF Спинов: <b>{new_user['spins']}</b>\n"
        f"\U0001F48E Джекпот: <b>{get_jackpot()}</b> \U0001FA99"
    )


def bonus_result(user_id):
    user = get_user(user_id)

    if user["last_bonus"] == today():
        return "\U0001F381 Ты уже получил ежедневный бонус сегодня."

    reward = 100 + user["level"] * 25
    new_balance = user["balance"] + reward

    update_user(
        user_id,
        balance=new_balance,
        last_bonus=today()
    )

    return (
        "\U0001F381 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"Ты получил <b>+{reward}</b> \U0001FA99!\n"
        f"\U0001F4B0 Баланс: <b>{new_balance}</b> \U0001FA99"
    )


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
        return "\U0001F3C6 Пока игроков нет."

    lines = [
        "\U0001F3C6 <b>ТОП ИГРОКОВ</b>\n"
    ]

    for i, row in enumerate(rows, 1):
        name = row["username"]

        if not name:
            name = f"Игрок {str(row['user_id'])[-4:]}"

        lines.append(
            f"{i}. {name} — "
            f"\U0001F4B0 {row['balance']} \U0001FA99 | "
            f"\u2B50 {row['level']}"
        )

    return "\n".join(lines)


dp = Dispatcher()


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


@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user = get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        f"\U0001F4B0 Баланс: <b>{user['balance']}</b> \U0001FA99\n"
        f"\u2B50 Уровень: <b>{user['level']}</b>\n"
        f"\u2728 XP: <b>{user['xp']}</b>\n"
        f"\U0001F3AF Спинов: <b>{user['spins']}</b>",
        reply_markup=main_keyboard()
    )


@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    await message.answer(
        bonus_result(message.from_user.id),
        reply_markup=main_keyboard()
    )


@dp.message(Command("top"))
async def cmd_top(message: Message):
    await message.answer(
        top_result(),
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data.startswith("spin:"))
async def cb_spin(callback: CallbackQuery):
    bet = int(callback.data.split(":")[1])

    text = spin_result(
        callback.from_user.id,
        bet
    )

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "bonus")
async def cb_bonus(callback: CallbackQuery):
    text = bonus_result(
        callback.from_user.id
    )

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):
    user = get_user(
        callback.from_user.id,
        callback.from_user.username or ""
    )

    await callback.answer()

    await callback.message.edit_text(
        f"\U0001F4B0 Баланс: <b>{user['balance']}</b> \U0001FA99\n"
        f"\u2B50 Уровень: <b>{user['level']}</b>\n"
        f"\u2728 XP: <b>{user['xp']}</b>\n"
        f"\U0001F3AF Спинов: <b>{user['spins']}</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "top")
async def cb_top(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        top_result(),
        reply_markup=main_keyboard()
    )


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path in ("/", "/healthz"):

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

    def log_message(self, format, *args):
        pass


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(
        f"Health server started on port {PORT}"
    )

    server.serve_forever()


async def main():

    print("BOT_TOKEN найден.")

    bot = Bot(BOT_TOKEN)

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    print(
        "Telegram bot starting..."
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

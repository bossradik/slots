import os
import sqlite3
import random
import asyncio
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder


TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN")

bot = Bot(TOKEN)
dp = Dispatcher()

DB = "slots.db"

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
BET_VALUES = [10, 25, 50, 100]

users_bet = {}


def db():
    return sqlite3.connect(DB)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 1000,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_bonus TEXT DEFAULT '',
            spins INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def get_user(user_id, username=""):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    )

    user = cur.fetchone()

    if not user:
        cur.execute("""
            INSERT INTO users
            (user_id, username, balance, xp, level, last_bonus, spins)
            VALUES (?, ?, 1000, 0, 1, '', 0)
        """, (user_id, username))

        conn.commit()

        cur.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )

        user = cur.fetchone()

    conn.close()
    return user


def update_user(
    user_id,
    balance=None,
    xp=None,
    level=None,
    last_bonus=None,
    spins=None
):
    conn = db()
    cur = conn.cursor()

    if balance is not None:
        cur.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (balance, user_id)
        )

    if xp is not None:
        cur.execute(
            "UPDATE users SET xp = ? WHERE user_id = ?",
            (xp, user_id)
        )

    if level is not None:
        cur.execute(
            "UPDATE users SET level = ? WHERE user_id = ?",
            (level, user_id)
        )

    if last_bonus is not None:
        cur.execute(
            "UPDATE users SET last_bonus = ? WHERE user_id = ?",
            (last_bonus, user_id)
        )

    if spins is not None:
        cur.execute(
            "UPDATE users SET spins = ? WHERE user_id = ?",
            (spins, user_id)
        )

    conn.commit()
    conn.close()


def main_keyboard(user_id):
    bet = users_bet.get(user_id, 10)

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🎰 КРУТИТЬ",
        callback_data="spin"
    )

    kb.button(
        text=f"💰 Ставка: {bet}",
        callback_data="bet"
    )

    kb.button(
        text="🎁 Бонус",
        callback_data="bonus"
    )

    kb.button(
        text="🏆 Топ",
        callback_data="top"
    )

    kb.adjust(1, 1, 2)

    return kb.as_markup()


def game_text(user_id):
    user = get_user(user_id)

    balance = user[2]
    xp = user[3]
    level = user[4]
    spins = user[6]

    bet = users_bet.get(user_id, 10)

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"⭐ Уровень: <b>{level}</b>\n"
        f"✨ XP: <b>{xp % 100}/100</b>\n"
        f"🎯 Спинов: <b>{spins}</b>\n"
        f"💵 Ставка: <b>{bet}</b>\n\n"
        "Нажми кнопку ниже и испытай удачу! 🍀"
    )


@dp.message(F.text == "/start")
async def start(message: Message):
    get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    users_bet.setdefault(message.from_user.id, 10)

    await message.answer(
        game_text(message.from_user.id),
        reply_markup=main_keyboard(message.from_user.id),
        parse_mode="HTML"
    )


@dp.message(F.text == "/balance")
async def balance_command(message: Message):
    get_user(
        message.from_user.id,
        message.from_user.username or ""
    )

    await message.answer(
        game_text(message.from_user.id),
        reply_markup=main_keyboard(message.from_user.id),
        parse_mode="HTML"
    )


@dp.message(F.text == "/bonus")
async def bonus_command(message: Message):
    await give_bonus(
        message.from_user.id,
        message
    )


async def give_bonus(user_id, message_or_call):
    user = get_user(user_id)

    balance = user[2]
    level = user[4]
    last_bonus = user[5]

    today = str(date.today())

    if last_bonus == today:

        text = (
            "🎁 <b>Ежедневный бонус</b>\n\n"
            "❌ Ты уже забрал бонус сегодня.\n"
            "Возвращайся завтра! ⏰"
        )

        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.answer(
                "Бонус уже получен сегодня!",
                show_alert=True
            )
        else:
            await message_or_call.answer(
                text,
                parse_mode="HTML"
            )

        return

    reward = 100 + level * 25
    balance += reward

    update_user(
        user_id,
        balance=balance,
        last_bonus=today
    )

    text = (
        "🎁 <b>Ежедневный бонус!</b>\n\n"
        f"💰 Ты получил: <b>+{reward}</b>\n\n"
        f"💵 Новый баланс: <b>{balance}</b>"
    )

    if isinstance(message_or_call, CallbackQuery):

        await message_or_call.answer(
            f"🎁 +{reward}",
            show_alert=True
        )

        await message_or_call.message.edit_text(
            text,
            reply_markup=main_keyboard(user_id),
            parse_mode="HTML"
        )

    else:

        await message_or_call.answer(
            text,
            reply_markup=main_keyboard(user_id),
            parse_mode="HTML"
        )


@dp.callback_query(F.data == "bet")
async def change_bet(call: CallbackQuery):
    user_id = call.from_user.id

    current = users_bet.get(user_id, 10)

    index = BET_VALUES.index(current)

    new_bet = BET_VALUES[
        (index + 1) % len(BET_VALUES)
    ]

    users_bet[user_id] = new_bet

    await call.answer(
        f"Ставка: {new_bet}"
    )

    await call.message.edit_text(
        game_text(user_id),
        reply_markup=main_keyboard(user_id),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "bonus")
async def bonus_callback(call: CallbackQuery):
    await give_bonus(
        call.from_user.id,
        call
    )


@dp.callback_query(F.data == "spin")
async def spin(call: CallbackQuery):
    user_id = call.from_user.id

    user = get_user(user_id)

    balance = user[2]
    xp = user[3]
    level = user[4]
    spins = user[6]

    bet = users_bet.get(user_id, 10)

    if balance < bet:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    balance -= bet

    reels = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    win = 0
    result_text = "😔 Не повезло..."

    if reels[0] == reels[1] == reels[2]:

        if reels[0] == "7️⃣":

            win = bet * 100
            result_text = "🔥 ДЖЕКПОТ! 🔥"

        else:

            multipliers = {
                "🍒": 5,
                "🍋": 7,
                "🍊": 10,
                "🔔": 15,
                "💎": 30
            }

            win = bet * multipliers.get(
                reels[0],
                5
            )

            result_text = "🎉 ТРИ ОДИНАКОВЫХ!"

    elif (
        reels[0] == reels[1]
        or reels[1] == reels[2]
        or reels[0] == reels[2]
    ):

        win = bet * 2
        result_text = "✨ ДВА ОДИНАКОВЫХ!"

    if win > 0:
        balance += win

    xp += 10
    spins += 1

    new_level = xp // 100 + 1
    level_up = new_level > level
    level = new_level

    update_user(
        user_id,
        balance=balance,
        xp=xp,
        level=level,
        spins=spins
    )

    if win > 0:

        result = (
            f"🎰 <b>{reels[0]} | {reels[1]} | {reels[2]}</b>\n\n"
            f"{result_text}\n"
            f"💰 Выигрыш: <b>+{win}</b>\n"
            f"💵 Баланс: <b>{balance}</b>"
        )

    else:

        result = (
            f"🎰 <b>{reels[0]} | {reels[1]} | {reels[2]}</b>\n\n"
            f"{result_text}\n"
            f"💸 Потрачено: <b>-{bet}</b>\n"
            f"💵 Баланс: <b>{balance}</b>"
        )

    result += (
        f"\n\n⭐ Уровень: <b>{level}</b>"
        f"\n✨ XP: <b>{xp % 100}/100</b>"
    )

    if level_up:
        result += (
            f"\n\n🆙 <b>НОВЫЙ УРОВЕНЬ!</b>\n"
            f"Ты достиг уровня <b>{level}</b>!"
        )

    await call.answer()

    await call.message.edit_text(
        result,
        reply_markup=main_keyboard(user_id),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "top")
async def top(call: CallbackQuery):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, balance, level
        FROM users
        ORDER BY balance DESC
        LIMIT 10
    """)

    players = cur.fetchall()

    conn.close()

    text = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"

    if not players:

        text += "Пока игроков нет."

    else:

        for i, player in enumerate(players, 1):

            username = player[0] or "Игрок"
            balance = player[1]
            level = player[2]

            text += (
                f"{i}. @{username} — "
                f"💰 {balance} | ⭐ {level}\n"
            )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅️ Назад",
        callback_data="back"
    )

    await call.answer()

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "back")
async def back(call: CallbackQuery):
    user_id = call.from_user.id

    await call.answer()

    await call.message.edit_text(
        game_text(user_id),
        reply_markup=main_keyboard(user_id),
        parse_mode="HTML"
    )


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path == "/healthz":

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8"
            )
            self.end_headers()

            self.wfile.write(
                b"OK"
            )

        else:

            self.send_response(200)
            self.end_headers()

            self.wfile.write(
                b"Slots bot is running"
            )

    def log_message(self, format, *args):
        return


def run_http_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"HTTP server started on port {port}"
    )

    server.serve_forever()


async def main():

    init_db()

    threading.Thread(
        target=run_http_server,
        daemon=True
    ).start()

    print("🎰 Slots bot started!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

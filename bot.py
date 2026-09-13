import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties


TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB = "slots.db"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Render")

db = sqlite3.connect(DB, check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.RLock()

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
MULT = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30,
    "7️⃣": 100
}

BETS = [10, 25, 50, 100]
START_BALANCE = 1000
JACKPOT_START = 5000


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def init_db():
    with lock:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            name TEXT DEFAULT '',
            balance INTEGER DEFAULT 1000,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            spins INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            best_win INTEGER DEFAULT 0,
            last_bonus TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS chats(
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY(chat_id,user_id)
        );

        CREATE TABLE IF NOT EXISTS tasks(
            user_id INTEGER,
            date TEXT,
            spins INTEGER DEFAULT 0,
            won INTEGER DEFAULT 0,
            big INTEGER DEFAULT 0,
            claimed INTEGER DEFAULT 0,
            PRIMARY KEY(user_id,date)
        );

        CREATE TABLE IF NOT EXISTS achievements(
            user_id INTEGER,
            achievement TEXT,
            PRIMARY KEY(user_id,achievement)
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value INTEGER
        );

        INSERT OR IGNORE INTO settings(key,value)
        VALUES('jackpot',5000);
        """)
        db.commit()


def get_user(u):
    with lock:
        r = db.execute(
            "SELECT * FROM users WHERE id=?",
            (u.id,)
        ).fetchone()

        if not r:
            db.execute(
                """
                INSERT INTO users(
                    id,username,name,balance
                )
                VALUES(?,?,?,?)
                """,
                (
                    u.id,
                    u.username or "",
                    u.first_name or "",
                    START_BALANCE
                )
            )
            db.commit()
            r = db.execute(
                "SELECT * FROM users WHERE id=?",
                (u.id,)
            ).fetchone()

        return dict(r)


def save_user(uid, **data):
    if not data:
        return

    q = ",".join(f"{k}=?" for k in data)

    with lock:
        db.execute(
            f"UPDATE users SET {q} WHERE id=?",
            [*data.values(), uid]
        )
        db.commit()


def register(chat_id, uid):
    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO chats(chat_id,user_id)
            VALUES(?,?)
            """,
            (chat_id, uid)
        )
        db.commit()


def get_jackpot():
    r = db.execute(
        "SELECT value FROM settings WHERE key='jackpot'"
    ).fetchone()
    return r["value"]


def set_jackpot(value):
    with lock:
        db.execute(
            "UPDATE settings SET value=? WHERE key='jackpot'",
            (value,)
        )
        db.commit()


def level(xp):
    return xp // 100 + 1


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
                    text="💰 25",
                    callback_data="spin:25"
                ),
                InlineKeyboardButton(
                    text="💰 50",
                    callback_data="spin:50"
                ),
                InlineKeyboardButton(
                    text="💰 100",
                    callback_data="spin:100"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Баланс",
                    callback_data="balance"
                ),
                InlineKeyboardButton(
                    text="🎁 Бонус",
                    callback_data="bonus"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Топ",
                    callback_data="top"
                ),
                InlineKeyboardButton(
                    text="🎯 Задания",
                    callback_data="tasks"
                )
            ]
        ]
    )


def game_text(u):
    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{u['balance']}</b> 🪙\n"
        f"⭐ Уровень: <b>{u['level']}</b>\n"
        f"✨ XP: <b>{u['xp'] % 100}/100</b>\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 🪙\n\n"
        "Выбери ставку:"
    )


def add_task(uid, win):
    d = today()

    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO tasks(user_id,date)
            VALUES(?,?)
            """,
            (uid, d)
        )

        db.execute(
            """
            UPDATE tasks
            SET spins=spins+1,
                won=won+?,
                big=big+?
            WHERE user_id=? AND date=?
            """,
            (
                win,
                1 if win >= 1000 else 0,
                uid,
                d
            )
        )

        db.commit()


def task_text(uid):
    d = today()

    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO tasks(user_id,date)
            VALUES(?,?)
            """,
            (uid, d)
        )
        db.commit()

        t = db.execute(
            """
            SELECT * FROM tasks
            WHERE user_id=? AND date=?
            """,
            (uid, d)
        ).fetchone()

    return (
        "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n\n"
        f"🎰 10 спинов: <b>{min(t['spins'],10)}/10</b>\n"
        "Награда: +100 🪙\n\n"
        f"💰 Выиграть 500: <b>{min(t['won'],500)}/500</b>\n"
        "Награда: +200 🪙\n\n"
        f"💎 Выигрыш 1000+: <b>{min(t['big'],1)}/1</b>\n"
        "Награда: +500 🪙"
    )


def top_text(chat_id):
    with lock:
        if chat_id < 0:
            rows = db.execute(
                """
                SELECT u.*
                FROM users u
                JOIN chats c ON c.user_id=u.id
                WHERE c.chat_id=?
                ORDER BY u.balance DESC
                LIMIT 10
                """,
                (chat_id,)
            ).fetchall()
            title = "🏆 <b>ТОП ГРУППЫ</b>"
        else:
            rows = db.execute(
                """
                SELECT * FROM users
                ORDER BY balance DESC
                LIMIT 10
                """
            ).fetchall()
            title = "🏆 <b>ТОП ИГРОКОВ</b>"

    if not rows:
        return title + "\n\nПока игроков нет."

    text = title + "\n\n"

    for i, r in enumerate(rows, 1):
        player = (
            "@" + r["username"]
            if r["username"]
            else r["name"]
        )

        text += (
            f"{i}. {player} — "
            f"<b>{r['balance']}</b> 🪙\n"
        )

    return text


def health_server():
    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/plain"
            )
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    HTTPServer(
        ("0.0.0.0", PORT),
        Handler
    ).serve_forever()


async def main():

    threading.Thread(
        target=health_server,
        daemon=True
    ).start()

    init_db()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )

    dp = Dispatcher()


    @dp.message(Command("start"))
    async def start(message: Message):

        u = get_user(message.from_user)

        register(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            game_text(u),
            reply_markup=keyboard()
        )


    @dp.message(Command("slots"))
    async def slots(message: Message):

        u = get_user(message.from_user)

        register(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            game_text(u),
            reply_markup=keyboard()
        )


    @dp.message(Command("balance"))
    async def balance(message: Message):

        u = get_user(message.from_user)

        await message.answer(
            f"💰 Твой баланс: "
            f"<b>{u['balance']}</b> 🪙",
            reply_markup=keyboard()
        )


    @dp.message(Command("bonus"))
    async def bonus_cmd(message: Message):

        u = get_user(message.from_user)

        if u["last_bonus"] == today():
            await message.answer(
                "🎁 Бонус уже получен сегодня.",
                reply_markup=keyboard()
            )
            return

        reward = 100 + u["level"] * 25

        save_user(
            u["id"],
            balance=u["balance"] + reward,
            last_bonus=today()
        )

        await message.answer(
            f"🎁 Ежедневный бонус!\n\n"
            f"<b>+{reward} 🪙</b>",
            reply_markup=keyboard()
        )


    @dp.message(Command("top"))
    async def top_cmd(message: Message):

        get_user(message.from_user)

        register(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            top_text(message.chat.id),
            reply_markup=keyboard()
        )


    @dp.message(Command("tasks"))
    async def tasks_cmd(message: Message):

        u = get_user(message.from_user)

        await message.answer(
            task_text(u["id"]),
            reply_markup=keyboard()
        )


    @dp.message(Command("profile"))
    async def profile_cmd(message: Message):

        u = get_user(message.from_user)

        await message.answer(
            "👤 <b>ПРОФИЛЬ</b>\n\n"
            f"Игрок: <b>{u['name']}</b>\n"
            f"💰 Баланс: <b>{u['balance']}</b> 🪙\n"
            f"⭐ Уровень: <b>{u['level']}</b>\n"
            f"🎰 Спинов: <b>{u['spins']}</b>\n"
            f"🏆 Побед: <b>{u['wins']}</b>\n"
            f"💎 Лучший выигрыш: "
            f"<b>{u['best_win']}</b> 🪙",
            reply_markup=keyboard()
        )


    @dp.callback_query(F.data.startswith("spin:"))
    async def spin(callback: CallbackQuery):

        bet = int(
            callback.data.split(":")[1]
        )

        if bet not in BETS:
            await callback.answer(
                "Неверная ставка.",
                show_alert=True
            )
            return

        u = get_user(callback.from_user)

        register(
            callback.message.chat.id,
            callback.from_user.id
        )

        if u["balance"] < bet:
            await callback.answer(
                "❌ Недостаточно монет.",
                show_alert=True
            )
            return

        reels = [
            random.choice(SYMBOLS)
            for _ in range(3)
        ]

        triple = (
            reels[0] == reels[1]
            and reels[1] == reels[2]
        )

        pair = len(set(reels)) == 2

        win = 0
        jackpot_win = False

        if triple and reels[0] == "7️⃣":
            win = get_jackpot()
            jackpot_win = True
            set_jackpot(JACKPOT_START)

        elif triple:
            win = bet * MULT[reels[0]]

        elif pair:
            win = bet * 2

        set_jackpot(
            get_jackpot()
            + max(1, bet // 10)
        )

        xp = u["xp"] + 10
        new_level = level(xp)

        save_user(
            u["id"],
            balance=u["balance"] - bet + win,
            xp=xp,
            level=new_level,
            spins=u["spins"] + 1,
            wins=u["wins"] + (1 if win else 0),
            best_win=max(u["best_win"], win)
        )

        add_task(
            u["id"],
            win
        )

        if jackpot_win:
            result = (
                "💎💎💎 7️⃣\n\n"
                "🎉 <b>ДЖЕКПОТ!</b>\n\n"
                f"+<b>{win}</b> 🪙"
            )

        elif win:
            result = (
                f"{' '.join(reels)}\n\n"
                f"🎉 Вы выиграли "
                f"<b>{win}</b> 🪙"
            )

        else:
            result = (
                f"{' '.join(reels)}\n\n"
                f"😢 Вы проиграли "
                f"<b>{bet}</b> 🪙"
            )

        u = get_user(callback.from_user)

        text = (
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"{result}\n\n"
            f"💰 Баланс: "
            f"<b>{u['balance']}</b> 🪙\n"
            f"⭐ Уровень: "
            f"<b>{u['level']}</b>\n"
            f"✨ XP: "
            f"<b>{u['xp'] % 100}/100</b>\n"
            f"💎 Джекпот: "
            f"<b>{get_jackpot()}</b> 🪙"
        )

        await callback.answer()

        await callback.message.edit_text(
            text,
            reply_markup=keyboard()
        )


    @dp.callback_query(F.data == "balance")
    async def balance_button(callback: CallbackQuery):

        u = get_user(callback.from_user)

        await callback.answer()

        await callback.message.edit_text(
            f"💰 <b>Баланс: "
            f"{u['balance']} 🪙</b>",
            reply_markup=keyboard()
        )


    @dp.callback_query(F.data == "bonus")
    async def bonus_button(callback: CallbackQuery):

        u = get_user(callback.from_user)

        if u["last_bonus"] == today():
            await callback.answer(
                "🎁 Бонус уже получен сегодня.",
                show_alert=True
            )
            return

        reward = 100 + u["level"] * 25

        save_user(
            u["id"],
            balance=u["balance"] + reward,
            last_bonus=today()
        )

        await callback.answer(
            f"🎁 +{reward} 🪙",
            show_alert=True
        )

        await callback.message.edit_text(
            game_text(get_user(callback.from_user)),
            reply_markup=keyboard()
        )


    @dp.callback_query(F.data == "top")
    async def top_button(callback: CallbackQuery):

        register(
            callback.message.chat.id,
            callback.from_user.id
        )

        await callback.answer()

        await callback.message.edit_text(
            top_text(
                callback.message.chat.id
            ),
            reply_markup=keyboard()
        )


    @dp.callback_query(F.data == "tasks")
    async def tasks_button(callback: CallbackQuery):

        u = get_user(callback.from_user)

        await callback.answer()

        await callback.message.edit_text(
            task_text(u["id"]),
            reply_markup=keyboard()
        )


    @dp.message()
    async def other(message: Message):

        get_user(message.from_user)

        register(
            message.chat.id,
            message.from_user.id
        )


    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

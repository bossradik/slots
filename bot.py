import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F, html
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties


# =========================
# НАСТРОЙКИ
# =========================

TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

DB = "slots.db"
MONEY = "💰"

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


if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")


# =========================
# DATABASE
# =========================

db = sqlite3.connect(
    DB,
    check_same_thread=False
)

db.row_factory = sqlite3.Row
lock = threading.Lock()


def today():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")


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
            day TEXT,
            spins INTEGER DEFAULT 0,
            won INTEGER DEFAULT 0,
            big INTEGER DEFAULT 0,
            claimed INTEGER DEFAULT 0,
            PRIMARY KEY(user_id,day)
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value INTEGER
        );

        INSERT OR IGNORE INTO settings
        VALUES('jackpot',5000);
        """)

        db.commit()


def get_user(tg):
    with lock:
        row = db.execute(
            "SELECT * FROM users WHERE id=?",
            (tg.id,)
        ).fetchone()

        if not row:
            db.execute(
                """
                INSERT INTO users(
                    id,username,name
                )
                VALUES(?,?,?)
                """,
                (
                    tg.id,
                    tg.username or "",
                    tg.first_name or "Игрок"
                )
            )
        else:
            db.execute(
                """
                UPDATE users
                SET username=?,name=?
                WHERE id=?
                """,
                (
                    tg.username or "",
                    tg.first_name or "Игрок",
                    tg.id
                )
            )

        db.commit()

        return dict(
            db.execute(
                "SELECT * FROM users WHERE id=?",
                (tg.id,)
            ).fetchone()
        )


def update_user(uid, **data):
    if not data:
        return

    with lock:
        db.execute(
            "UPDATE users SET "
            + ",".join(
                f"{key}=?"
                for key in data
            )
            + " WHERE id=?",
            [
                *data.values(),
                uid
            ]
        )

        db.commit()


def register_chat(chat_id, user_id):
    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO chats
            VALUES(?,?)
            """,
            (
                chat_id,
                user_id
            )
        )

        db.commit()


def get_jackpot():
    return db.execute(
        "SELECT value FROM settings WHERE key='jackpot'"
    ).fetchone()[0]


def set_jackpot(value):
    with lock:
        db.execute(
            """
            UPDATE settings
            SET value=?
            WHERE key='jackpot'
            """,
            (value,)
        )

        db.commit()


def get_level(xp):
    return xp // 100 + 1


# =========================
# KEYBOARDS
# =========================

def game_keyboard():
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
            ],
            [
                InlineKeyboardButton(
                    text="📖 Команды",
                    callback_data="help"
                )
            ]
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎰 Играть",
                    callback_data="back"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Топ",
                    callback_data="top"
                ),
                InlineKeyboardButton(
                    text="📖 Команды",
                    callback_data="help"
                )
            ]
        ]
    )


def top_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌍 Общий топ",
                    callback_data="top:global"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Монеты",
                    callback_data="top:balance"
                ),
                InlineKeyboardButton(
                    text="⭐ Уровень",
                    callback_data="top:level"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 Спины",
                    callback_data="top:spins"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Эта группа",
                    callback_data="top:group"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 Играть",
                    callback_data="back"
                )
            ]
        ]
    )


def task_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Забрать награды",
                    callback_data="claim"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 Играть",
                    callback_data="back"
                )
            ]
        ]
    )


# =========================
# TEXT
# =========================

def game_text(user):
    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"{MONEY} Баланс: "
        f"<b>{user['balance']}</b>\n"
        f"⭐ Уровень: "
        f"<b>{user['level']}</b>\n"
        f"✨ XP: "
        f"<b>{user['xp'] % 100}/100</b>\n"
        f"💎 Джекпот: "
        f"<b>{get_jackpot()}</b>\n\n"
        "Выбери ставку:"
    )


HELP = """
📖 <b>КОМАНДЫ</b>

<b>Основные:</b>

/start — запустить бота
/slots — открыть игру
/balance — баланс
/bonus — ежедневный бонус
/profile — профиль
/tasks — задания
/top — рейтинги
/help — помощь

👥 <b>ДЛЯ ГРУПП</b>

Добавьте бота в группу.

Используйте:

/slots
/balance
/bonus
/profile
/tasks
/top
/help

Игроки группы автоматически
попадают в рейтинг группы.

🎰 Каждый спин даёт +10 XP.
💰 Два одинаковых символа — x2.
💎 Три одинаковых — большой выигрыш.
7️⃣7️⃣7️⃣ — ДЖЕКПОТ.
"""


def tasks_text(uid):
    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO tasks(user_id,day)
            VALUES(?,?)
            """,
            (
                uid,
                today()
            )
        )

        db.commit()

        task = db.execute(
            """
            SELECT *
            FROM tasks
            WHERE user_id=? AND day=?
            """,
            (
                uid,
                today()
            )
        ).fetchone()

    return (
        "🎯 <b>ЗАДАНИЯ</b>\n\n"
        f"🎰 10 спинов: "
        f"<b>{min(task['spins'],10)}/10</b>"
        f" — +100 {MONEY}\n\n"
        f"💰 Выиграть 500: "
        f"<b>{min(task['won'],500)}/500</b>"
        f" — +200 {MONEY}\n\n"
        f"💎 Выигрыш 1000+: "
        f"<b>{min(task['big'],1)}/1</b>"
        f" — +500 {MONEY}"
    )


# =========================
# TOP
# =========================

def top_text(mode, chat_id=None):

    if mode == "group":
        rows = db.execute(
            """
            SELECT u.*
            FROM users u
            JOIN chats c ON u.id=c.user_id
            WHERE c.chat_id=?
            ORDER BY u.balance DESC
            LIMIT 10
            """,
            (chat_id,)
        ).fetchall()

        title = "👥 <b>ТОП ГРУППЫ</b>"

    elif mode == "level":
        rows = db.execute(
            """
            SELECT *
            FROM users
            ORDER BY level DESC,xp DESC
            LIMIT 10
            """
        ).fetchall()

        title = "⭐ <b>ТОП ПО УРОВНЮ</b>"

    elif mode == "spins":
        rows = db.execute(
            """
            SELECT *
            FROM users
            ORDER BY spins DESC
            LIMIT 10
            """
        ).fetchall()

        title = "🎰 <b>ТОП ПО СПИНАМ</b>"

    else:
        rows = db.execute(
            """
            SELECT *
            FROM users
            ORDER BY balance DESC
            LIMIT 10
            """
        ).fetchall()

        title = "🌍 <b>ТОП ПО МОНЕТАМ</b>"

    if not rows:
        return title + "\n\nПока игроков нет."

    result = [
        title,
        ""
    ]

    for number, row in enumerate(rows, 1):

        name = (
            "@"
            + row["username"]
            if row["username"]
            else html.quote(
                row["name"] or "Игрок"
            )
        )

        if mode == "level":
            value = f"{row['level']} ур."

        elif mode == "spins":
            value = f"{row['spins']} спинов"

        else:
            value = f"{row['balance']} {MONEY}"

        result.append(
            f"{number}. {name} — "
            f"<b>{value}</b>"
        )

    return "\n".join(result)


# =========================
# TASKS
# =========================

def add_task(uid, win):

    with lock:

        db.execute(
            """
            INSERT OR IGNORE INTO tasks(user_id,day)
            VALUES(?,?)
            """,
            (
                uid,
                today()
            )
        )

        db.execute(
            """
            UPDATE tasks
            SET
                spins=spins+1,
                won=won+?,
                big=big+?
            WHERE user_id=? AND day=?
            """,
            (
                win,
                1 if win >= 1000 else 0,
                uid,
                today()
            )
        )

        db.commit()


# =========================
# RENDER HEALTH SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"OK"
        )

    def log_message(self, *args):
        pass


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# =========================
# BOT
# =========================

async def main():

    init_db()

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )

    dp = Dispatcher()


    async def show_game(message):

        user = get_user(
            message.from_user
        )

        register_chat(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            game_text(user),
            reply_markup=game_keyboard()
        )


    # /start
    @dp.message(CommandStart())
    async def start(message: Message):

        await show_game(message)


    # /slots
    @dp.message(Command("slots"))
    async def slots(message: Message):

        await show_game(message)


    # /help
    @dp.message(Command("help"))
    async def help_command(message: Message):

        await message.answer(
            HELP,
            reply_markup=back_keyboard()
        )


    # /balance
    @dp.message(Command("balance"))
    async def balance(message: Message):

        user = get_user(
            message.from_user
        )

        await message.answer(
            f"{MONEY} Баланс: "
            f"<b>{user['balance']}</b>",
            reply_markup=game_keyboard()
        )


    # /bonus
    @dp.message(Command("bonus"))
    async def bonus(message: Message):

        user = get_user(
            message.from_user
        )

        if user["last_bonus"] == today():

            await message.answer(
                "🎁 Бонус уже получен сегодня.",
                reply_markup=game_keyboard()
            )

            return

        reward = 100 + user["level"] * 25

        update_user(
            user["id"],
            balance=user["balance"] + reward,
            last_bonus=today()
        )

        await message.answer(
            f"🎁 Бонус получен!\n\n"
            f"<b>+{reward} {MONEY}</b>",
            reply_markup=game_keyboard()
        )


    # /profile
    @dp.message(Command("profile"))
    async def profile(message: Message):

        user = get_user(
            message.from_user
        )

        await message.answer(
            "👤 <b>ПРОФИЛЬ</b>\n\n"
            f"Игрок: "
            f"<b>{html.quote(user['name'])}</b>\n"
            f"{MONEY} Монеты: "
            f"<b>{user['balance']}</b>\n"
            f"⭐ Уровень: "
            f"<b>{user['level']}</b>\n"
            f"🎰 Спины: "
            f"<b>{user['spins']}</b>\n"
            f"🏆 Победы: "
            f"<b>{user['wins']}</b>\n"
            f"💎 Лучший выигрыш: "
            f"<b>{user['best_win']}</b>",
            reply_markup=game_keyboard()
        )


    # /tasks
    @dp.message(Command("tasks"))
    async def tasks(message: Message):

        user = get_user(
            message.from_user
        )

        await message.answer(
            tasks_text(user["id"]),
            reply_markup=task_keyboard()
        )


    # /top
    @dp.message(Command("top"))
    async def top(message: Message):

        get_user(
            message.from_user
        )

        register_chat(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            top_text("global"),
            reply_markup=top_keyboard()
        )


    # =====================
    # SPIN
    # =====================

    @dp.callback_query(
        F.data.startswith("spin:")
    )
    async def spin(callback: CallbackQuery):

        bet = int(
            callback.data.split(":")[1]
        )

        user = get_user(
            callback.from_user
        )

        register_chat(
            callback.message.chat.id,
            callback.from_user.id
        )

        if bet not in BETS:

            await callback.answer(
                "Неверная ставка.",
                show_alert=True
            )

            return

        if user["balance"] < bet:

            await callback.answer(
                "❌ Недостаточно монет.",
                show_alert=True
            )

            return

        reels = [
            random.choice(SYMBOLS)
            for _ in range(3)
        ]

        triple = len(set(reels)) == 1
        pair = len(set(reels)) == 2

        win = 0

        if triple and reels[0] == "7️⃣":

            win = get_jackpot()

            set_jackpot(
                JACKPOT_START
            )

            result = "🎉 <b>ДЖЕКПОТ!</b>"

        elif triple:

            win = bet * MULT[reels[0]]

            result = "🎉 <b>ТРИ ОДИНАКОВЫХ!</b>"

        elif pair:

            win = bet * 2

            result = "🎉 <b>ДВА СОВПАДЕНИЯ!</b>"

        else:

            result = "😢 <b>Вы проиграли</b>"


        if not (
            triple
            and reels[0] == "7️⃣"
        ):

            set_jackpot(
                get_jackpot()
                + max(1, bet // 10)
            )


        xp = user["xp"] + 10

        update_user(
            user["id"],
            balance=user["balance"] - bet + win,
            xp=xp,
            level=get_level(xp),
            spins=user["spins"] + 1,
            wins=user["wins"] + (1 if win else 0),
            best_win=max(
                user["best_win"],
                win
            )
        )

        add_task(
            user["id"],
            win
        )

        user = get_user(
            callback.from_user
        )

        amount = win if win else bet

        sign = "+" if win else "-"

        text = (
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"{' '.join(reels)}\n\n"
            f"{result}\n"
            f"{sign}<b>{amount}</b> {MONEY}\n\n"
            f"{MONEY} Баланс: "
            f"<b>{user['balance']}</b>\n"
            f"⭐ Уровень: "
            f"<b>{user['level']}</b>\n"
            f"✨ XP: "
            f"<b>{user['xp'] % 100}/100</b>\n"
            f"💎 Джекпот: "
            f"<b>{get_jackpot()}</b>"
        )

        await callback.answer()

        await callback.message.edit_text(
            text,
            reply_markup=game_keyboard()
        )


    # =====================
    # BUTTONS
    # =====================

    @dp.callback_query(
        F.data == "balance"
    )
    async def balance_button(callback):

        user = get_user(
            callback.from_user
        )

        await callback.answer()

        await callback.message.edit_text(
            f"{MONEY} Баланс: "
            f"<b>{user['balance']}</b>",
            reply_markup=game_keyboard()
        )


    @dp.callback_query(
        F.data == "bonus"
    )
    async def bonus_button(callback):

        user = get_user(
            callback.from_user
        )

        if user["last_bonus"] == today():

            await callback.answer(
                "🎁 Бонус уже получен.",
                show_alert=True
            )

            return

        reward = 100 + user["level"] * 25

        update_user(
            user["id"],
            balance=user["balance"] + reward,
 

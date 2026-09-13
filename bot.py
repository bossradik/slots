import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties


TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB = "slots.db"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Render -> Environment.")

START_BALANCE = 1000
JACKPOT_START = 5000

BET_VALUES = (10, 25, 50, 100)

SYMBOLS = [
    "🍒",
    "🍋",
    "🍊",
    "🔔",
    "💎",
    "7️⃣",
]

MULT = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30,
    "7️⃣": 100,
}

lock = threading.RLock()

db = sqlite3.connect(
    DB,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def now():
    return datetime.now(timezone.utc)


def today():
    return now().strftime("%Y-%m-%d")


def init_db():
    with lock:
        db.executescript("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    balance INTEGER NOT NULL DEFAULT 1000,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    last_bonus TEXT DEFAULT '',
    bonus_streak INTEGER NOT NULL DEFAULT 0,
    spins INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    total_won INTEGER NOT NULL DEFAULT 0,
    best_win INTEGER NOT NULL DEFAULT 0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS achievements(
    user_id INTEGER NOT NULL,
    achievement_id TEXT NOT NULL,
    unlocked_at TEXT DEFAULT '',
    PRIMARY KEY(user_id, achievement_id)
);

CREATE TABLE IF NOT EXISTS daily_tasks(
    user_id INTEGER NOT NULL,
    task_date TEXT NOT NULL,
    spins INTEGER NOT NULL DEFAULT 0,
    won INTEGER NOT NULL DEFAULT 0,
    big_win INTEGER NOT NULL DEFAULT 0,
    spins_claimed INTEGER NOT NULL DEFAULT 0,
    won_claimed INTEGER NOT NULL DEFAULT 0,
    big_win_claimed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, task_date)
);

CREATE TABLE IF NOT EXISTS chat_members(
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY(chat_id, user_id)
);

INSERT OR IGNORE INTO settings(key,value)
VALUES('jackpot',5000);
""")

        db.commit()


def user(uid, username="", first_name=""):
    with lock:
        r = db.execute(
            "SELECT * FROM users WHERE user_id=?",
            (uid,)
        ).fetchone()

        if r is None:
            db.execute(
                """
                INSERT INTO users(
                    user_id,
                    username,
                    first_name,
                    balance,
                    created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    uid,
                    username or "",
                    first_name or "",
                    START_BALANCE,
                    now().isoformat(),
                )
            )

            db.commit()

            r = db.execute(
                "SELECT * FROM users WHERE user_id=?",
                (uid,)
            ).fetchone()

        elif (
            (username and r["username"] != username)
            or
            (first_name and r["first_name"] != first_name)
        ):
            db.execute(
                """
                UPDATE users
                SET username=?, first_name=?
                WHERE user_id=?
                """,
                (
                    username or r["username"],
                    first_name or r["first_name"],
                    uid,
                )
            )

            db.commit()

            r = db.execute(
                "SELECT * FROM users WHERE user_id=?",
                (uid,)
            ).fetchone()

        return dict(r)


def update(uid, **fields):
    allowed = {
        "username",
        "first_name",
        "balance",
        "xp",
        "level",
        "last_bonus",
        "bonus_streak",
        "spins",
        "wins",
        "total_won",
        "best_win",
        "current_streak",
        "best_streak",
    }

    fields = {
        k: v
        for k, v in fields.items()
        if k in allowed
    }

    if not fields:
        return

    sql = ",".join(
        f"{k}=?"
        for k in fields
    )

    with lock:
        db.execute(
            f"UPDATE users SET {sql} WHERE user_id=?",
            [*fields.values(), uid]
        )

        db.commit()


def register(chat_id, uid):
    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO chat_members(
                chat_id,
                user_id
            )
            VALUES(?,?)
            """,
            (chat_id, uid)
        )

        db.commit()


def name(u):
    if u["username"]:
        return "@" + u["username"]

    if u["first_name"]:
        return u["first_name"]

    return f"Игрок {u['user_id']}"


def level(xp):
    return xp // 100 + 1


def jackpot():
    with lock:
        r = db.execute(
            "SELECT value FROM settings WHERE key='jackpot'"
        ).fetchone()

        if r:
            return int(r["value"])

        return JACKPOT_START


def set_jackpot(value):
    with lock:
        db.execute(
            """
            INSERT INTO settings(key,value)
            VALUES('jackpot',?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
            """,
            (max(0, int(value)),)
        )

        db.commit()


ACH = {
    "first": ("🎰 Первый спин", 50),
    "100": ("🎯 100 спинов", 250),
    "1000": ("🔥 1000 спинов", 1000),
    "rich": ("💰 Богач", 500),
    "million": ("👑 Миллионер", 5000),
    "big": ("💎 Большой выигрыш", 500),
    "lucky": ("🍀 Счастливчик", 300),
    "jackpot": ("💎 Джекпот", 5000),
    "streak": ("🔥 Серия x5", 500),
    "level10": ("⭐ Уровень 10", 1000),
}


def unlock(uid, achievement_id):
    with lock:
        c = db.execute(
            """
            INSERT OR IGNORE INTO achievements(
                user_id,
                achievement_id,
                unlocked_at
            )
            VALUES(?,?,?)
            """,
            (
                uid,
                achievement_id,
                now().isoformat(),
            )
        )

        db.commit()

        return c.rowcount > 0


def check_ach(uid, lucky=False, jp=False):
    u = user(uid)

    ids = []

    if u["spins"] >= 1:
        ids.append("first")

    if u["spins"] >= 100:
        ids.append("100")

    if u["spins"] >= 1000:
        ids.append("1000")

    if u["balance"] >= 10000:
        ids.append("rich")

    if u["balance"] >= 100000:
        ids.append("million")

    if u["best_win"] >= 1000:
        ids.append("big")

    if lucky:
        ids.append("lucky")

    if jp:
        ids.append("jackpot")

    if u["best_streak"] >= 5:
        ids.append("streak")

    if u["level"] >= 10:
        ids.append("level10")

    result = []

    for achievement_id in ids:
        if unlock(uid, achievement_id):
            title, reward = ACH[achievement_id]

            u = user(uid)

            update(
                uid,
                balance=u["balance"] + reward
            )

            result.append(
                f"{title} — +{reward} 🪙"
            )

    return result


def task(uid):
    d = today()

    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                task_date
            )
            VALUES(?,?)
            """,
            (uid, d)
        )

        db.commit()

        return dict(
            db.execute(
                """
                SELECT *
                FROM daily_tasks
                WHERE user_id=?
                AND task_date=?
                """,
                (uid, d)
            ).fetchone()
        )


def task_add(uid, won=0, big=0):
    d = today()

    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                task_date
            )
            VALUES(?,?)
            """,
            (uid, d)
        )

        db.execute(
            """
            UPDATE daily_tasks
            SET
                spins=spins+1,
                won=won+?,
                big_win=big_win+?
            WHERE user_id=?
            AND task_date=?
            """,
            (
                won,
                big,
                uid,
                d,
            )
        )

        db.commit()


def claim(uid):
    t = task(uid)

    d = today()
    reward = 0

    with lock:

        if (
            t["spins"] >= 10
            and not t["spins_claimed"]
        ):
            reward += 100

            db.execute(
                """
                UPDATE daily_tasks
                SET spins_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (uid, d)
            )

        if (
            t["won"] >= 500
            and not t["won_claimed"]
        ):
            reward += 200

            db.execute(
                """
                UPDATE daily_tasks
                SET won_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (uid, d)
            )

        if (
            t["big_win"] >= 1
            and not t["big_win_claimed"]
        ):
            reward += 500

            db.execute(
                """
                UPDATE daily_tasks
                SET big_win_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (uid, d)
            )

        db.commit()

    if reward:
        u = user(uid)

        update(
            uid,
            balance=u["balance"] + reward
        )

    return reward


def task_text(uid):
    t = task(uid)

    return (
        "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n\n"

        f"{'✅' if t['spins_claimed'] else '⏳'} "
        f"🎰 10 спинов: "
        f"<b>{min(t['spins'],10)}/10</b> "
        f"— +100 🪙\n"

        f"{'✅' if t['won_claimed'] else '⏳'} "
        f"💰 Выиграть 500: "
        f"<b>{min(t['won'],500)}/500</b> "
        f"— +200 🪙\n"

        f"{'✅' if t['big_win_claimed'] else '⏳'} "
        f"💎 Выигрыш 1000+: "
        f"<b>{min(t['big_win'],1)}/1</b> "
        f"— +500 🪙\n\n"

        "Награды выдаются автоматически."
    )


def kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎰 КРУТИТЬ — 10",
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


def game(u):
    return (
        "🎰 <b>СЛОТЫ</b>\n\n"

        f"💰 Баланс: "
        f"<b>{u['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{u['level']}</b> | "
        f"XP: <b>{u['xp'] % 100}/100</b>\n"

        f"💎 Джекпот: "
        f"<b>{jackpot()}</b> 🪙\n\n"

        "Выбери ставку и крути!"
    )


def msg_user(message):
    u = user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or ""
    )

    register(
        message.chat.id,
        message.from_user.id
    )

    return u


def cb_user(callback):
    u = user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or ""
    )

    if callback.message:
        register(
            callback.message.chat.id,
            callback.from_user.id
        )

    return u


def top(chat_id=None):

    with lock:

        if chat_id and chat_id < 0:
            rows = db.execute(
                """
                SELECT u.*
                FROM users u
                JOIN chat_members c
                ON c.user_id=u.user_id
                WHERE c.chat_id=?
                ORDER BY u.balance DESC
                LIMIT 10
                """,
                (chat_id,)
            ).fetchall()

        else:
            rows = db.execute(
                """
                SELECT *
                FROM users
                ORDER BY balance DESC
                LIMIT 10
                """
            ).fetchall()

    if not rows:
        return "🏆 Пока игроков нет."

    title = (
        "🏆 <b>ТОП ГРУППЫ</b>"
        if chat_id and chat_id < 0
        else
        "🏆 <b>ТОП ИГРОКОВ</b>"
    )

    return (
        title
        + "\n\n"
        + "\n".join(
            f"{i}. {name(dict(r))} — "
            f"<b>{r['balance']}</b> 🪙"
            for i, r in enumerate(rows, 1)
        )
    )


def profile(u):
    return (
        "👤 <b>ПРОФИЛЬ</b>\n\n"

        f"Имя: <b>{name(u)}</b>\n"

        f"💰 Баланс: "
        f"<b>{u['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{u['level']}</b>\n"

        f"🎰 Спинов: "
        f"<b>{u['spins']}</b>\n"

        f"🏆 Побед: "
        f"<b>{u['wins']}</b>\n"

        f"💎 Лучший выигрыш: "
        f"<b>{u['best_win']}</b> 🪙\n"

        f"🔥 Лучшая серия: "
        f"<b>{u['best_streak']}</b>"
    )


async def spin(callback, bet):

    u = cb_user(callback)

    if bet not in BET_VALUES:
        return await callback.answer(
            "Неверная ставка.",
            show_alert=True
        )

    if u["balance"] < bet:
        return await callback.answer(
            "Недостаточно монет.",
            show_alert=True
        )

    reels = [
        random.choice(SYMBOLS)
        for _ in range(3)
    ]

    triple = (
        reels[0]
        == reels[1]
        == reels[2]
    )

    pair = len(set(reels)) == 2

    jackpot_win = (
        triple
        and reels[0] == "7️⃣"
    )

    win = 0

    if jackpot_win:

        win = jackpot()

        set_jackpot(
            JACKPOT_START
        )

    elif triple:

        win = (
            bet
            * MULT[reels[0]]
        )

    elif pair:

        win = bet * 2

    set_jackpot(
        jackpot()
        + max(1, bet // 10)
    )

    balance = (
        u["balance"]
        - bet
        + win
    )

    xp = u["xp"] + 10
    lv = level(xp)

    spins = u["spins"] + 1

    wins = (
        u["wins"]
        + (1 if win else 0)
    )

    best = max(
        u["best_win"],
        win
    )

    current_streak = (
        u["current_streak"] + 1
        if win
        else 0
    )

    best_streak = max(
        u["best_streak"],
        current_streak
    )

    update(
        u["user_id"],
        balance=balance,
        xp=xp,
        level=lv,
        spins=spins,
        wins=wins,
        total_won=u["total_won"] + win,
        best_win=best,
        current_streak=current_streak,
        best_streak=best_streak
    )

    task_add(
        u["user_id"],
        win,
        1 if win >= 1000 else 0
    )

    achievements = check_ach(
        u["user_id"],
        triple,
        jackpot_win
    )

    task_reward = claim(
        u["user_id"]
    )

    u = user(
        u["user_id"]
    )

    if jackpot_win:

        result = (
            "💎💎💎 7️⃣\n\n"
            "🎉 <b>ДЖЕКПОТ!</b> "
            f"+<b>{win}</b> 🪙"
        )

    elif win:

        result = (
            f"{' '.join(reels)}\n\n"
            "🎉 Вы выиграли "
            f"<b>{win}</b> 🪙"
        )

    else:

        result = (
            f"{' '.join(reels)}\n\n"
            "😢 Вы проиграли "
            f"<b>{bet}</b> 🪙"
        )

    extra = []

    if task_reward:
        extra.append(
            f"🎯 Задания: "
            f"+{task_reward} 🪙"
        )

    extra += achievements

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"

        f"{result}\n\n"

        f"💰 Баланс: "
        f"<b>{u['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{u['level']}</b> | "
        f"XP: <b>{u['xp'] % 100}/100</b>\n"

        f"💎 Джекпот: "
        f"<b>{jackpot()}</b> 🪙"
    )

    if extra:
        text += (
            "\n\n"
            + "\n".join(extra)
        )

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=kb()
    )


async def bonus(callback):

    u = cb_user(callback)

    if u["last_bonus"] == today():

        return await callback.answer(
            "🎁 Бонус уже получен сегодня.",
            show_alert=True
        )

    reward = (
        100
        + u["level"] * 25
    )

    update(
        u["user_id"],
        balance=u["balance"] + reward,
        last_bonus=today(),
        bonus_streak=u["bonus_streak"] + 1
    )

    await callback.answer(
        f"🎁 +{reward} 🪙",
        show_alert=True
    )

    await callback.message.edit_text(
        game(user(u["user_id"])),
        reply_markup=kb()
    )


def health():

    class H(BaseHTTPRequestHandler):

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

    HTTPServer(
        ("0.0.0.0", PORT),
        H
    ).serve_forever()


async def main():

    threading.Thread(
        target=health,
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

        await message.answer(
            game(msg_user(message)),
            reply_markup=kb()
        )


    @dp.message(Command("slots"))
    async def slots(message: Message):

        await message.answer(
            game(msg_user(message)),
            reply_markup=kb()
        )


    @dp.message(Command("balance"))
    async def balance(message: Message):

        u = msg_user(message)

        await message.answer(
            f"💰 Твой баланс: "
            f"<b>{u['balance']}</b> 🪙",
            reply_markup=kb()
        )


    @dp.message(Command("bonus"))
    async def bonus_cmd(message: Message):

        u = msg_user(message)

        if u["last_bonus"] == today():

            return await message.answer(
                "🎁 Сегодня бонус уже получен.",
                reply_markup=kb()
            )

        reward = (
            100
            + u["level"] * 25
        )

        update(
            u["user_id"],
            balance=u["balance"] + reward,
            last_bonus=today(),
            bonus_streak=u

import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "slots.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Render -> Environment.")

BET_VALUES = (10, 25, 50, 100)
SYMBOLS = ("🍒", "🍋", "🍊", "🔔", "💎", "7️⃣")
MULTIPLIERS = {"🍒": 5, "🍋": 7, "🍊": 10, "🔔": 15, "💎": 30, "7️⃣": 100}
START_BALANCE = 1000
JACKPOT_START = 5000

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.RLock()


def now():
    return datetime.now(timezone.utc)


def day():
    return now().strftime("%Y-%m-%d")


def init_db():
    with lock:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance INTEGER DEFAULT 1000,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                last_bonus TEXT DEFAULT '',
                bonus_streak INTEGER DEFAULT 0,
                spins INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                total_won INTEGER DEFAULT 0,
                best_win INTEGER DEFAULT 0,
                win_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                gear INTEGER DEFAULT 1
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                user_id INTEGER,
                task_day TEXT,
                spins INTEGER DEFAULT 0,
                won INTEGER DEFAULT 0,
                big_wins INTEGER DEFAULT 0,
                claimed_spins INTEGER DEFAULT 0,
                claimed_won INTEGER DEFAULT 0,
                claimed_big INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, task_day)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                name TEXT,
                PRIMARY KEY(user_id, name)
            )
        """)

        db.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES('jackpot', ?)",
            (JACKPOT_START,)
        )

        db.commit()


def ensure_columns():
    required = {
        "username": "TEXT DEFAULT ''",
        "first_name": "TEXT DEFAULT ''",
        "balance": "INTEGER DEFAULT 1000",
        "xp": "INTEGER DEFAULT 0",
        "level": "INTEGER DEFAULT 1",
        "last_bonus": "TEXT DEFAULT ''",
        "bonus_streak": "INTEGER DEFAULT 0",
        "spins": "INTEGER DEFAULT 0",
        "wins": "INTEGER DEFAULT 0",
        "total_won": "INTEGER DEFAULT 0",
        "best_win": "INTEGER DEFAULT 0",
        "win_streak": "INTEGER DEFAULT 0",
        "best_streak": "INTEGER DEFAULT 0",
        "gear": "INTEGER DEFAULT 1",
    }

    with lock:
        columns = {
            r["name"]
            for r in db.execute("PRAGMA table_info(users)")
        }

        for name, definition in required.items():
            if name not in columns:
                db.execute(
                    f"ALTER TABLE users ADD COLUMN {name} {definition}"
                )

        db.commit()


def get_user(user_id, username="", first_name=""):
    with lock:
        row = db.execute(
            "SELECT * FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        if row is None:
            db.execute(
                """
                INSERT INTO users(
                    user_id,
                    username,
                    first_name,
                    balance
                )
                VALUES(?,?,?,?)
                """,
                (
                    user_id,
                    username or "",
                    first_name or "",
                    START_BALANCE
                )
            )

            db.commit()

            row = db.execute(
                "SELECT * FROM users WHERE user_id=?",
                (user_id,)
            ).fetchone()

        else:
            db.execute(
                """
                UPDATE users
                SET username=?, first_name=?
                WHERE user_id=?
                """,
                (
                    username or row["username"],
                    first_name or row["first_name"],
                    user_id
                )
            )

            db.commit()

            row = db.execute(
                "SELECT * FROM users WHERE user_id=?",
                (user_id,)
            ).fetchone()

        return dict(row)


def update_user(user_id, **fields):
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
        "win_streak",
        "best_streak",
        "gear"
    }

    fields = {
        k: v
        for k, v in fields.items()
        if k in allowed
    }

    if not fields:
        return

    sql = ", ".join(
        f"{k}=?"
        for k in fields
    )

    values = list(fields.values())
    values.append(user_id)

    with lock:
        db.execute(
            f"""
            UPDATE users
            SET {sql}
            WHERE user_id=?
            """,
            values
        )

        db.commit()


def jackpot():
    with lock:
        row = db.execute(
            "SELECT value FROM settings WHERE key='jackpot'"
        ).fetchone()

        return int(row["value"])


def add_jackpot(amount):
    with lock:
        db.execute(
            """
            UPDATE settings
            SET value=value+?
            WHERE key='jackpot'
            """,
            (amount,)
        )

        db.commit()


def reset_jackpot():
    with lock:
        db.execute(
            """
            UPDATE settings
            SET value=?
            WHERE key='jackpot'
            """,
            (JACKPOT_START,)
        )

        db.commit()


def name(user):
    if user["username"]:
        return "@" + user["username"]

    return user["first_name"] or "Игрок"


def level(xp):
    return xp // 100 + 1


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎰 ИГРАТЬ",
                    callback_data="spin_menu"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 10",
                    callback_data="spin:10"
                ),
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
                    text="👤 Профиль",
                    callback_data="profile"
                ),
                InlineKeyboardButton(
                    text="🎁 Бонус",
                    callback_data="bonus"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📋 Задания",
                    callback_data="tasks"
                ),
                InlineKeyboardButton(
                    text="🏆 ТОП",
                    callback_data="top"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⛏️ Экипировка",
                    callback_data="gear"
                ),
                InlineKeyboardButton(
                    text="💎 Джекпот",
                    callback_data="jackpot"
                )
            ]
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ В меню",
                    callback_data="home"
                )
            ]
        ]
    )


def home_text(user):
    return (
        "🎰 СЛОТЫ\n\n"
        f"👤 {name(user)}\n"
        f"💰 Баланс: {user['balance']} 🪙\n"
        f"⭐ Уровень: {user['level']}\n"
        f"✨ XP: {user['xp'] % 100}/100\n"
        f"🎰 Спинов: {user['spins']}\n\n"
        "Выбери ставку или действие:"
    )


def profile_text(user):
    return (
        "👤 ПРОФИЛЬ\n\n"
        f"Имя: {name(user)}\n"
        f"💰 Баланс: {user['balance']} 🪙\n"
        f"⭐ Уровень: {user['level']}\n"
        f"✨ XP: {user['xp'] % 100}/100\n"
        f"🎰 Спинов: {user['spins']}\n"
        f"🏆 Побед: {user['wins']}\n"
        f"💎 Всего выиграно: {user['total_won']} 🪙\n"
        f"🔥 Серия: {user['win_streak']}\n"
        f"🏅 Лучшая серия: {user['best_streak']}\n"
        f"🥇 Лучший выигрыш: {user['best_win']} 🪙"
    )


def get_task(user_id):
    with lock:
        db.execute(
            """
            INSERT OR IGNORE INTO tasks(
                user_id,
                task_day
            )
            VALUES(?,?)
            """,
            (user_id, day())
        )

        db.commit()

        row = db.execute(
            """
            SELECT *
            FROM tasks
            WHERE user_id=?
            AND task_day=?
            """,
            (user_id, day())
        ).fetchone()

        return dict(row)


def task_update(user_id, spins=0, won=0, big=0):
    get_task(user_id)

    with lock:
        db.execute(
            """
            UPDATE tasks
            SET
                spins=spins+?,
                won=won+?,
                big_wins=big_wins+?
            WHERE user_id=?
            AND task_day=?
            """,
            (
                spins,
                won,
                big,
                user_id,
                day()
            )
        )

        db.commit()


def task_reward(user_id):
    task = get_task(user_id)
    reward = 0

    with lock:
        if task["spins"] >= 10 and not task["claimed_spins"]:
            reward += 100

            db.execute(
                """
                UPDATE tasks
                SET claimed_spins=1
                WHERE user_id=?
                AND task_day=?
                """,
                (user_id, day())
            )

        if task["won"] >= 500 and not task["claimed_won"]:
            reward += 200

            db.execute(
                """
                UPDATE tasks
                SET claimed_won=1
                WHERE user_id=?
                AND task_day=?
                """,
                (user_id, day())
            )

        if task["big_wins"] >= 1 and not task["claimed_big"]:
            reward += 500

            db.execute(
                """
                UPDATE tasks
                SET claimed_big=1
                WHERE user_id=?
                AND task_day=?
                """,
                (user_id, day())
            )

        db.commit()

    if reward:
        user = get_user(user_id)

        update_user(
            user_id,
            balance=user["balance"] + reward
        )

    return reward


def tasks_text(user_id):
    t = get_task(user_id)

    return (
        "📋 ЕЖЕДНЕВНЫЕ ЗАДАНИЯ\n\n"
        f"{'✅' if t['claimed_spins'] else '⏳'} "
        f"10 спинов: {min(t['spins'], 10)}/10 — +100 🪙\n"
        f"{'✅' if t['claimed_won'] else '⏳'} "
        f"Выиграть 500: {min(t['won'], 500)}/500 — +200 🪙\n"
        f"{'✅' if t['claimed_big'] else '⏳'} "
        f"Выигрыш 1000+: {min(t['big_wins'], 1)}/1 — +500 🪙"
    )


def claim_bonus(user_id):
    user = get_user(user_id)

    if user["last_bonus"] == day():
        return (
            0,
            user["bonus_streak"],
            user["balance"]
        )

    yesterday = (
        now() - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    if user["last_bonus"] == yesterday:
        streak = user["bonus_streak"] + 1
    else:
        streak = 1

    amount = (
        100
        + user["level"] * 25
        + min(streak, 7) * 10
    )

    new_balance = user["balance"] + amount

    update_user(
        user_id,
        balance=new_balance,
        last_bonus=day(),
        bonus_streak=streak
    )

    return (
        amount,
        streak,
        new_balance
    )


def achievement(user_id, key, reward):
    with lock:
        cur = db.execute(
            """
            INSERT OR IGNORE INTO achievements(
                user_id,
                name
            )
            VALUES(?,?)
            """,
            (user_id, key)
        )

        db.commit()

        new = cur.rowcount == 1

    if new:
        user = get_user(user_id)

        update_user(
            user_id,
            balance=user["balance"] + reward
        )

    return new


def check_achievements(user_id):
    user = get_user(user_id)
    messages = []

    checks = [
        (
            "first",
            user["spins"] >= 1,
            "🎰 Первый спин",
            50
        ),
        (
            "100",
            user["spins"] >= 100,
            "🎯 100 спинов",
            250
        ),
        (
            "1000",
            user["spins"] >= 1000,
            "🔥 1000 спинов",
            1000
        ),
        (
            "rich",
            user["balance"] >= 10000,
            "💰 10 000 монет",
            500
        ),
        (
            "big",
            user["best_win"] >= 1000,
            "💎 Выигрыш 1000+",
            500
        ),
        (
            "level10",
            user["level"] >= 10,
            "⭐ Уровень 10",
            1000
        )
    ]

    for key, ok, title, reward in checks:
        if ok and achievement(user_id, key, reward):
            messages.append(
                f"{title} — +{reward} 🪙"
            )

    return messages


def spin(user_id, bet):
    user = get_user(user_id)

    if bet not in BET_VALUES:
        return "❌ Неверная ставка."

    if user["balance"] < bet:
        return (
            f"❌ Недостаточно монет. "
            f"Нужно {bet} 🪙."
        )

    result = [
        random.choice(SYMBOLS)
        for _ in range(3)
    ]

    win = 0

    jackpot_win = (
        result == [
            "7️⃣",
            "7️⃣",
            "7️⃣"
        ]
    )

    if jackpot_win:
        win = jackpot()

    elif (
        result[0]
        == result[1]
        == result[2]
    ):
        win = (
            bet
            * MULTIPLIERS[result[0]]
        )

    elif (
        result[0] == result[1]
        or result[0] == result[2]
        or result[1] == result[2]
    ):
        win = bet * 2

    xp_gain = 10 + user["gear"]
    new_xp = user["xp"] + xp_gain
    new_level = level(new_xp)

    if win:
        streak = user["win_streak"] + 1
    else:
        streak = 0

    best_streak = max(
        user["best_streak"],
        streak
    )

    new_balance = (
        user["balance"]
        - bet
        + win
    )

    update_user(
        user_id,
        balance=new_balance,
        xp=new_xp,
        level=new_level,
        spins=user["spins"] + 1,
        wins=user["wins"] + (1 if win else 0),
        total_won=user["total_won"] + win,
        best_win=max(user["best_win"], win),
        win_streak=streak,
        best_streak=best_streak
    )

    add_jackpot(
        max(
            1,
            bet // 50
        )
    )

    if jackpot_win:
        reset_jackpot()
        achievement(
            user_id,
            "jackpot",
            5000
        )

    task_update(
        user_id,
        spins=1,
        won=win,
        big=int(win >= 1000)
    )

    reward = task_reward(user_id)
    achievements = check_achievements(user_id)

    if jackpot_win:
        title = "👑 ДЖЕКПОТ!!!"
    elif win:
        title = "🎉 ПОБЕДА!"
    else:
        title = "😔 Не повезло"

    text = (
        f"{title}\n\n"
        f"🎰 {' | '.join(result)}\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🏆 Выигрыш: {win} 🪙\n"
        f"⭐ +{xp_gain} XP\n"
        f"💳 Баланс: {new_balance} 🪙"
    )

    if new_level > user["level"]:
        text += (
            f"\n\n🆙 НОВЫЙ УРОВЕНЬ: "
            f"{new_level}!"
        )

    if streak >= 2:
        text += (
            f"\n🔥 Серия побед: "
            f"{streak}"
        )

    if reward:
        text += (
            f"\n🎁 Задания: "
            f"+{reward} 🪙"
        )

    if achievements:
        text += (
            "\n\n🏅 "
            + "\n🏅 ".join(achievements)
        )

    return text


def top_text():
    with lock:
        rows = db.execute(
            """
            SELECT *
            FROM users
            ORDER BY balance DESC, wins DESC
            LIMIT 10
            """
        ).fetchall()

    if not rows:
        return (
            "🏆 ТОП\n\n"
            "Пока игроков нет."
        )

    text = "🏆 ТОП ИГРОКОВ\n\n"
    medals = ("🥇", "🥈", "🥉")

    for i, row in enumerate(rows, 1):
        if i <= 3:
            prefix = medals[i - 1]
        else:
            prefix = f"{i}."

        text += (
            f"{prefix} "
            f"{name(dict(row))} — "
            f"{row['balance']} 🪙\n"
        )

    return text


def gear_text(user):
    cost = 500 * user["gear"]
    power = 1 + user["gear"]

    return (
        "⛏️ ЭКИПИРОВКА\n\n"
        f"Уровень: {user['gear']}\n"
        f"⚡ Сила: {power}\n"
        f"💰 Следующее улучшение: "
        f"{cost} 🪙"
    )


def gear_keyboard(user):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        f"⬆️ Улучшить за "
                        f"{500 * user['gear']} 🪙"
                    ),
                    callback_data="gear_up"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ В меню",
                    callback_data="home"
                )
            ]
        ]
    )


dp = Dispatcher()


@dp.message(Command("start"))
@dp.message(Command("slots"))
async def start(message: Message):
    user = get_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or ""
    )

    await message.answer(
        home_text(user),
        reply_markup=main_keyboard()
    )


@dp.message(Command("balance"))
async def balance(message: Message):
    user = get_user(
        message.from_user.id
    )

    await message.answer(
        f"💰 Твой баланс: "
        f"{user['balance']} 🪙",
        reply_markup=main_keyboard()
    )


@dp.message(Command("bonus"))
async def bonus_command(message: Message):
    amount, streak, balance_value = claim_bonus(
        message.from_user.id
    )

    if amount:
        text = (
            "🎁 БОНУС\n\n"
            f"+{amount} 🪙\n"
            f"🔥 Серия: {streak}\n"
            f"💰 Баланс: {balance_value} 🪙"
        )
    else:
        text = (
            "⏳ Бонус уже получен сегодня."
        )

    await message.answer(
        text,
        reply_markup=main_keyboard()
    )


@dp.message(Command("top"))
async def top_command(message: Message):
    await message.answer(
        top_text(),
        reply_markup=back_keyboard()
    )
    

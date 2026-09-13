import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Добавь BOT_TOKEN в Render -> Environment."
    )

PORT = int(os.getenv("PORT", "10000"))

DB_FILE = "slots.db"

START_BALANCE = 1000
JACKPOT_START = 5000
XP_PER_SPIN = 10

BET_VALUES = (10, 25, 50, 100)

SYMBOLS = [
    "🍒",
    "🍋",
    "🍊",
    "🔔",
    "💎",
    "7️⃣",
]

MULTIPLIERS = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30,
    "7️⃣": 100,
}


db_lock = threading.RLock()

conn = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

conn.row_factory = sqlite3.Row


def add_column_if_missing(table, column, definition):
    cols = {
        r["name"]
        for r in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
        conn.commit()


with db_lock:

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
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
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TEXT DEFAULT '',
            PRIMARY KEY (user_id, achievement_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_tasks (
            user_id INTEGER NOT NULL,
            task_date TEXT NOT NULL,
            spins INTEGER NOT NULL DEFAULT 0,
            won INTEGER NOT NULL DEFAULT 0,
            big_win INTEGER NOT NULL DEFAULT 0,
            spins_claimed INTEGER NOT NULL DEFAULT 0,
            won_claimed INTEGER NOT NULL DEFAULT 0,
            big_win_claimed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, task_date)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, user_id)
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


for col, definition in [
    ("first_name", "TEXT DEFAULT ''"),
    ("balance", "INTEGER NOT NULL DEFAULT 1000"),
    ("xp", "INTEGER NOT NULL DEFAULT 0"),
    ("level", "INTEGER NOT NULL DEFAULT 1"),
    ("last_bonus", "TEXT DEFAULT ''"),
    ("bonus_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("spins", "INTEGER NOT NULL DEFAULT 0"),
    ("wins", "INTEGER NOT NULL DEFAULT 0"),
    ("total_won", "INTEGER NOT NULL DEFAULT 0"),
    ("best_win", "INTEGER NOT NULL DEFAULT 0"),
    ("current_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("best_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("created_at", "TEXT DEFAULT ''"),
]:
    add_column_if_missing(
        "users",
        col,
        definition
    )


def now_utc():
    return datetime.now(timezone.utc)


def today():
    return now_utc().strftime("%Y-%m-%d")


def get_user(
    user_id,
    username="",
    first_name=""
):

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
                    first_name,
                    balance,
                    xp,
                    level,
                    created_at
                )
                VALUES(
                    ?,
                    ?,
                    ?,
                    ?,
                    0,
                    1,
                    ?
                )
                """,
                (
                    user_id,
                    username or "",
                    first_name or "",
                    START_BALANCE,
                    now_utc().isoformat()
                )
            )

            conn.commit()

        else:

            if (
                username != row["username"]
                or first_name != row["first_name"]
            ):

                conn.execute(
                    """
                    UPDATE users
                    SET username=?,
                        first_name=?
                    WHERE user_id=?
                    """,
                    (
                        username or "",
                        first_name or "",
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


def update_user(
    user_id,
    **fields
):

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
        "best_streak"
    }

    fields = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not fields:
        return

    sql = ", ".join(
        f"{key}=?"
        for key in fields
    )

    values = list(fields.values())
    values.append(user_id)

    with db_lock:

        conn.execute(
            f"""
            UPDATE users
            SET {sql}
            WHERE user_id=?
            """,
            values
        )

        conn.commit()


def register_member(
    chat_id,
    user_id
):

    with db_lock:

        conn.execute(
            """
            INSERT OR IGNORE INTO chat_members(
                chat_id,
                user_id
            )
            VALUES(?, ?)
            """,
            (
                chat_id,
                user_id
            )
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

        return int(
            row["value"]
        )


def set_jackpot(value):

    with db_lock:

        conn.execute(
            """
            UPDATE settings
            SET value=?
            WHERE key='jackpot'
            """,
            (
                max(
                    0,
                    int(value)
                ),
            )
        )

        conn.commit()


def level_from_xp(xp):

    return xp // 100 + 1


def xp_progress(xp):

    return xp % 100


def name_of(user):

    if user.get("username"):
        return "@" + user["username"]

    if user.get("first_name"):
        return user["first_name"]

    return (
        "Игрок "
        + str(user["user_id"] % 10000)
    )


ACHIEVEMENTS = {

    "first_spin": (
        "🎰 Первый спин",
        "Сделать первый спин",
        50
    ),

    "100_spins": (
        "🎯 100 спинов",
        "Сделать 100 спинов",
        250
    ),

    "1000_spins": (
        "🔥 1000 спинов",
        "Сделать 1000 спинов",
        1000
    ),

    "rich": (
        "💰 Богач",
        "Накопить 10 000 монет",
        500
    ),

    "very_rich": (
        "👑 Миллионер",
        "Накопить 100 000 монет",
        5000
    ),

    "big_win": (
        "💎 Большой выигрыш",
        "Выиграть 1000+ монет за спин",
        500
    ),

    "lucky": (
        "🍀 Счастливчик",
        "Получить три одинаковых",
        300
    ),

    "jackpot": (
        "💎 ДЖЕКПОТ",
        "Выиграть джекпот",
        5000
    ),

    "streak_5": (
        "🔥 Серия x5",
        "Пять побед подряд",
        500
    ),

    "level_10": (
        "⭐ Уровень 10",
        "Достичь 10 уровня",
        1000
    ),
}


def unlock(
    user_id,
    achievement_id
):

    with db_lock:

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO achievements(
                user_id,
                achievement_id,
                unlocked_at
            )
            VALUES(?, ?, ?)
            """,
            (
                user_id,
                achievement_id,
                now_utc().isoformat()
            )
        )

        conn.commit()

        return cursor.rowcount > 0


def achievements_for(user_id):

    with db_lock:

        rows = conn.execute(
            """
            SELECT achievement_id
            FROM achievements
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchall()

        return {
            row["achievement_id"]
            for row in rows
        }


def check_achievements(
    user_id,
    forced=()
):

    user = get_user(
        user_id
    )

    ids = set(
        forced
    )

    if user["spins"] >= 1:
        ids.add("first_spin")

    if user["spins"] >= 100:
        ids.add("100_spins")

    if user["spins"] >= 1000:
        ids.add("1000_spins")

    if user["balance"] >= 10000:
        ids.add("rich")

    if user["balance"] >= 100000:
        ids.add("very_rich")

    if user["best_win"] >= 1000:
        ids.add("big_win")

    if user["best_streak"] >= 5:
        ids.add("streak_5")

    if user["level"] >= 10:
        ids.add("level_10")

    result = []

    for achievement_id in ids:

        if achievement_id not in ACHIEVEMENTS:
            continue

        if unlock(
            user_id,
            achievement_id
        ):

            reward = ACHIEVEMENTS[
                achievement_id
            ][2]

            current = get_user(
                user_id
            )

            update_user(
                user_id,
                balance=(
                    current["balance"]
                    + reward
                )
            )

            result.append(
                f"{ACHIEVEMENTS[achievement_id][0]} "
                f"— +{reward} 🪙"
            )

    return result


def get_task(user_id):

    date = today()

    with db_lock:

        conn.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                task_date
            )
            VALUES(?, ?)
            """,
            (
                user_id,
                date
            )
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM daily_tasks
            WHERE user_id=?
            AND task_date=?
            """,
            (
                user_id,
                date
            )
        ).fetchone()

        return dict(row)


def update_task(
    user_id,
    spins=0,
    won=0,
    big=0
):

    date = today()

    with db_lock:

        conn.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                task_date
            )
            VALUES(?, ?)
            """,
            (
                user_id,
                date
            )
        )

        conn.execute(
            """
            UPDATE daily_tasks
            SET
                spins=spins+?,
                won=won+?,
                big_win=big_win+?
            WHERE user_id=?
            AND task_date=?
            """,
            (
                spins,
                won,
                big,
                user_id,
                date
            )
        )

        conn.commit()


def claim_tasks(user_id):

    task = get_task(
        user_id
    )

    reward = 0

    date = today()

    with db_lock:

        if (
            task["spins"] >= 10
            and not task["spins_claimed"]
        ):

            reward += 100

            conn.execute(
                """
                UPDATE daily_tasks
                SET spins_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (
                    user_id,
                    date
                )
            )

        if (
            task["won"] >= 500
            and not task["won_claimed"]
        ):

            reward += 200

            conn.execute(
                """
                UPDATE daily_tasks
                SET won_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (
                    user_id,
                    date
                )
            )

        if (
            task["big_win"] >= 1
            and not task["big_win_claimed"]
        ):

            reward += 500

            conn.execute(
                """
                UPDATE daily_tasks
                SET big_win_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (
                    user_id,
                    date
                )
            )

        conn.commit()

    if reward:

        user = get_user(
            user_id
        )

        update_user(
            user_id,
            balance=(
                user["balance"]
                + reward
            )
        )

    return reward


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
                    text="📊 Профиль",
                    callback_data="profile"
                ),

                InlineKeyboardButton(
                    text="🎯 Задания",
                    callback_data="tasks"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏅 Достижения",
                    callback_data="achievements"
                ),

                InlineKeyboardButton(
                    text="💎 Джекпот",
                    callback_data="jackpot"
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


def top_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="💰 Баланс",
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
                ),

                InlineKeyboardButton(
                    text="🏆 Выигрыши",
                    callback_data="top:wins"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home"
                )
            ]
        ]
    )


def welcome(user):

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"

        "Добро пожаловать в игру!\n\n"

        f"💰 Баланс: "
        f"<b>{user['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{user['level']}</b>\n"

        f"✨ XP: "
        f"<b>{xp_progress(user['xp'])}/100</b>\n"

        f"🎯 Спинов: "
        f"<b>{user['spins']}</b>\n\n"

        "Выбери ставку и крути барабаны! 🎰"
    )


def profile_text(user_id):

    user = get_user(
        user_id
    )

    return (
        "📊 <b>ПРОФИЛЬ</b>\n\n"

        f"👤 {name_of(user)}\n"

        f"💰 Баланс: "
        f"<b>{user['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{user['level']}</b>\n"

        f"✨ XP: "
        f"<b>{xp_progress(user['xp'])}/100</b>\n"

        f"🎰 Спинов: "
        f"<b>{user['spins']}</b>\n"

        f"🏆 Побед: "
        f"<b>{user['wins']}</b>\n"

        f"💵 Всего выиграно: "
        f"<b>{user['total_won']}</b> 🪙\n"

        f"💎 Лучший выигрыш: "
        f"<b>{user['best_win']}</b> 🪙\n"

        f"🔥 Серия: "
        f"<b>{user['current_streak']}</b>\n"

        f"🔥 Лучшая серия: "
        f"<b>{user['best_streak']}</b>\n"

        f"🏅 Достижений: "
        f"<b>{len(achievements_for(user_id))}</b>"
    )


def tasks_text(user_id):

    task = get_task(
        user_id
    )

    return (
        "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n\n"

        f"{'✅' if task['spins_claimed'] else '⏳'} "
        f"🎰 10 спинов: "
        f"<b>{min(task['spins'], 10)}/10</b> "
        f"— +100 🪙\n\n"

        f"{'✅' if task['won_claimed'] else '⏳'} "
        f"💰 Выиграть 500: "
        f"<b>{min(task['won'], 500)}/500</b> "
        f"— +200 🪙\n\n"

        f"{'✅' if task['big_win_claimed'] else '⏳'} "
        f"💎 Выигрыш 1000+: "
        f"<b>{min(task['big_win'], 1)}/1</b> "
        f"— +500 🪙"
    )


def achievements_text(user_id):

    unlocked = achievements_for(
        user_id
    )

    lines = [
        "🏅 <b>ДОСТИЖЕНИЯ</b>\n"
    ]

    for achievement_id, data in ACHIEVEMENTS.items():

        title = data[0]
        description = data[1]
        reward = data[2]

        mark = (
            "✅"
            if achievement_id in unlocked
            else "🔒"
        )

        lines.append(
            f"{mark} <b>{title}</b>\n"
            f"{description}\n"
            f"🎁 +{reward} 🪙"
        )

    return "\n\n".join(
        lines
    )


def jackpot_text():

    return (
        "💎 <b>ДЖЕКПОТ</b>\n\n"

        f"💰 Сейчас: "
        f"<b>{get_jackpo

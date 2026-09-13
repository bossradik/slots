import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
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


# =========================================================
# НАСТРОЙКИ
# =========================================================

ENV = {
    str(k).strip(): str(v).strip()
    for k, v in os.environ.items()
}

BOT_TOKEN = ENV.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Добавь BOT_TOKEN в Render -> Environment."
    )

PORT = int(os.environ.get("PORT", "10000"))

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


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

db_lock = threading.RLock()

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
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TEXT DEFAULT '',

            PRIMARY KEY (
                user_id,
                achievement_id
            )
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            user_id INTEGER NOT NULL,
            task_date TEXT NOT NULL,

            spins INTEGER NOT NULL DEFAULT 0,
            won INTEGER NOT NULL DEFAULT 0,
            big_win INTEGER NOT NULL DEFAULT 0,

            spins_claimed INTEGER NOT NULL DEFAULT 0,
            won_claimed INTEGER NOT NULL DEFAULT 0,
            big_win_claimed INTEGER NOT NULL DEFAULT 0,

            PRIMARY KEY (
                user_id,
                task_date
            )
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            PRIMARY KEY (
                chat_id,
                user_id
            )
        )
    """)

    conn.execute(
        """
        INSERT OR IGNORE INTO settings(
            key,
            value
        )
        VALUES(
            'jackpot',
            ?
        )
        """,
        (JACKPOT_START,)
    )

    conn.commit()


# =========================================================
# ВРЕМЯ
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def today():
    return now_utc().strftime("%Y-%m-%d")


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

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
                    now_utc().isoformat(),
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

        else:

            changed = False

            if username and row["username"] != username:

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

                changed = True

            if first_name and row["first_name"] != first_name:

                conn.execute(
                    """
                    UPDATE users
                    SET first_name=?
                    WHERE user_id=?
                    """,
                    (
                        first_name,
                        user_id
                    )
                )

                changed = True

            if changed:
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
        "best_streak",
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


def register_chat_member(
    chat_id,
    user_id
):

    if chat_id is None:
        return

    with db_lock:

        conn.execute(
            """
            INSERT OR IGNORE INTO chat_members(
                chat_id,
                user_id
            )
            VALUES(
                ?,
                ?
            )
            """,
            (
                chat_id,
                user_id
            )
        )

        conn.commit()


def display_name(user):

    if user.get("username"):
        return "@" + user["username"]

    if user.get("first_name"):
        return user["first_name"]

    return "Игрок " + str(user["user_id"])[-4:]


def user_from_message(message):

    user = get_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or ""
    )

    register_chat_member(
        message.chat.id,
        message.from_user.id
    )

    return user


def user_from_callback(callback):

    user = get_user(
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.first_name or ""
    )

    if callback.message:
        register_chat_member(
            callback.message.chat.id,
            callback.from_user.id
        )

    return user


# =========================================================
# УРОВНИ
# =========================================================

def level_from_xp(xp):
    return xp // 100 + 1


def xp_progress(xp):
    return xp % 100


# =========================================================
# ДЖЕКПОТ
# =========================================================

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


# =========================================================
# ДОСТИЖЕНИЯ
# =========================================================

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
        "Выиграть 1000+ монет за один спин",
        500
    ),

    "lucky": (
        "🍀 Счастливчик",
        "Получить три одинаковых символа",
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


def has_achievement(
    user_id,
    achievement_id
):

    with db_lock:

        row = conn.execute(
            """
            SELECT 1
            FROM achievements
            WHERE user_id=?
            AND achievement_id=?
            """,
            (
                user_id,
                achievement_id
            )
        ).fetchone()

        return row is not None


def unlock_achievement(
    user_id,
    achievement_id
):

    if achievement_id not in ACHIEVEMENTS:
        return False

    with db_lock:

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO achievements(
                user_id,
                achievement_id,
                unlocked_at
            )
            VALUES(
                ?,
                ?,
                ?
            )
            """,
            (
                user_id,
                achievement_id,
                now_utc().isoformat()
            )
        )

        conn.commit()

        return cursor.rowcount > 0


def check_achievements(
    user_id,
    force_ids=None
):

    user = get_user(user_id)

    ids = set(force_ids or [])

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

    messages = []

    for achievement_id in ids:

        if achievement_id not in ACHIEVEMENTS:
            continue

        if unlock_achievement(
            user_id,
            achievement_id
        ):

            reward = ACHIEVEMENTS[
                achievement_id
            ][2]

            current = get_user(user_id)

            update_user(
                user_id,
                balance=current["balance"] + reward
            )

            title = ACHIEVEMENTS[
                achievement_id
            ][0]

            messages.append(
                f"{title} — +{reward} 🪙"
            )

    return messages


def get_achievement_ids(
    user_id
):

    with db_lock:

        rows = conn.execute(
            """
            SELECT achievement_id
            FROM achievements
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchall()

    return [
        row["achievement_id"]
        for row in rows
    ]


# =========================================================
# ЕЖЕДНЕВНЫЕ ЗАДАНИЯ
# =========================================================

def get_daily_task(
    user_id
):

    current_day = today()

    with db_lock:

        conn.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                task_date
            )
            VALUES(
                ?,
                ?
            )
            """,
            (
                user_id,
                current_day
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
                current_day
            )
        ).fetchone()

    return dict(row)


def update_daily_task(
    user_id,
    spins=0,
    won=0,
    big_win=0
):

    current_day = today()

    with db_lock:

        conn.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                task_date
            )
            VALUES(
                ?,
                ?
            )
            """,
            (
                user_id,
                current_day
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
                big_win,
                user_id,
                current_day
            )
        )

        conn.commit()


def claim_daily_task_rewards(
    user_id
):

    task = get_daily_task(user_id)

    reward = 0

    if (
        task["spins"] >= 10
        and task["spins_claimed"] == 0
    ):

        reward += 100

        with db_lock:

            conn.execute(
                """
                UPDATE daily_tasks
                SET spins_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (
                    user_id,
                    today()
                )
            )

            conn.commit()

    if (
        task["won"] >= 500
        and task["won_claimed"] == 0
    ):

        reward += 200

        with db_lock:

            conn.execute(
                """
                UPDATE daily_tasks
                SET won_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (
                    user_id,
                    today()
                )
            )

            conn.commit()

    if (
        task["big_win"] >= 1
        and task["big_win_claimed"] == 0
    ):

        reward += 500

        with db_lock:

            conn.execute(
                """
                UPDATE daily_tasks
                SET big_win_claimed=1
                WHERE user_id=?
                AND task_date=?
                """,
                (
                    user_id,
                    today()
                )
            )

            conn.commit()

    if reward:

        user = get_user(user_id)

        update_user(
            user_id,
            balance=user["balance"] + reward
        )

    return reward


def tasks_text(
    user_id
):

    task = get_daily_task(user_id)

    spins = min(
        task["spins"],
        10
    )

    won = min(
        task["won"],
        500
    )

    big_win = min(
        task["big_win"],
        1
    )

    spin_mark = (
        "✅"
        if task["spins_claimed"]
        else "⏳"
    )

    won_mark = (
        "✅"
        if task["won_claimed"]
        else "⏳"
    )

    big_mark = (
        "✅"
        if task["big_win_claimed"]
        else "⏳"
    )

    return (
        "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n\n"

        f"{spin_mark} 🎰 Сделать 10 спинов: "
        f"<b>{spins}/10</b>\n"
        "🎁 Награда: <b>+100</b> 🪙\n\n"

        f"{won_mark} 💰 Выиграть 500 монет: "
        f"<b>{won}/500</b>\n"
        "🎁 Награда: <b>+200</b> 🪙\n\n"

        f"{big_mark} 💎 Выигрыш 1000+: "
        f"<b>{big_win}/1</b>\n"
        "🎁 Награда: <b>+500</b> 🪙\n\n"

        "Награды выдаются автоматически."
    )


# =========================================================
# КНОПКИ
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
            ],
        ]
    )


def top_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="💰 Баланс",
                    callback_data="top:balance"
   

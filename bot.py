import os
import asyncio
import random
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "slots.db"

START_BALANCE = 1000
JACKPOT_START = 5000

BET_VALUES = (
    10,
    25,
    50,
    100
)

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


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден в Render -> Environment."
    )


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

db_lock = threading.RLock()

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


with db_lock:

    db.execute(
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
            pickaxe INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT ''
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            PRIMARY KEY(user_id, achievement_id)
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_tasks (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            spins INTEGER DEFAULT 0,
            won INTEGER DEFAULT 0,
            big_win INTEGER DEFAULT 0,
            spins_claimed INTEGER DEFAULT 0,
            won_claimed INTEGER DEFAULT 0,
            big_win_claimed INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, day)
        )
        """
    )

    db.execute(
        """
        INSERT OR IGNORE INTO settings(key, value)
        VALUES('jackpot', ?)
        """,
        (JACKPOT_START,)
    )

    db.commit()


# =========================================================
# МИГРАЦИЯ СТАРОЙ БАЗЫ
# =========================================================

def ensure_column(
    name,
    definition
):

    with db_lock:

        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        if name not in columns:

            db.execute(
                f"""
                ALTER TABLE users
                ADD COLUMN {name} {definition}
                """
            )

            db.commit()


old_columns = [
    (
        "username",
        "TEXT DEFAULT ''"
    ),
    (
        "first_name",
        "TEXT DEFAULT ''"
    ),
    (
        "balance",
        "INTEGER NOT NULL DEFAULT 1000"
    ),
    (
        "xp",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "level",
        "INTEGER NOT NULL DEFAULT 1"
    ),
    (
        "last_bonus",
        "TEXT DEFAULT ''"
    ),
    (
        "bonus_streak",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "spins",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "wins",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "total_won",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "best_win",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "current_streak",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "best_streak",
        "INTEGER NOT NULL DEFAULT 0"
    ),
    (
        "pickaxe",
        "INTEGER NOT NULL DEFAULT 1"
    ),
    (
        "created_at",
        "TEXT DEFAULT ''"
    )
]


for column_name, column_definition in old_columns:

    ensure_column(
        column_name,
        column_definition
    )


# =========================================================
# ВРЕМЯ
# =========================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def current_day():

    return utc_now().strftime(
        "%Y-%m-%d"
    )


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

def get_user(
    user_id,
    username="",
    first_name=""
):

    with db_lock:

        row = db.execute(
            """
            SELECT *
            FROM users
            WHERE user_id=?
            """,
            (user_id,)
        ).fetchone()

        if row is None:

            db.execute(
                """
                INSERT INTO users(
                    user_id,
                    username,
                    first_name,
                    balance,
                    xp,
                    level,
                    pickaxe,
                    created_at
                )
                VALUES(
                    ?,
                    ?,
                    ?,
                    ?,
                    0,
                    1,
                    1,
                    ?
                )
                """,
                (
                    user_id,
                    username or "",
                    first_name or "",
                    START_BALANCE,
                    utc_now().isoformat()
                )
            )

            db.commit()

            row = db.execute(
                """
                SELECT *
                FROM users
                WHERE user_id=?
                """,
                (user_id,)
            ).fetchone()

        else:

            changed = False

            if username:

                if row["username"] != username:

                    db.execute(
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

            if first_name:

                if row["first_name"] != first_name:

                    db.execute(
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

                db.commit()

                row = db.execute(
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
        "pickaxe"
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

    values = list(
        fields.values()
    )

    values.append(
        user_id
    )

    with db_lock:

        db.execute(
            f"""
            UPDATE users
            SET {columns}
            WHERE user_id=?
            """,
            values
        )

        db.commit()


def display_name(user):

    if user.get("username"):

        return "@" + user["username"]

    if user.get("first_name"):

        return user["first_name"]

    return (
        "Игрок "
        + str(user["user_id"])[-4:]
    )


# =========================================================
# XP И УРОВЕНЬ
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

        row = db.execute(
            """
            SELECT value
            FROM settings
            WHERE key='jackpot'
            """
        ).fetchone()

        if row is None:

            db.execute(
                """
                INSERT INTO settings(
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

            db.commit()

            return JACKPOT_START

        return int(
            row["value"]
        )


def set_jackpot(value):

    with db_lock:

        db.execute(
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

        db.commit()


def add_jackpot(value):

    set_jackpot(
        get_jackpot()
        + int(value)
    )


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def main_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎰 ИГРАТЬ",
                    callback_data="menu:spin"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Ставка 10",
                    callback_data="bet:10"
                ),
                InlineKeyboardButton(
                    text="💰 Ставка 25",
                    callback_data="bet:25"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Ставка 50",
                    callback_data="bet:50"
                ),
                InlineKeyboardButton(
                    text="💰 Ставка 100",
                    callback_data="bet:100"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👤 Профиль",
                    callback_data="menu:profile"
                ),
                InlineKeyboardButton(
                    text="🎁 Бонус",
                    callback_data="menu:bonus"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📋 Задания",
                    callback_data="menu:tasks"
                ),
                InlineKeyboardButton(
                    text="🏆 Топ",
                    callback_data="menu:top"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⛏️ Экипировка",
                    callback_data="menu:gear"
                ),
                InlineKeyboardButton(
                    text="💎 Джекпот",
                    callback_data="menu:jackpot"
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
                    callback_data="menu:home"
                )
            ]
        ]
    )


def spin_keyboard():

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
                    text="⬅️ В меню",
                    callback_data="menu:home"
                )
            ]
        ]
    )


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

def home_text(user):

    return (
        "🎰 <b>СЛОТЫ</b>\n\n"

        f"👤 {escape(display_name(user))}\n"

        f"💰 Баланс: "
        f"<b>{user['balance']}</b> 🪙\n"

        f"⭐ Уровень: "
        f"<b>{user['level']}</b>\n"

        f"✨ XP: "
        f"<b>{xp_progress(user['xp'])}/100</b>\n"

        f"🎰 Спинов: "
        f"<b>{user['spins']}</b>\n\n"

        "Выбери действие:"
    )


# =========================================================
# ПРОФИЛЬ
# =========================================================

def profile_text(user):

    return (
        "👤 <b>ПРОФИЛЬ</b>\n\n"

        f"Имя: "
        f"<b>{escape(display_name(user))}</b>\n\n"

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

        f"💎 Всего выиграно: "
        f"<b>{user['total_won']}</b> 🪙\n"

        f"🔥 Серия побед: "
        f"<b>{user['current_streak']}</b>\n"

        f"🏅 Лучшая серия: "
        f"<b>{user['best_streak']}</b>\n"

        f"🥇 Лучший выигрыш: "
        f"<b>{user['best_win']}</b> 🪙"
    )


# =========================================================
# ЭКИПИРОВКА
# =========================================================

def gear_text(user):

    level = user["pickaxe"]

    cost = 500 * level

    power = 1 + level

    return (
        "⛏️ <b>ЭКИПИРОВКА</b>\n\n"

        f"⛏️ Уровень: "
        f"<b>{level}</b>\n"

        f"⚡ Сила: "
        f"<b>{power}</b>\n"

        f"💰 Следующее улучшение: "
        f"<b>{cost}</b> 🪙\n\n"

        "Улучшение даёт больше XP "
        "за каждый спин."
    )


def gear_keyboard(user):

    cost = 500 * user["pickaxe"]

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=f"⬆️ Улучшить за {cost} 🪙",
                    callback_data="gear:up"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅️ В меню",
                    callback_data="menu:home"
                )
            ]
        ]
    )


# =========================================================
# ДОСТИЖЕНИЯ
# =========================================================

ACHIEVEMENTS = {

    "first":
        (
            "🎰 Первый спин",
            50
        ),

    "100":
        (
            "🎯 100 спинов",
            250
        ),

    "1000":
        (
            "🔥 1000 спинов",
            1000
        ),

    "rich":
        (
            "💰 10 000 монет",
            500
        ),

    "big":
        (
            "💎 Выигрыш 1000+",
            500
        ),

    "jackpot":
        (
            "👑 Джекпот",
            5000
        ),

    "level10":
        (
            "⭐ Уровень 10",
            1000
        )
}


def unlock_achievement(
    user_id,
    achievement_id
):

    if achievement_id not in ACHIEVEMENTS:

        return False

    with db_lock:

        cursor = db.execute(
            """
            INSERT OR IGNORE INTO achievements(
                user_id,
                achievement_id
            )
            VALUES(
                ?,
                ?
            )
            """,
            (
                user_id,
                achievement_id
            )
        )

        db.commit()

        return cursor.rowcount > 0


def check_achievements(
    user_id
):

    user = get_user(
        user_id
    )

    ids = []

    if user["spins"] >= 1:
        ids.append("first")

    if user["spins"] >= 100:
        ids.append("100")

    if user["spins"] >= 1000:
        ids.append("1000")

    if user["balance"] >= 10000:
        ids.append("rich")

    if user["best_win"] >= 1000:
        ids.append("big")

    if user["level"] >= 10:
        ids.append("level10")

    messages = []

    for achievement_id in ids:

        if unlock_achievement(
            user_id,
            achievement_id
        ):

            reward = ACHIEVEMENTS[
                achievement_id
            ][1]

            current = get_user(
                user_id
            )

            update_user(
                user_id,
                balance=current["balance"] + reward
            )

            messages.append(
                f"{ACHIEVEMENTS[achievement_id][0]} "
                f"— +{reward} 🪙"
            )

    return messages


# =========================================================
# ЕЖЕДНЕВНЫЕ ЗАДАНИЯ
# =========================================================

def get_daily_task(
    user_id
):

    today = current_day()

    with db_lock:

        db.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                day
            )
            VALUES(
                ?,
                ?
            )
            """,
            (
                user_id,
                today
            )
        )

        db.commit()

        row = db.execute(
            """
            SELECT *
            FROM daily_tasks
            WHERE user_id=?
            AND day=?
            """,
            (
                user_id,
                today
            )
        ).fetchone()

    return dict(row)


def update_daily_task(
    user_id,
    spins=0,
    won=0,
    big_win=0
):

    today = current_day()

    with db_lock:

        db.execute(
            """
            INSERT OR IGNORE INTO daily_tasks(
                user_id,
                day
            )
            VALUES(
                ?,
                ?
            )
            """,
            (
                user_id,
                today
            )
        )

        db.execute(
            """
            UPDATE daily_tasks
            SET
                spins=spins+?,
                won=won+?,
                big_win=big_win+?
            WHERE user_id=?
            AND day=?
            """,
            (
                spins,
                won,
                big_win,
                user_id,
     

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

START = 1000
JACKPOT_START = 5000

MONEY = "💰"


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


def user(tg):
    with lock:
        r = db.execute(
            "SELECT * FROM users WHERE id=?",
            (tg.id,)
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
                    tg.id,
                    tg.username or "",
                    tg.first_name or "",
                    START
                )
            )
            db.commit()

        else:
            db.execute(
                """
                UPDATE users
                SET username=?,name=?
                WHERE id=?
                """,
                (
                    tg.username or "",
                    tg.first_name or "",
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


def save(uid, **data):
    if not data:
        return

    with lock:
        db.execute(
            "UPDATE users SET "
            + ",".join(f"{k}=?" for k in data)
            + " WHERE id=?",
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


def jackpot():
    return db.execute(
        "SELECT value FROM settings WHERE key='jackpot'"
    ).fetchone()["value"]


def set_jackpot(value):
    with lock:
        db.execute(
            "UPDATE settings SET value=? WHERE key='jackpot'",
            (value,)
        )

        db.commit()


def lvl(xp):
    return xp // 100 + 1


def game_kb():
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


def back_kb():
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


def task_kb():
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


def top_menu():
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
                    text="💰 По монетам",
                    callback_data="top:balance"
                ),
                InlineKeyboardButton(
                    text="⭐ По уровню",
                    callback_data="top:level"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 По спинам",
                    callback_data="top:spins"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Топ этой группы",
                    callback_data="top:group"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 Играть",
                    callback_data="back"
                ),
                InlineKeyboardButton(
                    text="📖 Команды",
                    callback_data="help"
                )
            ]
        ]
    )


def game_text(u):
    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"{MONEY} Баланс: <b>{u['balance']}</b>\n"
        f"⭐ Уровень: <b>{u['level']}</b>\n"
        f"✨ XP: <b>{u['xp'] % 100}/100</b>\n"
        f"💎 Джекпот: <b>{jackpot()}</b>\n\n"
        "Выбери ставку:"
    )


def help_text():
    return (
        "📖 <b>КОМАНДЫ И ПОМОЩЬ</b>\n\n"

        "<b>Основные:</b>\n"
        "/start — запустить бота\n"
        "/slots — открыть игру\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/profile — профиль\n"
        "/tasks — задания\n"
        "/top — рейтинги\n"
        "/help — помощь\n\n"

        "<b>👥 В группе:</b>\n"
        "Добавьте бота в группу и используйте /slots.\n"
        "Работают /balance, /bonus, /profile, /tasks, /top и /help.\n"
        "Игроки группы автоматически попадают в рейтинг этой группы.\n\n"

        "🎰 Каждый спин даёт +10 XP.\n"
        "💎 Три 7️⃣ — джекпот.\n"
        "💰 Два одинаковых символа — x2."
    )


def top_text(mode, chat_id=None):

    if mode == "group":

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

        title = "👥 <b>ТОП ЭТОЙ ГРУППЫ</b>"

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

    out = [title, ""]

    for i, r in enumerate(rows, 1):

        name = (
            "@" + r["username"]
            if r["username"]
            else html.quote(r["name"] or "Игрок")
        )

        if mode == "level":
            value = f"{r['level']} ур."

        elif mode == "spins":
            value = f"{r['spins']} спинов"

        else:
            value = f"{r['balance']} {MONEY}"

        out.append(
            f"{i}. {name} — <b>{value}</b>"
        )

    return "\n".join(out)


def ensure_task(uid):

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

        return db.execute(
            """
            SELECT *
            FROM tasks
            WHERE user_id=? AND date=?
            """,
            (uid, d)
        ).fetchone()


def task_text(uid):

    t = ensure_task(uid)

    return (
        "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n\n"

        f"🎰 10 спинов: "
        f"<b>{min(t['spins'],10)}/10</b> "
        f"— +100 {MONEY}\n"

        f"💰 Выиграть 500: "
        f"<b>{min(t['won'],500)}/500</b> "
        f"— +200 {MONEY}\n"

        f"💎 Выигрыш 1000+: "
        f"<b>{min(t['big'],1)}/1</b> "
        f"— +500 {MONEY}\n\n"

        "Награды можно забрать после выполнения."
    )


def add_task(uid, win):

    d = today()

    ensure_task(uid)

    with lock:

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


def health():

    class H(BaseHTTPRequestHandler):

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
        H
    ).serve_forever()


async def main():

    init_db()

    threading.Thread(
        target=health,
        daemon=True
    ).start()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )

    # Убираем старый webhook перед polling
    await bot.delete_webhook(
        drop_pending_updates=False
    )

    dp = Dispatcher()


    async def show_game(message):

        u = user(message.from_user)

        register(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            game_text(u),
            reply_markup=game_kb()
        )


    # START
    @dp.message(CommandStart())
    async def start(message: Message):

        await show_game(message)


    # SLOTS
    @dp.message(Command("slots"))
    async def slots(message: Message):

        await show_game(message)


    # HELP
    @dp.message(Command("help"))
    async def help_cmd(message: Message):

        await message.answer(
            help_text(),
            reply_markup=back_kb()
        )


    # BALANCE
    @dp.message(Command("balance"))
    async def balance(message: Message):

        u = user(message.from_user)

        await message.answer(
            f"{MONEY} <b>Баланс: "
            f"{u['balance']}</b>",
            reply_markup=game_kb()
        )


    # BONUS
    @dp.message(Command("bonus"))
    async def bonus(message: Message):

        u = user(message.from_user)

        if u["last_bonus"] == today():

            await message.answer(
                "🎁 Бонус уже получен сегодня.",
                reply_markup=game_kb()
            )

            return

        reward = 100 + u["level"] * 25

        save(
            u["id"],
            balance=u["balance"] + reward,
            last_bonus=today()
        )

        await message.answer(
            f"🎁 Бонус получен!\n\n"
            f"<b>+{reward} {MONEY}</b>",
            reply_markup=game_kb()
        )


    # PROFILE
    @dp.message(Command("profile"))
    async def profile(message: Message):

        u = user(message.from_user)

        await message.answer(
            "👤 <b>ПРОФИЛЬ</b>\n\n"
            f"Игрок: "
            f"<b>{html.quote(u['name'])}</b>\n"
            f"{MONEY} Баланс: "
            f"<b>{u['balance']}</b>\n"
            f"⭐ Уровень: "
            f"<b>{u['level']}</b>\n"
            f"🎰 Спинов: "
            f"<b>{u['spins']}</b>\n"
            f"🏆 Побед: "
            f"<b>{u['wins']}</b>\n"
            f"💎 Лучший выигрыш: "
            f"<b>{u['best_win']}</b>",
            reply_markup=game_kb()
        )


    # TASKS
    @dp.message(Command("tasks"))
    async def tasks(message: Message):

        await message.answer(
            task_text(
                user(message.from_user)["id"]
            ),
            reply_markup=task_kb()
        )


    # TOP
    @dp.message(Command("top"))
    async def top(message: Message):

        user(message.from_user)

        register(
            message.chat.id,
            message.from_user.id
        )

        await message.answer(
            top_text("global"),
            reply_markup=top_menu()
        )


    # SPIN
    @dp.callback_query(F.data.startswith("spin:"))
    async def spin(c: CallbackQuery):

        bet = int(
            c.data.split(":")[1]
        )

        u = user(c.from_user)

        register(
            c.message.chat.id,
            c.from_user.id
        )

        if bet not in BETS:

            await c.answer(
                "Неверная ставка.",
                show_alert=True
            )

            return

        if u["balance"] < bet:

            await c.answer(
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

        jackpot_win = (
            triple and reels[0] == "7️⃣"
        )

        if jackpot_win:

            win = jackpot()

            set_jackpot(
                JACKPOT_START
            )

        elif triple:

            win = bet * MULT[reels[0]]

        elif pair:

            win = bet * 2

        set_jackpot(
            jackpot() + max(1, bet // 10)
        )

        xp = u["xp"] + 10

        save(
            u["id"],
            balance=u["balance"] - bet + win,
            xp=xp,
            level=lvl(xp),
            spins=u["spins"] + 1,
            wins=u["wins"] + bool(win),
            best_win=max(
                u["best_win"],
                win
            )
        )

        add_task(
            u["id"],
            win
        )

        if jackpot_win:

            result = (
                "🎉 <b>ДЖЕКПОТ!</b>\n\n"
            )

        elif win:

            result = (
                "🎉 Вы выиграли\n\n"
            )

        else:

            result = (
                "😢 Вы проиграли\n\n"
            )

        result += (
            f"{' '.join(reels)}\n\n"
        )

        if win:

            result += (
                f"+<b>{win}</b> {MONEY}"
            )

        else:

            result += (
                f"-<b>{bet}</b> {MONEY}"
            )

        u = user(c.from_user)

        text = (
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"{result}\n\n"
            f"{MONEY} Баланс: "
            f"<b>{u['balance']}</b>\n"
            f"⭐ Уровень: "
            f"<b>{u['level']}</b>\n"
            f"✨ XP: "
            f"<b>{u['xp'] % 100}/100</b>\n"
            f"💎 Джекпот: "
            f"<b>{jackpot()}</b>"
        )

        await c.answer()

        await c.message.edit_text(
            text,
            reply_markup=game_kb()
        )


    # BALANCE BUTTON
    @dp.callback_query(F.data == "balance")
    async def balance_btn(c: CallbackQuery):

        await c.answer()

        await c.message.edit_text(
            f"{MONEY} <b>Баланс: "
            f"{user(c.from_user)['balance']}</b>",
            reply_markup=game_kb()
        )


    # BONUS BUTTON
    @dp.callback_query(F.data == "bonus")
    async def bonus_btn(c: CallbackQuery):

        u = user(c.from_user)

        if u["last_bonus"] == today():

            await c.answer(
                "🎁 Бонус уже получен сегодня.",
                show_alert=True
            )

            return

        reward = 100 + u["level"] * 25

        save(
            u["id"],
            balance=u["balance"] + reward,
            last_bonus=today()
        )

        await c.answer(
            f"🎁 +{reward} {MONEY}",
            show_alert=True
        )

        await c.message.edit_text(
            game_text(
                user(c.from_user)
            ),
            reply_markup=game_kb()
        )


    # HELP BUTTON
    @dp.callback_query(F.data == "help")
    async def help_btn(c: CallbackQuery):

        await c.answer()

        await c.message.edit_text(
            help_text(),
            reply_markup=back_kb()
        )


    # BACK
    @dp.callback_query(F.data == "back")
    async def back(c: CallbackQuery):

        await c.answer()

        await c.message.edit_text(
            game_text(
                user(c.from_user)
            ),
            reply_markup=game_kb()
        )


    # TOP BUTTON
    @dp.callback_query(F.data == "top")
    async def top_btn(c: CallbackQuery):

        await c.answer()

        await c.message.edit_text(
            top_text("global"),
            reply_markup=top_menu()
        )


    # TOP CH

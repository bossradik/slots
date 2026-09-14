import os
import sqlite3
import random
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

TOKEN = os.getenv("BOT_TOKEN")
DB = "slots.db"

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]

MULT = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30,
    "7️⃣": 100
}

BET_LIST = [10, 25, 50, 100]


def db():
    return sqlite3.connect(DB)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        balance INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best_win INTEGER DEFAULT 0,
        bet INTEGER DEFAULT 10,
        bonus_day TEXT DEFAULT '',
        wheel_day TEXT DEFAULT '',
        mission_day TEXT DEFAULT '',
        mission_spins INTEGER DEFAULT 0,
        mission_wins INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY,
        title TEXT,
        spins INTEGER DEFAULT 0,
        coins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_users(
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(chat_id,user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS duels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user1 INTEGER,
        user2 INTEGER,
        bet INTEGER,
        status TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        owner INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clan_users(
        clan_id INTEGER,
        user_id INTEGER UNIQUE
    )
    """)

    con.commit()
    con.close()


def register_user(user, chat=None):
    con = db()
    cur = con.cursor()

    name = user.full_name or "Игрок"
    username = user.username or ""

    cur.execute(
        "INSERT OR IGNORE INTO users(id,username,name) VALUES(?,?,?)",
        (user.id, username, name)
    )

    cur.execute(
        "UPDATE users SET username=?, name=? WHERE id=?",
        (username, name, user.id)
    )

    if chat:
        cur.execute(
            "INSERT OR IGNORE INTO chats(id,title) VALUES(?,?)",
            (chat.id, chat.title or "Чат")
        )
        cur.execute(
            "INSERT OR IGNORE INTO chat_users(chat_id,user_id) VALUES(?,?)",
            (chat.id, user.id)
        )

    con.commit()
    con.close()


def get_user(uid):
    con = db()
    row = con.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()
    con.close()
    return row


def update_user(uid, field, value):
    allowed = {
        "balance", "xp", "spins", "wins", "best_win",
        "bet", "bonus_day", "wheel_day", "mission_day",
        "mission_spins", "mission_wins"
    }

    if field not in allowed:
        return

    con = db()
    con.execute(
        f"UPDATE users SET {field}=? WHERE id=?",
        (value, uid)
    )
    con.commit()
    con.close()


def add_xp(uid, amount):
    u = get_user(uid)
    if not u:
        return

    update_user(uid, "xp", u[4] + amount)


def level(uid):
    u = get_user(uid)
    if not u:
        return 1
    return u[4] // 100 + 1


def main_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(text="🎰 Слоты", callback_data="game")
    kb.button(text="👤 Профиль", callback_data="profile")

    kb.button(text="🏆 Топ", callback_data="top")
    kb.button(text="🔢 Комбинации", callback_data="combos")

    kb.button(text="🎲 Дуэль", callback_data="duel")
    kb.button(text="📋 Миссии", callback_data="missions")

    kb.button(text="🎡 Колесо", callback_data="wheel")
    kb.button(text="⏰ Счастливый час", callback_data="happy")

    kb.button(text="👥 Группа", callback_data="group")
    kb.button(text="🏅 Достижения", callback_data="achievements")

    kb.adjust(2)
    return kb.as_markup()


def game_keyboard(uid):
    u = get_user(uid)
    bet = u[8] if u else 10

    kb = InlineKeyboardBuilder()

    kb.button(text=f"🎰 КРУТИТЬ • {bet} 💰", callback_data="spin")
    kb.button(text="💰 10", callback_data="bet:10")
    kb.button(text="💰 25", callback_data="bet:25")
    kb.button(text="💰 50", callback_data="bet:50")
    kb.button(text="💰 100", callback_data="bet:100")
    kb.button(text="🔙 Меню", callback_data="menu")

    kb.adjust(1, 4, 1)
    return kb.as_markup()


async def game_screen(message, uid):
    u = get_user(uid)
    if not u:
        return

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{u[3]}</b>\n"
        f"⭐ Уровень: <b>{level(uid)}</b>\n"
        f"✨ XP: <b>{u[4]}</b>\n"
        f"🎯 Ставка: <b>{u[8]}</b> 💰\n\n"
        "Выбери ставку один раз и крути снова."
    )

    await message.edit_text(
        text,
        reply_markup=game_keyboard(uid)
    )


@dp.message(CommandStart())
async def start(message: Message):
    register_user(message.from_user, message.chat)

    await message.answer(
        "🎰 <b>Добро пожаловать в СЛОТЫ!</b>\n\n"
        "Крути барабаны, выигрывай 💰, "
        "повышай уровень и попадай в топ!\n\n"
        "Выбирай действие:",
        reply_markup=main_keyboard()
    )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    register_user(message.from_user, message.chat)

    await message.answer(
        "📖 <b>КОМАНДЫ</b>\n\n"
        "/start — главное меню\n"
        "/slots — открыть слоты\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/top — рейтинг\n"
        "/profile — профиль\n"
        "/group — статистика группы\n"
        "/pay 100 — перевод игроку ответом\n"
        "/help — помощь"
    )


@dp.message(Command("slots"))
async def slots_cmd(message: Message):
    register_user(message.from_user, message.chat)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Текущая ставка сохранится.\n"
        "Можно просто нажимать «КРУТИТЬ» снова.",
        reply_markup=game_keyboard(message.from_user.id)
    )


@dp.message(Command("balance"))
async def balance_cmd(message: Message):
    register_user(message.from_user, message.chat)
    u = get_user(message.from_user.id)

    await message.answer(
        f"💰 Твой баланс: <b>{u[3]}</b>\n"
        f"⭐ Уровень: <b>{level(message.from_user.id)}</b>\n"
        f"✨ XP: <b>{u[4]}</b>"
    )


@dp.message(Command("profile"))
async def profile_cmd(message: Message):
    register_user(message.from_user, message.chat)
    await show_profile(message, message.from_user.id)


async def show_profile(message, uid):
    u = get_user(uid)
    if not u:
        return

    await message.answer(
        "👤 <b>ПРОФИЛЬ ИГРОКА</b>\n\n"
        f"👤 {u[2]}\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💰 Баланс: <b>{u[3]}</b>\n"
        f"⭐ Уровень: <b>{level(uid)}</b>\n"
        f"✨ XP: <b>{u[4]}</b>\n"
        f"🎰 Круток: <b>{u[5]}</b>\n"
        f"🏆 Побед: <b>{u[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[7]}</b>\n"
        f"🎯 Текущая ставка: <b>{u[8]}</b> 💰",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "menu")
async def menu_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    await call.answer()
    await call.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\nВыбери действие:",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "game")
async def game_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    await call.answer()
    await game_screen(call.message, call.from_user.id)


@dp.callback_query(F.data.startswith("bet:"))
async def bet_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    bet = int(call.data.split(":")[1])
    update_user(call.from_user.id, "bet", bet)

    await call.answer(f"Ставка: {bet} 💰")
    await game_screen(call.message, call.from_user.id)


async def slot_animation(message, uid):
    frames = [
        "🎰 <b>КРУТИМ...</b>\n\n❓ | ❓ | ❓",
        "🎰 <b>КРУТИМ...</b>\n\n🍒 | ❓ | ❓",
        "🎰 <b>КРУТИМ...</b>\n\n🍒 | 🔔 | ❓",
        "🎰 <b>КРУТИМ...</b>\n\n🍒 | 🔔 | 💎"
    ]

    for frame in frames:
        try:
            await message.edit_text(frame)
        except Exception:
            pass

        await asyncio.sleep(0.25)


def spin_result():
    return [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]


def calculate_win(result, bet):
    a, b, c = result

    if a == b == c:
        return bet * MULT[a]

    if a == b or a == c or b == c:
        return bet * 2

    return 0


@dp.callback_query(F.data == "spin")
async def spin_callback(call: CallbackQuery):
    uid = call.from_user.id
    register_user(call.from_user, call.message.chat)

    u = get_user(uid)
    bet = u[8]

    if u[3] < bet:
        await call.answer("❌ Недостаточно монет!", show_alert=True)
        return

    update_user(uid, "balance", u[3] - bet)
    update_user(uid, "spins", u[5] + 1)
    add_xp(uid, 10)

    await call.answer()
    await slot_animation(call.message, uid)

    result = spin_result()
    win = calculate_win(result, bet)

    u = get_user(uid)

    if win > 0:
        update_user(uid, "balance", u[3] + win)
        update_user(uid, "wins", u[6] + 1)

        if win > u[7]:
            update_user(uid, "best_win", win)

        text = (
            "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"{result[0]} | {result[1]} | {result[2]}\n\n"
            f"🎉 <b>ВЫИГРЫШ: +{win} 💰</b>\n"
        )

        if result[0] == result[1] == result[2] == "7️⃣":
            text += "\n💎💎💎 <b>ДЖЕКПОТ!</b> 💎💎💎"

    else:
        text = (
            "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"{result[0]} | {result[1]} | {result[2]}\n\n"
            f"😢 Проигрыш: <b>-{bet} 💰</b>"
        )

    u = get_user(uid)

    text += (
        f"\n\n💰 Баланс: <b>{u[3]}</b>"
        f"\n⭐ Уровень: <b>{level(uid)}</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"🎰 КРУТИТЬ ЕЩЁ • {bet} 💰", callback_data="spin")
    kb.button(text="🎯 Изменить ставку", callback_data="game")
    kb.button(text="🔙 Меню", callback_data="menu")
    kb.adjust(1)

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )
    @dp.message(Command("bonus"))
async def bonus_cmd(message: Message):
    register_user(message.from_user, message.chat)

    uid = message.from_user.id
    u = get_user(uid)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if u[9] == today:
        await message.answer("🎁 Ты уже забрал ежедневный бонус сегодня!")
        return

    reward = 100 + level(uid) * 25

    update_user(uid, "balance", u[3] + reward)
    update_user(uid, "bonus_day", today)

    await message.answer(
        f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"Ты получил <b>+{reward} 💰</b>!"
    )


@dp.callback_query(F.data == "profile")
async def profile_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()
    await show_profile(call.message, call.from_user.id)


@dp.callback_query(F.data == "combos")
async def combos_callback(call: CallbackQuery):
    await call.answer()

    text = (
        "🔢 <b>КОМБИНАЦИИ</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — x100 💎\n\n"
        "Любые 2 одинаковых символа — x2"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "top")
async def top_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)
    await call.answer()

    con = db()

    rows = con.execute(
        """
        SELECT name,balance,spins,wins
        FROM users
        ORDER BY balance DESC
        LIMIT 10
        """
    ).fetchall()

    con.close()

    text = "🏆 <b>ТОП ЛУДИКОВ ПО МОНЕТАМ</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += (
            f"{i}. {row[0]} — "
            f"<b>{row[1]} 💰</b>\n"
        )

    if not rows:
        text += "Пока никого нет."

    kb = InlineKeyboardBuilder()
    kb.button(text="💰 По монетам", callback_data="top_money")
    kb.button(text="🎰 По круткам", callback_data="top_spins")
    kb.button(text="🏆 По победам", callback_data="top_wins")
    kb.button(text="💎 Лучшие выигрыши", callback_data="top_best")
    kb.button(text="🔙 Назад", callback_data="menu")
    kb.adjust(2, 2, 1)

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


async def show_top(call, mode):
    con = db()

    if mode == "money":
        rows = con.execute(
            "SELECT name,balance FROM users ORDER BY balance DESC LIMIT 10"
        ).fetchall()
        title = "💰 ТОП ПО МОНЕТАМ"

    elif mode == "spins":
        rows = con.execute(
            "SELECT name,spins FROM users ORDER BY spins DESC LIMIT 10"
        ).fetchall()
        title = "🎰 ТОП ПО КРУТКАМ"

    elif mode == "wins":
        rows = con.execute(
            "SELECT name,wins FROM users ORDER BY wins DESC LIMIT 10"
        ).fetchall()
        title = "🏆 ТОП ПО ПОБЕДАМ"

    else:
        rows = con.execute(
            "SELECT name,best_win FROM users ORDER BY best_win DESC LIMIT 10"
        ).fetchall()
        title = "💎 ТОП ЛУЧШИХ ВЫИГРЫШЕЙ"

    con.close()

    text = f"🏆 <b>{title}</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]} — <b>{row[1]}</b>\n"

    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Монеты", callback_data="top_money")
    kb.button(text="🎰 Крутки", callback_data="top_spins")
    kb.button(text="🏆 Победы", callback_data="top_wins")
    kb.button(text="💎 Лучший выигрыш", callback_data="top_best")
    kb.button(text="🔙 Назад", callback_data="menu")
    kb.adjust(2, 2, 1)

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "top_money")
async def top_money(call: CallbackQuery):
    await call.answer()
    await show_top(call, "money")


@dp.callback_query(F.data == "top_spins")
async def top_spins(call: CallbackQuery):
    await call.answer()
    await show_top(call, "spins")


@dp.callback_query(F.data == "top_wins")
async def top_wins(call: CallbackQuery):
    await call.answer()
    await show_top(call, "wins")


@dp.callback_query(F.data == "top_best")
async def top_best(call: CallbackQuery):
    await call.answer()
    await show_top(call, "best")


@dp.callback_query(F.data == "achievements")
async def achievements_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    uid = call.from_user.id
    u = get_user(uid)

    achievements = []

    if u[5] >= 1:
        achievements.append("🎰 Первая крутка")

    if u[5] >= 100:
        achievements.append("🎰 100 круток")

    if u[6] >= 10:
        achievements.append("🏆 10 побед")

    if u[3] >= 10000:
        achievements.append("💰 10 000 монет")

    if u[7] >= 1000:
        achievements.append("💎 Большой выигрыш")

    if level(uid) >= 10:
        achievements.append("⭐ 10 уровень")

    text = "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"

    if achievements:
        text += "\n".join(
            "✅ " + x for x in achievements
        )
    else:
        text += "🔒 Пока нет открытых достижений."

    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="🔙 Назад", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "missions")
async def missions_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    uid = call.from_user.id
    u = get_user(uid)

    text = (
        "📋 <b>МИССИИ</b>\n\n"
        f"🎰 Сделать 10 круток: "
        f"<b>{min(u[11], 10)}/10</b>\n"
        f"🏆 Получить 3 победы: "
        f"<b>{min(u[12], 3)}/3</b>\n\n"
        "Награда за выполнение:\n"
        "💰 <b>250 монет</b>"
    )

    if u[11] >= 10 and u[12] >= 3:
        text += "\n\n🎉 <b>МИССИИ ВЫПОЛНЕНЫ!</b>"

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "wheel")
async def wheel_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    uid = call.from_user.id
    u = get_user(uid)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if u[10] == today:
        await call.answer(
            "🎡 Ты уже крутил колесо сегодня!",
            show_alert=True
        )
        return

    rewards = [50, 100, 150, 250, 500, 1000]
    reward = random.choice(rewards)

    update_user(uid, "balance", u[3] + reward)
    update_user(uid, "wheel_day", today)

    await call.answer()

    await call.message.edit_text(
        "🎡 <b>КОЛЕСО УДАЧИ</b>\n\n"
        "🎡 Крутим...\n"
        "🔄 🔄 🔄"
    )

    await asyncio.sleep(1)

    await call.message.edit_text(
        "🎡 <b>КОЛЕСО УДАЧИ</b>\n\n"
        f"🎉 Тебе выпало <b>+{reward} 💰</b>!"
    )


@dp.callback_query(F.data == "happy")
async def happy_callback(call: CallbackQuery):
    await call.answer()

    hour = datetime.now(timezone.utc).hour

    if hour in [18, 19, 20]:
        text = (
            "⏰ <b>СЧАСТЛИВЫЙ ЧАС</b>\n\n"
            "🔥 Сейчас действует счастливый час!\n"
            "Шанс на хороший результат повышен."
        )
    else:
        text = (
            "⏰ <b>СЧАСТЛИВЫЙ ЧАС</b>\n\n"
            "Сейчас счастливый час не активен.\n"
            "Приходи вечером!"
        )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "group")
async def group_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    chat = call.message.chat

    if chat.type == "private":
        await call.answer(
            "👥 Этот раздел работает в группе.",
            show_alert=True
        )
        return

    con = db()

    row = con.execute(
        """
        SELECT title,spins,coins,wins
        FROM chats
        WHERE id=?
        """,
        (chat.id,)
    ).fetchone()

    members = con.execute(
        "SELECT COUNT(*) FROM chat_users WHERE chat_id=?",
        (chat.id,)
    ).fetchone()[0]

    con.close()

    if not row:
        title = chat.title or "Группа"
        spins = coins = wins = 0
    else:
        title, spins, coins, wins = row

    text = (
        f"👥 <b>{title}</b>\n\n"
        f"👤 Игроков: <b>{members}</b>\n"
        f"🎰 Круток: <b>{spins}</b>\n"
        f"🏆 Побед: <b>{wins}</b>\n"
        f"💰 Монет выиграно: <b>{coins}</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Топ группы", callback_data="group_top")
    kb.button(text="🔙 Назад", callback_data="menu")
    kb.adjust(1)

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "group_top")
async def group_top_callback(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    con = db()

    rows = con.execute(
        """
        SELECT u.name,u.balance
        FROM users u
        JOIN chat_users c ON c.user_id=u.id
        WHERE c.chat_id=?
        ORDER BY u.balance DESC
        LIMIT 10
        """,
        (call.message.chat.id,)
    ).fetchall()

    con.close()

    text = "🏆 <b>ТОП ГРУППЫ</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]} — <b>{row[1]} 💰</b>\n"

    if not rows:
        text += "Пока игроков нет."

    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Статистика", callback_data="group")
    kb.button(text="🔙 Назад", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "duel")
async def duel_callback(call: CallbackQuery):
    await call.answer()

    text = (
        "🎲 <b>ДУЭЛЬ</b>\n\n"
        "Сыграй с другим игроком.\n\n"
        "Для создания дуэли:\n"
        "<code>/duel 100</code>\n\n"
        "После этого соперник сможет принять вызов."
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="menu")

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )


@dp.message(Command("duel"))
async def duel_cmd(message: Message):
    register_user(message.from_user, message.chat)

    args = message.text.split()

    if len(args) < 2:
        await message.answer(
            "🎲 Используй:\n"
            "<code>/duel 100</code>"
        )
        return

    try:
        bet = int(args[1])
    except ValueError:
        await message.answer("❌ Неверная ставка.")
        return

    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше нуля.")
        return

    u = get_user(message.from_user.id)

    if u[3] < bet:
        await message.answer("❌ Недостаточно монет.")
        return

    con = db()

    cur = con.execute(
        """
        INSERT INTO duels(chat_id,user1,bet,status)
        VALUES(?,?,?,'waiting')
        """,
        (message.chat.id, message.from_user.id, bet)
    )

    duel_id = cur.lastrowid

    con.commit()
    con.close()

    kb = InlineKeyboardBuilder()
    kb.button(
        text="🎲 Принять дуэль",
        callback_data=f"accept_duel:{duel_id}"
    )

    await message.answer(
        f"🎲 <b>НОВАЯ ДУЭЛЬ</b>\n\n"
        f"Игрок: {message.from_user.full_name}\n"
        f"Ставка: <b>{bet} 💰</b>\n\n"
        "Кто рискнёт?",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data.startswith("accept_duel:"))
async def accept_duel(call: CallbackQuery):
    register_user(call.from_user, call.message.chat)

    duel_id = int(call.data.split(":")[1])

    con = db()

    duel = con.execute(
        """
        SELECT user1,bet,status
        FROM duels
        WHERE id=?
        """,
        (duel_id,)
    ).fetchone()

    if not duel or duel[2] != "waiting":
        con.close()
        await call.answer(
            "❌ Дуэль уже недоступна.",
            show_alert=True
        )
        return

    user1, bet, status = duel

    if user1 == call.from_user.id:
        con.close()
        await call.answer(
            "❌ Нельзя принять свою дуэль.",
            show_alert=True
        )
        return

    u2 = get_user(call.from_user.id)

    if u2[3] < bet:
        con.close()
        await call.answer(
            "❌ У тебя недостаточно монет.",
            show_alert=True
        )
        return

    u1 = get_user(user1)

    if u1[3] < bet:
        con.close()
        await call.answer(
            "❌ У создателя уже недостаточно монет.",
            show_alert=True
        )
        return

    winner = random.choice([user1, call.from_user.id])

    update_user(user1, "balance", u1[3] - bet)
    update_user(
        call.from_user.id,
        "balance",
        u2[3] - bet
    )

    prize = bet * 2

    winner_user = get_user(winner)
    update_user(
        winner,
        "balance",
        winner_user[3] + prize
    )

    con.execute(
        "UPDATE duels SET user2=?,status='finished' WHERE id=?",
        (call.from_user.id, duel_id)
    )

    con.commit()
    con.close()

    if winner == user1:
        winner_name = u1[2]
    else:
        winner_name = u2[2]

    await call.answer()

    await call.message.edit_text(
        "🎲 <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
        f"🏆 Победитель: <b>{winner_name}</b>\n"
        f"💰 Приз: <b>{prize} 💰</b>"
    )


@dp.message(Command("pay"))
async def pay_cmd(message: Message):
    register_user(message.from_user, message.chat)

    if not message.reply_to_message:
        await message.answer(
            "💸 Чтобы перевести монеты, ответь на сообщение игрока:\n\n"
            "<code>/pay 100</code>"
        )
        return

    args = message.text.split()

    if len(args) < 2:
        await message.answer("❌ Укажи сумму.")
        return

    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ Неверная сумма.")
        return

    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше нуля.")
        return

    sender = get_user(message.from_user.id)
    target_id = message.reply_to_message.from_user.id

    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя переводить самому себе.")
        return

    target = get_user(target_id)

    if not target:
        register_user(
            message.reply_to_message.from_user,
            message.chat
        )
        target = get_user(target_id)

    if sender[3] < amount:
        await message.answer("❌ Недостаточно монет.")
        return

    update_user(
        message.from_user.id,
        "balance",
        sender[3] - amount
    )

    update_user(
        target_id,
        "balance",
        target[3] + amount
    )

    await message.answer(
        f"💸 <b>Перевод выполнен!</b>\n\n"
        f"👤 Получатель: {target[2]}\n"
        f"💰 Сумма: <b>{amount}</b>"
    )


@dp.message(Command("group"))
async def group_cmd(message: Message):
    register_user(message.from_user, message.chat)

    if message.chat.type == "private":
        await message.answer(
            "👥 Команда работает внутри группы."
        )
        return

    await group_callback(
        FakeCallback(message)
    )


class FakeCallback:
    def __init__(self, message):
        self.message = message
        self.from_user = message.from_user

    async def answer(self, *args, **kwargs):
        pass


@dp.callback_query(F.data == "stats")
async def stats_callback(call: CallbackQuery):
    uid = call.from_user.id
    u = get_user(uid)

    await call.answer()

    await call.message.edit_text(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎰 Круток: <b>{u[5]}</b>\n"
        f"🏆 Побед: <b>{u[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[7]}</b>\n"
        f"⭐ Уровень: <b>{level(uid)}</b>\n"
        f"✨ XP: <b>{u[4]}</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "my_rating")
async def my_rating(call: CallbackQuery):
    uid = call.from_user.id

    con = db()

    better = con.execute(
        "SELECT COUNT(*) FROM users WHERE balance > "
        "(SELECT balance FROM users WHERE id=?)",
        (uid,)
    ).fetchone()[0]

    con.close()

    await call.answer()

    await call.message.edit_text(
        "🏆 <b>МОЙ РЕЙТИНГ</b>\n\n"
        f"Твоё место: <b>#{better + 1}</b>",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "my_clan")
async def my_clan(call: CallbackQuery):
    await call.answer()

    con = db()

    row = con.execute(
        """
        SELECT c.name
        FROM clans c
        JOIN clan_users cu ON cu.clan_id=c.id
        WHERE cu.user_id=?
        """,
        (call.from_user.id,)
    ).fetchone()

    con.close()

    if row:
        text = f"👥 <b>МОЙ КЛАН</b>\n\n🏰 {row[0]}"
    else:
        text = (
            "👥 <b>МОЙ КЛАН</b>\n\n"
            "Ты пока не состоишь в клане."
        )

    await call.message.edit_text(
        text,
        reply_markup=main_keyboard()
    )


def update_missions(uid, win=False):
    u = get_user(uid)

    if not u:
        return

    spins = u[11] + 1
    wins = u[12] + (1 if win else 0)

    update_user(uid, "mission_spins", spins)
    update_user(uid, "mission_wins", wins)


def update_chat_stats(chat_id, win, win_amount):
    con = db()

    con.execute(
        """
        UPDATE chats
        SET spins=spins+1,
            wins=wins+?,
            coins=coins+?
        WHERE id=?
        """,
        (1 if win else 0, win_amount, chat_id)
    )

    con.commit()
    con.close()


@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    register_user(message.from_user, message.chat)

    uid = message.from_user.id
    u = get_user(uid)

    await message.answer(
        "📊 <b>ТВОЯ СТАТИСТИКА</b>\n\n"
        f"🎰 Круток: <b>{u[5]}</b>\n"
        f"🏆 Побед: <b>{u[6]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[7]}</b>\n"
        f"⭐ Уровень: <b>{level(uid)}</b>\n"
        f"✨ XP: <b>{u[4]}</b>"
    )


@dp.message(Command("rating"))
async def rating_cmd(message: Message):
    register_user(message.from_user, message.chat)

    uid = message.from_user.id

    con = db()

    place = con.execute(
        """
        SELECT COUNT(*) + 1
        FROM users
        WHERE balance >
        (SELECT balance FROM users WHERE id=?)
        """,
        (uid,)
    ).fetchone()[0]

    con.close()

    await message.answer(
        f"🏆 Твоё место в рейтинге: <b>#{place}</b>"
    )


@dp.message(Command("wheel"))
async def wheel_cmd(message: Message):
    register_user(message.from_user, message.chat)

    fake = FakeCallback(message)
    await wheel_callback(fake)


@dp.message(Command("missions"))
async def missions_cmd(message: Message):
    register_user(message.from_user, message.chat)

    fake = FakeCallback(message)
    await missions_callback(fake)


@dp.message(Command("top"))
async def top_cmd(message: Message):
    register_user(message.from_user, message.chat)

    fake = FakeCallback(message)
    await top_callback(fake)


@dp.message(Command("group"))
async def group_command_again(message: Message):
    register_user(message.from_user, message.chat)

    if message.chat.type == "private":
        await message.answer(
            "👥 Эта команда работает в группе."
        )
        return

    con = db()

    row = con.execute(
        """
        SELECT title,spins,coins,wins
        FROM chats
        WHERE id=?
        """,
        (message.chat.id,)
    ).fetchone()

    members = con.execute(
        "SELECT COUNT(*) FROM chat_users WHERE chat_id=?",
        (message.chat.id,)
    ).fetchone()[0]

    con.close()

    title = row[0] if row 

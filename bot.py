import os
import random
import sqlite3
import asyncio
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

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

MULTI = {
    "🍒": 5,
    "🍋": 7,
    "🍊": 10,
    "🔔": 15,
    "💎": 30
}

BETS = [10, 25, 50, 100]


# =========================
# DATABASE
# =========================

def con():
    return sqlite3.connect(DB)


def init_db():
    c = con()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        name TEXT,
        balance INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best INTEGER DEFAULT 0,
        bet INTEGER DEFAULT 10,
        bonus TEXT DEFAULT '',
        wheel TEXT DEFAULT ''
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS jackpot(
        id INTEGER PRIMARY KEY,
        money INTEGER DEFAULT 5000
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS duels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator INTEGER,
        opponent INTEGER DEFAULT 0,
        bet INTEGER,
        status TEXT DEFAULT 'waiting',
        winner INTEGER DEFAULT 0
    )
    """)

    c.execute(
        "INSERT OR IGNORE INTO jackpot(id,money) VALUES(1,5000)"
    )

    c.commit()
    c.close()


def register(u):
    c = con()

    c.execute(
        "INSERT OR IGNORE INTO users(id,name) VALUES(?,?)",
        (u.id, u.full_name or "Игрок")
    )

    c.execute(
        "UPDATE users SET name=? WHERE id=?",
        (u.full_name or "Игрок", u.id)
    )

    c.commit()
    c.close()


def user(uid):
    c = con()
    r = c.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()
    c.close()
    return r


def update(uid, field, value):
    allowed = {
        "balance",
        "xp",
        "spins",
        "wins",
        "best",
        "bet",
        "bonus",
        "wheel"
    }

    if field not in allowed:
        return

    c = con()

    c.execute(
        f"UPDATE users SET {field}=? WHERE id=?",
        (value, uid)
    )

    c.commit()
    c.close()


def level(uid):
    return user(uid)[3] // 100 + 1


def get_jackpot():
    c = con()

    r = c.execute(
        "SELECT money FROM jackpot WHERE id=1"
    ).fetchone()

    c.close()

    return r[0]


def add_jackpot(value):
    c = con()

    c.execute(
        "UPDATE jackpot SET money=money+? WHERE id=1",
        (value,)
    )

    c.commit()
    c.close()


def reset_jackpot():
    c = con()

    c.execute(
        "UPDATE jackpot SET money=5000 WHERE id=1"
    )

    c.commit()
    c.close()


# =========================
# MENUS
# =========================

def make_keyboard(items, columns=2):
    k = InlineKeyboardBuilder()

    for text, data in items:
        k.button(
            text=text,
            callback_data=data
        )

    k.adjust(columns)

    return k.as_markup()


def menu():
    return make_keyboard([
        ("🎰 Слоты", "game"),
        ("👤 Профиль", "profile"),
        ("🎁 Бонус", "bonus"),
        ("🏆 Топ", "top"),
        ("🔢 Комбинации", "combos"),
        ("⚔️ Дуэли", "duel"),
        ("🎡 Колесо", "wheel"),
        ("📊 Статистика", "stats"),
        ("❓ Помощь", "help")
    ], 2)


def game_menu(uid):
    bet = user(uid)[7]

    items = [
        (f"🎰 КРУТИТЬ • {bet} 💰", "spin")
    ]

    for value in BETS:
        items.append(
            (f"💰 {value}", f"bet:{value}")
        )

    items.append(
        ("🔙 Меню", "menu")
    )

    return make_keyboard(items, 4)


def duel_menu():
    return make_keyboard([
        ("⚔️ Создать дуэль", "duel_create"),
        ("🔎 Найти соперника", "duel_find"),
        ("🔙 Меню", "menu")
    ], 1)


def duel_bets():
    items = []

    for value in BETS:
        items.append(
            (f"💰 {value}", f"duel_bet:{value}")
        )

    items.append(
        ("🔙 Назад", "duel")
    )

    return make_keyboard(items, 2)


async def edit(call, text, markup=None):
    await call.answer()

    if markup is None:
        markup = menu()

    await call.message.edit_text(
        text,
        reply_markup=markup
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    register(message.from_user)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Добро пожаловать!\n\n"
        "💰 Стартовый баланс: 1000\n"
        "⭐ +10 XP за каждую крутку\n"
        "💎 7️⃣7️⃣7️⃣ — джекпот\n"
        "⚔️ Дуэли с игроками\n\n"
        "👇 Выбирай:",
        reply_markup=menu()
    )


@dp.message(Command("slots"))
async def slots(message: Message):
    register(message.from_user)

    await message.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 💰",
        reply_markup=game_menu(message.from_user.id)
    )


@dp.message(Command("balance"))
async def balance(message: Message):
    register(message.from_user)

    u = user(message.from_user.id)

    await message.answer(
        f"💰 Баланс: <b>{u[2]}</b>\n"
        f"⭐ Уровень: <b>{level(u[0])}</b>\n"
        f"✨ XP: <b>{u[3]}</b>"
    )


@dp.message(Command("bonus"))
async def bonus_command(message: Message):
    register(message.from_user)

    uid = message.from_user.id
    u = user(uid)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if u[8] == today:
        await message.answer(
            "🎁 Бонус уже получен сегодня!"
        )
        return

    reward = 100 + level(uid) * 25

    update(
        uid,
        "balance",
        u[2] + reward
    )

    update(
        uid,
        "bonus",
        today
    )

    await message.answer(
        f"🎁 Получено <b>+{reward} 💰</b>"
    )


# =========================
# MAIN MENU
# =========================

@dp.callback_query(F.data == "menu")
async def menu_button(call: CallbackQuery):
    register(call.from_user)

    await edit(
        call,
        "🎰 <b>СЛОТЫ</b>\n\n👇 Выбирай:"
    )


@dp.callback_query(F.data == "game")
async def game_button(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id

    await edit(
        call,
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"🎯 Ставка: <b>{user(uid)[7]}</b> 💰\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 💰",
        game_menu(uid)
    )


# =========================
# BET
# =========================

@dp.callback_query(F.data.startswith("bet:"))
async def bet_button(call: CallbackQuery):
    register(call.from_user)

    value = int(
        call.data.split(":")[1]
    )

    update(
        call.from_user.id,
        "bet",
        value
    )

    await edit(
        call,
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"🎯 Ставка: <b>{value}</b> 💰\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b> 💰",
        game_menu(call.from_user.id)
    )


# =========================
# SPIN
# =========================

@dp.callback_query(F.data == "spin")
async def spin(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)
    bet = u[7]

    if u[2] < bet:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    update(
        uid,
        "balance",
        u[2] - bet
    )

    update(
        uid,
        "spins",
        u[4] + 1
    )

    update(
        uid,
        "xp",
        u[3] + 10
    )

    await call.answer()

    await call.message.edit_text(
        "🎰 <b>КРУТИМ...</b>\n\n"
        "❓ | ❓ | ❓"
    )

    await asyncio.sleep(0.25)

    result = [
        random.choice(SYMBOLS),
        random.choice(SYMBOLS),
        random.choice(SYMBOLS)
    ]

    await call.message.edit_text(
        "🎰 <b>КРУТИМ...</b>\n\n"
        f"{result[0]} | ❓ | ❓"
    )

    await asyncio.sleep(0.25)

    await call.message.edit_text(
        "🎰 <b>КРУТИМ...</b>\n\n"
        f"{result[0]} | {result[1]} | ❓"
    )

    await asyncio.sleep(0.25)

    win = 0
    jackpot_win = False

    if result[0] == result[1] == result[2] == "7️⃣":
        win = get_jackpot()
        reset_jackpot()
        jackpot_win = True

    elif result[0] == result[1] == result[2]:
        win = bet * MULTI[result[0]]

    elif (
        result[0] == result[1]
        or result[0] == result[2]
        or result[1] == result[2]
    ):
        win = bet * 2

    else:
        add_jackpot(
            max(1, bet // 10)
        )

    if win:
        now = user(uid)

        update(
            uid,
            "balance",
            now[2] + win
        )

        update(
            uid,
            "wins",
            now[5] + 1
        )

        if win > now[6]:
            update(
                uid,
                "best",
                win
            )

    now = user(uid)

    if jackpot_win:
        result_text = (
            "💎💎💎 <b>ДЖЕКПОТ!</b>\n"
            f"💰 +{win}"
        )

    elif win:
        result_text = (
            f"🎉 <b>Выигрыш +{win} 💰</b>"
        )

    else:
        result_text = (
            f"😢 Проигрыш -{bet} 💰"
        )

    await call.message.edit_text(
        "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
        f"{result[0]} | {result[1]} | {result[2]}\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{now[2]}</b>\n"
        f"⭐ Уровень: <b>{level(uid)}</b>\n"
        f"💎 Джекпот: <b>{get_jackpot()}</b>",
        reply_markup=game_menu(uid)
    )


# =========================
# PROFILE
# =========================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    register(call.from_user)

    u = user(call.from_user.id)

    await edit(
        call,
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 {u[1]}\n"
        f"💰 Баланс: <b>{u[2]}</b>\n"
        f"⭐ Уровень: <b>{level(u[0])}</b>\n"
        f"✨ XP: <b>{u[3]}</b>\n"
        f"🎰 Круток: <b>{u[4]}</b>\n"
        f"🏆 Побед: <b>{u[5]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[6]}</b>"
    )


# =========================
# BONUS
# =========================

@dp.callback_query(F.data == "bonus")
async def bonus(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if u[8] == today:
        await call.answer(
            "🎁 Бонус уже получен сегодня!",
            show_alert=True
        )
        return

    reward = 100 + level(uid) * 25

    update(
        uid,
        "balance",
        u[2] + reward
    )

    update(
        uid,
        "bonus",
        today
    )

    await edit(
        call,
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"💰 Получено: <b>+{reward}</b>\n\n"
        "Возвращайся завтра!"
    )


# =========================
# TOP
# =========================

@dp.callback_query(F.data == "top")
async def top(call: CallbackQuery):
    register(call.from_user)

    c = con()

    rows = c.execute(
        "SELECT name,balance,wins FROM users "
        "ORDER BY balance DESC LIMIT 10"
    ).fetchall()

    c.close()

    text = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += (
            f"<b>{i}.</b> {row[0]} — "
            f"{row[1]} 💰 | {row[2]} 🏆\n"
        )

    await edit(call, text)


# =========================
# COMBINATIONS
# =========================

@dp.callback_query(F.data == "combos")
async def combos(call: CallbackQuery):
    register(call.from_user)

    await edit(
        call,
        "🔢 <b>КОМБИНАЦИИ</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — 💎 ДЖЕКПОТ\n\n"
        "Любые 2 одинаковых — x2"
    )


# =========================
# STATS
# =========================

@dp.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    register(call.from_user)

    u = user(call.from_user.id)

    await edit(
        call,
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎰 Круток: <b>{u[4]}</b>\n"
        f"🏆 Побед: <b>{u[5]}</b>\n"
        f"💎 Лучший выигрыш: <b>{u[6]}</b>\n"
        f"✨ XP: <b>{u[3]}</b>\n"
        f"⭐ Уровень: <b>{level(u[0])}</b>"
    )


# =========================
# WHEEL
# =========================

@dp.callback_query(F.data == "wheel")
async def wheel(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if u[9] == today:
        await call.answer(
            "🎡 Колесо уже использовано сегодня!",
            show_alert=True
        )
        return

    reward = random.choice(
        [25, 50, 100, 150, 250, 500, 1000, 5000]
    )

    update(
        uid,
        "balance",
        u[2] + reward
    )

    update(
        uid,
        "wheel",
        today
    )

    await edit(
        call,
        "🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
        f"🎉 Ты получил <b>+{reward} 💰</b>"
    )


# =========================
# ⚔️ DUELS
# =========================

@dp.callback_query(F.data == "duel")
async def duel(call: CallbackQuery):
    register(call.from_user)

    await edit(
        call,
        "⚔️ <b>ДУЭЛИ</b>\n\n"
        "Сразись с другим игроком за монеты!\n\n"
        "🏆 Победитель получает весь банк.\n"
        "💰 Ставки: 10 / 25 / 50 / 100\n\n"
        "Выбирай:",
        duel_menu()
    )


@dp.callback_query(F.data == "duel_create")
async def duel_create(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    c = con()

    active = c.execute(
        "SELECT id FROM duels "
        "WHERE creator=? AND status='waiting'",
        (uid,)
    ).fetchone()

    c.close()

    if active:
        await call.answer(
            "❌ У тебя уже есть ожидающая дуэль!",
            show_alert=True
        )
        return

    await edit(
        call,
        "⚔️ <b>СОЗДАНИЕ ДУЭЛИ</b>\n\n"
        f"💰 Твой баланс: <b>{u[2]}</b>\n\n"
        "Выбери ставку:",
        duel_bets()
    )


@dp.callback_query(F.data.startswith("duel_bet:"))
async def duel_bet(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    bet = int(
        call.data.split(":")[1]
    )

    u = user(uid)

    if u[2] < bet:
        await call.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    c = con()

    active = c.execute(
        "SELECT id FROM duels "
        "WHERE creator=? AND status='waiting'",
        (uid,)
    ).fetchone()

    if active:
        c.close()

        await call.answer(
            "❌ У тебя уже есть дуэль!",
            show_alert=True
        )
        return

    c.execute(
        "INSERT INTO duels(creator,bet) VALUES(?,?)",
        (uid, bet)
    )

    duel_id = c.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    c.commit()
    c.close()

    update(
        uid,
        "balance",
        u[2] - bet
    )

    buttons = make_keyboard([
        ("🔎 Найти соперника", "duel_find"),
        ("❌ Отменить", f"duel_cancel:{duel_id}")
    ], 1)

    await edit(
        call,
        "⚔️ <b>ДУЭЛЬ СОЗДАНА!</b>\n\n"
        f"💰 Ставка: <b>{bet}</b>\n"
        "⏳ Ждём соперника...",
        buttons
    )


@dp.callback_query(F.data == "duel_find")
async def duel_find(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    u = user(uid)

    c = con()

    d = c.execute(
        "SELECT id,creator,bet FROM duels "
        "WHERE status='waiting' AND creator!=? "
        "ORDER BY id LIMIT 1",
        (uid,)
    ).fetchone()

    if not d:
        c.close()

        await call.answer(
            "⏳ Сейчас нет доступных дуэлей.",
            show_alert=True
        )
        return

    duel_id, creator, bet = d

    if u[2] < bet:
        c.close()

        await call.answer(
            f"❌ Для этой дуэли нужно {bet} 💰",
            show_alert=True
        )
        return

    result = c.execute(
        "UPDATE duels "
        "SET opponent=?,status='playing' "
        "WHERE id=? AND status='waiting'",
        (uid, duel_id)
    )

    if result.rowcount != 1:
        c.close()

        await call.answer(
            "❌ Дуэль уже занята.",
            show_alert=True
        )
        return

    c.commit()
    c.close()

    update(
        uid,
        "balance",
        u[2] - bet
    )

    winner = random.choice([
        creator,
        uid
    ])

    total = bet * 2

    winner_data = user(winner)

    update(
        winner,
        "balance",
        winner_data[2] + total
    )

    c = con()

    c.execute(
        "UPDATE duels SET status='finished',winner=? "
        "WHERE id=?",
        (winner, duel_id)
    )

    c.commit()
    c.close()

    if winner == uid:
        text = (
            "🏆 <b>ТЫ ПОБЕДИЛ!</b>\n\n"
            f"💰 Ставка: {bet}\n"
            f"🏦 Банк: <b>{total} 💰</b>\n"
            f"🎉 Тебе: <b>+{total} 💰</b>"
        )
    else:
        text = (
            "💀 <b>ТЫ ПРОИГРАЛ!</b>\n\n"
            f"💰 Ставка: {bet}\n"
            f"🏦 Банк: <b>{total} 💰</b>\n"
            "😢 Победил соперник."
        )

    await call.answer(
        "🏆 Победа!" if winner == uid else "💀 Поражение!",
        show_alert=True
    )

    await call.message.edit_text(
        "⚔️ <b>РЕЗУЛЬТАТ ДУЭЛИ</b>\n\n"
        f"{text}\n\n"
        "⚔️ Можно сыграть ещё.",
        reply_markup=duel_menu()
    )


@dp.callback_query(F.data.startswith("duel_cancel:"))
async def duel_cancel(call: CallbackQuery):
    register(call.from_user)

    uid = call.from_user.id
    duel_id = int(
        call.data.split(":")[1]
    )

    c = con()

    d = c.execute(
        "SELECT bet FROM duels "
        "WHERE id=? AND creator=? AND status='waiting'",
        (duel_id, uid)
    ).fetchone()

    if not d:
        c.close()

        await call.answer(
            "❌ Дуэль уже недоступна.",
            show_alert=True
        )
        return

    c.execute(
        "UPDATE duels SET status='cancelled' WHERE id=?",
        (duel_id,)
    )

    c.commit()
    c.close()

    u = user(uid)

    update(
        uid,
        "balance",
        u[2] + d[0]
    )

    await edit(
        call,
        "❌ <b>ДУЭЛЬ ОТМЕНЕНА</b>\n\n"
        f"💰 Возвращено: <b>{d[0]} 💰</b>",
        duel_menu()
    )


# =========================
# HELP
# =========================

@dp.callback_query(F.data == "help")
async def help_button(call: CallbackQuery):
    register(call.from_user)

    await edit(
        call,
        "❓ <b>ПОМОЩЬ</b>\n\n"
        "/start — меню\n"
        "/slots — слоты\n"
        "/balance — баланс\n"
        "/bonus — бонус\n\n"
        "🎰 Выбирай ставку один раз.\n"
        "После игры можно сразу крутить ещё.\n"
        "⚔️ В дуэлях можно играть против других игроков."
    )


# =========================
# RENDER
# =========================

class Health(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def server():
    port = int(
        os.getenv("PORT", "10000")
    )

    HTTPServer(
        ("0.0.0.0", port),
        Health
    ).serve_forever()


# =========================
# START
# =========================

async def main():

    init_db()

    threading.Thread(
        target=server,
        daemon=True
    ).start()

    pr

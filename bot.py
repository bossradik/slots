import os
import random
import sqlite3
import threading
import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder


TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = "slots.db"

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

db_lock = threading.Lock()
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
conn.row_factory = sqlite3.Row


# =========================
# DATABASE
# =========================

def db(sql, params=(), one=False):
    with db_lock:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.fetchone() if one else cur.fetchall()


def init_db():
    db("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        name TEXT DEFAULT '',
        coins INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best_win INTEGER DEFAULT 0,
        bet INTEGER DEFAULT 10,
        dice_games INTEGER DEFAULT 0,
        dice_wins INTEGER DEFAULT 0,
        duel_games INTEGER DEFAULT 0,
        duel_wins INTEGER DEFAULT 0,
        clan_id INTEGER DEFAULT 0,
        wheel_day TEXT DEFAULT '',
        mission_day TEXT DEFAULT '',
        mission_spins INTEGER DEFAULT 0,
        mission_wins INTEGER DEFAULT 0,
        mission_coins INTEGER DEFAULT 0
    )
    """)

    db("""
    CREATE TABLE IF NOT EXISTS chats(
        chat_id INTEGER PRIMARY KEY,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        coins INTEGER DEFAULT 0
    )
    """)

    db("""
    CREATE TABLE IF NOT EXISTS chat_users(
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(chat_id,user_id)
    )
    """)

    db("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value INTEGER
    )
    """)

    if not db(
        "SELECT * FROM settings WHERE key='jackpot'",
        one=True
    ):
        db(
            "INSERT INTO settings(key,value) VALUES('jackpot',5000)"
        )


# =========================
# USER
# =========================

def register(m):
    uid = m.from_user.id
    username = m.from_user.username or ""
    name = m.from_user.full_name[:40]

    u = db(
        "SELECT * FROM users WHERE id=?",
        (uid,),
        one=True
    )

    if not u:
        db(
            """
            INSERT INTO users(id,username,name)
            VALUES(?,?,?)
            """,
            (uid, username, name)
        )
    else:
        db(
            """
            UPDATE users
            SET username=?,name=?
            WHERE id=?
            """,
            (username, name, uid)
        )

    if m.chat.type != "private":
        db(
            "INSERT OR IGNORE INTO chats(chat_id) VALUES(?)",
            (m.chat.id,)
        )
        db(
            """
            INSERT OR IGNORE INTO chat_users(chat_id,user_id)
            VALUES(?,?)
            """,
            (m.chat.id, uid)
        )

    return db(
        "SELECT * FROM users WHERE id=?",
        (uid,),
        one=True
    )


def get_user(uid):
    return db(
        "SELECT * FROM users WHERE id=?",
        (uid,),
        one=True
    )


def level(xp):
    return xp // 100 + 1


def level_progress(xp):
    return xp % 100


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def happy_hour():
    h = datetime.now(timezone.utc).hour
    return 18 <= h < 20


# =========================
# KEYBOARDS
# =========================

def main_keyboard():
    b = InlineKeyboardBuilder()

    b.button(text="🎰 Слоты", callback_data="game")
    b.button(text="🎲 Кубик", callback_data="dice_menu")
    b.button(text="⚔️ Дуэли", callback_data="duel_menu")
    b.button(text="👤 Профиль", callback_data="profile")

    b.button(text="🏆 Рейтинг", callback_data="top")
    b.button(text="👥 Кланы", callback_data="clans")
    b.button(text="🎯 Задания", callback_data="missions")
    b.button(text="🎡 Колесо", callback_data="wheel")

    b.button(text="📖 Комбинации", callback_data="combos")
    b.button(text="📚 Помощь", callback_data="help")

    b.adjust(2, 2, 2, 2, 2)
    return b.as_markup()


def game_keyboard(u):
    b = InlineKeyboardBuilder()

    b.button(
        text="🎰 КРУТИТЬ",
        callback_data="spin"
    )

    b.button(
        text=f"💰 Ставка {u['bet']}",
        callback_data="bets"
    )

    b.button(
        text="👤 Профиль",
        callback_data="profile"
    )

    b.button(
        text="🏠 Меню",
        callback_data="menu"
    )

    b.adjust(1, 2, 1)
    return b.as_markup()


def bet_keyboard():
    b = InlineKeyboardBuilder()

    for x in (10, 25, 50, 100):
        b.button(
            text=f"💰 {x}",
            callback_data=f"bet:{x}"
        )

    b.button(
        text="⬅️ Назад",
        callback_data="game"
    )

    b.adjust(2, 2, 1)
    return b.as_markup()


# =========================
# MAIN COMMANDS
# =========================

@dp.message(CommandStart())
async def start(m: Message):
    register(m)

    await m.answer(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Добро пожаловать в игру!\n\n"
        "🎰 Слоты\n"
        "🎲 Кубики\n"
        "⚔️ Дуэли\n"
        "👥 Кланы\n"
        "🏆 Рейтинги\n"
        "🎯 Задания\n"
        "🎡 Колесо\n"
        "🏅 Достижения\n\n"
        "Выбирай раздел 👇",
        reply_markup=main_keyboard()
    )


@dp.message(Command("help"))
async def help_command(m: Message):
    register(m)

    await m.answer(
        "📚 <b>КОМАНДЫ</b>\n\n"
        "/start — главное меню\n"
        "/slots — играть в слоты\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/profile — профиль\n"
        "/top — рейтинг\n"
        "/group — рейтинг группы\n"
        "/pay — передать монеты\n"
        "/dice — кубик\n"
        "/duel — дуэль\n\n"
        "Большинство функций можно использовать "
        "через кнопки меню."
    )


@dp.message(Command("slots"))
async def slots_command(m: Message):
    register(m)
    await show_game(m)


@dp.message(Command("profile"))
async def profile_command(m: Message):
    register(m)
    await show_profile(m)


@dp.message(Command("balance"))
async def balance_command(m: Message):
    u = register(m)

    await m.answer(
        f"💰 Баланс: <b>{u['coins']}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"✨ XP: <b>{u['xp']}</b>"
    )


# =========================
# GAME SCREEN
# =========================

async def show_game(m):
    u = get_user(m.from_user.id)

    jackpot = db(
        "SELECT value FROM settings WHERE key='jackpot'",
        one=True
    )["value"]

    hh = "\n🔥 <b>HAPPY HOUR АКТИВЕН!</b>" if happy_hour() else ""

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{u['coins']}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"✨ XP: <b>{level_progress(u['xp'])}/100</b>\n"
        f"💵 Ставка: <b>{u['bet']}</b>\n"
        f"👑 Джекпот: <b>{jackpot}</b>"
        f"{hh}\n\n"
        "Нажми 🎰 КРУТИТЬ"
    )

    if hasattr(m, "message") and m.message:
        await m.message.edit_text(
            text,
            reply_markup=game_keyboard(u)
        )
    else:
        await m.answer(
            text,
            reply_markup=game_keyboard(u)
        )


@dp.callback_query(F.data == "game")
async def game_callback(c: CallbackQuery):
    await show_game(c)
    await c.answer()


# =========================
# BET
# =========================

@dp.callback_query(F.data == "bets")
async def bets_callback(c: CallbackQuery):
    await c.message.edit_text(
        "💰 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
        "После выбора она сохранится.\n"
        "При следующем вращении выбирать её заново "
        "не понадобится.",
        reply_markup=bet_keyboard()
    )
    await c.answer()


@dp.callback_query(F.data.startswith("bet:"))
async def bet_callback(c: CallbackQuery):
    amount = int(c.data.split(":")[1])

    db(
        "UPDATE users SET bet=? WHERE id=?",
        (amount, c.from_user.id)
    )

    u = get_user(c.from_user.id)

    await c.message.edit_text(
        "🎰 <b>СТАВКА ИЗМЕНЕНА</b>\n\n"
        f"💰 Текущая ставка: <b>{amount}</b>\n"
        f"💰 Баланс: <b>{u['coins']}</b>\n\n"
        "Теперь можно просто нажимать "
        "🎰 <b>КРУТИТЬ</b>.",
        reply_markup=game_keyboard(u)
    )

    await c.answer()


# =========================
# SLOT SPIN
# =========================

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


async def spin_animation(c):
    frames = [
        "🎰 <b>🍒 | 🍋 | 🔔</b>",
        "🎰 <b>💎 | 🍊 | 7️⃣</b>",
        "🎰 <b>🔔 | 🍒 | 💎</b>",
        "🎰 <b>🍋 | 7️⃣ | 🍊</b>",
        "🎰 <b>💎 | 🔔 | 🍒</b>"
    ]

    for frame in frames:
        try:
            await c.message.edit_text(
                frame + "\n\n⏳ <i>Прокрутка...</i>"
            )
        except Exception:
            pass

        await asyncio.sleep(0.35)


@dp.callback_query(F.data == "spin")
async def spin_callback(c: CallbackQuery):
    u = get_user(c.from_user.id)

    if not u:
        await c.answer(
            "Сначала нажми /start",
            show_alert=True
        )
        return

    bet = u["bet"]

    if u["coins"] < bet:
        await c.answer(
            "❌ Недостаточно монет!",
            show_alert=True
        )
        return

    await c.answer()

    await spin_animation(c)

    a, b, d = random.choices(
        SYMBOLS,
        k=3
    )

    jackpot = db(
        "SELECT value FROM settings WHERE key='jackpot'",
        one=True
    )["value"]

    win = 0
    result = "💨 Не повезло..."

    # Очень редкий супердроп
    if random.randint(1, 10000) == 1:
        win = 50000
        result = "👑 <b>ЛЕГЕНДАРНЫЙ ДРОП!</b>\n💎 +50 000"

    # Джекпот
    elif a == b == d == "7️⃣":
        win = jackpot
        result = (
            "👑 <b>ДЖЕКПОТ!</b>\n"
            f"💰 +{jackpot}"
        )

        db(
            "UPDATE settings SET value=5000 "
            "WHERE key='jackpot'"
        )

    # Три одинаковых
    elif a == b == d:
        mult = MULTIPLIERS[a]
        win = bet * mult
        result = (
            f"🔥 <b>ТРОЙКА!</b>\n"
            f"{a}{b}{d} — x{mult}"
        )

    # Два одинаковых
    elif a == b or a == d or b == d:
        win = bet * 2
        result = "✨ <b>ДВА ОДИНАКОВЫХ!</b> — x2"

    # Happy Hour
    if win > 0 and happy_hour():
        win *= 2
        result += "\n🔥 <b>HAPPY HOUR x2!</b>"

    new_coins = u["coins"] - bet + win
    new_xp = u["xp"] + 10
    new_best = max(u["best_win"], win)

    db(
        """
        UPDATE users SET
        coins=?,
        xp=?,
        spins=spins+1,
        wins=wins+?,
        best_win=?,
        mission_spins=mission_spins+1,
        mission_wins=mission_wins+?,
        mission_coins=mission_coins+?
        WHERE id=?
        """,
        (
            new_coins,
            new_xp,
            1 if win > 0 else 0,
            new_best,
            1 if win > 0 else 0,
            win,
            u["id"]
        )
    )

    # Пополняем джекпот
    db(
        """
        UPDATE settings
        SET value=value+?
        WHERE key='jackpot'
        """,
        (max(1, bet // 10),)
    )

    # Статистика группы
    if c.message.chat.type != "private":
        db(
            """
            INSERT OR IGNORE INTO chats(chat_id)
            VALUES(?)
            """,
            (c.message.chat.id,)
        )

        db(
            """
            UPDATE chats
            SET spins=spins+1,
                wins=wins+?,
                coins=coins+?
            WHERE chat_id=?
            """,
            (
                1 if win > 0 else 0,
                win,
                c.message.chat.id
            )
        )

    text = (
        f"🎰 <b>{a} | {b} | {d}</b>\n\n"
        f"{result}\n\n"
        f"💵 Ставка: <b>{bet}</b>\n"
        f"🏆 Выигрыш: <b>{win}</b>\n"
        f"💰 Баланс: <b>{new_coins}</b>\n"
        f"⭐ Уровень: <b>{level(new_xp)}</b>\n"
        f"✨ XP: <b>{level_progress(new_xp)}/100</b>"
    )

    bld = InlineKeyboardBuilder()

    bld.button(
        text="🎰 КРУТИТЬ ЕЩЁ РАЗ",
        callback_data="spin"
    )

    bld.button(
        text="💰 Изменить ставку",
        callback_data="bets"
    )

    bld.button(
        text="👤 Профиль",
        callback_data="profile"
    )

    bld.button(
        text="🏠 Меню",
        callback_data="menu"
    )

    bld.adjust(1, 2, 1)

    await c.message.edit_text(
        text,
        reply_markup=bld.as_markup()
    )


# =========================
# PROFILE
# =========================

def profile_keyboard():
    b = InlineKeyboardBuilder()

    b.button(
        text="🏅 Достижения",
        callback_data="achievements"
    )

    b.button(
        text="📊 Статистика",
        callback_data="statistics"
    )

    b.button(
        text="👥 Мой клан",
        callback_data="my_clan"
    )

    b.button(
        text="🏆 Мой рейтинг",
        callback_data="my_rating"
    )

    b.button(
        text="🏠 Главное меню",
        callback_data="menu"
    )

    b.adjust(2, 2, 1)
    return b.as_markup()


async def show_profile(obj):
    uid = obj.from_user.id
    u = get_user(uid)

    if not u:
        return

    name = u["name"]

    need = (level(u["xp"])) * 100
    current = level_progress(u["xp"])

    clan_text = (
        f"👥 Клан ID: <b>{u['clan_id']}</b>"
        if u["clan_id"]
        else "👥 Клан: <b>нет</b>"
    )

    text = (
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Игрок: <b>{name}</b>\n"
        f"🆔 ID: <code>{uid}</code>\n\n"
        f"💰 Баланс: <b>{u['coins']}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"✨ XP: <b>{current}/100</b>\n\n"
        f"🎰 Вращений: <b>{u['spins']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b>\n"
        f"💎 Лучший выигрыш: <b>{u['best_win']}</b>\n\n"
        f"🎲 Игр в кости: <b>{u['dice_games']}</b>\n"
        f"🎲 Побед в костях: <b>{u['dice_wins']}</b>\n"
        f"⚔️ Дуэлей: <b>{u['duel_games']}</b>\n"
        f"⚔️ Побед в дуэлях: <b>{u['duel_wins']}</b>\n\n"
        f"{clan_text}"
    )

    if isinstance(obj, CallbackQuery):
        await obj.message.edit_text(
            text,
            reply_markup=profile_keyboard()
        )
    else:
        await obj.answer(
            text,
            reply_markup=profile_keyboard()
        )


@dp.callback_query(F.data == "profile")
async def profile_callback(c: CallbackQuery):
    await show_profile(c)
    await c.answer()


# =========================
# MENU
# =========================

@dp.callback_query(F.data == "menu")
async def menu_callback(c: CallbackQuery):
    await c.message.edit_text(
        "🎰 <b>ГЛАВНОЕ МЕНЮ</b>\n\n"
        "Выбери нужный раздел 👇",
        reply_markup=main_keyboard()
    )
    await c.answer()
    # =========================
# DAILY BONUS
# =========================

@dp.message(Command("bonus"))
async def bonus_command(m: Message):
    u = register(m)
    d = today()

    if u["mission_day"] == d:
        await m.answer("🎁 Ежедневный бонус уже получен сегодня.")
        return

    amount = 100 + level(u["xp"]) * 25

    db(
        """
        UPDATE users
        SET coins=coins+?,
            mission_day=?
        WHERE id=?
        """,
        (amount, d, u["id"])
    )

    await m.answer(
        f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"Ты получил: <b>+{amount} 💰</b>"
    )


# =========================
# DICE
# =========================

@dp.callback_query(F.data == "dice_menu")
async def dice_menu(c: CallbackQuery):
    await c.message.edit_text(
        "🎲 <b>ИГРА В КУБИК</b>\n\n"
        "Стоимость броска: <b>50 💰</b>\n\n"
        "Выпало 4, 5 или 6 — победа!\n"
        "Награда: <b>100 💰</b>\n\n"
        "Нажми бросить 👇",
        reply_markup=dice_keyboard()
    )
    await c.answer()


def dice_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="🎲 БРОСИТЬ", callback_data="dice")
    b.button(text="🏠 Меню", callback_data="menu")
    b.adjust(1)
    return b.as_markup()


@dp.message(Command("dice"))
async def dice_command(m: Message):
    register(m)
    await play_dice(m)


async def play_dice(obj):
    uid = obj.from_user.id
    u = get_user(uid)

    if not u or u["coins"] < 50:
        text = "❌ Для игры нужно минимум <b>50 💰</b>."
        if isinstance(obj, CallbackQuery):
            await obj.answer(text, show_alert=True)
        else:
            await obj.answer(text)
        return

    roll = random.randint(1, 6)

    win = roll >= 4

    if win:
        db(
            """
            UPDATE users
            SET coins=coins+50,
                dice_games=dice_games+1,
                dice_wins=dice_wins+1
            WHERE id=?
            """,
            (uid,)
        )

        result = (
            f"🎲 Выпало: <b>{roll}</b>\n\n"
            "🎉 <b>ПОБЕДА!</b>\n"
            "💰 +50"
        )
    else:
        db(
            """
            UPDATE users
            SET coins=coins-50,
                dice_games=dice_games+1
            WHERE id=?
            """,
            (uid,)
        )

        result = (
            f"🎲 Выпало: <b>{roll}</b>\n\n"
            "💨 <b>ПРОИГРЫШ</b>\n"
            "💰 -50"
        )

    if isinstance(obj, CallbackQuery):
        await obj.message.edit_text(
            "🎲 <b>КУБИК</b>\n\n" + result,
            reply_markup=dice_keyboard()
        )
        await obj.answer()
    else:
        await obj.answer(
            "🎲 <b>КУБИК</b>\n\n" + result
        )


@dp.callback_query(F.data == "dice")
async def dice_callback(c: CallbackQuery):
    await play_dice(c)


# =========================
# DUELS
# =========================

@dp.callback_query(F.data == "duel_menu")
async def duel_menu(c: CallbackQuery):
    await c.message.edit_text(
        "⚔️ <b>ДУЭЛИ</b>\n\n"
        "Сразись с другим игроком на монеты.\n\n"
        "Чтобы вызвать игрока, ответь на его сообщение:\n\n"
        "<code>/duel 100</code>\n\n"
        "Оба игрока бросают кубик 🎲.\n"
        "У кого больше — тот забирает ставку.",
        reply_markup=back_keyboard()
    )
    await c.answer()


def back_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="🏠 Главное меню", callback_data="menu")
    return b.as_markup()


@dp.message(Command("duel"))
async def duel_command(m: Message):
    a = register(m)

    if not m.reply_to_message:
        await m.answer(
            "⚔️ <b>ДУЭЛЬ</b>\n\n"
            "Ответь на сообщение игрока и напиши:\n"
            "<code>/duel 100</code>"
        )
        return

    target = register(m.reply_to_message)

    if target["id"] == a["id"]:
        await m.answer("❌ Нельзя вызвать самого себя.")
        return

    parts = m.text.split()
    amount = 100

    if len(parts) > 1:
        try:
            amount = int(parts[1])
        except ValueError:
            await m.answer("❌ Неверная ставка.")
            return

    if amount <= 0:
        await m.answer("❌ Ставка должна быть больше нуля.")
        return

    if a["coins"] < amount:
        await m.answer("❌ У тебя недостаточно монет.")
        return

    if target["coins"] < amount:
        await m.answer("❌ У соперника недостаточно монет.")
        return

    ra = random.randint(1, 6)
    rb = random.randint(1, 6)

    db(
        """
        UPDATE users
        SET coins=coins-?,
            duel_games=duel_games+1
        WHERE id=?
        """,
        (amount, a["id"])
    )

    db(
        """
        UPDATE users
        SET coins=coins-?,
            duel_games=duel_games+1
        WHERE id=?
        """,
        (amount, target["id"])
    )

    if ra == rb:
        db(
            "UPDATE users SET coins=coins+? WHERE id=?",
            (amount, a["id"])
        )
        db(
            "UPDATE users SET coins=coins+? WHERE id=?",
            (amount, target["id"])
        )

        await m.answer(
            "⚔️ <b>ДУЭЛЬ — НИЧЬЯ!</b>\n\n"
            f"👤 {a['name']}: 🎲 {ra}\n"
            f"👤 {target['name']}: 🎲 {rb}\n\n"
            "💰 Ставки возвращены."
        )
        return

    if ra > rb:
        winner = a
        loser = target
        rw = ra
        rl = rb
    else:
        winner = target
        loser = a
        rw = rb
        rl = ra

    prize = amount * 2

    db(
        """
        UPDATE users
        SET coins=coins+?,
            duel_wins=duel_wins+1
        WHERE id=?
        """,
        (prize, winner["id"])
    )

    await m.answer(
        "⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
        f"👤 {a['name']}: 🎲 {ra}\n"
        f"👤 {target['name']}: 🎲 {rb}\n\n"
        f"👑 Победитель: <b>{winner['name']}</b>\n"
        f"💰 Приз: <b>{prize}</b>"
    )


# =========================
# CLANS
# =========================

@dp.callback_query(F.data == "clans")
async def clans_menu(c: CallbackQuery):
    u = get_user(c.from_user.id)

    if u["clan_id"]:
        clan = db(
            "SELECT * FROM clans WHERE id=?",
            (u["clan_id"],),
            one=True
        )

        if clan:
            await show_clan(c, clan)
            return

    await c.message.edit_text(
        "👥 <b>КЛАНЫ</b>\n\n"
        "Ты пока не состоишь в клане.\n\n"
        "Создать клан:\n"
        "<code>/clan_create Название</code>\n\n"
        "Вступить в клан:\n"
        "<code>/clan_join ID</code>\n\n"
        "Посмотреть кланы:\n"
        "<code>/clans</code>",
        reply_markup=back_keyboard()
    )
    await c.answer()


def ensure_clans():
    db("""
    CREATE TABLE IF NOT EXISTS clans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        owner_id INTEGER,
        treasury INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0
    )
    """)

    db("""
    CREATE TABLE IF NOT EXISTS clan_members(
        clan_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(clan_id,user_id)
    )
    """)


@dp.message(Command("clan_create"))
async def clan_create(m: Message):
    ensure_clans()
    u = register(m)

    if u["clan_id"]:
        await m.answer("❌ Ты уже состоишь в клане.")
        return

    parts = m.text.split(maxsplit=1)

    if len(parts) < 2:
        await m.answer(
            "👥 Использование:\n"
            "<code>/clan_create Название</code>"
        )
        return

    name = parts[1].strip()[:30]

    try:
        db(
            """
            INSERT INTO clans(name,owner_id)
            VALUES(?,?)
            """,
            (name, u["id"])
        )

        clan = db(
            "SELECT * FROM clans WHERE name=?",
            (name,),
            one=True
        )

        db(
            """
            INSERT INTO clan_members(clan_id,user_id)
            VALUES(?,?)
            """,
            (clan["id"], u["id"])
        )

        db(
            "UPDATE users SET clan_id=? WHERE id=?",
            (clan["id"], u["id"])
        )

        await m.answer(
            f"👑 <b>КЛАН СОЗДАН!</b>\n\n"
            f"👥 {name}\n"
            f"🆔 ID: <b>{clan['id']}</b>"
        )

    except sqlite3.IntegrityError:
        await m.answer("❌ Такое название клана уже занято.")


@dp.message(Command("clan_join"))
async def clan_join(m: Message):
    ensure_clans()
    u = register(m)

    if u["clan_id"]:
        await m.answer("❌ Ты уже состоишь в клане.")
        return

    parts = m.text.split()

    if len(parts) < 2:
        await m.answer(
            "Использование:\n"
            "<code>/clan_join ID</code>"
        )
        return

    try:
        cid = int(parts[1])
    except ValueError:
        await m.answer("❌ Неверный ID клана.")
        return

    clan = db(
        "SELECT * FROM clans WHERE id=?",
        (cid,),
        one=True
    )

    if not clan:
        await m.answer("❌ Клан не найден.")
        return

    db(
        """
        INSERT INTO clan_members(clan_id,user_id)
        VALUES(?,?)
        """,
        (cid, u["id"])
    )

    db(
        "UPDATE users SET clan_id=? WHERE id=?",
        (cid, u["id"])
    )

    await m.answer(
        f"👥 Ты вступил в клан <b>{clan['name']}</b>!"
    )


@dp.message(Command("clans"))
async def clans_command(m: Message):
    ensure_clans()
    register(m)

    rows = db(
        """
        SELECT c.id,c.name,c.treasury,
        COUNT(cm.user_id) members
        FROM clans c
        LEFT JOIN clan_members cm
        ON cm.clan_id=c.id
        GROUP BY c.id
        ORDER BY c.treasury DESC
        LIMIT 15
        """
    )

    if not rows:
        await m.answer(
            "👥 Кланов пока нет.\n\n"
            "Создай первый:\n"
            "<code>/clan_create Название</code>"
        )
        return

    text = "👥 <b>ТОП КЛАНОВ</b>\n\n"

    for i, x in enumerate(rows, 1):
        text += (
            f"{i}. <b>{x['name']}</b>\n"
            f"🆔 {x['id']} | 👤 {x['members']} | "
            f"💰 {x['treasury']}\n\n"
        )

    await m.answer(text)


async def show_clan(c, clan):
    members = db(
        """
        SELECT COUNT(*) amount
        FROM clan_members
        WHERE clan_id=?
        """,
        (clan["id"],),
        one=True
    )["amount"]

    owner = get_user(clan["owner_id"])

    text = (
        "👥 <b>МОЙ КЛАН</b>\n\n"
        f"🏰 <b>{clan['name']}</b>\n"
        f"🆔 ID: <b>{clan['id']}</b>\n"
        f"👑 Глава: <b>{owner['name']}</b>\n"
        f"👤 Участников: <b>{members}</b>\n"
        f"💰 Казна: <b>{clan['treasury']}</b>\n"
        f"🏆 Победы: <b>{clan['wins']}</b>\n\n"
        "Для пополнения казны:\n"
        "<code>/clan_pay 100</code>"
    )

    await c.message.edit_text(
        text,
        reply_markup=back_keyboard()
    )


@dp.message(Command("clan_pay"))
async def clan_pay(m: Message):
    ensure_clans()
    u = register(m)

    if not u["clan_id"]:
        await m.answer("❌ Ты не состоишь в клане.")
        return

    parts = m.text.split()

    if len(parts) < 2:
        await m.answer(
            "Использование:\n"
            "<code>/clan_pay 100</code>"
        )
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await m.answer("❌ Неверная сумма.")
        return

    if amount <= 0 or u["coins"] < amount:
        await m.answer("❌ Недостаточно монет.")
        return

    db(
        "UPDATE users SET coins=coins-? WHERE id=?",
        (amount, u["id"])
    )

    db(
        "UPDATE clans SET treasury=treasury+? WHERE id=?",
        (amount, u["clan_id"])
    )

    await m.answer(
        f"👥 В казну клана внесено <b>{amount} 💰</b>."
    )


# =========================
# TOP
# =========================

@dp.callback_query(F.data == "top")
async def top_callback(c: CallbackQuery):
    await show_top(c)


@dp.message(Command("top"))
async def top_command(m: Message):
    register(m)
    await show_top(m)


async def show_top(obj):
    rows = db(
        """
        SELECT name,coins,spins,wins,best_win
        FROM users
        ORDER BY coins DESC
        LIMIT 10
        """
    )

    text = "🏆 <b>ТОП ЛУДИКОВ</b>\n\n"

    for i, x in enumerate(rows, 1):
        text += (
            f"{i}. <b>{x['name']}</b>\n"
            f"💰 {x['coins']} | 🎰 {x['spins']} | "
            f"🏆 {x['wins']}\n"
        )

    b = InlineKeyboardBuilder()
    b.button(text="🏠 Меню", callback_data="menu")

    if isinstance(obj, CallbackQuery):
        await obj.message.edit_text(
            text,
            reply_markup=b.as_markup()
        )
        await obj.answer()
    else:
        await obj.answer(
            text,
            reply_markup=b.as_markup()
        )


# =========================
# GROUP TOP
# =========================

@dp.message(Command("group"))
async def group_command(m: Message):
    if m.chat.type == "private":
        await m.answer("👥 Эта команда работает в группе.")
        return

    register(m)

    rows = db(
        """
        SELECT u.name,u.coins,u.wins
        FROM users u
        JOIN chat_users c
        ON c.user_id=u.id
        WHERE c.chat_id=?
        ORDER BY u.coins DESC
        LIMIT 10
        """,
        (m.chat.id,)
    )

    st = db(
        "SELECT * FROM chats WHERE chat_id=?",
        (m.chat.id,),
        one=True
    )

    text = (
        "👥 <b>СТАТИСТИКА ГРУППЫ</b>\n\n"
        f"🎰 Игр: <b>{st['spins']}</b>\n"
        f"🏆 Побед: <b>{st['wins']}</b>\n"
        f"💰 Выиграно: <b>{st['coins']}</b>\n\n"
        "🏆 <b>ТОП ГРУППЫ</b>\n\n"
    )

    for i, x in enumerate(rows, 1):
        text += (
            f"{i}. {x['name']} — "
            f"💰 {x['coins']} | 🏆 {x['wins']}\n"
        )

    await m.answer(text)


# =========================
# TRANSFER
# =========================

@dp.message(Command("pay"))
async def pay_command(m: Message):
    sender = register(m)

    if not m.reply_to_message:
        await m.answer(
            "💸 Чтобы передать монеты:\n\n"
            "Ответь на сообщение игрока и напиши:\n"
            "<code>/pay 500</code>"
        )
        return

    target = register(m.reply_to_message)

    parts = m.text.split()

    if len(parts) < 2:
        await m.answer("❌ Укажи сумму.")
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await m.answer("❌ Неверная сумма.")
        return

    if amount <= 0:
        await m.answer("❌ Сумма должна быть больше нуля.")
        return

    if sender["coins"] < amount:
        await m.answer("❌ Недостаточно монет.")
        return

    if sender["id"] == target["id"]:
        await m.answer("❌ Нельзя отправить монеты самому себе.")
        return

    db(
        "UPDATE users SET coins=coins-? WHERE id=?",
        (amount, sender["id"])
    )

    db(
        "UPDATE users SET coins=coins+? WHERE id=?",
        (amount, target["id"])
    )

    await m.answer(
        f"💸 <b>{amount} 💰</b> передано игроку "
        f"<b>{target['name']}</b>!"
    )


# =========================
# MISSIONS
# =========================

@dp.callback_query(F.data == "missions")
async def missions_callback(c: CallbackQuery):
    await show_missions(c)


async def show_missions(obj):
    u = get_user(obj.from_user.id)

    text = (
        "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n\n"
        f"🎰 10 вращений: "
        f"<b>{min(u['mission_spins'],10)}/10</b>\n"
        f"🏆 5 побед: "
        f"<b>{min(u['mission_wins'],5)}/5</b>\n"
        f"💰 Выиграть 1000: "
        f"<b>{min(u['mission_coins'],1000)}/1000</b>\n\n"
        "🎁 Награда за выполнение: <b>500 💰</b>"
    )

    b = InlineKeyboardBuilder()
    b.button(text="🎁 Забрать награду", callback_data="claim_mission")
    b.button(text="🏠 Меню", callback_data="menu")
    b.adjust(1)

    if isinstance(obj, CallbackQuery):
        await obj.message.edit_text(
            text,
            reply_markup=b.as_markup()
        )
        await obj.answer()
    else:
        await obj.answer(
            text,
            reply_markup=b.as_markup()
        )


@dp.message(Command("missions"))
async def missions_command(m: Message):
    register(m)
    await show_missions(m)


@dp.callback_query(F.data == "claim_mission")
async def claim_mission(c: CallbackQuery):
    u = get_user(c.from_user.id)

    if (
        u["mission_spins"] < 10
        or u["mission_wins"] < 5
        or u["mission_coins"] < 1000
    ):
        await c.answer(
            "❌ Все задания ещё не выполнены.",
            show_alert=True
        )
        return

    db(
        """
        UPDATE users
        SET coins=coins+500,
            mission_spins=0,
            mission_wins=0,
            mission_coins=0
        WHERE id=?
        """,
        (u["id"],)
    )

    await c.answer("🎁 +500 💰")
    await show_missions(c)


# =========================
# WHEEL
# =========================

@dp.callback_query(F.data == "wheel")
async def wheel_callback(c: CallbackQuery):
    u = get_user(c.from_user.id)

    if u["wheel_day"] == today():
        await c.answer(
            "🎡 Сегодня колесо уже использовано.",
            show_alert=True
        )
        return

    prizes = [50, 100, 150, 250, 500, 1000, 2000]
    prize = random.choice(prizes)

    db(
        """
        UPDATE users
        SET coins=coins+?,
            wheel_day=?
        WHERE id=?
        """,
        (prize, today(), u["id"])
    )

    await c.message.edit_text(
        "🎡 <b>КОЛЕСО УДАЧИ</b>\n\n"
        "🎰 Колесо вращается...\n\n"
        f"🎉 Твой приз: <b>+{prize} 💰</b>",
        reply_markup=main_keyboard()
    )

    await c.answer()


# =========================
# ACHIEVEMENTS
# =========================

@dp.callback_query(F.data == "achievements")
async def achievements(c: CallbackQuery):
    u = get_user(c.from_user.id)

    items = []

    if u["spins"] >= 10:
        items.append("🎰 Ветеран — 10 вращений")

    if u["spins"] >= 100:
        items.append("🎰 Мастер — 100 вращений")

    if u["wins"] >= 10:
        items.append("🏆 Победитель — 10 побед")

    if u["best_win"] >= 1000:
        items.append("💎 Большой куш — выигрыш 1000+")

    if level(u["xp"]) >= 10:
        items.append("⭐ Опытный игрок — уровень 10")

    if u["dice_wins"] >= 10:
        items.append("🎲 Кубик — 10 побед")

    if u["duel_wins"] >= 10:
        items.append("⚔️ Дуэлянт — 10 побед")

    text = "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"

    if items:
        text += "\n".join("✅ " + x for x in items)
    else:
        text += "🔒 Пока нет открытых достижений.\n\n"
        text += "Продолжай играть!"

    b = InlineKeyboardBuilder()
    b.button(text="👤 Профиль", callback_data="profile")
    b.button(text="🏠 Меню", callback_data="menu")
    b.adjust(1)

    await c.message.edit_text(
        text,
        reply_markup=b.as_markup()
    )
    await c.answer()


# =========================
# STATISTICS
# =========================

@dp.callback_query(F.data == "statistics")
async def statistics(c: CallbackQuery):
    u = get_user(c.from_user.id)

    text = (
        "📊 <b>СТАТИСТИКА</b>\n\n"
        "🎰 <b>Слоты</b>\n"
        f"Игры: {u['spins']}\n"
        f"Победы: {u['wins']}\n"
        f"Лучший выигрыш: {u['best_win']}\n\n"
        "🎲 <b>Кубик</b>\n"
        f"Игры: {u['dice_games']}\n"
        f"Победы: {u['dice_wins']}\n\n"
        "⚔️ <b>Дуэли</b>\n"
        f"Дуэлей: {u['duel_games']}\n"
        f"Побед: {u['duel_wins']}"
    )

    b = InlineKeyboardBuilder()
    b.button(text="👤 Профиль", callback_data="profile")
    b.button(text="🏠 Меню", callback_data="menu")
    b.adjust(1)

    await c.message.edit_text(
        text,
        reply_markup=b.as_markup()
    )
    await c.answer()


# =========================
# MY RATING
# =========================

@dp.callback_query(F.data == "my_rating")
async def my_rating(c: CallbackQuery):
    u = get_user(c.from_user.id)

    row = db(
        """
        SELECT COUNT(*)+1 place
       

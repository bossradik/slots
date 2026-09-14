import os
import random
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("BOT_TOKEN")
DB = "slots.db"

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

lock = threading.Lock()
conn = sqlite3.connect(DB, check_same_thread=False)
conn.row_factory = sqlite3.Row


def db(q, p=(), one=False):
    with lock:
        cur = conn.execute(q, p)
        conn.commit()
        return cur.fetchone() if one else cur.fetchall()


def init():
    db("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        coins INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best INTEGER DEFAULT 0,
        bet INTEGER DEFAULT 10,
        mission_spins INTEGER DEFAULT 0,
        mission_wins INTEGER DEFAULT 0,
        mission_coins INTEGER DEFAULT 0,
        wheel_day TEXT DEFAULT '',
        mission_day TEXT DEFAULT '',
        season INTEGER DEFAULT 0
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
    if not db("SELECT * FROM settings WHERE key='jackpot'", one=True):
        db("INSERT INTO settings VALUES('jackpot',5000)")


def user(m):
    u = db("SELECT * FROM users WHERE id=?", (m.from_user.id,), True)
    if not u:
        db(
            "INSERT INTO users(id,username,name) VALUES(?,?,?)",
            (m.from_user.id, m.from_user.username or "",
             m.from_user.full_name[:40])
        )
    else:
        db(
            "UPDATE users SET username=?,name=? WHERE id=?",
            (m.from_user.username or "", m.from_user.full_name[:40],
             m.from_user.id)
        )

    if m.chat.type != "private":
        db(
            "INSERT OR IGNORE INTO chat_users VALUES(?,?)",
            (m.chat.id, m.from_user.id)
        )
        db("INSERT OR IGNORE INTO chats(chat_id) VALUES(?)", (m.chat.id,))

    return db("SELECT * FROM users WHERE id=?", (m.from_user.id,), True)


def level(xp):
    return xp // 100 + 1


def day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def happy():
    h = datetime.now(timezone.utc).hour
    return 18 <= h < 20


def game_kb(u):
    b = InlineKeyboardBuilder()
    b.button(text="🎰 КРУТИТЬ", callback_data="spin")
    b.button(text=f"💰 Ставка: {u['bet']}", callback_data="bets")
    b.button(text="📖 Комбинации", callback_data="combos")
    b.button(text="🎡 Колесо", callback_data="wheel")
    b.button(text="🎯 Задания", callback_data="missions")
    b.adjust(1, 1, 2)
    return b.as_markup()


def bets_kb():
    b = InlineKeyboardBuilder()
    for x in (10, 25, 50, 100):
        b.button(text=f"💰 {x}", callback_data=f"bet:{x}")
    b.button(text="⬅️ Назад", callback_data="back")
    b.adjust(2, 2, 1)
    return b.as_markup()


async def game(m):
    u = user(m)
    j = db("SELECT value FROM settings WHERE key='jackpot'", one=True)["value"]
    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{u['coins']}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"✨ XP: <b>{u['xp']}</b>\n"
        f"💵 Ставка: <b>{u['bet']}</b>\n"
        f"👑 Джекпот: <b>{j}</b>\n\n"
        "Нажми <b>КРУТИТЬ</b> 🎰"
    )
    await m.answer(text, reply_markup=game_kb(u))


@dp.message(CommandStart())
async def start(m: Message):
    user(m)
    await m.answer(
        "🎰 <b>Добро пожаловать в СЛОТЫ!</b>\n\n"
        "Крути барабаны, выполняй задания, "
        "соревнуйся с игроками и собирай монеты.\n\n"
        "Нажми /slots",
    )


@dp.message(Command("slots"))
async def slots(m: Message):
    await game(m)


@dp.message(Command("help"))
async def help_cmd(m: Message):
    user(m)
    await m.answer(
        "📚 <b>КОМАНДЫ</b>\n\n"
        "/slots — 🎰 играть\n"
        "/balance — 💰 баланс\n"
        "/bonus — 🎁 ежедневный бонус\n"
        "/top — 🏆 общий топ\n"
        "/group — 👥 статистика группы\n"
        "/pay — 💸 передать монеты\n"
        "/duel — ⚔️ дуэль\n"
        "/dice — 🎲 кости\n"
        "/help — 📚 команды"
    )


@dp.message(Command("balance"))
async def balance(m: Message):
    u = user(m)
    await m.answer(
        f"💰 Баланс: <b>{u['coins']}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"✨ XP: <b>{u['xp']}</b>\n"
        f"🎰 Игр: <b>{u['spins']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b>\n"
        f"💎 Лучший выигрыш: <b>{u['best']}</b>"
    )


@dp.message(Command("bonus"))
async def bonus(m: Message):
    u = user(m)
    d = day()

    if u["mission_day"] == d:
        await m.answer("🎁 Сегодняшний бонус уже получен.")
        return

    amount = 100 + level(u["xp"]) * 25
    db(
        "UPDATE users SET coins=coins+?,mission_day=? WHERE id=?",
        (amount, d, u["id"])
    )
    await m.answer(f"🎁 Бонус получен: <b>+{amount}</b> 💰")


@dp.callback_query(F.data == "bets")
async def bets(c: CallbackQuery):
    await c.message.edit_text(
        "💰 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
        "Ставка сохранится и будет использоваться "
        "при следующем вращении.",
        reply_markup=bets_kb()
    )
    await c.answer()


@dp.callback_query(F.data.startswith("bet:"))
async def set_bet(c: CallbackQuery):
    x = int(c.data.split(":")[1])
    db("UPDATE users SET bet=? WHERE id=?", (x, c.from_user.id))
    u = db("SELECT * FROM users WHERE id=?", (c.from_user.id,), True)
    await c.message.edit_text(
        f"💵 Ставка установлена: <b>{x}</b>\n\n"
        "Можно сразу крутить 🎰",
        reply_markup=game_kb(u)
    )
    await c.answer()


@dp.callback_query(F.data == "spin")
async def spin(c: CallbackQuery):
    u = db("SELECT * FROM users WHERE id=?", (c.from_user.id,), True)

    if not u or u["coins"] < u["bet"]:
        await c.answer("❌ Недостаточно монет", show_alert=True)
        return

    bet = u["bet"]

    await c.message.edit_text("🎰 <b>7️⃣ | 🍒 | 🔔</b>\n\nКрутим...")
    await c.answer()

    symbols = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
    a, b, d = random.choices(symbols, k=3)

    jackpot = db(
        "SELECT value FROM settings WHERE key='jackpot'",
        one=True
    )["value"]

    win = 0
    reason = ""

    if random.randint(1, 10000) == 1:
        win = 50000
        reason = "👑 <b>ЛЕГЕНДАРНЫЙ ДРОП!</b>"
    elif a == b == d == "7️⃣":
        win = jackpot
        db("UPDATE settings SET value=5000 WHERE key='jackpot'")
        reason = "👑 <b>ДЖЕКПОТ!</b>"
    elif a == b == d:
        mult = {
            "🍒": 5,
            "🍋": 7,
            "🍊": 10,
            "🔔": 15,
            "💎": 30,
            "7️⃣": 100
        }[a]
        win = bet * mult
        reason = f"🔥 Тройка! x{mult}"
    elif a == b or a == d or b == d:
        win = bet * 2
        reason = "✨ Два одинаковых! x2"

    if happy() and win:
        win *= 2
        reason += "\n🔥 <b>HAPPY HOUR x2!</b>"

    newcoins = u["coins"] - bet + win
    xp = u["xp"] + 10
    best = max(u["best"], win)

    db("""
    UPDATE users SET
    coins=?,xp=?,spins=spins+1,wins=wins+?,best=?,
    mission_spins=mission_spins+1,
    mission_wins=mission_wins+?,
    mission_coins=mission_coins+?,
    season=season+?
    WHERE id=?
    """, (
        newcoins, xp, 1 if win else 0, best,
        1 if win else 0, win, win, u["id"]
    ))

    db(
        "UPDATE settings SET value=value+? WHERE key='jackpot'",
        (max(1, bet // 10),)
    )

    if c.message.chat.type != "private":
        db(
            "UPDATE chats SET spins=spins+1,wins=wins+?,coins=coins+? WHERE chat_id=?",
            (1 if win else 0, win, c.message.chat.id)
        )

    text = (
        f"🎰 <b>{a} | {b} | {d}</b>\n\n"
        f"{reason or '💨 Не повезло...'}\n\n"
        f"💰 Ставка: <b>{bet}</b>\n"
        f"🏆 Выигрыш: <b>{win}</b>\n"
        f"💰 Баланс: <b>{newcoins}</b>\n"
        f"⭐ Уровень: <b>{level(xp)}</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🎰 КРУТИТЬ ЕЩЁ РАЗ", callback_data="spin")
    kb.button(text="💰 Изменить ставку", callback_data="bets")
    kb.button(text="📖 Комбинации", callback_data="combos")
    kb.adjust(1, 2)

    await c.message.edit_text(text, reply_markup=kb.as_markup())


@dp.callback_query(F.data == "combos")
async def combos(c: CallbackQuery):
    await c.message.edit_text(
        "📖 <b>КОМБИНАЦИИ</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — ДЖЕКПОТ 👑\n\n"
        "✨ Любые 2 одинаковых — x2\n"
        "👑 Редкий дроп — 50 000 💰\n"
        "🔥 Happy Hour — удвоение выигрыша",
        reply_markup=InlineKeyboardBuilder().button(
            text="⬅️ Играть", callback_data="back"
        ).as_markup()
    )
    await c.answer()


@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery):
    u = db("SELECT * FROM users WHERE id=?", (c.from_user.id,), True)
    await c.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{u['coins']}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"💵 Ставка: <b>{u['bet']}</b>",
        reply_markup=game_kb(u)
    )
    await c.answer()


@dp.callback_query(F.data == "missions")
async def missions(c: CallbackQuery):
    u = db("SELECT * FROM users WHERE id=?", (c.from_user.id,), True)
    text = (
        "🎯 <b>ЗАДАНИЯ</b>\n\n"
        f"🎰 10 вращений: {min(u['mission_spins'],10)}/10\n"
        f"🏆 5 побед: {min(u['mission_wins'],5)}/5\n"
        f"💰 Выиграть 1000: {min(u['mission_coins'],1000)}/1000\n\n"
        "Награда: <b>500 💰</b>"
    )

    b = InlineKeyboardBuilder()
    b.button(text="🎁 Забрать", callback_data="claim_mission")
    b.button(text="⬅️ Назад", callback_data="back")
    b.adjust(1, 1)

    await c.message.edit_text(text, reply_markup=b.as_markup())
    await c.answer()


@dp.callback_query(F.data == "claim_mission")
async def claim_mission(c: CallbackQuery):
    u = db("SELECT * FROM users WHERE id=?", (c.from_user.id,), True)

    if (
        u["mission_spins"] < 10
        or u["mission_wins"] < 5
        or u["mission_coins"] < 1000
    ):
        await c.answer("❌ Задание ещё не выполнено", show_alert=True)
        return

    db("""
    UPDATE users SET coins=coins+500,
    mission_spins=0,mission_wins=0,mission_coins=0
    WHERE id=?
    """, (u["id"],))

    await c.answer("🎁 +500 монет!")
    await missions(c)


@dp.callback_query(F.data == "wheel")
async def wheel(c: CallbackQuery):
    u = db("SELECT * FROM users WHERE id=?", (c.from_user.id,), True)

    if u["wheel_day"] == day():
        await c.answer("🎡 Сегодня колесо уже использовано", show_alert=True)
        return

    prizes = [50, 100, 150, 250, 500, 1000, 2000]
    prize = random.choice(prizes)

    db(
        "UPDATE users SET coins=coins+?,wheel_day=? WHERE id=?",
        (prize, day(), u["id"])
    )

    await c.message.edit_text(
        f"🎡 <b>КОЛЕСО</b>\n\n"
        f"🎉 Тебе выпало: <b>+{prize} 💰</b>",
        reply_markup=game_kb(
            db("SELECT * FROM users WHERE id=?", (u["id"],), True)
        )
    )
    await c.answer()


@dp.message(Command("top"))
async def top(m: Message):
    user(m)
    rows = db("""
    SELECT name,coins,spins,wins,best
    FROM users ORDER BY coins DESC LIMIT 10
    """)

    text = "🏆 <b>ТОП ЛУДИКОВ</b>\n\n"
    for i, x in enumerate(rows, 1):
        text += (
            f"{i}. {x['name']} — 💰 {x['coins']} "
            f"| 🎰 {x['spins']} | 🏆 {x['wins']}\n"
        )

    await m.answer(text)


@dp.message(Command("group"))
async def group(m: Message):
    if m.chat.type == "private":
        await m.answer("👥 Эта команда работает в группе.")
        return

    user(m)
    rows = db("""
    SELECT u.name,u.coins,u.wins
    FROM users u
    JOIN chat_users c ON c.user_id=u.id
    WHERE c.chat_id=?
    ORDER BY u.coins DESC LIMIT 10
    """, (m.chat.id,))

    st = db(
        "SELECT * FROM chats WHERE chat_id=?",
        (m.chat.id,), True
    )

    text = (
        "👥 <b>СТАТИСТИКА ГРУППЫ</b>\n\n"
        f"🎰 Вращений: <b>{st['spins']}</b>\n"
        f"🏆 Побед: <b>{st['wins']}</b>\n"
        f"💰 Выиграно: <b>{st['coins']}</b>\n\n"
        "🏆 <b>ТОП ГРУППЫ</b>\n"
    )

    for i, x in enumerate(rows, 1):
        text += f"{i}. {x['name']} — 💰 {x['coins']}\n"

    await m.answer(text)


@dp.message(Command("pay"))
async def pay(m: Message):
    user(m)
    parts = m.text.split()

    if len(parts) < 2:
        await m.answer(
            "💸 Использование:\n"
            "<code>/pay 500</code> — ответом на сообщение игрока"
        )
        return

    try:
        amount = int(parts[-1])
    except ValueError:
        await m.answer("❌ Укажи сумму.")
        return

    if amount <= 0:
        await m.answer("❌ Неверная сумма.")
        return

    target = None

    if m.reply_to_message:
        target = user(m.reply_to_message)

    elif len(parts) >= 3 and parts[1].startswith("@"):
        target = db(
            "SELECT * FROM users WHERE username=?",
            (parts[1][1:],), True
        )

    if not target:
        await m.answer("❌ Игрок не найден. Лучше используй ответ на его сообщение.")
        return

    sender = db("SELECT * FROM users WHERE id=?", (m.from_user.id,), True)

    if sender["coins"] < amount:
        await m.answer("❌ Недостаточно монет.")
        return

    if target["id"] == sender["id"]:
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
        f"💸 Передано <b>{amount}</b> 💰 игроку "
        f"<b>{target['name']}</b>"
    )


@dp.message(Command("dice"))
async def dice(m: Message):
    u = user(m)

    if u["coins"] < 50:
        await m.answer("❌ Нужно минимум 50 💰.")
        return

    roll = random.randint(1, 6)

    if roll >= 4:
        win = 100
        db("UPDATE users SET coins=coins+50 WHERE id=?", (u["id"],))
        result = f"🎉 Победа! Выпало <b>{roll}</b>. +50 💰"
    else:
        db("UPDATE users SET coins=coins-50 WHERE id=?", (u["id"],))
        result = f"💨 Проигрыш. Выпало <b>{roll}</b>. -50 💰"

    await m.answer("🎲 <b>КОСТИ</b>\n\n" + result)


@dp.message(Command("duel"))
async def duel(m: Message):
    user(m)

    if not m.reply_to_message:
        await m.answer(
            "⚔️ Для дуэли ответь на сообщение игрока:\n"
            "<code>/duel 100</code>"
        )
        return

    parts = m.text.split()

    try:
        amount = int(parts[1]) if len(parts) > 1 else 100
    except ValueError:
        amount = 100

    if amount <= 0:
        await m.answer("❌ Неверная ставка.")
        return

    a = db("SELECT * FROM users WHERE id=?", (m.from_user.id,), True)
    b = user(m.reply_to_message)

    if a["coins"] < amount or b["coins"] < amount:
        await m.answer("❌ У одного из игроков недостаточно монет.")
        return

    ra = random.randint(1, 6)
    rb = random.randint(1, 6)

    if ra == rb:
        await m.answer(
            f"⚔️ <b>НИЧЬЯ!</b>\n\n"
            f"{a['name']}: 🎲 {ra}\n"
            f"{b['name']}: 🎲 {rb}"
        )
        return

    winner = a if ra > rb else b
    loser = b if ra > rb else a

    db("UPDATE users SET coins=coins+? WHERE id=?", (amount, winner["id"]))
    db("UPDATE users SET coins=coins-? WHERE id=?", (amount, loser["id"]))

    await m.answer(
        "⚔️ <b>ДУЭЛЬ</b>\n\n"
        f"{a['name']}: 🎲 {ra}\n"
        f"{b['name']}: 🎲 {rb}\n\n"
        f"👑 Победитель: <b>{winner['name']}</b>\n"
        f"💰 Приз: <b>{amount}</b>"
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def server():
    port = int(os.getenv("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


async def main():
    init()
    threading.Thread(target=server, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=False)
    print("BOT STARTED")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

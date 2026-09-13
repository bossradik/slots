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

TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB = "slots.db"
START = 1000
JACKPOT_START = 5000
BETS = (10, 25, 50, 100)
SYMBOLS = ("🍒", "🍋", "🍊", "🔔", "💎", "7️⃣")
MULT = {"🍒": 5, "🍋": 7, "🍊": 10, "🔔": 15, "💎": 30, "7️⃣": 100}

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Render Environment.")

db = sqlite3.connect(DB, check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.RLock()

def init_db():
    with lock:
        db.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, username TEXT DEFAULT '', name TEXT DEFAULT '',
            balance INTEGER DEFAULT 1000, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1,
            last_bonus TEXT DEFAULT '', streak INTEGER DEFAULT 0, spins INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0, best_win INTEGER DEFAULT 0,
            win_streak INTEGER DEFAULT 0, best_streak INTEGER DEFAULT 0, gear INTEGER DEFAULT 1)""")
        db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value INTEGER)")
        db.execute("INSERT OR IGNORE INTO settings VALUES('jackpot', ?)", (JACKPOT_START,))
        db.execute("""CREATE TABLE IF NOT EXISTS tasks(
            user_id INTEGER, day TEXT, spins INTEGER DEFAULT 0, won INTEGER DEFAULT 0,
            big INTEGER DEFAULT 0, claimed_spins INTEGER DEFAULT 0,
            claimed_won INTEGER DEFAULT 0, claimed_big INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, day))""")
        db.commit()
        cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
        needed = {
            "username":"TEXT DEFAULT ''","name":"TEXT DEFAULT ''","balance":"INTEGER DEFAULT 1000",
            "xp":"INTEGER DEFAULT 0","level":"INTEGER DEFAULT 1","last_bonus":"TEXT DEFAULT ''",
            "streak":"INTEGER DEFAULT 0","spins":"INTEGER DEFAULT 0","wins":"INTEGER DEFAULT 0",
            "total_won":"INTEGER DEFAULT 0","best_win":"INTEGER DEFAULT 0","win_streak":"INTEGER DEFAULT 0",
            "best_streak":"INTEGER DEFAULT 0","gear":"INTEGER DEFAULT 1"}
        for col, typ in needed.items():
            if col not in cols:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        db.commit()

def user(uid, username="", name=""):
    with lock:
        r = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            db.execute("INSERT INTO users(id,username,name,balance) VALUES(?,?,?,?)",
                       (uid, username or "", name or "", START))
            db.commit()
        else:
            db.execute("UPDATE users SET username=?,name=? WHERE id=?",
                       (username or r["username"], name or r["name"], uid))
            db.commit()
        return dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())

def update(uid, **kw):
    if not kw:
        return
    allowed = {"username","name","balance","xp","level","last_bonus","streak","spins","wins",
               "total_won","best_win","win_streak","best_streak","gear"}
    kw = {k:v for k,v in kw.items() if k in allowed}
    sql = ",".join(f"{k}=?" for k in kw)
    with lock:
        db.execute(f"UPDATE users SET {sql} WHERE id=?", (*kw.values(), uid))
        db.commit()

def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def jp():
    return int(db.execute("SELECT value FROM settings WHERE key='jackpot'").fetchone()["value"])

def add_jp(n):
    with lock:
        db.execute("UPDATE settings SET value=value+? WHERE key='jackpot'", (n,))
        db.commit()

def reset_jp():
    with lock:
        db.execute("UPDATE settings SET value=? WHERE key='jackpot'", (JACKPOT_START,))
        db.commit()

def pname(u):
    return "@" + u["username"] if u["username"] else (u["name"] or f"Игрок {u['id']}")

def home(u):
    return (f"🎰 <b>СЛОТЫ</b>\n\n👤 {pname(u)}\n💰 Баланс: <b>{u['balance']}</b> 🪙\n"
            f"⭐ Уровень: <b>{u['level']}</b>\n✨ XP: <b>{u['xp']%100}/100</b>\n"
            f"🎰 Спинов: <b>{u['spins']}</b>\n\nВыбери действие:")

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 КРУТИТЬ 10", callback_data="spin:10")],
        [InlineKeyboardButton(text="💰 25", callback_data="spin:25"),
         InlineKeyboardButton(text="💰 50", callback_data="spin:50"),
         InlineKeyboardButton(text="💰 100", callback_data="spin:100")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🎁 Бонус", callback_data="bonus")],
        [InlineKeyboardButton(text="🏆 ТОП", callback_data="top"),
         InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="⛏️ Экипировка", callback_data="gear"),
         InlineKeyboardButton(text="💎 Джекпот", callback_data="jackpot")]])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="home")]])

def spin(uid, bet):
    u = user(uid)
    if bet not in BETS:
        return "❌ Неверная ставка."
    if u["balance"] < bet:
        return f"❌ Недостаточно монет. Нужно {bet} 🪙."

    a = [random.choice(SYMBOLS) for _ in range(3)]

    if a == ["7️⃣"] * 3:
        win, title = jp(), "👑 <b>ДЖЕКПОТ!</b>"
        reset_jp()
    elif a[0] == a[1] == a[2]:
        win, title = bet * MULT[a[0]], "🎉 <b>ПОБЕДА!</b>"
    elif a[0] == a[1] or a[0] == a[2] or a[1] == a[2]:
        win, title = bet * 2, "🎉 <b>ПАРА!</b>"
    else:
        win, title = 0, "😔 <b>Не повезло</b>"

    xp = u["xp"] + 10 + u["gear"]
    lvl = xp // 100 + 1
    streak = u["win_streak"] + 1 if win else 0
    balance = u["balance"] - bet + win

    update(
        uid,
        balance=balance,
        xp=xp,
        level=lvl,
        spins=u["spins"]+1,
        wins=u["wins"]+(1 if win else 0),
        total_won=u["total_won"]+win,
        best_win=max(u["best_win"], win),
        win_streak=streak,
        best_streak=max(u["best_streak"], streak)
    )

    add_jp(max(1, bet//50))

    return (
        f"{title}\n\n"
        f"🎰 {' | '.join(a)}\n\n"
        f"💰 Ставка: <b>{bet}</b> 🪙\n"
        f"🏆 Выигрыш: <b>{win}</b> 🪙\n"
        f"⭐ +{10+u['gear']} XP\n"
        f"💳 Баланс: <b>{balance}</b> 🪙"
    )

def bonus(uid):
    u = user(uid)
    d = today()

    if u["last_bonus"] == d:
        return 0, u["streak"], u["balance"]

    yesterday = (
        datetime.now(timezone.utc)
        - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    s = u["streak"] + 1 if u["last_bonus"] == yesterday else 1
    amount = 100 + u["level"] * 25 + min(s, 7) * 10

    update(
        uid,
        balance=u["balance"]+amount,
        last_bonus=d,
        streak=s
    )

    return amount, s, u["balance"]+amount

def top():
    rows = db.execute(
        "SELECT * FROM users ORDER BY balance DESC, wins DESC LIMIT 10"
    ).fetchall()

    text = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"

    for i, r in enumerate(rows, 1):
        text += f"{i}. {pname(dict(r))} — <b>{r['balance']}</b> 🪙\n"

    return text

def profile(u):
    return (
        f"👤 <b>ПРОФИЛЬ</b>\n\n"
        f"{pname(u)}\n"
        f"💰 {u['balance']} 🪙\n"
        f"⭐ Уровень {u['level']}\n"
        f"🎰 Спинов: {u['spins']}\n"
        f"🏆 Побед: {u['wins']}\n"
        f"💎 Всего выиграно: {u['total_won']} 🪙\n"
        f"🔥 Серия: {u['win_streak']}\n"
        f"🥇 Лучший выигрыш: {u['best_win']} 🪙"
    )

def tasks(uid):
    with lock:
        db.execute(
            "INSERT OR IGNORE INTO tasks(user_id,day) VALUES(?,?)",
            (uid, today())
        )
        db.commit()

        t = dict(
            db.execute(
                "SELECT * FROM tasks WHERE user_id=? AND day=?",
                (uid, today())
            ).fetchone()
        )

    return (
        f"📋 <b>ЗАДАНИЯ</b>\n\n"
        f"🎰 10 спинов: {min(t['spins'],10)}/10 — +100 🪙\n"
        f"💰 Выиграть 500: {min(t['won'],500)}/500 — +200 🪙\n"
        f"💎 Выигрыш 1000+: {min(t['big'],1)}/1 — +500 🪙"
    )

def gear(u):
    return (
        f"⛏️ <b>ЭКИПИРОВКА</b>\n\n"
        f"Уровень: {u['gear']}\n"
        f"⚡ Сила: {1+u['gear']}\n"
        f"💰 Улучшение: {500*u['gear']} 🪙"
    )

def gear_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬆️ Улучшить",
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
async def start(m: Message):
    u = user(
        m.from_user.id,
        m.from_user.username,
        m.from_user.first_name
    )

    await m.answer(
        home(u),
        reply_markup=main_kb()
    )

@dp.message(Command("balance"))
async def balance(m: Message):
    u = user(m.from_user.id)

    await m.answer(
        f"💰 Баланс: <b>{u['balance']}</b> 🪙",
        reply_markup=main_kb()
    )

@dp.message(Command("bonus"))
async def bonus_cmd(m: Message):
    a, s, b = bonus(m.from_user.id)

    text = (
        f"🎁 +<b>{a}</b> 🪙\n"
        f"🔥 Серия: {s}\n"
        f"💰 Баланс: {b} 🪙"
        if a
        else "⏳ Бонус уже получен сегодня."
    )

    await m.answer(
        text,
        reply_markup=main_kb()
    )

@dp.message(Command("top"))
async def top_cmd(m: Message):
    await m.answer(
        top(),
        reply_markup=back_kb()
    )

@dp.callback_query(F.data == "home")
async def cb_home(c: CallbackQuery):
    await c.message.edit_text(
        home(user(c.from_user.id)),
        reply_markup=main_kb()
    )
    await c.answer()

@dp.callback_query(F.data.startswith("spin:"))
async def cb_spin(c: CallbackQuery):
    await c.message.edit_text(
        spin(
            c.from_user.id,
            int(c.data.split(":")[1])
        ),
        reply_markup=main_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "profile")
async def cb_profile(c: CallbackQuery):
    await c.message.edit_text(
        profile(user(c.from_user.id)),
        reply_markup=back_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "bonus")
async def cb_bonus(c: CallbackQuery):
    a, s, b = bonus(c.from_user.id)

    text = (
        f"🎁 <b>БОНУС</b>\n\n"
        f"+{a} 🪙\n"
        f"🔥 Серия: {s}\n"
        f"💰 Баланс: {b} 🪙"
        if a
        else "⏳ Бонус уже получен сегодня."
    )

    await c.message.edit_text(
        text,
        reply_markup=back_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "top")
async def cb_top(c: CallbackQuery):
    await c.message.edit_text(
        top(),
        reply_markup=back_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "tasks")
async def cb_tasks(c: CallbackQuery):
    await c.message.edit_text(
        tasks(c.from_user.id),
        reply_markup=back_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "jackpot")
async def cb_jp(c: CallbackQuery):
    await c.message.edit_text(
        f"💎 <b>ДЖЕКПОТ</b>\n\n"
        f"Сейчас: <b>{jp()}</b> 🪙\n\n"
        f"Три 7️⃣ забирают джекпот.",
        reply_markup=back_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "gear")
async def cb_gear(c: CallbackQuery):
    await c.message.edit_text(
        gear(user(c.from_user.id)),
        reply_markup=gear_kb()
    )
    await c.answer()

@dp.callback_query(F.data == "gear_up")
async def cb_gear_up(c: CallbackQuery):
    u = user(c.from_user.id)
    cost = 500 * u["gear"]

    if u["balance"] < cost:
        await c.answer(
            "❌ Недостаточно монет.",
            show_alert=True
        )
        return

    update(
        c.from_user.id,
        balance=u["balance"]-cost,
        gear=u["gear"]+1
    )

    await c.message.edit_text(
        "✅ Улучшено!\n\n"
        + gear(user(c.from_user.id)),
        reply_markup=gear_kb()
    )
    await c.answer()

class Health(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass

def serve():
    HTTPServer(
        ("0.0.0.0", PORT),
        Health
    ).serve_forever()

async def main():
    init_db()

    threading.Thread(
        target=serve,
        daemon=True
    ).start()

    print(
        f"SLOTS BOT STARTED | PORT {PORT}",
        flush=True
    )

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

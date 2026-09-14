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

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

conn = sqlite3.connect(DB, check_same_thread=False)
conn.row_factory = sqlite3.Row
lock = threading.Lock()

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
MULT = {"🍒": 5, "🍋": 7, "🍊": 10, "🔔": 15, "💎": 30, "7️⃣": 100}
BETS = [10, 25, 50, 100]

def db(q, p=(), one=False, many=False):
    with lock:
        c = conn.cursor()
        c.execute(q, p)
        r = c.fetchall() if many else c.fetchone()
        conn.commit()
        return r

def init():
    db("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        balance INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best_win INTEGER DEFAULT 0,
        last_bonus TEXT,
        wheel TEXT,
        bet INTEGER DEFAULT 10,
        mission_day TEXT,
        m1 INTEGER DEFAULT 0,
        m2 INTEGER DEFAULT 0,
        m3 INTEGER DEFAULT 0,
        season TEXT,
        season_points INTEGER DEFAULT 0
    )""")
    db("""CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY,
        title TEXT,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        coins INTEGER DEFAULT 0
    )""")
    db("""CREATE TABLE IF NOT EXISTS achievements(
        uid INTEGER,
        code TEXT,
        PRIMARY KEY(uid,code)
    )""")

    cols = db("PRAGMA table_info(users)", many=True)
    have = {x["name"] for x in cols}
    extra = {
        "wheel":"TEXT", "bet":"INTEGER DEFAULT 10",
        "mission_day":"TEXT", "m1":"INTEGER DEFAULT 0",
        "m2":"INTEGER DEFAULT 0", "m3":"INTEGER DEFAULT 0",
        "season":"TEXT", "season_points":"INTEGER DEFAULT 0"
    }
    for n, t in extra.items():
        if n not in have:
            db(f"ALTER TABLE users ADD COLUMN {n} {t}")

def user(u):
    r = db("SELECT * FROM users WHERE id=?", (u.id,))
    if not r:
        db("INSERT INTO users(id,username,name) VALUES(?,?,?)",
           (u.id, u.username or "", u.full_name))
        r = db("SELECT * FROM users WHERE id=?", (u.id,))
    else:
        db("UPDATE users SET username=?,name=? WHERE id=?",
           (u.username or "", u.full_name, u.id))
    return r

def chat(m):
    if m.chat.type == "private":
        return
    db("""INSERT INTO chats(id,title) VALUES(?,?)
       ON CONFLICT(id) DO UPDATE SET title=excluded.title""",
       (m.chat.id, m.chat.title or ""))

def season_key():
    return datetime.now(timezone.utc).strftime("%Y-%m")

def sync_season(uid):
    s = season_key()
    r = db("SELECT season FROM users WHERE id=?", (uid,))
    if r and r["season"] != s:
        db("UPDATE users SET season=?,season_points=0 WHERE id=?", (s, uid))

def add_xp(uid, n):
    sync_season(uid)
    r = db("SELECT xp FROM users WHERE id=?", (uid,))
    xp = (r["xp"] if r else 0) + n
    level = xp // 100 + 1
    db("UPDATE users SET xp=?,level=?,season_points=season_points+? WHERE id=?",
       (xp, level, n, uid))

def menu():
    k = InlineKeyboardBuilder()
    k.button(text="🎰 Играть", callback_data="play")
    k.button(text="📖 Комбинации", callback_data="combos")
    k.button(text="🎡 Колесо", callback_data="wheel")
    k.button(text="🎯 Миссии", callback_data="missions")
    k.button(text="🏆 Топ", callback_data="top")
    k.button(text="🌍 Сезон", callback_data="season")
    k.button(text="🎲 Кости", callback_data="dice")
    k.button(text="⚔️ Дуэли", callback_data="duels")
    k.button(text="🏅 Достижения", callback_data="ach")
    k.adjust(2, 2, 2, 2, 1)
    return k.as_markup()

def game_menu(uid):
    r = db("SELECT balance,level,bet FROM users WHERE id=?", (uid,))
    bet = r["bet"]
    k = InlineKeyboardBuilder()
    k.button(text=f"🎰 КРУТИТЬ — 💰{bet}", callback_data="spin")
    k.button(text="➖ 10", callback_data="bet:10")
    k.button(text="➕ 25", callback_data="bet:25")
    k.button(text="🔥 50", callback_data="bet:50")
    k.button(text="💎 100", callback_data="bet:100")
    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(1, 4, 1)
    return k.as_markup()

def game_text(uid):
    r = db("SELECT * FROM users WHERE id=?", (uid,))
    return (
        f"🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{r['balance']}</b>\n"
        f"⭐ Уровень: <b>{r['level']}</b>\n"
        f"🎯 Ставка: <b>{r['bet']}</b>\n\n"
        f"Нажми кнопку ниже!"
    )

def happy():
    return datetime.now(timezone.utc).hour in (18, 19)

def mission_text(uid):
    r = db("SELECT * FROM users WHERE id=?", (uid,))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if r["mission_day"] != today:
        db("""UPDATE users SET mission_day=?,m1=0,m2=0,m3=0 WHERE id=?""",
           (today, uid))
        r = db("SELECT * FROM users WHERE id=?", (uid,))
    return (
        "🎯 <b>Миссии дня</b>\n\n"
        f"🎰 Сыграть 10 раз: {min(r['m1'],10)}/10\n"
        f"🏆 Выиграть 3 раза: {min(r['m2'],3)}/3\n"
        f"💰 Выиграть 1000 монет: {min(r['m3'],1000)}/1000\n\n"
        "Награда за каждую выполненную миссию: <b>+250💰</b>"
    )

def mission_menu():
    k = InlineKeyboardBuilder()
    k.button(text="🎁 Забрать награды", callback_data="claim")
    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(1)
    return k.as_markup()

def top_menu():
    k = InlineKeyboardBuilder()
    k.button(text="💰 Монеты", callback_data="top:money")
    k.button(text="🎰 Игры", callback_data="top:spins")
    k.button(text="🏆 Победы", callback_data="top:wins")
    k.button(text="💎 Лучший выигрыш", callback_data="top:best")
    k.button(text="👥 Топ группы", callback_data="top:chat")
    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(2, 2, 1, 1)
    return k.as_markup()

def top_text(mode, chat_id=None):
    names = {
        "money": ("balance","💰 Монеты"),
        "spins": ("spins","🎰 Игры"),
        "wins": ("wins","🏆 Победы"),
        "best": ("best_win","💎 Лучший выигрыш")
    }
    col, title = names[mode]
    rows = db(f"SELECT * FROM users ORDER BY {col} DESC LIMIT 10", many=True)
    out = f"<b>{title}</b>\n\n"
    for i, r in enumerate(rows, 1):
        n = "@" + r["username"] if r["username"] else r["name"]
        out += f"{i}. {n} — <b>{r[col]}</b>\n"
    return out

def combos():
    return (
        "📖 <b>Комбинации</b>\n\n"
        "🍒🍒🍒 — x5\n"
        "🍋🍋🍋 — x7\n"
        "🍊🍊🍊 — x10\n"
        "🔔🔔🔔 — x15\n"
        "💎💎💎 — x30\n"
        "7️⃣7️⃣7️⃣ — x100\n\n"
        "Любые 2 одинаковых — x2\n"
        "👑💎7️⃣ — МИФИЧЕСКИЙ выигрыш!"
    )

async def spin_game(uid, bet):
    r = db("SELECT balance FROM users WHERE id=?", (uid,))
    if r["balance"] < bet:
        return "❌ Недостаточно монет."

    a = [random.choice(SYMBOLS) for _ in range(3)]
    win = 0
    rare = False

    if random.randint(1,10000) == 1:
        a = ["👑","💎","7️⃣"]
        win = 50000
        rare = True
    elif a[0] == a[1] == a[2]:
        win = bet * MULT[a[0]]
    elif a[0] == a[1] or a[0] == a[2] or a[1] == a[2]:
        win = bet * 2

    if win and happy():
        win *= 2

    nb = r["balance"] - bet + win
    db("""UPDATE users SET balance=?,spins=spins+1,
       wins=wins+?,best_win=MAX(best_win,?),m1=m1+1,
       m2=m2+?,m3=m3+? WHERE id=?""",
       (nb, 1 if win else 0, win, 1 if win else 0, win, uid))

    add_xp(uid, 500 if rare else 10)

    if rare:
        return f"👑 <b>МИФИЧЕСКИЙ ДРОП!</b>\n\n{''.join(a)}\n\n💰 <b>+{win}</b>"

    if win:
        extra = "\n🔥 HAPPY HOUR x2!" if happy() else ""
        return f"{' | '.join(a)}\n\n🎉 Выигрыш: <b>+{win}</b>{extra}"
    return f"{' | '.join(a)}\n\n💸 Проигрыш: <b>-{bet}</b>"

@dp.message(CommandStart())
async def start(m: Message):
    user(m.from_user)
    chat(m)
    await m.answer(
        "🎰 <b>Добро пожаловать в СЛОТЫ!</b>\n\n"
        "Крути, выполняй миссии, участвуй в дуэлях и поднимайся в топе.",
        reply_markup=menu()
    )

@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(
        "<b>📚 Команды</b>\n\n"
        "/start — главное меню\n"
        "/slots — играть\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/top — топ игроков\n"
        "/group — статистика группы\n"
        "/pay 500 — перевод ответом на сообщение\n"
        "/pay @username 500 — перевод игроку\n"
        "/duel @username 100 — дуэль в кости\n\n"
        "Также всё доступно через кнопки 👇",
        reply_markup=menu()
    )

@dp.message(Command("slots"))
async def slots_cmd(m: Message):
    user(m.from_user)
    await m.answer(game_text(m.from_user.id), reply_markup=game_menu(m.from_user.id))

@dp.message(Command("balance"))
async def balance(m: Message):
    r = user(m.from_user)
    await m.answer(
        f"💰 Баланс: <b>{r['balance']}</b>\n"
        f"⭐ Уровень: <b>{r['level']}</b>\n"
        f"✨ XP: <b>{r['xp']}</b>"
    )

@dp.message(Command("bonus"))
async def bonus(m: Message):
    r = user(m.from_user)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if r["last_bonus"] == today:
        await m.answer("⏳ Ежедневный бонус уже получен.")
        return
    reward = 100 + r["level"] * 25
    db("UPDATE users SET balance=balance+?,last_bonus=? WHERE id=?",
       (reward, today, m.from_user.id))
    await m.answer(f"🎁 Бонус получен: <b>+{reward}💰</b>")

@dp.message(Command("top"))
async def top_cmd(m: Message):
    await m.answer(top_text("money"), reply_markup=top_menu())

@dp.message(Command("group"))
async def group_cmd(m: Message):
    if m.chat.type == "private":
        await m.answer("👥 Эта команда работает в группе.")
        return
    chat(m)
    r = db("SELECT * FROM chats WHERE id=?", (m.chat.id,))
    await m.answer(
        f"👥 <b>Статистика группы</b>\n\n"
        f"🎰 Игр: <b>{r['spins']}</b>\n"
        f"🏆 Побед: <b>{r['wins']}</b>\n"
        f"💰 Выиграно: <b>{r['coins']}</b>"
    )

@dp.message(Command("pay"))
async def pay(m: Message):
    user(m.from_user)
    parts = m.text.split()

    target = None
    amount = 0

    if m.reply_to_message and len(parts) >= 2:
        target = m.reply_to_message.from_user
        amount = int(parts[1])
    elif len(parts) >= 3:
        username = parts[1].lstrip("@")
        amount = int(parts[2])
        target = db("SELECT * FROM users WHERE username=?", (username,))

    if not target or amount <= 0:
        await m.answer("💰 Используй: /pay 500 ответом на сообщение")
        return

    if hasattr(target, "id"):
        tid = target.id
        if tid == m.from_user.id:
            await m.answer("❌ Нельзя переводить самому себе.")
            return
        user(target)
    else:
        tid = target["id"]

    sender = user(m.from_user)
    if sender["balance"] < amount:
        await m.answer("❌ Недостаточно монет.")
        return

    db("UPDATE users SET balance=balance-? WHERE id=?",
       (amount, m.from_user.id))
    db("UPDATE users SET balance=balance+? WHERE id=?",
       (amount, tid))
    await m.answer(f"💰 Перевод выполнен: <b>{amount}</b>")

@dp.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text("🎰 <b>Главное меню</b>", reply_markup=menu())

@dp.callback_query(F.data == "play")
async def cb_play(c: CallbackQuery):
    user(c.from_user)
    await c.answer()
    await c.message.edit_text(game_text(c.from_user.id),
                              reply_markup=game_menu(c.from_user.id))

@dp.callback_query(F.data.startswith("bet:"))
async def cb_bet(c: CallbackQuery):
    bet = int(c.data.split(":")[1])
    db("UPDATE users SET bet=? WHERE id=?", (bet, c.from_user.id))
    await c.answer(f"Ставка: {bet}💰")
    await c.message.edit_text(game_text(c.from_user.id),
                              reply_markup=game_menu(c.from_user.id))

@dp.callback_query(F.data == "spin")
async def cb_spin(c: CallbackQuery):
    user(c.from_user)
    r = db("SELECT bet FROM users WHERE id=?", (c.from_user.id,))
    await c.answer("🎰 Крутим!")
    await c.message.edit_text("🎰 <b>ВРАЩЕНИЕ...</b>\n\n❔ | ❔ | ❔")
    await c.message.edit_text("🎰 <b>ВРАЩЕНИЕ...</b>\n\n🍒 | 🔔 | 💎")
    result = await spin_game(c.from_user.id, r["bet"])
    await c.message.edit_text(
        result,
        reply_markup=game_menu(c.from_user.id)
    )

@dp.callback_query(F.data == "combos")
async def cb_combos(c: CallbackQuery):
    await c.answer()
    k = InlineKeyboardBuilder()
    k.button(text="⬅️ Назад", callback_data="menu")
    await c.message.edit_text(combos(), reply_markup=k.as_markup())

@dp.callback_query(F.data == "missions")
async def cb_missions(c: CallbackQuery):
    user(c.from_user)
    await c.answer()
    await c.message.edit_text(mission_text(c.from_user.id),
                              reply_markup=mission_menu())

@dp.callback_query(F.data == "claim")
async def cb_claim(c: CallbackQuery):
    r = db("SELECT * FROM users WHERE id=?", (c.from_user.id,))
    reward = 0

    if r["m1"] >= 10:
        reward += 250
        db("UPDATE users SET m1=-10 WHERE id=?", (c.from_user.id,))
    if r["m2"] >= 3:
        reward += 250
        db("UPDATE users SET m2=-3 WHERE id=?", (c.from_user.id,))
    if r["m3"] >= 1000:
        reward += 250
        db("UPDATE users SET m3=-1000 WHERE id=?", (c.from_user.id,))

    if reward:
        db("UPDATE users SET balance=balance+? WHERE id=?",
           (reward, c.from_user.id))
        await c.answer(f"🎁 +{reward}💰")
    else:
        await c.answer("❌ Выполненных миссий пока нет.", show_alert=True)

    await c.message.edit_text(mission_text(c.from_user.id),
                              reply_markup=mission_menu())

@dp.callback_query(F.data == "wheel")
async def cb_wheel(c: CallbackQuery):
    user(c.from_user)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = db("SELECT wheel FROM users WHERE id=?", (c.from_user.id,))
    if r["wheel"] == today:
        await c.answer("⏳ Колесо уже использовано сегодня.", show_alert=True)
        return

    rewards = [50,100,150,250,500,1000,2000]
    reward = random.choice(rewards)
    db("UPDATE users SET balance=balance+?,wheel=? WHERE id=?",
       (reward, today, c.from_user.id))
    await c.answer("🎡 Колесо остановилось!")
    await c.message.edit_text(
        f"🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
        f"🎉 Тебе выпало: <b>+{reward}💰</b>",
        reply_markup=menu()
    )

@dp.callback_query(F.data == "top")
async def cb_top(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text(top_text("money"), reply_markup=top_menu())

@dp.callback_query(F.data.startswith("top:"))
async def cb_top_mode(c: CallbackQuery):
    mode = c.data.split(":")[1]
    await c.answer()
    if mode == "chat":
        if c.message.chat.type == "private":
            await c.message.edit_text(
                "👥 Топ группы доступен только в группе.",
                reply_markup=top_menu()
            )
            return
        rows = db("""SELECT * FROM users
                     WHERE id IN
                     (SELECT DISTINCT id FROM users)
                     ORDER BY balance DESC LIMIT 10""", many=True)
        text = "👥 <b>Топ игроков</b>\n\n"
        for i,r in enumerate(rows,1):
            n = "@" + r["username"] if r["username"] else r["name"]
            text += f"{i}. {n} — {r['balance']}💰\n"
    else:
        text = top_text(mode)
    await c.message.edit_text(text, reply_markup=top_menu())

@dp.callback_query(F.data == "season")
async def cb_season(c: CallbackQuery):
    sync_season(c.from_user.id)
    rows = db("""SELECT * FROM users
                 WHERE season=?
                 ORDER BY season_points DESC LIMIT 10""",
              (season_key(),), many=True)
    text = f"🌍 <b>СЕЗОН {season_key()}</b>\n\n"
    for i,r in enumerate(rows,1):
        n = "@" + r["username"] if r["username"] else r["name"]
        text += f"{i}. {n} — <b>{r['season_points']}</b> очков\n"
    k = InlineKeyboardBuilder()
    k.button(text="⬅️ Меню", callback_data="menu")
    await c.answer()
    await c.message.edit_text(text, reply_markup=k.as_markup())

@dp.callback_query(F.data == "ach")
async def cb_ach(c: CallbackQuery):
    r = db("SELECT * FROM users WHERE id=?", (c.from_user.id,))
    text = "🏅 <b>Достижения</b>\n\n"
    text += ("✅ " if r["spins"] >= 10 else "⬜ ") + "10 игр\n"
    text += ("✅ " if r["spins"] >= 100 else "⬜ ") + "100 игр\n"
    text += ("✅ " if r["wins"] >= 10 else "⬜ ") + "10 побед\n"
    text += ("✅ " if r["best_win"] >= 1000 else "⬜ ") + "Выиграть 1000\n"
    text += ("✅ " if r["best_win"] >= 10000 else "⬜ ") + "Выиграть 10000\n"
    k = InlineKeyboardBuilder()
    k.button(text="⬅️ Меню", callback_data="menu")
    await c.answer()
    await c.message.edit_text(text, reply_markup=k.as_markup())

@dp.callback_query(F.data == "dice")
async def cb_dice(c: CallbackQuery):
    user(c.from_user)
    k = InlineKeyboardBuilder()
    k.button(text="🎲 Бросить за 50💰", callback_data="dice:50")
    k.button(text="🎲 Бросить за 100💰", callback_data="dice:100")
    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(1)
    await c.answer()
    await c.message.edit_text("🎲 <b>ИГРА В КОСТИ</b>", reply_markup=k.as_markup())

@dp.callback_query(F.data.startswith("dice:"))
async def cb_dice_play(c: CallbackQuery):
    bet = int(c.data.split(":")[1])
    r = db("SELECT balance FROM users WHERE id=?", (c.from_user.id,))
    if r["balance"] < bet:
        await c.answer("❌ Недостаточно монет.", show_alert=True)
        return

    a,b = random.randint(1,6), random.randint(1,6)
    db("UPDATE users SET balance=balance-? WHERE id=?", (bet,c.from_user.id))

    if a > 3:
        win = bet * 2
        db("UPDATE users SET balance=balance+?,wins=wins+1,best_win=MAX(best_win,?) WHERE id=?",
           (win,win,c.from_user.id))
        text = f"🎲 Выпало: <b>{a}</b>\n🎉 Ты выиграл <b>+{win}💰</b>"
    else:
        text = f"🎲 Выпало: <b>{a}</b>\n💸 Ты проиграл <b>{bet}💰</b>"

    k = InlineKeyboardBuilder()
    k.button(text="🎲 Ещё раз", callback_data=f"dice:{bet}")
    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(1)
    await c.answer()
    await c.message.edit_text(text, reply_markup=k.as_markup())

@dp.callback_query(F.data == "duels")
async def cb_duels(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text(
        "⚔️ <b>ДУЭЛИ</b>\n\n"
        "Чтобы вызвать игрока в дуэль:\n"
        "<code>/duel @username 100</code>\n\n"
        "Или ответь на сообщение игрока:\n"
        "<code>/duel 100</code>",
        reply_markup=menu()
    )

@dp.message(Command("duel"))
async def duel(m: Message):
    parts = m.text.split()
    amount = 100
    target = None

    if m.reply_to_message and len(parts) >= 2:
        target = m.reply_to_message.from_user
        amount = int(parts[1])
    elif len(parts) >= 3:
        name = parts[1].lstrip("@")
        amount = int(parts[2])
        target = db("SELECT * FROM users WHERE username=?", (name,))

    if not target or amount <= 0:
        await m.answer("⚔️ /duel @username 100")
        return

    user(m.from_user)
    if hasattr(target, "id"):
        tid = target.id
        user(target)
    else:
        tid = target["id"]

    if tid == m.from_user.id:
        await m.answer("❌ Нельзя вызвать самого себя.")
        return

    a = db("SELECT balance FROM users WHERE id=?", (m.from_user.id,))
    b = db("SELECT balance FROM users WHERE id=?", (tid,))

    if a[

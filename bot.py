import os, random, sqlite3, threading, asyncio
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

con = sqlite3.connect(DB, check_same_thread=False)
con.row_factory = sqlite3.Row
lock = threading.Lock()

SYM = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
MUL = {"🍒": 5, "🍋": 7, "🍊": 10, "🔔": 15, "💎": 30, "7️⃣": 100}
BETS = [10, 25, 50, 100]


def q(sql, p=(), many=False):
    with lock:
        c = con.cursor()
        c.execute(sql, p)
        r = c.fetchall() if many else c.fetchone()
        con.commit()
        return r


def init():
    q("""CREATE TABLE IF NOT EXISTS users(
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
    season_points INTEGER DEFAULT 0,
    claimed1 INTEGER DEFAULT 0,
    claimed2 INTEGER DEFAULT 0,
    claimed3 INTEGER DEFAULT 0
    )""")

    q("""CREATE TABLE IF NOT EXISTS chats(
    id INTEGER PRIMARY KEY,
    title TEXT,
    spins INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0
    )""")

    have = {x["name"] for x in q("PRAGMA table_info(users)", many=True)}

    cols = {
        "wheel": "TEXT",
        "bet": "INTEGER DEFAULT 10",
        "mission_day": "TEXT",
        "m1": "INTEGER DEFAULT 0",
        "m2": "INTEGER DEFAULT 0",
        "m3": "INTEGER DEFAULT 0",
        "season": "TEXT",
        "season_points": "INTEGER DEFAULT 0",
        "claimed1": "INTEGER DEFAULT 0",
        "claimed2": "INTEGER DEFAULT 0",
        "claimed3": "INTEGER DEFAULT 0"
    }

    for name, typ in cols.items():
        if name not in have:
            q(f"ALTER TABLE users ADD COLUMN {name} {typ}")


def U(u):
    r = q("SELECT * FROM users WHERE id=?", (u.id,))

    if not r:
        q(
            "INSERT INTO users(id,username,name) VALUES(?,?,?)",
            (u.id, u.username or "", u.full_name)
        )
        r = q("SELECT * FROM users WHERE id=?", (u.id,))
    else:
        q(
            "UPDATE users SET username=?,name=? WHERE id=?",
            (u.username or "", u.full_name, u.id)
        )

    return r


def C(m):
    if m.chat.type != "private":
        q(
            """INSERT INTO chats(id,title)
            VALUES(?,?)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title""",
            (m.chat.id, m.chat.title or "")
        )


def season():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def sync(uid):
    r = q("SELECT season FROM users WHERE id=?", (uid,))

    if not r or r["season"] != season():
        q(
            "UPDATE users SET season=?,season_points=0 WHERE id=?",
            (season(), uid)
        )


def add_xp(uid, n):
    sync(uid)

    r = q("SELECT xp FROM users WHERE id=?", (uid,))
    new_xp = r["xp"] + n
    level = new_xp // 100 + 1

    q(
        """UPDATE users
        SET xp=?,level=?,season_points=season_points+?
        WHERE id=?""",
        (new_xp, level, n, uid)
    )


def menu():
    k = InlineKeyboardBuilder()

    buttons = [
        ("🎰 Играть", "play"),
        ("📖 Комбинации", "comb"),
        ("🎡 Колесо", "wheel"),
        ("🎯 Миссии", "missions"),
        ("🏆 Топ", "top"),
        ("🌍 Сезон", "season"),
        ("🎲 Кости", "dice"),
        ("⚔️ Дуэли", "duels"),
        ("🏅 Достижения", "ach")
    ]

    for text, data in buttons:
        k.button(text=text, callback_data=data)

    k.adjust(2, 2, 2, 2, 1)
    return k.as_markup()


def game(uid):
    r = q(
        "SELECT balance,level,bet FROM users WHERE id=?",
        (uid,)
    )

    k = InlineKeyboardBuilder()

    k.button(
        text=f"🎰 КРУТИТЬ — 💰{r['bet']}",
        callback_data="spin"
    )

    for b in BETS:
        k.button(
            text=f"Ставка {b}",
            callback_data=f"bet:{b}"
        )

    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(1, 4, 1)

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{r['balance']}</b>\n"
        f"⭐ Уровень: <b>{r['level']}</b>\n"
        f"🎯 Ставка: <b>{r['bet']}</b>"
    )

    return text, k.as_markup()


def combos():
    return """📖 <b>КОМБИНАЦИИ</b>

🍒🍒🍒 — x5
🍋🍋🍋 — x7
🍊🍊🍊 — x10
🔔🔔🔔 — x15
💎💎💎 — x30
7️⃣7️⃣7️⃣ — x100

Любые 2 одинаковых — x2

👑💎7️⃣
МИФИЧЕСКИЙ ДРОП
+50 000💰"""


def missions(uid):
    r = q("SELECT * FROM users WHERE id=?", (uid,))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if r["mission_day"] != today:
        q(
            """UPDATE users
            SET mission_day=?,m1=0,m2=0,m3=0,
            claimed1=0,claimed2=0,claimed3=0
            WHERE id=?""",
            (today, uid)
        )
        r = q("SELECT * FROM users WHERE id=?", (uid,))

    k = InlineKeyboardBuilder()
    k.button(
        text="🎁 Забрать награды",
        callback_data="claim"
    )
    k.button(text="⬅️ Меню", callback_data="menu")
    k.adjust(1)

    text = (
        "🎯 <b>МИССИИ ДНЯ</b>\n\n"
        f"🎰 10 игр: {min(r['m1'],10)}/10 "
        f"{'✅' if r['claimed1'] else ''}\n"
        f"🏆 3 победы: {min(r['m2'],3)}/3 "
        f"{'✅' if r['claimed2'] else ''}\n"
        f"💰 1000 выигранных: {min(r['m3'],1000)}/1000 "
        f"{'✅' if r['claimed3'] else ''}\n\n"
        "🎁 Каждая награда: 250💰"
    )

    return text, k.as_markup()


def topmenu():
    k = InlineKeyboardBuilder()

    buttons = [
        ("💰 Монеты", "top:money"),
        ("🎰 Игры", "top:spins"),
        ("🏆 Победы", "top:wins"),
        ("💎 Лучший", "top:best"),
        ("👥 Группа", "top:group"),
        ("⬅️ Меню", "menu")
    ]

    for text, data in buttons:
        k.button(text=text, callback_data=data)

    k.adjust(2, 2, 1, 1)
    return k.as_markup()


def toptext(mode):
    columns = {
        "money": "balance",
        "spins": "spins",
        "wins": "wins",
        "best": "best_win"
    }

    titles = {
        "money": "💰 МОНЕТЫ",
        "spins": "🎰 ИГРЫ",
        "wins": "🏆 ПОБЕДЫ",
        "best": "💎 ЛУЧШИЙ ВЫИГРЫШ"
    }

    col = columns[mode]

    rows = q(
        f"SELECT * FROM users ORDER BY {col} DESC LIMIT 10",
        many=True
    )

    text = f"<b>{titles[mode]}</b>\n\n"

    for i, r in enumerate(rows, 1):
        name = "@" + r["username"] if r["username"] else r["name"]
        text += f"{i}. {name} — <b>{r[col]}</b>\n"

    return text


def happy():
    return datetime.now(timezone.utc).hour in (18, 19)


async def spin(uid):
    r = q(
        "SELECT balance,bet FROM users WHERE id=?",
        (uid,)
    )

    bet = r["bet"]

    if r["balance"] < bet:
        return "❌ Недостаточно монет."

    a = [
        random.choice(SYM),
        random.choice(SYM),
        random.choice(SYM)
    ]

    win = 0
    rare = False

    if random.randint(1, 10000) == 1:
        a = ["👑", "💎", "7️⃣"]
        win = 50000
        rare = True

    elif a[0] == a[1] == a[2]:
        win = bet * MUL[a[0]]

    elif (
        a[0] == a[1]
        or a[0] == a[2]
        or a[1] == a[2]
    ):
        win = bet * 2

    if win and happy():
        win *= 2

    q(
        """UPDATE users
        SET balance=balance-?+?,
        spins=spins+1,
        wins=wins+?,
        best_win=MAX(best_win,?),
        m1=m1+1,
        m2=m2+?,
        m3=m3+?
        WHERE id=?""",
        (
            bet,
            win,
            int(win > 0),
            win,
            int(win > 0),
            win,
            uid
        )
    )

    add_xp(uid, 500 if rare else 10)

    if rare:
        return (
            "👑 <b>МИФИЧЕСКИЙ ДРОП!</b>\n\n"
            f"{''.join(a)}\n\n"
            f"💰 <b>+{win}</b>"
        )

    if win:
        extra = "\n🔥 HAPPY HOUR x2!" if happy() else ""

        return (
            f"{' | '.join(a)}\n\n"
            f"🎉 Выигрыш: <b>+{win}</b>"
            f"{extra}"
        )

    return (
        f"{' | '.join(a)}\n\n"
        f"💸 Проигрыш: <b>-{bet}</b>"
    )


@dp.message(CommandStart())
async def start(m: Message):
    U(m.from_user)
    C(m)

    await m.answer(
        "🎰 <b>Добро пожаловать в СЛОТЫ!</b>\n\n"
        "Крути, выполняй миссии и поднимайся в рейтинге.",
        reply_markup=menu()
    )


@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(
        "<b>📚 КОМАНДЫ</b>\n\n"
        "/start — меню\n"
        "/slots — играть\n"
        "/balance — баланс\n"
        "/bonus — ежедневный бонус\n"
        "/top — рейтинг\n"
        "/group — статистика группы\n"
        "/pay 500 — перевод ответом\n"
        "/pay @username 500 — перевод\n"
        "/duel @username 100 — дуэль\n\n"
        "Все основные функции также есть в меню 👇",
        reply_markup=menu()
    )


@dp.message(Command("slots"))
async def slots(m: Message):
    U(m.from_user)

    text, keyboard = game(m.from_user.id)

    await m.answer(
        text,
        reply_markup=keyboard
    )


@dp.message(Command("balance"))
async def balance(m: Message):
    r = U(m.from_user)

    await m.answer(
        f"💰 Баланс: <b>{r['balance']}</b>\n"
        f"⭐ Уровень: <b>{r['level']}</b>\n"
        f"✨ XP: <b>{r['xp']}</b>"
    )


@dp.message(Command("bonus"))
async def bonus(m: Message):
    r = U(m.from_user)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if r["last_bonus"] == today:
        await m.answer("⏳ Ежедневный бонус уже получен.")
        return

    reward = 100 + r["level"] * 25

    q(
        """UPDATE users
        SET balance=balance+?,last_bonus=?
        WHERE id=?""",
        (reward, today, m.from_user.id)
    )

    await m.answer(
        f"🎁 Бонус получен: <b>+{reward}💰</b>"
    )


@dp.message(Command("top"))
async def top_cmd(m: Message):
    await m.answer(
        toptext("money"),
        reply_markup=topmenu()
    )


@dp.message(Command("group"))
async def group_cmd(m: Message):
    if m.chat.type == "private":
        await m.answer("👥 Эта команда работает в группе.")
        return

    C(m)

    r = q(
        "SELECT * FROM chats WHERE id=?",
        (m.chat.id,)
    )

    await m.answer(
        f"👥 <b>{r['title']}</b>\n\n"
        f"🎰 Игр: <b>{r['spins']}</b>\n"
        f"🏆 Побед: <b>{r['wins']}</b>\n"
        f"💰 Выиграно: <b>{r['coins']}</b>"
    )


@dp.message(Command("pay"))
async def pay(m: Message):
    U(m.from_user)

    parts = m.text.split()
    target = None
    amount = 0

    try:
        if m.reply_to_message and len(parts) >= 2:
            target = m.reply_to_message.from_user
            amount = int(parts[1])

        elif len(parts) >= 3:
            username = parts[1].lstrip("@")
            target = q(
                "SELECT * FROM users WHERE username=?",
                (username,)
            )
            amount = int(parts[2])

    except ValueError:
        pass

    if not target or amount <= 0:
        await m.answer(
            "💰 Используй:\n"
            "/pay 500 — ответом на сообщение"
        )
        return

    tid = target.id if hasattr(target, "id") else target["id"]

    if tid == m.from_user.id:
        await m.answer("❌ Нельзя переводить самому себе.")
        return

    r = U(m.from_user)

    if r["balance"] < amount:
        await m.answer("❌ Недостаточно монет.")
        return

    if hasattr(target, "id"):
        U(target)

    q(
        "UPDATE users SET balance=balance-? WHERE id=?",
        (amount, m.from_user.id)
    )

    q(
        "UPDATE users SET balance=balance+? WHERE id=?",
        (amount, tid)
    )

    await m.answer(
        f"💰 Перевод выполнен: <b>{amount}</b>"
    )


@dp.message(Command("duel"))
async def duel(m: Message):
    parts = m.text.split()
    target = None
    amount = 100

    try:
        if m.reply_to_message and len(parts) >= 2:
            target = m.reply_to_message.from_user
            amount = int(parts[1])

        elif len(parts) >= 3:
            username = parts[1].lstrip("@")
            target = q(
                "SELECT * FROM users WHERE username=?",
                (username,)
            )
            amount = int(parts[2])

    except ValueError:
        pass

    if not target or amount <= 0:
        await m.answer(
            "⚔️ Используй:\n"
            "/duel @username 100"
        )
        return

    tid = target.id if hasattr(target, "id") else target["id"]

    U(m.from_user)

    if hasattr(target, "id"):
        U(target)

    if tid == m.from_user.id:
        await m.answer("❌ Нельзя вызвать самого себя.")
        return

    a = q(
        "SELECT balance FROM users WHERE id=?",
        (m.from_user.id,)
    )

    b = q(
        "SELECT balance FROM users WHERE id=?",
        (tid,)
    )

    if a["balance"] < amount or b["balance"] < amount:
        await m.answer(
            "❌ У одного из игроков недостаточно монет."
        )
        return

    x = random.randint(1, 6)
    y = random.randint(1, 6)

    q(
        """UPDATE users
        SET balance=balance-?
        WHERE id IN (?,?)""",
        (amount, m.from_user.id, tid)
    )

    winner = m.from_user.id if x >= y else tid

    q(
        """UPDATE users
        SET balance=balance+?,
        wins=wins+1
        WHERE id=?""",
        (amount * 2, winner)
    )

    add_xp(winner, 25)

    await m.answer(
        "⚔️ <b>ДУЭЛЬ</b>\n\n"
        f"🎲 {x} против {y}\n\n"
        f"🏆 Победитель получает "
        f"<b>{amount * 2}💰</b>"
    )


@dp.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery):
    await c.answer()

    await c.message.edit_text(
        "🎰 <b>Главное меню</b>",
        reply_markup=menu()
    )


@dp.callback_query(F.data == "play")
async def cb_play(c: CallbackQuery):
    U(c.from_user)

    text, keyboard = game(c.from_user.id)

    await c.answer()

    await c.message.edit_text(
        text,
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("bet:"))
async def cb_bet(c: CallbackQuery):
    bet = int(c.data.split(":")[1])

    q(
        "UPDATE users SET bet=? WHERE id=?",
        (bet, c.from_user.id)
    )

    text, keyboard = game(c.from_user.id)

    await c.answer(
        f"Ставка установлена: {bet}💰"
    )

    await c.message.edit_text(
        text,
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "spin")
async def cb_spin(c: CallbackQuery):
    U(c.from_user)

    await c.answer("🎰 Крутим!")

    await c.message.edit_text(
        "🎰 <b>ВРАЩЕНИЕ...</b>\n\n"
        "❔ | ❔ | ❔"
    )

    await asyncio.sleep(0.35)

    await c.message.edit_text(
        "🎰 <b>ВРАЩЕНИЕ...</b>\n\n"
        "🍒 | 🔔 | 💎"
    )

    await asyncio.sleep(0.35)

    result = await spin(c.from_user.id)

    text, keyboard = game(c.from_user.id)

    await c.message.edit_text(
        result + "\n\n" + text,
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "comb")
async def cb_comb(c: CallbackQuery):
    k = InlineKeyboardBuilder()
    k.button(
        text="⬅️ Меню",
        callback_data="menu"
    )

    await c.answer()

    await c.message.edit_text(
        combos(),
        reply_markup=k.as_markup()
    )


@dp.callback_query(F.data == "missions")
async def cb_missions(c: CallbackQuery):
    text, keyboard = missions(c.from_user.id)

    await c.answer()

    await c.message.edit_text(
        text,
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "claim")
async def cb_claim(c: CallbackQuery):
    r = q(
        "SELECT * FROM users WHERE id=?",
        (c.from_user.id,)
    )

    reward = 0

    missions_data = [
        (1, 10, "m1"),
        (2, 3, "m2"),
        (3, 1000, "m3")
    ]

    for num, need, field in missions_data:
        if r[field] >= need and not r[f"claimed{num}"]:
            reward += 250

            q(
                f"UPDATE users SET claimed{num}=1 WHERE id=?",
                (c.from_user.id,)
            )

    if reward:
        q(
            "UPDATE users SET balance=balance+? WHERE id=?",
            (reward, c.from_user.id)
        )

        await c.answer(
            f"🎁 Получено +{reward}💰"
        )

    else:
        await c.answer(
            "❌ Выполненных миссий пока нет.",
            show_alert=True
        )

    text, keyboard = missions(c.from_user.id)

    await c.message.edit_text(
        text,
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "wheel")
async def cb_wheel(c: CallbackQuery):
    r = U(c.from_user)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if r["wheel"] == today:
        await c.answer(
            "⏳ Колесо уже использовано сегодня.",
            show_alert=True
        )
        return

    reward = random.choice([
        50, 100, 150, 250, 500, 1000, 2000
    ])

    q(
        """UPDATE users
        SET balance=balance+?,wheel=?
        WHERE id=?""",
        (reward, today, c.from_user.id)
    )

    await c.answer("🎡 Готово!")

    await c.message.edit_text(
        "🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n\n"
        f"🎉 Тебе выпало: <b>+{reward}💰</b>",
        reply_markup=menu()
    )


@dp.callback_query(F.data == "top")
async def cb_top(c: CallbackQuery):
    await c.answer()

    await c.message.edit_text(
        toptext("money"),
        reply_markup=topmenu()
    )


@dp.callback_query(F.data.startswith("top:"))
async def cb_top_mode(c: CallbackQuery):
    mode = c.data.split(":")[1]

    await c.answer()

    if mode == "group":
        if c.message.chat.type == "private":
            await c.message.edit_text(
                "👥 Топ группы доступен в группе.",
                reply_markup=topmenu()
            )
            return

        rows = q(
            "SELECT * FROM users ORDER BY balance DESC LIMIT 10",
            many=True
        )

        text = "👥 <b>ТОП ИГРОКОВ</b>\n\n"

        for i, r in enumerate(rows, 1):
            name = (
                "@" + r["username"]
                if r["username"]
                else r["name"]
            )

            text += (
                f"{i}. {name} — "
                f"{r['balance']}💰\n"
            )

    else:
        text = toptext(mode)

    await c.message.edit_text(
        text,
        reply_markup=topmenu()
    )


@dp.callback_query(F.data == "season")
async def cb_season(c: CallbackQuery):
    sync(c.from_user.id)

    rows = q(
        """SELECT * FROM users
        WHERE season=?
        ORDER BY season_points DESC
        LIMIT 10""",
        (season(),),
        many=True
    )

    text = (
        f"🌍 <b>СЕЗОН {season()}</b>\n\n"
    )

    for i, r in enumerate(rows, 1):
        name = (
            "@" + r["username"]
            if r["username"]
            else r["name"]
        )

        text += (
            f"{i}. {name} — "
            f"{r['season_points']} очков\n"
        )

    k = InlineKeyboardBuilder()
    k.button(
        text="⬅️ Меню",
        callback_data="menu"
    )

    await c.answer()

    await c.message.edit_text(
        text,
        reply_markup=k.as_markup()
    )


@dp.callback_query(F.data == "ach")
async def cb_ach(c: CallbackQuery):
    r = q(
        "SELECT * FROM users WHERE id=?",
        (c.from_user.id,)
    )

    achievements = [
        (r["spins"] >= 10, "10 игр"),
        (r["spins"] >= 100, "100 игр"),
        (r["wins"] >= 10, "10 побед"),
        (r["best_win"] >= 1000, "Выиграть 1000"),
  

import os, asyncio, random, sqlite3, threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, F, html
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

db = sqlite3.connect("slots.db", check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.Lock()

MONEY = "💰"
START = 1000
JACKPOT_START = 5000
SYM = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
MULT = {"🍒": 5, "🍋": 7, "🍊": 10, "🔔": 15, "💎": 30, "7️⃣": 100}
BETS = [10, 25, 50, 100]


def day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def init():
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
        day TEXT,
        spins INTEGER DEFAULT 0,
        won INTEGER DEFAULT 0,
        big INTEGER DEFAULT 0,
        claimed INTEGER DEFAULT 0,
        PRIMARY KEY(user_id,day)
    );

    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value INTEGER
    );

    INSERT OR IGNORE INTO settings VALUES('jackpot',5000);
    """)
    db.commit()


def get(u):
    with lock:
        r = db.execute(
            "SELECT * FROM users WHERE id=?",
            (u.id,)
        ).fetchone()

        if not r:
            db.execute(
                "INSERT INTO users(id,username,name) VALUES(?,?,?)",
                (u.id, u.username or "", u.first_name or "Игрок")
            )
        else:
            db.execute(
                "UPDATE users SET username=?,name=? WHERE id=?",
                (u.username or "", u.first_name or "Игрок", u.id)
            )

        db.commit()

        return dict(
            db.execute(
                "SELECT * FROM users WHERE id=?",
                (u.id,)
            ).fetchone()
        )


def upd(uid, **x):
    with lock:
        db.execute(
            "UPDATE users SET " +
            ",".join(f"{k}=?" for k in x) +
            " WHERE id=?",
            [*x.values(), uid]
        )
        db.commit()


def reg(cid, uid):
    with lock:
        db.execute(
            "INSERT OR IGNORE INTO chats VALUES(?,?)",
            (cid, uid)
        )
        db.commit()


def jp():
    return db.execute(
        "SELECT value FROM settings WHERE key='jackpot'"
    ).fetchone()[0]


def setjp(v):
    with lock:
        db.execute(
            "UPDATE settings SET value=? WHERE key='jackpot'",
            (v,)
        )
        db.commit()


def level(xp):
    return xp // 100 + 1


def kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎰 КРУТИТЬ 10",
            callback_data="s:10"
        )],
        [
            InlineKeyboardButton(text="💰 25", callback_data="s:25"),
            InlineKeyboardButton(text="💰 50", callback_data="s:50"),
            InlineKeyboardButton(text="💰 100", callback_data="s:100")
        ],
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="bal"),
            InlineKeyboardButton(text="🎁 Бонус", callback_data="bon")
        ],
        [
            InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
            InlineKeyboardButton(text="🎯 Задания", callback_data="tasks")
        ],
        [
            InlineKeyboardButton(text="📖 Команды", callback_data="help")
        ]
    ])


def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎰 Играть",
            callback_data="back"
        )],
        [InlineKeyboardButton(
            text="🏆 Топ",
            callback_data="top"
        )]
    ])


def tops():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🌍 Общий",
                callback_data="t:balance"
            ),
            InlineKeyboardButton(
                text="⭐ Уровень",
                callback_data="t:level"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎰 Спины",
                callback_data="t:spins"
            ),
            InlineKeyboardButton(
                text="👥 Группа",
                callback_data="t:group"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎰 Играть",
                callback_data="back"
            )
        ]
    ])


def taskkb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎁 Забрать",
            callback_data="claim"
        )],
        [InlineKeyboardButton(
            text="🎰 Играть",
            callback_data="back"
        )]
    ])


def game(u):
    return (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"{MONEY} Баланс: <b>{u['balance']}</b>\n"
        f"⭐ Уровень: <b>{u['level']}</b>\n"
        f"✨ XP: <b>{u['xp'] % 100}/100</b>\n"
        f"💎 Джекпот: <b>{jp()}</b>\n\n"
        "Выбери ставку:"
    )


HELP = """📖 <b>КОМАНДЫ</b>

/start — запуск
/slots — игра
/balance — баланс
/bonus — ежедневный бонус
/profile — профиль
/tasks — задания
/top — рейтинги
/help — помощь

👥 <b>В ГРУППЕ</b>

Добавьте бота в группу.
Используйте те же команды.

Игроки автоматически попадают
в рейтинг группы.

🎰 Спин: +10 XP
💰 Два одинаковых: x2
💎 Три одинаковых: большой выигрыш
7️⃣7️⃣7️⃣ — ДЖЕКПОТ"""


def tasktext(uid):
    with lock:
        db.execute(
            "INSERT OR IGNORE INTO tasks(user_id,day) VALUES(?,?)",
            (uid, day())
        )
        db.commit()

        t = db.execute(
            "SELECT * FROM tasks WHERE user_id=? AND day=?",
            (uid, day())
        ).fetchone()

    return (
        "🎯 <b>ЗАДАНИЯ</b>\n\n"
        f"🎰 10 спинов: <b>{min(t['spins'],10)}/10</b>"
        f" — +100 {MONEY}\n"
        f"💰 Выиграть 500: <b>{min(t['won'],500)}/500</b>"
        f" — +200 {MONEY}\n"
        f"💎 Выигрыш 1000+: <b>{min(t['big'],1)}/1</b>"
        f" — +500 {MONEY}"
    )


def addtask(uid, win):
    with lock:
        db.execute(
            "INSERT OR IGNORE INTO tasks(user_id,day) VALUES(?,?)",
            (uid, day())
        )

        db.execute(
            """
            UPDATE tasks
            SET spins=spins+1,
                won=won+?,
                big=big+?
            WHERE user_id=? AND day=?
            """,
            (win, int(win >= 1000), uid, day())
        )
        db.commit()


def top(mode, cid):
    if mode == "group":
        q = """
        SELECT u.* FROM users u
        JOIN chats c ON u.id=c.user_id
        WHERE c.chat_id=?
        ORDER BY balance DESC LIMIT 10
        """
        args = (cid,)
        title = "👥 ТОП ГРУППЫ"

    elif mode == "level":
        q = "SELECT * FROM users ORDER BY level DESC,xp DESC LIMIT 10"
        args = ()
        title = "⭐ ТОП УРОВНЕЙ"

    elif mode == "spins":
        q = "SELECT * FROM users ORDER BY spins DESC LIMIT 10"
        args = ()
        title = "🎰 ТОП СПИНОВ"

    else:
        q = "SELECT * FROM users ORDER BY balance DESC LIMIT 10"
        args = ()
        title = "🌍 ТОП МОНЕТ"

    rows = db.execute(q, args).fetchall()

    if not rows:
        return f"<b>{title}</b>\n\nПока игроков нет."

    out = [f"<b>{title}</b>", ""]

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


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


async def main():
    init()

    threading.Thread(
        target=lambda: HTTPServer(
            ("0.0.0.0", PORT),
            Health
        ).serve_forever(),
        daemon=True
    ).start()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )

    dp = Dispatcher()

    async def show(m):
        u = get(m.from_user)
        reg(m.chat.id, m.from_user.id)

        await m.answer(
            game(u),
            reply_markup=kb()
        )

    @dp.message(CommandStart())
    async def start(m: Message):
        await show(m)

    @dp.message(Command("slots"))
    async def slots(m: Message):
        await show(m)

    @dp.message(Command("help"))
    async def help_cmd(m: Message):
        await m.answer(
            HELP,
            reply_markup=back()
        )

    @dp.message(Command("balance"))
    async def balance(m: Message):
        u = get(m.from_user)

        await m.answer(
            f"{MONEY} <b>Баланс: {u['balance']}</b>",
            reply_markup=kb()
        )

    @dp.message(Command("bonus"))
    async def bonus(m: Message):
        u = get(m.from_user)

        if u["last_bonus"] == day():
            await m.answer(
                "🎁 Бонус уже получен сегодня.",
                reply_markup=kb()
            )
            return

        reward = 100 + u["level"] * 25

        upd(
            u["id"],
            balance=u["balance"] + reward,
            last_bonus=day()
        )

        await m.answer(
            f"🎁 Бонус: <b>+{reward} {MONEY}</b>",
            reply_markup=kb()
        )

    @dp.message(Command("profile"))
    async def profile(m: Message):
        u = get(m.from_user)

        await m.answer(
            "👤 <b>ПРОФИЛЬ</b>\n\n"
            f"{html.quote(u['name'])}\n"
            f"{MONEY} {u['balance']}\n"
            f"⭐ Уровень: {u['level']}\n"
            f"🎰 Спины: {u['spins']}\n"
            f"🏆 Победы: {u['wins']}\n"
            f"💎 Лучший выигрыш: {u['best_win']}",
            reply_markup=kb()
        )

    @dp.message(Command("tasks"))
    async def tasks(m: Message):
        await m.answer(
            tasktext(get(m.from_user)["id"]),
            reply_markup=taskkb()
        )

    @dp.message(Command("top"))
    async def topcmd(m: Message):
        get(m.from_user)
        reg(m.chat.id, m.from_user.id)

        await m.answer(
            top("balance", m.chat.id),
            reply_markup=tops()
        )

    @dp.callback_query(F.data.startswith("s:"))
    async def spin(c: CallbackQuery):
        bet = int(c.data[2:])
        u = get(c.from_user)

        reg(c.message.chat.id, c.from_user.id)

        if bet not in BETS:
            return await c.answer(
                "Неверная ставка.",
                show_alert=True
            )

        if u["balance"] < bet:
            return await c.answer(
                "❌ Недостаточно монет.",
                show_alert=True
            )

        reels = [
            random.choice(SYM)
            for _ in range(3)
        ]

        win = 0

        if len(set(reels)) == 1:
            if reels[0] == "7️⃣":
                win = jp()
            else:
                win = bet * MULT[reels[0]]

        elif len(set(reels)) == 2:
            win = bet * 2

        jackpot_win = reels == ["7️⃣", "7️⃣", "7️⃣"]

        if jackpot_win:
            setjp(JACKPOT_START)
            result = "🎉 <b>ДЖЕКПОТ!</b>"
        else:
            setjp(jp() + max(1, bet // 10))
            result = (
                "🎉 <b>Выигрыш!</b>"
                if win
                else "😢 <b>Проигрыш</b>"
            )

        xp = u["xp"] + 10

        upd(
            u["id"],
            balance=u["balance"] - bet + win,
            xp=xp,
            level=level(xp),
            spins=u["spins"] + 1,
            wins=u["wins"] + int(win > 0),
            best_win=max(u["best_win"], win)
        )

        addtask(u["id"], win)

        u = get(c.from_user)
        amount = win if win else bet
        sign = "+" if win else "-"

        await c.answer()

        await c.message.edit_text(
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"{' '.join(reels)}\n\n"
            f"{result}\n"
            f"{sign}<b>{amount}</b> {MONEY}\n\n"
            f"{MONEY} Баланс: <b>{u['balance']}</b>\n"
            f"⭐ Уровень: <b>{u['level']}</b>\n"
            f"✨ XP: <b>{u['xp'] % 100}/100</b>\n"
            f"💎 Джекпот: <b>{jp()}</b>",
            reply_markup=kb()
        )

    @dp.callback_query(F.data == "bal")
    async def bal(c: CallbackQuery):
        await c.answer()

        await c.message.edit_text(
            f"{MONEY} <b>Баланс: "
            f"{get(c.from_user)['balance']}</b>",
            reply_markup=kb()
        )

    @dp.callback_query(F.data == "bon")
    async def bon(c: CallbackQuery):
        u = get(c.from_user)

        if u["last_bonus"] == day():
            return await c.answer(
                "🎁 Уже получен",
                show_alert=True
            )

        reward = 100 + u["level"] * 25

        upd(
            u["id"],
            balance=u["balance"] + reward,
            last_bonus=day()
        )

        await c.answer(
            f"🎁 +{reward} {MONEY}",
            show_alert=True
        )

        await c.message.edit_text(
            game(get(c.from_user)),
            reply_markup=kb()
        )

    @dp.callback_query(F.data == "help")
    async def help_button(c: CallbackQuery):
        await c.answer()
        await c.message.edit_text(
            HELP,
            reply_markup=back()
        )

    @dp.callback_query(F.data == "back")
    async def back_button(c: CallbackQuery):
        await c.answer()
        await c.message.edit_text(
            game(get(c.from_user)),
            reply_markup=kb()
        )

    @dp.callback_query(F.data == "top")
    async def top_button(c: CallbackQuery):
        await c.answer()
        await c.message.edit_text(
            top("balance", c.message.chat.id),
            reply_markup=tops()
        )

    @dp.callback_query(F.data.startswith("t:"))
    async def top_choice(c: CallbackQuery):
        await c.answer()

        await c.message.edit_text(
            top(
                c.data[2:],
                c.message.chat.id
            ),
            reply_markup=tops()
        )

    @dp.callback_query(F.data == "tasks")
    async def tasks_button(c: CallbackQuery):
        await c.answer()

        await c.message.edit_text(
            tasktext(get(c.from_user)["id"]),
            reply_markup=taskkb()
        )

    @dp.callback_query(F.data == "claim")
    async def claim(c: CallbackQuery):
        uid = get(c.from_user)["id"]

        with lock:
            db.execute(
                "INSERT OR IGNORE INTO tasks(user_id,day) VALUES(?,?)",
                (uid, day())
            )

            t = db.execute(
                "SELECT * FROM tasks WHERE user_id=? AND day=?",
                (uid, day())
            ).fetchone()

            reward = 0
            claimed = t["claimed"]

            if t["spins"] >= 10 and not claimed & 1:
                reward += 100
                claimed |= 1

            if t["won"] >= 500 and not claimed & 2:
                reward += 200
                claimed |= 2

            if t["big"] >= 1 and not claimed & 4:
                reward += 500
                claimed |= 4

            db.execute(
                "UPDATE tasks SET claimed=? WHERE user_id=? AND day=?",
                (claimed, uid, day())
            )

            db.commit()

        if reward:
            u = get(c.from_user)

            upd(
                uid,
                balance=u["balance"] + reward
            )

        await c.answer(
            f"🎁 +{reward} {MONEY}"
            if reward
            else "Наград пока нет",
            show_alert=True
        )

        await c.message.edit_text(
            tasktext(uid),
            reply_markup=taskkb()
        )

    @dp.message()
    async def other(m: Message):
        get(m.from_user)
        reg(m.chat.id, m.from_user.id)

    await bot.delete_webhook(
        drop_pending_updates=False
    )

    print(
        f"🎰 BOT STARTED | 0.0.0.0:{PORT}"
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

import os, asyncio, random, sqlite3, threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F, html
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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


def q(sql, args=(), one=False, many=False):
    with lock:
        c = db.cursor()
        c.execute(sql, args)
        if many:
            r = c.fetchall()
        else:
            r = c.fetchone() if one else None
        db.commit()
        return r


def init_db():
    q("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        name TEXT,
        balance INTEGER DEFAULT 1000,
        xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        best INTEGER DEFAULT 0,
        bonus TEXT DEFAULT ''
    )""")

    q("""CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY,
        title TEXT,
        spins INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        total_bets INTEGER DEFAULT 0
    )""")

    q("""CREATE TABLE IF NOT EXISTS chat_users(
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(chat_id,user_id)
    )""")

    q("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value INTEGER
    )""")

    r = q("SELECT value FROM settings WHERE key='jackpot'", one=True)
    if not r:
        q("INSERT INTO settings VALUES('jackpot',?)", (JACKPOT_START,))


def user(m):
    u = m.from_user
    name = u.username or u.first_name or str(u.id)

    q("""INSERT OR IGNORE INTO users(id,name,balance)
        VALUES(?,?,?)""", (u.id, name, START))

    q("UPDATE users SET name=? WHERE id=?", (name, u.id))

    if m.chat.type != "private":
        q("""INSERT OR IGNORE INTO chats(id,title)
            VALUES(?,?)""",
          (m.chat.id, m.chat.title or "Чат"))

        q("""INSERT OR IGNORE INTO chat_users(chat_id,user_id)
            VALUES(?,?)""", (m.chat.id, u.id))

    return q("SELECT * FROM users WHERE id=?", (u.id,), True)


def level(xp):
    return xp // 100 + 1


def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎰 Играть", callback_data="game"),
            InlineKeyboardButton(text="💰 Баланс", callback_data="balance")
        ],
        [
            InlineKeyboardButton(text="🎁 Бонус", callback_data="bonus"),
            InlineKeyboardButton(text="🏆 Топ", callback_data="top")
        ],
        [
            InlineKeyboardButton(text="👥 Чат", callback_data="group"),
            InlineKeyboardButton(text="📖 Команды", callback_data="help")
        ]
    ])


def bets():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 {x}", callback_data=f"bet:{x}")
         for x in BETS],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")]
    ])


def top_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Монеты", callback_data="top:money"),
            InlineKeyboardButton(text="🎰 Игры", callback_data="top:spins")
        ],
        [
            InlineKeyboardButton(text="🏆 Победы", callback_data="top:wins"),
            InlineKeyboardButton(text="💎 Выигрыш", callback_data="top:best")
        ],
        [InlineKeyboardButton(text="🌍 Глобальный", callback_data="top:global")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")]
    ])


def help_text():
    return """📖 <b>КОМАНДЫ</b>

🎰 <b>Игра</b>
/slots — открыть слоты
/balance — мой баланс
/bonus — ежедневный бонус

🏆 <b>Рейтинги</b>
/top — рейтинг игроков
/group — рейтинг и статистика чата

💸 <b>Переводы</b>
/pay @username сумма
/pay сумма — ответом на сообщение

ℹ️ /help — список команд"""


def top_text(mode="money", chat_id=None):
    names = {
        "money": ("💰 ТОП ЛУДИКОВ ПО МОНЕТАМ", "balance"),
        "spins": ("🎰 ТОП ЛУДИКОВ ПО ИГРАМ", "spins"),
        "wins": ("🏆 ТОП ЛУДИКОВ ПО ПОБЕДАМ", "wins"),
        "best": ("💎 ТОП ПО ЛУЧШЕМУ ВЫИГРЫШУ", "best")
    }

    title, col = names.get(mode, names["money"])

    if chat_id:
        rows = q(f"""SELECT u.name,u.{col} value
            FROM users u JOIN chat_users c ON c.user_id=u.id
            WHERE c.chat_id=?
            ORDER BY value DESC LIMIT 10""", (chat_id,), many=True)
    else:
        rows = q(f"""SELECT name,{col} value FROM users
            ORDER BY {col} DESC LIMIT 10""", many=True)

    text = f"<b>{title}</b>\n\n"

    if not rows:
        return text + "Пока здесь никого нет."

    for i, r in enumerate(rows, 1):
        text += f"{i}. {html.quote(r['name'])} — {r['value']:,} "
        text += MONEY if col == "balance" else ("🎰" if col == "spins"
                 else ("🏆" if col == "wins" else MONEY))
        text += "\n"

    return text


def group_text(chat_id):
    chat = q("SELECT * FROM chats WHERE id=?", (chat_id,), True)

    if not chat:
        return "👥 Статистика чата пока недоступна."

    users = q("""SELECT COUNT(*) n FROM chat_users
                 WHERE chat_id=?""", (chat_id,), True)["n"]

    return f"""👥 <b>СТАТИСТИКА ЧАТА</b>

👤 Игроков: <b>{users}</b>
🎰 Игр: <b>{chat['spins']}</b>
🏆 Побед: <b>{chat['wins']}</b>
💰 Сумма ставок: <b>{chat['total_bets']:,}</b>

Ниже можно посмотреть ТОП игроков этого чата."""


async def safe_edit(msg, text, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except Exception as e:
        if "message is not modified" not in str(e):
            raise


async def show_game(msg):
    await safe_edit(
        msg,
        "🎰 <b>СЛОТЫ</b>\n\nВыбери размер ставки:",
        bets()
    )


async def spin(msg, amount):
    u = user(msg)

    if amount not in BETS:
        return

    if u["balance"] < amount:
        await msg.answer(
            f"❌ Недостаточно монет.\n\n"
            f"Баланс: {u['balance']:,} {MONEY}"
        )
        return

    result = [random.choice(SYMBOLS) for _ in range(3)]
    win = 0
    jackpot = q("SELECT value FROM settings WHERE key='jackpot'", one=True)["value"]

    if result[0] == result[1] == result[2]:
        if result[0] == "7️⃣":
            win = jackpot
            jackpot = JACKPOT_START
        else:
            win = amount * MULT[result[0]]
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        win = amount * 2

    if win:
        jackpot += amount // 10
    else:
        jackpot += amount

    new_balance = u["balance"] - amount + win
    new_xp = u["xp"] + 10

    q("""UPDATE users SET balance=?,xp=?,spins=spins+1,
       wins=wins+?,best=MAX(best,?) WHERE id=?""",
      (new_balance, new_xp, 1 if win else 0, win, u["id"]))

    if msg.chat.type != "private":
        q("""UPDATE chats SET spins=spins+1,wins=wins+?,
           total_bets=total_bets+? WHERE id=?""",
          (1 if win else 0, amount, msg.chat.id))

    q("UPDATE settings SET value=? WHERE key='jackpot'", (jackpot,))

    title = "🎉 <b>ПОБЕДА!</b>" if win else "💀 <b>ПРОИГРЫШ</b>"

    if result[0] == result[1] == result[2] == "7️⃣":
        title = "🎰💎 <b>ДЖЕКПОТ!</b>"

    text = f"""{title}

┌─────────────┐
│  {result[0]}  {result[1]}  {result[2]}  │
└─────────────┘

💰 Ставка: <b>{amount:,}</b>
💵 Выигрыш: <b>{win:,}</b>
💰 Баланс: <b>{new_balance:,}</b>
⭐ Уровень: <b>{level(new_xp)}</b>
🎰 Игр: <b>{u['spins'] + 1}</b>

💎 Джекпот: <b>{jackpot:,}</b>"""

    await msg.answer(text, reply_markup=menu())


async def daily_bonus(msg):
    u = user(msg)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if u["bonus"] == today:
        await msg.answer("🎁 Ты уже забрал сегодняшний бонус.")
        return

    amount = 100 + level(u["xp"]) * 25
    q("UPDATE users SET balance=balance+?,bonus=? WHERE id=?",
      (amount, today, u["id"]))

    await msg.answer(
        f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"Ты получил <b>{amount:,} {MONEY}</b>!\n\n"
        f"💰 Баланс: <b>{u['balance'] + amount:,}</b>"
    )


async def transfer(msg, target_id, amount):
    sender = user(msg)

    if amount <= 0:
        await msg.answer("❌ Сумма должна быть больше нуля.")
        return

    if target_id == sender["id"]:
        await msg.answer("❌ Нельзя отправить монеты самому себе.")
        return

    target = q("SELECT * FROM users WHERE id=?", (target_id,), True)

    if not target:
        await msg.answer(
            "❌ Этот игрок ещё не запускал бота.\n"
            "Пусть он напишет /start."
        )
        return

    if sender["balance"] < amount:
        await msg.answer(
            f"❌ Недостаточно монет.\n"
            f"Твой баланс: {sender['balance']:,} {MONEY}"
        )
        return

    q("UPDATE users SET balance=balance-? WHERE id=?",
      (amount, sender["id"]))
    q("UPDATE users SET balance=balance+? WHERE id=?",
      (amount, target_id))

    await msg.answer(
        f"💸 <b>ПЕРЕВОД ВЫПОЛНЕН</b>\n\n"
        f"👤 Получатель: <b>{html.quote(target['name'])}</b>\n"
        f"💰 Сумма: <b>{amount:,}</b>\n\n"
        f"💵 Твой баланс: <b>{sender['balance'] - amount:,}</b>"
    )


async def pay(msg):
    args = msg.text.split()

    if msg.reply_to_message:
        if len(args) != 2 or not args[1].isdigit():
            await msg.answer(
                "💸 Использование:\n"
                "<code>/pay 500</code>\n\n"
                "Отправь команду ответом на сообщение игрока."
            )
            return

        target = msg.reply_to_message.from_user
        await transfer(msg, target.id, int(args[1]))
        return

    if len(args) != 3 or not args[1].startswith("@") or not args[2].isdigit():
        await msg.answer(
            "💸 Использование:\n"
            "<code>/pay @username 500</code>\n\n"
            "Или просто ответь на сообщение игрока:\n"
            "<code>/pay 500</code>"
        )
        return

    username = args[1][1:].lower()
    target = q(
        "SELECT * FROM users WHERE LOWER(name)=?",
        (username,),
        True
    )

    if not target:
        await msg.answer(
            "❌ Игрок не найден.\n\n"
            "Лучше ответь на сообщение игрока и напиши:\n"
            "<code>/pay 500</code>"
        )
        return

    await transfer(msg, target["id"], int(args[2]))


async def start(msg):
    user(msg)

    await msg.answer(
        "🎰 <b>ДОБРО ПОЖАЛОВАТЬ В СЛОТЫ!</b>\n\n"
        "💰 Здесь тебя ждут ставки, выигрыши,\n"
        "💎 джекпот и рейтинги.\n\n"
        "Выбирай действие:",
        reply_markup=menu()
    )


dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(m: Message):
    await start(m)


@dp.message(Command("slots"))
async def cmd_slots(m: Message):
    user(m)
    await m.answer(
        "🎰 <b>СЛОТЫ</b>\n\nВыбери ставку:",
        reply_markup=bets()
    )


@dp.message(Command("balance"))
async def cmd_balance(m: Message):
    u = user(m)
    await m.answer(
        f"💰 <b>ТВОЙ БАЛАНС</b>\n\n"
        f"💰 Монеты: <b>{u['balance']:,}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"✨ XP: <b>{u['xp']}</b>\n"
        f"🎰 Игр: <b>{u['spins']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b>\n"
        f"💎 Лучший выигрыш: <b>{u['best']:,}</b>"
    )


@dp.message(Command("bonus"))
async def cmd_bonus(m: Message):
    await daily_bonus(m)


@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(help_text(), reply_markup=menu())


@dp.message(Command("top"))
async def cmd_top(m: Message):
    user(m)
    await m.answer(top_text(), reply_markup=top_menu())


@dp.message(Command("group"))
async def cmd_group(m: Message):
    user(m)

    if m.chat.type == "private":
        await m.answer("👥 Эта команда работает внутри группы.")
        return

    await m.answer(
        group_text(m.chat.id),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="👥 ТОП ЧАТА",
                callback_data="top:chat"
            )],
            [InlineKeyboardButton(
                text="🏠 Меню",
                callback_data="menu"
            )]
        ])
    )


@dp.message(Command("pay"))
async def cmd_pay(m: Message):
    await pay(m)


@dp.message()
async def remember_group(m: Message):
    if m.chat.type != "private":
        user(m)


@dp.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery):
    await c.answer()
    await safe_edit(
        c.message,
        "🎰 <b>ГЛАВНОЕ МЕНЮ</b>\n\nВыбирай действие:",
        menu()
    )


@dp.callback_query(F.data == "game")
async def cb_game(c: CallbackQuery):
    await c.answer()
    await show_game(c.message)


@dp.callback_query(F.data.startswith("bet:"))
async def cb_bet(c: CallbackQuery):
    await c.answer()
    amount = int(c.data.split(":")[1])
    await spin(c.message, amount)


@dp.callback_query(F.data == "balance")
async def cb_balance(c: CallbackQuery):
    await c.answer()
    u = user(c.message)
    await safe_edit(
        c.message,
        f"💰 <b>БАЛАНС</b>\n\n"
        f"💰 Монеты: <b>{u['balance']:,}</b>\n"
        f"⭐ Уровень: <b>{level(u['xp'])}</b>\n"
        f"🎰 Игр: <b>{u['spins']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b>\n"
        f"💎 Лучший выигрыш: <b>{u['best']:,}</b>",
        menu()
    )


@dp.callback_query(F.data == "bonus")
async def cb_bonus(c: CallbackQuery):
    await c.answer()
    await daily_bonus(c.message)


@dp.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await c.answer()
    await safe_edit(c.message, help_text(), menu())


@dp.callback_query(F.data == "top")
async def cb_top(c: CallbackQuery):
    await c.answer()
    await safe_edit(c.message, top_text(), top_menu())


@dp.callback_query(F.data.startswith("top:"))
async def cb_top_mode(c: CallbackQuery):
    await c.answer()

    mode = c.data.split(":")[1]

    if mode == "chat":
        if c.message.chat.type == "private":
            await safe_edit(
                c.message,
                "👥 Рейтинг доступен только в группе.",
                top_menu()
            )
            return

        await safe_edit(
            c.message,
            top_text("money", c.message.chat.id),
            top_menu()
        )
        return

    await safe_edit(
        c.message,
        top_text(mode),
        top_menu()
    )


@dp.callback_query(F.data == "group")
async def cb_group(c: CallbackQuery):
    await c.answer()

    if c.message.chat.type == "private":
        await safe_edit(
            c.message,
            "👥 Статистика чата доступна внутри группы.",
            menu()
        )
        return

    await safe_edit(
        c.message,
        group_text(c.message.chat.id),
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="👥 ТОП ЧАТА",
                callback_data="top:chat"
            )],
            [InlineKeyboardButton(
                text="🏠 Меню",
                callback_data="menu"
            )]
        ])
    )


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def web():
    HTTPServer(("0.0.0.0", PORT), Health).serve_forever()


async def main():
    init_db()

    threading.Thread(target=web, daemon=True).start()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    await bot.delete_webhook(drop_pending_updates=False)

    print(f"BOT STARTED | 0.0.0.0:{PORT}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

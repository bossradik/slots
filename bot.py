import os,sqlite3,random,threading,asyncio
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,HTTPServer
from aiogram import Bot,Dispatcher,F,html
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest

TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
if not TOKEN: raise RuntimeError("BOT_TOKEN не найден")

db=sqlite3.connect("slots.db",check_same_thread=False)
db.row_factory=sqlite3.Row
lock=threading.Lock()

MONEY="💰"; START=1000; JACKPOT_START=5000
SYM=["🍒","🍋","🍊","🔔","💎","7️⃣"]
MULT={"🍒":5,"🍋":7,"🍊":10,"🔔":15,"💎":30,"7️⃣":100}
BETS=[10,25,50,100]

def q(sql,args=(),one=False):
    with lock:
        c=db.cursor();c.execute(sql,args);db.commit()
        return c.fetchone() if one else c.fetchall()

def col(table,name,typ="INTEGER DEFAULT 0"):
    try:q(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    except:pass

q("""CREATE TABLE IF NOT EXISTS users(
id INTEGER PRIMARY KEY,
name TEXT DEFAULT '',
balance INTEGER DEFAULT 1000,
xp INTEGER DEFAULT 0,
spins INTEGER DEFAULT 0,
wins INTEGER DEFAULT 0,
best INTEGER DEFAULT 0,
bonus TEXT DEFAULT '')""")
q("""CREATE TABLE IF NOT EXISTS chats(
id INTEGER PRIMARY KEY,
title TEXT DEFAULT '',
spins INTEGER DEFAULT 0,
wins INTEGER DEFAULT 0,
total_bets INTEGER DEFAULT 0)""")
q("""CREATE TABLE IF NOT EXISTS chat_users(
chat_id INTEGER,
user_id INTEGER,
name TEXT DEFAULT '',
PRIMARY KEY(chat_id,user_id))""")
q("""CREATE TABLE IF NOT EXISTS tasks(
user_id INTEGER PRIMARY KEY,
claimed INTEGER DEFAULT 0)""")
q("""CREATE TABLE IF NOT EXISTS settings(
key TEXT PRIMARY KEY,
value INTEGER DEFAULT 0)""")

for x,t in [
("name","TEXT DEFAULT ''"),("balance","INTEGER DEFAULT 1000"),
("xp","INTEGER DEFAULT 0"),("spins","INTEGER DEFAULT 0"),
("wins","INTEGER DEFAULT 0"),("best","INTEGER DEFAULT 0"),
("bonus","TEXT DEFAULT ''")]: col("users",x,t)

if not q("SELECT * FROM settings WHERE key='jackpot'",one=True):
    q("INSERT INTO settings(key,value) VALUES('jackpot',?)",(JACKPOT_START,))

def user(uid,name=""):
    u=q("SELECT * FROM users WHERE id=?",(uid,),True)
    if not u:
        q("INSERT INTO users(id,name,balance) VALUES(?,?,?)",(uid,name,START))
        u=q("SELECT * FROM users WHERE id=?",(uid,),True)
    elif name and u["name"]!=name:
        q("UPDATE users SET name=? WHERE id=?",(name,uid))
        u=q("SELECT * FROM users WHERE id=?",(uid,),True)
    return u

def touch(m):
    u=user(m.from_user.id,m.from_user.full_name)
    if m.chat.type!="private":
        q("""INSERT OR IGNORE INTO chats(id,title) VALUES(?,?)""",
          (m.chat.id,m.chat.title or "Группа"))
        q("""INSERT OR REPLACE INTO chat_users(chat_id,user_id,name)
             VALUES(?,?,?)""",(m.chat.id,m.from_user.id,m.from_user.full_name))
    return u

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Играть",callback_data="game")],
        [InlineKeyboardButton(text="💰 Баланс",callback_data="bal"),
         InlineKeyboardButton(text="🎁 Бонус",callback_data="bonus")],
        [InlineKeyboardButton(text="🏆 Топ",callback_data="top"),
         InlineKeyboardButton(text="👥 Группа",callback_data="group")],
        [InlineKeyboardButton(text="📋 Задания",callback_data="tasks")]])

def bets():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 10",callback_data="bet:10"),
         InlineKeyboardButton(text="💰 25",callback_data="bet:25")],
        [InlineKeyboardButton(text="💰 50",callback_data="bet:50"),
         InlineKeyboardButton(text="💰 100",callback_data="bet:100")],
        [InlineKeyboardButton(text="⬅️ Назад",callback_data="home")]])

def safe_edit(c,text,markup=None):
    async def x():
        try: await c.message.edit_text(text,reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e): raise
    return x()

def game_text(u):
    return f"""🎰 <b>СЛОТЫ</b>

💰 Баланс: <b>{u['balance']}</b>
⭐ Уровень: <b>{u['xp']//100+1}</b>
✨ XP: <b>{u['xp']%100}/100</b>

Выбери ставку:"""

async def spin(c,bet):
    u=user(c.from_user.id,c.from_user.full_name)
    if u["balance"]<bet:
        return await safe_edit(c,f"❌ Недостаточно денег!\n\n💰 Баланс: <b>{u['balance']}</b>",bets())

    a=[random.choice(SYM) for _ in range(3)]
    win=0;jack=False

    if a==["7️⃣","7️⃣","7️⃣"]:
        jackpot=q("SELECT value FROM settings WHERE key='jackpot'",one=True)["value"]
        win=jackpot;jack=True
        q("UPDATE settings SET value=? WHERE key='jackpot'",(JACKPOT_START,))
    elif a[0]==a[1]==a[2]:
        win=bet*MULT[a[0]]
    elif len(set(a))==2:
        win=bet*2

    newbal=u["balance"]-bet+win
    xp=u["xp"]+10
    best=max(u["best"],win)

    q("""UPDATE users SET balance=?,xp=?,spins=spins+1,
       wins=wins+?,best=? WHERE id=?""",
      (newbal,xp,1 if win else 0,best,u["id"]))

    if c.message.chat.type!="private":
        q("""UPDATE chats SET spins=spins+1,total_bets=total_bets+?
           WHERE id=?""",(bet,c.message.chat.id))
        if win:q("UPDATE chats SET wins=wins+1 WHERE id=?",(c.message.chat.id,))

    q("UPDATE settings SET value=value+? WHERE key='jackpot'",(max(1,bet//10),))

    if jack:
        result=f"🎉 <b>ДЖЕКПОТ!</b>\n\n{''.join(a)}\n\n💰 Выигрыш: <b>{win}</b>"
    elif win:
        result=f"🎉 <b>ПОБЕДА!</b>\n\n{''.join(a)}\n\n💰 Выигрыш: <b>{win}</b>"
    else:
        result=f"😢 <b>Не повезло</b>\n\n{''.join(a)}\n\n💸 Ставка: <b>{bet}</b>"

    u=user(c.from_user.id,c.from_user.full_name)
    text=f"""🎰 <b>РЕЗУЛЬТАТ</b>

{result}

💰 Баланс: <b>{u['balance']}</b>
⭐ Уровень: <b>{u['xp']//100+1}</b>
✨ +10 XP"""

    return await safe_edit(c,text,bets())

async def start(m:Message):
    u=touch(m)
    await m.answer(
        f"🎰 <b>Добро пожаловать в СЛОТЫ!</b>\n\n"
        f"💰 Баланс: <b>{u['balance']}</b>\n"
        f"⭐ Уровень: <b>{u['xp']//100+1}</b>\n\n"
        f"Выбирай действие:",reply_markup=menu())

async def balance(m):
    u=touch(m)
    await m.answer(
        f"💰 <b>Твой баланс</b>\n\n"
        f"💰 Монеты: <b>{u['balance']}</b>\n"
        f"⭐ Уровень: <b>{u['xp']//100+1}</b>\n"
        f"✨ XP: <b>{u['xp']%100}/100</b>\n"
        f"🎰 Спинов: <b>{u['spins']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b>\n"
        f"💎 Лучший выигрыш: <b>{u['best']}</b>",reply_markup=menu())

async def bonus(m):
    u=touch(m)
    today=datetime.now(timezone.utc).date().isoformat()
    if u["bonus"]==today:
        return await m.answer("🎁 <b>Бонус уже получен сегодня!</b>",reply_markup=menu())
    amount=100+(u["xp"]//100+1)*25
    q("UPDATE users SET balance=balance+?,bonus=? WHERE id=?",(amount,today,u["id"]))
    await m.answer(f"🎁 <b>Ежедневный бонус!</b>\n\n💰 Получено: <b>+{amount}</b>",reply_markup=menu())

async def top(c):
    rows=q("""SELECT name,balance,spins,wins,best FROM users
              ORDER BY balance DESC LIMIT 10""")
    s="🏆 <b>ТОП ШАХТЁРОВ СЛОТОВ</b>\n\n"
    for i,r in enumerate(rows,1):
        s+=f"<b>{i}.</b> {html.quote(r['name'] or 'Игрок')} — 💰 {r['balance']} | 🎰 {r['spins']}\n"
    return await safe_edit(c,s,menu())

async def group(c):
    if c.message.chat.type=="private":
        return await safe_edit(c,"👥 <b>Статистика группы</b>\n\nЭта функция доступна внутри группы.",menu())
    r=q("SELECT * FROM chats WHERE id=?", (c.message.chat.id,),True)
    n=q("SELECT COUNT(*) n FROM chat_users WHERE chat_id=?",(c.message.chat.id,),True)["n"]
    await safe_edit(c,
        f"👥 <b>СТАТИСТИКА ГРУППЫ</b>\n\n"
        f"👤 Игроков: <b>{n}</b>\n"
        f"🎰 Спинов: <b>{r['spins']}</b>\n"
        f"🏆 Побед: <b>{r['wins']}</b>\n"
        f"💰 Сумма ставок: <b>{r['total_bets']}</b>",menu())

async def tasks(c):
    u=user(c.from_user.id,c.from_user.full_name)
    t=q("SELECT * FROM tasks WHERE user_id=?",(u["id"],),True)
    claimed=t["claimed"] if t else 0
    spins=u["spins"]
    wins=u["wins"]
    text=f"""📋 <b>ЗАДАНИЯ</b>

🎰 Сделать 5 спинов: {min(spins,5)}/5
🏆 Одержать 1 победу: {min(wins,1)}/1

"""
    if spins>=5 and wins>=1 and not claimed:
        text+="🎁 Награда готова!"
    elif claimed:
        text+="✅ Награда уже получена."
    else:
        text+="Продолжай играть!"
    return await safe_edit(c,text,menu())

async def claim_tasks(c):
    u=user(c.from_user.id,c.from_user.full_name)
    t=q("SELECT * FROM tasks WHERE user_id=?",(u["id"],),True)
    if not t:q("INSERT INTO tasks(user_id) VALUES(?)",(u["id"],))
    if u["spins"]<5 or u["wins"]<1:
        return await safe_edit(c,"❌ Задания ещё не выполнены.",menu())
    t=q("SELECT * FROM tasks WHERE user_id=?",(u["id"],),True)
    if t["claimed"]:
        return await safe_edit(c,"✅ Награда уже получена.",menu())
    q("UPDATE tasks SET claimed=1 WHERE user_id=?",(u["id"],))
    q("UPDATE users SET balance=balance+250 WHERE id=?",(u["id"],))
    await safe_edit(c,"🎁 <b>Задания выполнены!</b>\n\n💰 Награда: <b>+250</b>",menu())

dp=Dispatcher()

@dp.message(CommandStart())
async def _(m):await start(m)

@dp.message(Command("balance"))
async def _(m):await balance(m)

@dp.message(Command("bonus"))
async def _(m):await bonus(m)

@dp.message(Command("top"))
async def _(m):
    touch(m)
    rows=q("SELECT name,balance FROM users ORDER BY balance DESC LIMIT 10")
    s="🏆 <b>ТОП 10</b>\n\n"
    for i,r in enumerate(rows,1):
        s+=f"{i}. {html.quote(r['name'] or 'Игрок')} — 💰 {r['balance']}\n"
    await m.answer(s,reply_markup=menu())

@dp.message(Command("slots"))
async def _(m):
    touch(m);await m.answer(game_text(user(m.from_user.id,m.from_user.full_name)),reply_markup=bets())

@dp.callback_query(F.data=="home")
async def _(c):
    await c.answer()
    u=user(c.from_user.id,c.from_user.full_name)
    await safe_edit(c,
        f"🎰 <b>СЛОТЫ</b>\n\n💰 Баланс: <b>{u['balance']}</b>\n"
        f"⭐ Уровень: <b>{u['xp']//100+1}</b>\n\nВыбери действие:",
        menu())

@dp.callback_query(F.data=="game")
async def _(c):
    await c.answer()
    u=user(c.from_user.id,c.from_user.full_name)
    await safe_edit(c,game_text(u),bets())

@dp.callback_query(F.data.startswith("bet:"))
async def _(c):
    await c.answer()
    await spin(c,int(c.data.split(":")[1]))

@dp.callback_query(F.data=="bal")
async def _(c):
    await c.answer()
    u=user(c.from_user.id,c.from_user.full_name)
    await safe_edit(c,
        f"💰 <b>БАЛАНС</b>\n\n💰 {u['balance']}\n"
        f"⭐ Уровень: {u['xp']//100+1}\n✨ XP: {u['xp']%100}/100\n"
        f"🎰 Спинов: {u['spins']}\n🏆 Побед: {u['wins']}\n"
        f"💎 Лучший выигрыш: {u['best']}",menu())

@dp.callback_query(F.data=="bonus")
async def _(c):
    await c.answer()
    await bonus(c.message)

@dp.callback_query(F.data=="top")
async def _(c):
    await c.answer();await top(c)

@dp.callback_query(F.data=="group")
async def _(c):
    await c.answer();await group(c)

@dp.callback_query(F.data=="tasks")
async def _(c):
    await c.answer();await tasks(c)

@dp.callback_query(F.data=="claim")
async def _(c):
    await c.answer();await claim_tasks(c)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b"OK")
    def log_message(self,*a):pass

def server():
    HTTPServer(("0.0.0.0",PORT),H).serve_forever()

async def main():
    threading.Thread(target=server,daemon=True).start()
    bot=Bot(TOKEN,default=DefaultBotProperties(parse_mode="HTML"))
    await bot.delete_webhook(drop_pending_updates=False)
    print(f"BOT STARTED | 0.0.0.0:{PORT}")
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())

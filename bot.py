import os,sqlite3,random,asyncio
from datetime import datetime,date
from threading import Thread
from http.server import BaseHTTPRequestHandler,HTTPServer
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton

TOKEN=os.getenv("BOT_TOKEN")
if not TOKEN: raise RuntimeError("BOT_TOKEN not set")

db=sqlite3.connect("slots.db",check_same_thread=False)
db.row_factory=sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(
id INTEGER PRIMARY KEY,name TEXT,username TEXT,bal INTEGER DEFAULT 1000,xp INTEGER DEFAULT 0,
spins INTEGER DEFAULT 0,wins INTEGER DEFAULT 0,best INTEGER DEFAULT 0,bonus TEXT,last_chat INTEGER DEFAULT 0,
bet INTEGER DEFAULT 10,legend INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS duels(
id INTEGER PRIMARY KEY AUTOINCREMENT,challenger INTEGER,opponent INTEGER,bet INTEGER,status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY);
""")
db.commit()

def q(s,p=()):
    return db.execute(s,p)
def save():
    db.commit()

def user(m):
    u=q("SELECT * FROM users WHERE id=?",(m.from_user.id,)).fetchone()
    if not u:
        q("INSERT INTO users(id,name,username) VALUES(?,?,?)",
          (m.from_user.id,m.from_user.full_name,m.from_user.username or ""))
        save()
        u=q("SELECT * FROM users WHERE id=?",(m.from_user.id,)).fetchone()
    else:
        q("UPDATE users SET name=?,username=? WHERE id=?",
          (m.from_user.full_name,m.from_user.username or "",m.from_user.id));save()
    return q("SELECT * FROM users WHERE id=?",(m.from_user.id,)).fetchone()

def level(u): return u["xp"]//100+1
def kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)

MAIN=kb([
 [InlineKeyboardButton(text="🎰 КРУТИТЬ",callback_data="spin")],
 [InlineKeyboardButton(text="💰 СТАВКА",callback_data="bets"),
  InlineKeyboardButton(text="📖 КОМБИНАЦИИ",callback_data="comb")],
 [InlineKeyboardButton(text="🏆 ТОП",callback_data="top"),
  InlineKeyboardButton(text="👥 ГРУППА",callback_data="group")],
 [InlineKeyboardButton(text="⚔️ ДУЭЛЬ",callback_data="duel"),
  InlineKeyboardButton(text="💸 ПЕРЕВОД",callback_data="pay")],
 [InlineKeyboardButton(text="🎁 БОНУС",callback_data="bonus"),
  InlineKeyboardButton(text="📋 КОМАНДЫ",callback_data="help")]
])

def game(u):
    return f"""🎰 <b>СЛОТЫ</b>

💰 Баланс: <b>{u['bal']}</b>
⭐ Уровень: <b>{level(u)}</b> | XP: <b>{u['xp']%100}/100</b>
🎯 Ставка: <b>{u['bet']}</b>

🎰 Готов к вращению?"""

def menu_back(): return kb([[InlineKeyboardButton(text="🔙 НАЗАД",callback_data="menu")]])

def bets():
    return kb([
      [InlineKeyboardButton(text="💰 10",callback_data="bet:10"),
       InlineKeyboardButton(text="💰 25",callback_data="bet:25")],
      [InlineKeyboardButton(text="💰 50",callback_data="bet:50"),
       InlineKeyboardButton(text="💰 100",callback_data="bet:100")],
      [InlineKeyboardButton(text="💰 500",callback_data="bet:500"),
       InlineKeyboardButton(text="💰 1000",callback_data="bet:1000")],
      [InlineKeyboardButton(text="🔙 НАЗАД",callback_data="menu")]
    ])

SY=["🍒","🍋","🍊","🔔","💎","7️⃣"]
MULT={"🍒":5,"🍋":7,"🍊":10,"🔔":15,"💎":30,"7️⃣":100}

def result(a,b,c,bet):
    # сверхредкая комбинация
    if random.randint(1,10000)==1:
        return "👑💎7️⃣",50000,500,True
    if a==b==c:
        if a=="7️⃣": return "7️⃣7️⃣7️⃣",bet*100,100,False
        return a*3,bet*MULT[a],30,False
    if a==b or a==c or b==c:
        return f"{a}{b}{c}",bet*2,15,False
    return f"{a}{b}{c}",0,10,False

async def spin_game(m,edit=False):
    u=user(m)
    bet=u["bet"]
    if u["bal"]<bet:
        text="❌ Недостаточно денег."
        if edit: await m.edit_text(text,reply_markup=MAIN)
        else: await m.answer(text,reply_markup=MAIN)
        return
    u=q("SELECT * FROM users WHERE id=?",(m.from_user.id,)).fetchone()
    msg=await m.answer("🎰 <b>КРУТИМ...</b>\n\n🍒 🍋 🔔")
    for _ in range(4):
        await asyncio.sleep(.35)
        await msg.edit_text(
            "🎰 <b>КРУТИМ...</b>\n\n"+
            "   ".join(random.choice(SY) for _ in range(3)))
    a,b,c=[random.choice(SY) for _ in range(3)]
    combo,win,xp,legend=result(a,b,c,bet)
    bal=u["bal"]-bet+win
    wins=u["wins"]+(1 if win else 0)
    best=max(u["best"],win)
    leg=u["legend"]+(1 if legend else 0)
    q("""UPDATE users SET bal=?,xp=?,spins=spins+1,wins=?,best=?,legend=? WHERE id=?""",
      (bal,u["xp"]+xp,wins,best,leg,u["id"]))
    save()
    if legend:
        title="🌟 <b>ЛЕГЕНДАРНОЕ ВЫПАДЕНИЕ!</b>\n👑💎7️⃣\n\n💰 <b>+50 000</b>"
    elif combo=="7️⃣7️⃣7️⃣":
        title="🔥 <b>ДЖЕКПОТ!</b>\n7️⃣ 7️⃣ 7️⃣"
    elif win:
        title=f"🎉 <b>ВЫИГРЫШ!</b>\n{combo}"
    else:
        title="💨 <b>НЕ ПОВЕЗЛО</b>"
    nu=q("SELECT * FROM users WHERE id=?",(m.from_user.id,)).fetchone()
    await msg.edit_text(
        f"""🎰 <b>РЕЗУЛЬТАТ</b>

{combo}

{title}

💰 Баланс: <b>{nu['bal']}</b>
⭐ XP: <b>+{xp}</b>
🎯 Ставка: <b>{bet}</b>""",
        reply_markup=kb([
          [InlineKeyboardButton(text="🎰 КРУТИТЬ ЕЩЁ РАЗ",callback_data="spin")],
          [InlineKeyboardButton(text="💰 ИЗМЕНИТЬ СТАВКУ",callback_data="bets"),
           InlineKeyboardButton(text="🔙 МЕНЮ",callback_data="menu")]
        ]))

def top_text(mode="money",chat=None):
    if chat:
        rows=q("SELECT * FROM users WHERE last_chat=? ORDER BY bal DESC LIMIT 10",(chat,)).fetchall()
        title="👥 <b>ТОП ГРУППЫ</b>"
    else:
        order={"money":"bal","spins":"spins","wins":"wins","best":"best","legend":"legend"}.get(mode,"bal")
        rows=q(f"SELECT * FROM users ORDER BY {order} DESC LIMIT 10").fetchall()
        title={"money":"💰 ТОП ПО БАЛАНСУ","spins":"🎰 ТОП ПО ВРАЩЕНИЯМ",
               "wins":"🏆 ТОП ПОБЕДИТЕЛЕЙ","best":"💎 ЛУЧШИЕ ВЫИГРЫШИ",
               "legend":"🌟 ЛЕГЕНДАРНЫЕ ВЫПАДЕНИЯ"}.get(mode,"🏆 ТОП")
    s=title+"\n\n"
    for i,r in enumerate(rows,1):
        n=r["name"][:18]
        val=r["bal"] if not chat and mode=="money" else (
            r["spins"] if mode=="spins" else r["wins"] if mode=="wins" else
            r["best"] if mode=="best" else r["legend"] if mode=="legend" else r["bal"])
        s+=f"{i}. {n} — <b>{val}</b>\n"
    return s or "Пока никого нет."

def top_k():
    return kb([
      [InlineKeyboardButton(text="💰 МОНЕТЫ",callback_data="top:money"),
       InlineKeyboardButton(text="🎰 ВРАЩЕНИЯ",callback_data="top:spins")],
      [InlineKeyboardButton(text="🏆 ПОБЕДЫ",callback_data="top:wins"),
       InlineKeyboardButton(text="💎 ЛУЧШИЙ",callback_data="top:best")],
      [InlineKeyboardButton(text="🌟 ЛЕГЕНДЫ",callback_data="top:legend")],
      [InlineKeyboardButton(text="👥 ТОП ГРУППЫ",callback_data="top:chat")],
      [InlineKeyboardButton(text="🔙 НАЗАД",callback_data="menu")]
    ])

def comb_text():
    return """📖 <b>КОМБИНАЦИИ</b>

🍒🍒🍒 — x5
🍋🍋🍋 — x7
🍊🍊🍊 — x10
🔔🔔🔔 — x15
💎💎💎 — x30
7️⃣7️⃣7️⃣ — x100 🔥 ДЖЕКПОТ

👥 Любые 2 одинаковых — x2

🌟 <b>ЛЕГЕНДАРНАЯ</b>
👑💎7️⃣
💰 +50 000
🏆 +500 XP
🎯 Шанс: 1 из 10 000"""

def help_text():
    return """📋 <b>КОМАНДЫ</b>

/start — главное меню
/slots — игра
/balance — баланс
/bonus — ежедневный бонус
/top — рейтинг
/group — статистика группы
/pay 100 — перевод по ответу
/pay @username 100 — перевод игроку
/duel 100 @username — вызвать на дуэль

🎰 Остальное доступно через кнопки."""

def group_text(cid):
    rows=q("SELECT * FROM users WHERE last_chat=?",(cid,)).fetchall()
    if not rows:return "👥 В группе пока нет статистики."
    return f"""👥 <b>СТАТИСТИКА ГРУППЫ</b>

👤 Игроков: <b>{len(rows)}</b>
💰 Монеты: <b>{sum(x['bal'] for x in rows)}</b>
🎰 Вращений: <b>{sum(x['spins'] for x in rows)}</b>
🏆 Побед: <b>{sum(x['wins'] for x in rows)}</b>

🏆 Самый богатый:
<b>{max(rows,key=lambda x:x['bal'])['name']}</b>"""

def duel_menu():
    return kb([[InlineKeyboardButton(text="🔙 НАЗАД",callback_data="menu")]])

bot=Bot(TOKEN)
dp=Dispatcher()

@dp.message(CommandStart())
async def start(m):
    u=user(m)
    if m.chat.type!="private":
        q("INSERT OR IGNORE INTO chats(id) VALUES(?)",(m.chat.id,))
        q("UPDATE users SET last_chat=? WHERE id=?",(m.chat.id,u["id"]));save()
    await m.answer(game(u),reply_markup=MAIN)

@dp.message(Command("slots"))
async def slots(m): await start(m)

@dp.message(Command("balance"))
async def balance(m):
    u=user(m);await m.answer(f"💰 Баланс: <b>{u['bal']}</b>\n⭐ Уровень: <b>{level(u)}</b>")

@dp.message(Command("help"))
async def helpcmd(m): await m.answer(help_text(),reply_markup=menu_back())

@dp.message(Command("top"))
async def topcmd(m): await m.answer(top_text(),reply_markup=top_k())

@dp.message(Command("group"))
async def groupcmd(m): await m.answer(group_text(m.chat.id),reply_markup=menu_back())

@dp.message(Command("bonus"))
async def bonus(m):
    u=user(m);today=str(date.today())
    if u["bonus"]==today:
        await m.answer("🎁 Ты уже получил бонус сегодня.",reply_markup=MAIN);return
    amount=100+level(u)*25
    q("UPDATE users SET bal=?,bonus=? WHERE id=?",(u["bal"]+amount,today,u["id"]));save()
    await m.answer(f"🎁 <b>БОНУС ПОЛУЧЕН!</b>\n\n💰 +{amount}",reply_markup=MAIN)

@dp.message(Command("pay"))
async def pay(m):
    u=user(m);p=m.text.split()
    target=None;amount=None
    if m.reply_to_message:
        target=user(m.reply_to_message)
        if len(p)>1:
            try: amount=int(p[1])
            except: pass
    elif len(p)>=3:
        name=p[1].lstrip("@")
        target=q("SELECT * FROM users WHERE username=?",(name,)).fetchone()
        try: amount=int(p[2])
        except: pass
    if not target or not amount or amount<=0:
        await m.answer("💸 Используй: /pay 100 ответом на сообщение\nили /pay @username 100");return
    if target["id"]==u["id"]: await m.answer("❌ Себе переводить нельзя.");return
    if u["bal"]<amount: await m.answer("❌ Недостаточно денег.");return
    q("UPDATE users SET bal=bal-? WHERE id=?",(amount,u["id"]))
    q("UPDATE users SET bal=bal+? WHERE id=?",(amount,target["id"]));save()
    await m.answer(f"💸 Перевод выполнен!\n\nТы отправил <b>{amount}</b> 💰 игроку <b>{target['name']}</b>.")

@dp.message(Command("duel"))
async def duel(m):
    u=user(m);p=m.text.split()
    if len(p)<3:
        await m.answer("⚔️ Используй: /duel 100 @username");return
    try: amount=int(p[1])
    except: await m.answer("❌ Неверная ставка.");return
    target=q("SELECT * FROM users WHERE username=?",(p[2].lstrip("@"),)).fetchone()
    if not target or target["id"]==u["id"]: await m.answer("❌ Игрок не найден.");return
    if amount<=0 or u["bal"]<amount: await m.answer("❌ Недостаточно денег.");return
    cur=q("INSERT INTO duels(challenger,opponent,bet) VALUES(?,?,?)",(u["id"],target["id"],amount));save()
    await m.answer(f"⚔️ <b>ДУЭЛЬ!</b>\n\n👤 {u['name']}\n💰 Ставка: {amount}\n\n👤 {target['name']}, принимаешь?",
      reply_markup=kb([[InlineKeyboardButton(text="⚔️ ПРИНЯТЬ",callback_data=f"accept:{cur.lastrowid}"),
                        InlineKeyboardButton(text="❌ ОТКАЗ",callback_data=f"decline:{cur.lastrowid}")]]))

@dp.callback_query(F.data=="menu")
async def cb_menu(c):
    await c.answer();u=user(c.message);await c.message.edit_text(game(u),reply_markup=MAIN)

@dp.callback_query(F.data=="spin")
async def cb_spin(c):
    await c.answer();await spin_game(c.message,True)

@dp.callback_query(F.data=="bets")
async def cb_bets(c):
    await c.answer();await c.message.edit_text("💰 <b>ВЫБЕРИ СТАВКУ</b>",reply_markup=bets())

@dp.callback_query(F.data.startswith("bet:"))
async def cb_bet(c):
    await c.answer()
    n=int(c.data.split(":")[1]);u=user(c.message)
    q("UPDATE users SET bet=? WHERE id=?",(n,u["id"]));save()
    u=q("SELECT * FROM users WHERE id=?",(u["id"],)).fetchone()
    await c.message.edit_text(game(u),reply_markup=MAIN)

@dp.callback_query(F.data=="comb")
async def cb_comb(c):
    await c.answer();await c.message.edit_text(comb_text(),reply_markup=menu_back())

@dp.callback_query(F.data=="help")
async def cb_help(c):
    await c.answer();await c.message.edit_text(help_text(),reply_markup=menu_back())

@dp.callback_query(F.data=="top")
async def cb_top(c):
    await c.answer();await c.message.edit_text(top_text(),reply_markup=top_k())

@dp.callback_query(F.data.startswith("top:"))
async def cb_topmode(c):
    await c.answer();mode=c.data.split(":")[1]
    await c.message.edit_text(top_text("money" if mode=="chat" else mode,c.message.chat.id if mode=="chat" else None),reply_markup=top_k())

@dp.callback_query(F.data=="group")
async def cb_group(c):
    await c.answer();await c.message.edit_text(group_text(c.message.chat.id),reply_markup=menu_back())

@dp.callback_query(F.data=="bonus")
async def cb_bonus(c):
    await c.answer()
    await bonus(c.message)

@dp.callback_query(F.data=="pay")
async def cb_pay(c):
    await c.answer();await c.message.edit_text("💸 Перевод:\n\nОтветь на сообщение игрока командой:\n/pay 100\n\nили:\n/pay @username 100",reply_markup=menu_back())

@dp.callback_query(F.data=="duel")
async def cb_duel(c):
    await c.answer();await c.message.edit_text("⚔️ <b>ДУЭЛИ</b>\n\nВ группе используй:\n/duel 100 @username",reply_markup=duel_menu())

@dp.callback_query(F.data.startswith("decline:"))
async def decline(c):
    await c.answer("Дуэль отклонена")
    did=int(c.data.split(":")[1]);q("UPDATE duels SET status='declined' WHERE id=?",(did,));save()
    await c.message.edit_text("❌ Дуэль отклонена.",reply_markup=MAIN)

@dp.callback_query(F.data.startswith("accept:"))
async def accept(c):
    await c.answer()
    did=int(c.data.split(":")[1])
    d=q("SELECT * FROM duels WHERE id=? AND status='pending'",(did,)).fetchone()
    if not d or d["opponent"]!=c.from_user.id:
        await c.message.edit_text("❌ Дуэль недоступна.");return
    a=q("SELECT * FROM users WHERE id=?",(d["challenger"],)).fetchone()
    b=q("SELECT * FROM users WHERE id=?",(d["opponent"],)).fetchone()
    bet=d["bet"]
    if a["bal"]<bet or b["bal"]<bet:
        await c.message.edit_text("❌ У одного из игроков недостаточно денег.");return
    # 3 вращения каждому
    sa=sb=0
    for _ in range(3):
        sa+=random.choice([0,bet,bet*2,bet*3,bet*5])
        sb+=random.choice([0,bet,bet*2,bet*3,bet*5])
    winner=a if sa>sb else b if sb>sa else None
    if winner:
        loser=b if winner["id"]==a["id"] else a
        prize=bet*2
        q("UPDATE users SET bal=bal-? WHERE id=?",(bet,a["id"]))
        q("UPDATE users SET bal=bal-? WHERE id=?",(bet,b["id"]))
        q("UPDATE users SET bal=bal+? WHERE id=?",(prize,winner["id"]))
        text=f"⚔️ <b>ДУЭЛЬ ОКОНЧЕНА!</b>\n\n🏆 Победитель: <b>{winner['name']}</b>\n\n🎰 {a['name']}: {sa}\n🎰 {b['name']}: {sb}\n\n💰 Приз: <b>{prize}</b>"
    else:
        text=f"⚔️ <b>НИЧЬЯ!</b>\n\n🎰 {a['name']}: {sa}\n🎰 {b['name']}: {sb}\n\n💰 Ставки возвращены."
    q("UPDATE duels SET status='done' WHERE id=?",(did,));save()
    if not winner:
        pass
    await c.message.edit_text(text,reply_markup=MAIN)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b"OK")
    def log_message(self,*a): pass

def server():
    HTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),H).serve_forever()

Thread(target=server,daemon=True).start()

async def main():
    print("BOT STARTED")
    print("0.0.0.0:"+os.getenv("PORT","10000"))
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())

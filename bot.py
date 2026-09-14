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

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "💎", "7️⃣"]
MULTI = {"🍒": 5, "🍋": 7, "🍊": 10, "🔔": 15, "💎": 30}
BETS = [10, 25, 50, 100]
ACHIEV_NAMES = {"newbie": "👶 Новичок", "rich": "💰 Богач", "highroller": "🔥 Хайроллер"}
MISSION_NAMES = {"daily_spin": "🎰 Крутки", "daily_win": "🏆 Победа"}

def con(): return sqlite3.connect(DB)

def init_db():
    c = con()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, name TEXT, balance INTEGER DEFAULT 1000, xp INTEGER DEFAULT 0,
        spins INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, best INTEGER DEFAULT 0, bet INTEGER DEFAULT 10,
        bonus TEXT DEFAULT '', wheel TEXT DEFAULT '', achievements TEXT DEFAULT '', missions TEXT DEFAULT '')""")
    c.execute("""CREATE TABLE IF NOT EXISTS jackpot(id INTEGER PRIMARY KEY, money INTEGER DEFAULT 5000)""")
    c.execute("INSERT OR IGNORE INTO jackpot(id,money) VALUES(1,5000)")
    c.commit(); c.close()

def register(u): 
    c = con()
    c.execute("INSERT OR IGNORE INTO users(id,name,bonus,wheel,achievements,missions) VALUES(?,?,?,?,?,?)",
              (u.id, u.full_name or "Игрок", '', '', '', ''))
    c.execute("UPDATE users SET name=? WHERE id=?", (u.full_name or "Игрок", u.id)); c.commit(); c.close()

def user(uid): 
    c = con(); r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); c.close(); return r

def update(uid, field, value):
    allowed = {"balance","xp","spins","wins","best","bet","bonus","wheel","achievements","missions"}
    if field not in allowed: return
    c = con(); c.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, uid)); c.commit(); c.close()

def level(uid): u = user(uid); return u[3] // 100 + 1
def get_jackpot(): c = con(); r = c.execute("SELECT money FROM jackpot WHERE id=1").fetchone()[0]; c.close(); return r
def add_jackpot(v): c = con(); c.execute("UPDATE jackpot SET money=money+? WHERE id=1", (v,)); c.commit(); c.close()
def reset_jackpot(): c = con(); c.execute("UPDATE jackpot SET money=5000 WHERE id=1"); c.commit(); c.close()

def menu(): 
    k = InlineKeyboardBuilder()
    items = [("🎰 Слоты","game"), ("👤 Профиль","profile"), ("🎁 Бонус","bonus"), ("🏆 Топ","top"), ("🔢 Комбинации","combos"), ("🎡 Колесо","wheel"), ("📊 Статистика","stats"), ("❓ Помощь","help")]
    for t,d in items: k.button(text=t, callback_data=d); k.adjust(2); return k.as_markup()

def game_menu(uid): 
    u = user(uid); k = InlineKeyboardBuilder()
    k.button(text=f"🎰 КРУТИТЬ • {u[7]} 💰", callback_data="spin")
    for b in BETS: k.button(text=f"💰 {b}", callback_data=f"bet:{b}")
    k.button(text="🔙 Меню", callback_data="menu"); k.adjust(1,4,1); return k.as_markup()

@dp.message(CommandStart())
async def start(m): register(m.from_user); await m.answer("🎰 <b>СЛОТЫ</b>\n\nДобро пожаловать!\n💰 Баланс: 1000\n👇 Выбирай:", reply_markup=menu())
@dp.message(Command("slots")): register(m:=Message); await m.answer(f"🎰 <b>СЛОТЫ</b>\n\n💎 Джекпот: <b>{get_jackpot()}</b>", reply_markup=game_menu(m.from_user.id))
@dp.message(Command("balance")): register(m:=Message); u=user(m.from_user.id); await m.answer(f"💰 Баланс: <b>{u[2]}</b>\n⭐ Уровень: <b>{level(u[0])}</b>\n✨ XP: <b>{u[3]}</b>")
@dp.callback_query(F.data=="menu"): register(c:=CallbackQuery); await c.answer(); await c.message.edit_text("🎰 <b>СЛОТЫ</b>\n\n👇 Выбирай:", reply_markup=menu())
@dp.callback_query(F.data=="game"): register(c:=CallbackQuery); await c.answer(); await c.message.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n💎 Джекпот: <b>{get_jackpot()}</b>", reply_markup=game_menu(c.from_user.id))

@dp.callback_query(F.data.startswith("bet:"))
async def bet_button(c: CallbackQuery):
    register(c.from_user); v=int(c.data.split(":")[1]); update(c.from_user.id,"bet",v)
    await c.answer(f"Ставка {v} 💰"); await c.message.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎯 Ставка: <b>{v}</b> 💰\n💎 Джекпот: <b>{get_jackpot()}</b>", reply_markup=game_menu(c.from_user.id))

@dp.callback_query(F.data == "spin")
async def spin(c: CallbackQuery):
    register(c.from_user); uid=c.from_user.id; u=user(uid); bet=u[7]
    if u[2]<bet: await c.answer("❌ Недостаточно монет!", show_alert=True); return
    update(uid,"balance",u[2]-bet); update(uid,"spins",u[4]+1); update(uid,"xp",u[3]+10)
    await c.answer(); await c.message.edit_text("🎰 <b>КРУТИМ...</b>\n\n❓ | ❓ | ❓"); await asyncio.sleep(0.3)
    res=[random.choice(SYMBOLS) for _ in range(3)]
    await c.message.edit_text(f"🎰 <b>КРУТИМ...</b>\n\n{res[0]} | ❓ | ❓"); await asyncio.sleep(0.3)
    await c.message.edit_text(f"🎰 <b>КРУТИМ...</b>\n\n{res[0]} | {res[1]} | ❓"); await asyncio.sleep(0.3)
    
    win=0; achieved=[]; today=datetime.now(timezone.utc).date().isoformat()
    if res[0]==res[1]==res[2]=="7️⃣": win=get_jackpot(); reset_jackpot(); achieved.append("jackpot")
    elif res[0]==res[1]==res[2]: win=bet*MULTI[res[0]]
    elif res[0]==res[1] or res[0]==res[2] or res[1]==res[2]: win=bet*2
    else: add_jackpot(max(1, bet//10))
    
    if win>0: now=user(uid); update(uid,"balance",now[2]+win); update(uid,"wins",now[5]+1); if win>now[6]: update(uid,"best",win)
    
    # Достижения
    achs = user(uid)[10].split(',') if user(uid)[10] else []
    if "newbie" not in achs and u[4]==0: update(uid,"achievements", f"{user(uid)[10]},newbie".strip(',')); achieved.append("newbie")
    if "rich" not in achs and win>=1000: update(uid,"achievements", f"{user(uid)[10]},rich".strip(',')); achieved.append("rich")
    if "highroller" not in achs and bet==100: update(uid,"achievements", f"{user(uid)[10]},highroller".strip(',')); achieved.append("highroller")

    text = "🎰 <b>РЕЗУЛЬТАТ</b>\n\n" + f"{res[0]} | {res[1]} | {res[2]}\n\n"
    text += "💎💎💎 <b>ДЖЕКПОТ!</b>\n💰 +" + str(win) if res[0]==res[1]==res[2]=="7️⃣" else ("🎉 <b>Выигрыш +" + str(win) + "</b> 💰" if win else f"😢 Проигрыш -{bet} 💰")
    if achieved: text += "\n🏅 " + ", ".join([ACHIEV_NAMES[a] for a in achieved])
    text += f"\n\n💰 Баланс: <b>{user(uid)[2]}</b>\n⭐ Уровень: <b>{level(uid)}</b>\n💎 Джекпот: <b>{get_jackpot()}</b>"

    # Кнопка Крутить ещё
    k = InlineKeyboardBuilder(); k.button(text="🔁 Крутить ещё", callback_data="spin"); k.button(text="🔙 Меню", callback_data="menu"); k.adjust(2)
    await c.message.edit_text(text, reply_markup=k.as_markup())

# --- ПРОФИЛЬ И МЕНЮ ---
@dp.callback_query(F.data=="profile"): register(c:=CallbackQuery); u=user(c.from_user.id); await c.answer(); await c.message.edit_text(f"👤 <b>ПРОФИЛЬ</b>\n\n👤 {u[1]}\n💰 Баланс: <b>{u[2]}</b>\n⭐ Уровень: <b>{level(u[0])}</b>\n✨ XP: <b>{u[3]}</b>\n🎰 Круток: <b>{u[4]}</b>\n🏆 Побед: <b>{u[5]}</b>\n💎 Лучший: <b>{u[6]}</b>", reply_markup=menu())
@dp.callback_query(F.data=="bonus"): register(c:=CallbackQuery); uid=c.from_user.id; u=user(uid); today=datetime.now(timezone.utc).date().isoformat(); if u[8]==today: await c.answer("Уже сегодня!", show_alert=True); return; reward=100+level(uid)*25; update(uid,"balance",u[2]+reward); update(uid,"bonus",today); await c.answer(f"+{reward} 💰"); await c.message.edit_text(f"🎁 <b>БОНУС</b>\n\n💰 +{reward}\n\nВозвращайся завтра!", reply_markup=menu())
@dp.callback_query(F.data=="top"): register(c:=CallbackQuery); c.answer(); c.con(); rows=c.con().execute("SELECT name,balance FROM users ORDER BY balance DESC LIMIT 10").fetchall(); c.con().close(); txt="🏆 <b>ТОП</b>\n\n"; [txt := txt + f"<b>{i}.</b> {r[0]} — {r[1]} 💰\n" for i,r in enumerate(rows,1)]; await c.message.edit_text(txt, reply_markup=menu())
@dp.callback_query(F.data=="combos"): register(c:=CallbackQuery); c.answer(); await c.message.edit_text("🔢 <b>КОМБИНАЦИИ</b>\n\n🍒x5 🍋x7 🍊x10 🔔x15 💎x30\n7️⃣7️⃣7️⃣ — 💎 ДЖЕКПОТ\nЛюбые 2 — x2", reply_markup=menu())
@dp.callback_query(F.data=="stats"): register(c:=CallbackQuery); u=user(c.from_user.id); c.answer(); await c.message.edit_text(f"📊 <b>СТАТИСТИКА</b>\n\n🎰 Круток: <b>{u[4]}</b>\n🏆 Побед: <b>{u[5]}</b>\n💎 Лучший: <b>{u[6]}</b>\n✨ XP: <b>{u[3]}</b>\n⭐ Уровень: <b>{level(u[0])}</b>", reply_markup=menu())
@dp.callback_query(F.data=="wheel"): register(c:=CallbackQuery); uid=c.from_user.id; u=user(uid); today=datetime.now(timezone.utc).date().isoformat(); if u[9]==today: await c.answer("Уже крутил!", show_alert=True); return; rew=random.choice([25,50,100,150,250,500,1000,5000]); update(uid,"balance",u[2]+rew); update(uid,"wheel",today); await c.answer(f"+{rew} 💰"); await c.message.edit_text(f"🎡 <b>КОЛЕСО</b>\n\n🎉 +{rew} 💰", reply_markup=menu())
@dp.callback_query(F.data=="help"): register(c:=CallbackQuery); c.answer(); await c.message.edit_text("❓ <b>ПОМОЩЬ</b>\n\n/start /slots /balance /bonus /profile /top", reply_markup=menu())

# --- НОВОЕ: ПЕРЕВОДЫ (/give @user сумма) ---
@dp.message(Command("give"))
async def cmd_give(m: Message):
    register(m.from_user); args=m.text.split(); u=user(m.from_user.id)
    if len(args)<3: await m.answer("Формат: /give @username 50"); return
    try: amt=int(args[2]); target_name=args[1].lstrip('@'); if amt<=0 or amt>u[2]: raise ValueError
    except: await m.answer("Ошибка суммы."); return
    c=con(); to=c.execute("SELECT id,name FROM users WHERE name LIKE ?", ('%'+target_name+'%',)).fetchone(); c.close()
    if not to: await m.answer("Пользователь не найден."); return
    update(m.from_user.id,"balance", u[2]-amt); update(to[0],"balance", user(to[0])[2]+amt)
    await m.answer(f"✅ Перевел {amt} 💰 пользователю {to[1]}")
    try: await bot.send_message(to[0], f"📨 Пришло {amt} 💰 от {m.from_user.full_name}"); except: pass

class Health(BaseHTTPRequestHandler): 
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, format, *args): pass

def server(): port=int(os.getenv("PORT","10000")); HTTPServer(("0.0.0.0",port),Health).serve_forever()

async def main():
    init_db(); threading.Thread(target=server, daemon=True).start()
    print("BOT STARTED"); await bot.delete_webhook(drop_pending_updates=True); await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())

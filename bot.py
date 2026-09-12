импорт os
import asyncio
импорт случайных чисел
импорт sqlite3
импорт потоков
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# =========================
# КОНФИГ
# =========================

# Функция Render иногда сохраняет случайные пробелы в именах переменных.
# Эта команда нормализует имя переменной окружения перед её чтением.
ENV = {str(k).strip(): str(v).strip() for k, v in os.environ.items()}
BOT_TOKEN = ENV.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    вызвать RuntimeError(
        "Нет BOT_TOKEN.В Render -> Переменные среды"
        "Создан доступ к BOT_TOKEN с помощью BotFather."
    )

PORT = int(os.environ.get("PORT", "10000"))
DB_FILE = "slots.db"

START_BALANCE = 1000
JACKPOT_START = 5000

СИМВОЛЫ = ["рџЌ'", "рџЌ‹", "рџЌЉ", "рџ"”", "рџ'Ћ", "7пёЏвѓЈ"]
МНОЖИТЕЛИ = {
    "рџЌ'": 5,
    "рџЌ‹": 7,
    "рџЌЉ": 10,
    "рџ””): 15,
    "рџ'Ћ": 30,
    "7пёЏвѓЈ": 100,
}

# =========================
# БАЗА ДАННЫХ
# =========================

db_lock = threading.Lock()
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
conn.row_factory = sqlite3.Row

с db_lock:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id — целочисленный первичный ключ.
            username TEXT DEFAULT '',
            balance INTEGER NOT NULL DEFAULT 1000,
            xp INTEGER NOT NULL DEFAULT 0,
            уровень INTEGER NOT NULL DEFAULT 1,
            last_bonus TEXT DEFAULT '',
            spins INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            Основной ключ текста
            значение INTEGER NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO settings(key, value) VALUES('jackpot', ?)",
        (JACKPOT_START,),
    )
    conn.commit()


def get_jackpot():
    с db_lock:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='jackpot'"
        ).fetchone()
        return int(row["value"])


def set_jackpot(value):
    с db_lock:
        conn.execute(
            "ОБНОВИТЬ настройки SET value=? WHERE key='jackpot'",
            (max(0, int(value)),),
        )
        conn.commit()


def get_user(user_id, username=""):
    с db_lock:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id=?",
            (ID пользователя,),
        ).fetchone()

        если строка равна None:
            conn.execute(
                """
                INSERT INTO users(user_id, username, balance, xp, level)
                ЗНАЧЕНИЯ(?, ?, ?, 0, 1)
                """,
                (user_id, username или "", START_BALANCE),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM users WHERE user_id=?",
                (ID пользователя,),
            ).fetchone()
        elif username and row["username"] != username:
            conn.execute(
                "UPDATE users SET username=? WHERE user_id=?",
                (имя пользователя, идентификатор пользователя),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM users WHERE user_id=?",
                (ID пользователя,),
            ).fetchone()

        return dict(row)


def update_user(user_id, **fields):
    allowed = {"username", "balance", "xp", "level", "last_bonus", "spins"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    если не поля:
        возвращаться

    columns = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [user_id]

    с db_lock:
        conn.execute(
            f"UPDATE users SET {columns} WHERE user_id=?",
            ценности,
        )
        conn.commit()


# =========================
# ИГРА
# =========================

def level_from_xp(xp):
    возврат опыта // 100 + 1


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџЋ° РљР РЈРўР˜РўР¬", callback_data="spin:10")],
            [
                InlineKeyboardButton(text="спин:10", callback_data="spin:10"),
                InlineKeyboardButton(text="спин:25", callback_data="spin:25"),
            ],
            [
                InlineKeyboardButton(text="спин:50", callback_data="spin:50"),
                InlineKeyboardButton(text="спин:100", callback_data="spin:100"),
            ],
            [
                InlineKeyboardButton(text="рџЋЃ Р'РѕРЅСѓСЃ", callback_data="bonus"),
                InlineKeyboardButton(text="рџЏ† РўРѕРї", callback_data="top"),
            ],
            [InlineKeyboardButton(text="рџ'° Р'Р°Р"Р°РЅСЃ", callback_data="balance")],
        ]
    )


def welcome_text(user):
    возвращаться (
        "рџЋ° <b>СВРўР"</b>\n\n"
        f"рџ'° Р'Р°Р°РЅСЃ: <b>{user['balance']</b> рџЄ™\n"
        f"v РЈСЂРѕРІРµРЅСЊ: <b>{user['level']}</b>\n"
        f"вњЁ XP: <b>{user['xp']}</b>\n"
        f"рџЋЇ РЎРїРёРЅРѕРІ: <b>{user['spins']</b>\n\n"
        "Нет сЃС‚Р°РІРєСѓ Рё РєСЂСѓС‚Рё Н±Р°СЂР°Р°РЅС‹!"
    )


def spin_result(user_id, bet):
    пользователь = get_user(user_id)

    если user["balance"] < bet:
        возвращаться (
            "ќЊ РќРμХРѕСЃС‚Р°С‚РѕС‡РЅРѕ РјРѕРЅРµС‚.\n"
            f"РўРІРѕР№ Р±Р°Р°РЅСЃ: <b>{user['balance']</b> рџЄ™"
        )

    reels = [random.choice(SYMBOLS) for _ in range(3)]

    баланс = пользователь["баланс"] - ставка
    xp = user["xp"] + 10
    spins = user["spins"] + 1

    джекпот = get_jackpot() + max(1, bet // 10)
    победа = 0
    result_text = "Рџ˜ђ РќРёС‡РµРіРѕ. РџРѕРїСЂРѕР±СѓР№ РµС‰С'!"

    если reels[0] == reels[1] == reels[2] == "7пёЏвѓЈ":
        выигрыш = джекпот
        джекпот = JACKPOT_START
        result_text = f"рџЋ‰ <b>Н–Р•РљРџРћРў!</b> РўС‹ РІС‹РёРіСЂР°Р» <b>{win</b> рџЄ™!"
    elif reels[0] == reels[1] == reels[2]:
        выигрыш = ставка * МНОЖИТЕЛИ[reels[0]]
        result_text = f"рџ”Ґ РўСЂРё РѕРґРёРЅР°РєРѕРІС‹С…!\nР'С‹РёРіСЂС‹С€: <b>{win}</b> рџЄ™"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        выигрыш = ставка * 2
        result_text = f"вњЁ РІР° РѕРґРёРЅР°РєРѕРІС‹С…! Д'С‹РёРіСЂС‹С€: <b>{win}</b> рџЄ™"

    баланс += победа

    update_user(
        ID пользователя,
        баланс = баланс,
        xp=xp,
        level=level_from_xp(xp),
        spins=spins,
    )
    set_jackpot(jackpot)

    new_user = get_user(user_id)

    возвращаться (
        "рџЋ° <b>СВРўР"</b>\n\n"
        f"в"ѓ {reels[0]} в"ѓ {reels[1]} в"ѓ {reels[2]} в"ѓ\n\n"
        f"{result_text}\n\n"
        f"рџ'ё РЎС‚Р°РІРєР°: <b>{bet</b> рџЄ™\n"
        f"рџ'° Р'Р°Р°РЅСЃ: <b>{new_user['balance']</b> рџЄ™\n"
        f"в списке: <b>{new_user['level']</b>\n"
        f"рџЋЇ РЎРїРёРЅРѕРІ: <b>{new_user['spins']</b>\n"
        f"рџ'Ћ Р"Р¶РµРїРѕС‚: <b>{get_jackpot()}</b> рџЄ™"
    )


def bonus_result(user_id):
    пользователь = get_user(user_id)

    if user["last_bonus"] == today():
        return "РџЋЃ РўС‹ СѓР¶Рµ РїРѕР»СѓС‡РёР» РµР¶РµРґРЅРµРЅС‹Р№ Р±РѕРЅСѓСЃ СЃРµРіРѕРґРЅСЏ."

    награда = 100 + user["уровень"] * 25
    new_balance = user["balance"] + reward

    update_user(
        ID пользователя,
        balance=new_balance,
        last_bonus=today(),
    )

    возвращаться (
        "рџЋЃ <b>Р•Р–Р•Р»РќР•Р'Р™ Р'РћРЈС</b>\n\n"
        f"РўС‹ РїРѕР»СѓС‡РёР» <b>+{reward}</b> рџЄ™!\n"
        f"рџ'° Р'Р°Р°РЅСЃ: <b>{new_balance</b> рџЄ™"
    )


def top_result():
    с db_lock:
        rows = conn.execute(
            """
            SELECT username, user_id, balance, level, spins
            ОТ пользователей
            ORDER BY balance DESC
            ЛИМИТ 10
            """
        ).fetchall()

    если не строки:
        return "РџЏ† РџРѕРєР° РёРіСЂРѕРєРѕРІ РЅРµС‚."

    lines = ["рџЏ† <b>РўРћРџ Р˜Р“Р РћРљРћР'</b>\n"]
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"Р˜РіСЂРѕРє {str(row['user_id'])[-4:]}"
        lines.append(
            f"{i}. {имя} — рџ'° {строка['баланс']} рџЄ™ | ✔ {строка['уровень']}"
        )
    return "\n".join(lines)


# =========================
#ТЕЛЕГРАМ
# =========================

dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    пользователь = get_user(
        сообщение.от_пользователя.id,
        сообщение.от_пользователя.имя_пользователя или "",
    )
    await message.answer(
        welcome_text(user),
        reply_markup=main_keyboard(),
    )


@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    пользователь = get_user(
        сообщение.от_пользователя.id,
        сообщение.от_пользователя.имя_пользователя или "",
    )
    await message.answer(
        f"рџ'° Р'Р°Р°РЅСЃ: <b>{user['balance']</b> рџЄ™\n"
        f"v РЈСЂРѕРІРµРЅСЊ: <b>{user['level']}</b>\n"
        f"вњЁ XP: <b>{user['xp']}</b>\n"
        f"рџЋЇ РЎРїРёРЅРѕРІ: <b>{user['spins']</b>",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    await message.answer(
        bonus_result(message.from_user.id),
        reply_markup=main_keyboard(),
    )


@dp.message(Command("top"))
async def cmd_top(message: Message):
    await message.answer(
        top_result(),
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data.startswith("spin:"))
async def cb_spin(callback: CallbackQuery):
    ставка = int(callback.data.split(":")[1])
    текст = spin_result(callback.from_user.id, bet)
    await callback.answer()
    await callback.message.edit_text(
        текст,
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "bonus")
async def cb_bonus(callback: CallbackQuery):
    текст = bonus_result(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        текст,
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):
    пользователь = get_user(
        callback.from_user.id,
        callback.from_user.username or "",
    )
    await callback.answer()
    await callback.message.edit_text(
        f"рџ'° Р'Р°Р°РЅСЃ: <b>{user['balance']</b> рџЄ™\n"
        f"v РЈСЂРѕРІРµРЅСЊ: <b>{user['level']}</b>\n"
        f"вњЁ XP: <b>{user['xp']}</b>\n"
        f"рџЋЇ РЎРїРёРЅРѕРІ: <b>{user['spins']</b>",
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "top")
async def cb_top(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        top_result(),
        reply_markup=main_keyboard(),
    )


# =========================
# ОБЕСПЕЧЕНИЕ ЗДОРОВЬЯ ВЕБ-СЕРВИСА ОТОБРАЖЕНИЯ
# =========================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/healthz"):
            тело = "ОК"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        еще:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        проходить


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Сервер здоровья запущен на порту {PORT}")
    server.serve_forever()


# =========================
# НАЧИНАТЬ
# =========================

async def main():
    print("BOT_TOKEN №ХР.")
    бот = Бот(BOT_TOKEN)

    threading.Thread(
        target=start_health_server,
        daemon=True,
    ).начинать()

    print("Запуск Telegram-бота...")
    await dp.start_polling(bot)


если __name__ == "__main__":
    asyncio.run(main())

import os
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")


PORT = int(os.getenv("PORT", "10000"))

dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🎰 Привет!\n\n"
        "Добро пожаловать в мои СЛОТЫ!\n"
        "Бот работает ✅"
    )


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        body = b"OK"

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain"
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.end_headers()

        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def start_server():
    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(f"HTTP server started on port {PORT}")

    server.serve_forever()


async def main():

    health_thread = threading.Thread(
        target=start_server,
        daemon=True
    )

    health_thread.start()

    bot = Bot(TOKEN)

    print("Telegram bot started!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

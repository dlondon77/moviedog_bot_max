"""
Максимально простой тестовый бот для Max (без клавиатур)
"""

import asyncio
import logging
import os
from maxapi import Bot, Dispatcher
from maxapi.types import Message
from maxapi.filters import Command

# Токен из переменных окружения
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=MAX_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    """Простое приветствие без кнопок"""
    await message.answer(
        "🐾 Привет! Я бот КиноИщейка!\n\n"
        "✅ Бот работает!\n"
        "✅ Подключение к Max успешно!\n\n"
        "Просто напиши мне что-нибудь, и я отвечу.\n\n"
        "Команды:\n"
        "/start - это сообщение\n"
        "/ping - проверить что бот жив"
    )


@dp.message(Command("ping"))
async def ping(message: Message):
    """Проверка связи"""
    await message.answer("🏓 Понг! Бот работает!")


@dp.message()
async def echo(message: Message):
    """Эхо на любое сообщение"""
    text = message.body.text if message.body else ""
    if text:
        await message.answer(f"Ты написал: {text}\n\nИспользуй /start для списка команд")
    else:
        await message.answer("Используй /start для списка команд")


async def main():
    logger.info("🚀 Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

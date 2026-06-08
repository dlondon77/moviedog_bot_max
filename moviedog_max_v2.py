"""
Простой тестовый бот для Max
"""

import asyncio
import logging
import os
from maxapi import Bot, Dispatcher
from maxapi.types import Message
from maxapi.filters import Command

# Токен берем из переменных окружения
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан! Укажи токен в переменных окружения")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=MAX_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    """Простое приветствие"""
    await message.answer(
        "🐾 Привет! Я бот КиноИщейка!\n\n"
        "✅ Бот работает!\n"
        "✅ Подключение к Max успешно!\n\n"
        "Мои команды:\n"
        "/start - показать это сообщение\n"
        "/help - помощь\n"
        "/ping - проверить что бот жив"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    """Помощь"""
    await message.answer(
        "🤖 Я простой тестовый бот\n\n"
        "Доступные команды:\n"
        "/start - приветствие\n"
        "/help - эта справка\n"
        "/ping - проверка связи"
    )


@dp.message(Command("ping"))
async def ping(message: Message):
    """Проверка что бот отвечает"""
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
    logger.info("✅ Бот запущен!")


if __name__ == "__main__":
    asyncio.run(main())

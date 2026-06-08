"""
Простейший тестовый бот для Max
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
    raise ValueError("MAX_TOKEN не задан! Укажи токен в переменных окружения")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создаём бота и диспетчер
bot = Bot(token=MAX_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "🐾 Привет! Я тестовый бот!\n\n"
        "✅ Бот успешно запущен\n"
        "✅ Подключение к Max работает\n\n"
        "Доступные команды:\n"
        "/start - это сообщение\n"
        "/ping - проверка связи\n"
        "/info - информация о боте"
    )


@dp.message(Command("ping"))
async def ping(message: Message):
    """Проверка что бот жив"""
    await message.answer("🏓 Понг! Бот работает и отвечает!")


@dp.message(Command("info"))
async def info(message: Message):
    """Информация о боте"""
    await message.answer(
        "🤖 Тестовый бот для мессенджера Max\n\n"
        "Версия: 1.0\n"
        "Статус: ✅ активен\n\n"
        "Это простейший пример для проверки работоспособности."
    )


@dp.message()
async def echo(message: Message):
    """На любое другое сообщение отвечаем эхом"""
    user_text = message.body.text if message.body else ""
    if user_text:
        await message.answer(
            f"📝 Ты написал: {user_text}\n\n"
            f"Используй /start для списка команд"
        )
    else:
        await message.answer("Используй /start для списка команд")


async def main():
    """Запуск бота"""
    logger.info("🚀 Запуск тестового бота...")
    logger.info(f"Бот использует токен: {MAX_TOKEN[:10]}...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

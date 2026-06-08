"""
Простейший тестовый бот для Max (без Command фильтра)
"""

import asyncio
import logging
import os
from maxapi import Bot, Dispatcher
from maxapi.types import Message

# Токен из переменных окружения
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан! Укажи токен в переменных окружения")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создаём бота и диспетчер
bot = Bot(token=MAX_TOKEN)
dp = Dispatcher()


@dp.message()
async def handle_all_messages(message: Message):
    """Обработчик всех сообщений"""
    user_text = message.body.text if message.body else ""
    
    # Проверяем команды вручную
    if user_text == "/start":
        await message.answer(
            "🐾 Привет! Я тестовый бот!\n\n"
            "✅ Бот успешно запущен\n"
            "✅ Подключение к Max работает\n\n"
            "Доступные команды:\n"
            "/start - это сообщение\n"
            "/ping - проверка связи\n"
            "/info - информация о боте"
        )
    
    elif user_text == "/ping":
        await message.answer("🏓 Понг! Бот работает и отвечает!")
    
    elif user_text == "/info":
        await message.answer(
            "🤖 Тестовый бот для мессенджера Max\n\n"
            "Версия: 1.0\n"
            "Статус: ✅ активен\n\n"
            "Это простейший пример для проверки работоспособности."
        )
    
    elif user_text:
        await message.answer(
            f"📝 Ты написал: {user_text}\n\n"
            f"Напиши /start для списка команд"
        )
    else:
        await message.answer("Напиши /start для списка команд")


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

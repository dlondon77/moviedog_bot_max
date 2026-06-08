"""
Рабочий тестовый бот для Max
Основан на официальном примере из GitHub max-messenger/max-botapi-python
"""

import asyncio
import logging
import os

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated

# Токен из переменных окружения
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан! Укажи токен в переменных окружения")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создаём бота и диспетчер
bot = Bot(MAX_TOKEN)
dp = Dispatcher()


# Ответ бота при нажатии на кнопку "Начать" в диалоге
@dp.bot_started()
async def bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='🐾 Привет! Напиши /start чтобы начать работу с КиноИщейкой'
    )


# Ответ бота на команду /start
@dp.message_created(Command("start"))
async def cmd_start(event: MessageCreated):
    await event.message.answer(
        "🐾 Привет! Я тестовый бот КиноИщейка!\n\n"
        "✅ Бот успешно запущен\n"
        "✅ Подключение к Max работает\n\n"
        "Доступные команды:\n"
        "/start - это сообщение\n"
        "/ping - проверка связи\n"
        "/info - информация о боте"
    )


# Ответ бота на команду /ping
@dp.message_created(Command("ping"))
async def cmd_ping(event: MessageCreated):
    await event.message.answer("🏓 Понг! Бот работает и отвечает!")


# Ответ бота на команду /info
@dp.message_created(Command("info"))
async def cmd_info(event: MessageCreated):
    await event.message.answer(
        "🤖 Тестовый бот для мессенджера Max\n\n"
        "Версия: 1.0\n"
        "Статус: ✅ активен\n\n"
        "Это простейший пример для проверки работоспособности."
    )


# Обработчик всех остальных сообщений
@dp.message_created()
async def handle_any_message(event: MessageCreated):
    user_text = event.message.body.text if event.message.body else ""
    if user_text:
        await event.message.answer(
            f"📝 Ты написал: {user_text}\n\n"
            f"Напиши /start для списка команд"
        )
    else:
        await event.message.answer("Напиши /start для списка команд")


async def main():
    """Запуск бота через polling"""
    logger.info("🚀 Запуск тестового бота...")
    logger.info(f"Бот использует токен: {MAX_TOKEN[:10]}...")
    
    # Важно: удаляем вебхук, если он был установлен
    await bot.delete_webhook()
    
    # Запускаем polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

"""
Тестовый бот для Bothost
Переменные окружения берутся из панели управления Bothost
"""

import asyncio
import logging
import os

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated

# Переменные окружения — они уже есть в системе на Bothost
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан! Добавь переменную в панели Bothost")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(MAX_TOKEN)
dp = Dispatcher()


@dp.bot_started()
async def bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='🐾 Бот запущен! Напиши /start'
    )


@dp.message_created(Command("start"))
async def cmd_start(event: MessageCreated):
    # Проверяем, какие переменные заданы
    max_token_status = "✅" if os.environ.get("MAX_TOKEN") else "❌"
    deepseek_status = "✅" if os.environ.get("DEEPSEEK_KEY") else "❌"
    
    await event.message.answer(
        f"🐾 Привет! Бот работает!\n\n"
        f"Статус переменных окружения:\n"
        f"MAX_TOKEN: {max_token_status}\n"
        f"DEEPSEEK_KEY: {deepseek_status}\n\n"
        f"Напиши /ping для проверки связи"
    )


@dp.message_created(Command("ping"))
async def cmd_ping(event: MessageCreated):
    await event.message.answer("🏓 Понг!")


@dp.message_created()
async def handle_message(event: MessageCreated):
    text = event.message.body.text if event.message.body else ""
    if text and not text.startswith("/"):
        await event.message.answer(f"Ты написал: {text}")


async def main():
    logger.info("🚀 Бот запускается на Bothost...")
    await bot.delete_webhook()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

"""
КиноИщейка — подборки фильмов через DeepSeek
"""

import asyncio
import logging
import os
from openai import OpenAI
import httpx
from maxapi import Bot, Dispatcher
from maxapi.types import Message
from maxapi import InlineKeyboardMarkup, InlineKeyboardButton
from maxapi.filters import Command

# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────────
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан!")
if not DEEPSEEK_KEY:
    raise ValueError("DEEPSEEK_KEY не задан!")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=MAX_TOKEN)
dp = Dispatcher()

# Настройка DeepSeek
http_client = httpx.Client(timeout=60.0, follow_redirects=True)
ai_client = OpenAI(
    api_key=DEEPSEEK_KEY,
    base_url="https://api.deepseek.com/v1",
    http_client=http_client,
)


# ── ФУНКЦИЯ ПОДБОРКИ ─────────────────────────────────────────────────────
async def get_recommendations(request: str) -> str:
    """Получает подборку фильмов от DeepSeek"""
    
    system_prompt = """Ты — КиноИщейка, собака-девочка, кинокритик.
Говори о себе в женском роде, с юмором и энтузиазмом.

Когда просят подборку фильмов:
1. Предложи 3-5 фильмов
2. Для каждого: название (год), рейтинг (X/10), краткое описание
3. В конце посоветуй, что посмотреть первым
4. Используй эмодзи для оформления
5. Фильмы должны быть реальными (известные фильмы)"""

    user_prompt = f"""Составь подборку фильмов по запросу: "{request}"

Формат:
🎬 Название (Год) — ⭐ Рейтинг: X/10
📝 Краткое описание

В конце: 🐾 Первым советую: [название] потому что..."""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            timeout=60,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return "🐾 Гав! Что-то пошло не так. Попробуй ещё раз!"


# ── КОМАНДЫ ──────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Случайный фильм", callback_data="random")],
        [InlineKeyboardButton(text="❤️ Романтика", callback_data="romance")],
        [InlineKeyboardButton(text="😂 Комедия", callback_data="comedy")],
        [InlineKeyboardButton(text="😱 Ужасы", callback_data="horror")],
    ])
    
    await message.answer(
        "🐾 <b>Привет! Я КиноИщейка!</b>\n\n"
        "Просто напиши, что хочешь посмотреть, например:\n"
        "• «что-то атмосферное на вечер»\n"
        "• «хороший детектив»\n"
        "• «фильм под пиво»\n\n"
        "Или выбери кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🐾 <b>Как это работает:</b>\n\n"
        "Я использую DeepSeek, чтобы подобрать фильмы под твоё настроение.\n\n"
        "<b>Примеры запросов:</b>\n"
        "• «фантастика про космос»\n"
        "• «что посмотреть с девушкой»\n"
        "• «лучшие фильмы 90-х»\n"
        "• «мотивирующее кино»",
        parse_mode="HTML"
    )


@dp.message()
async def handle_message(message: Message):
    user_message = message.body.text if message.body else ""
    if not user_message:
        return
    
    await message.answer("🐾 Нюхаю базу знаний... 🎬")
    recommendations = await get_recommendations(user_message)
    await message.answer(recommendations)


# ── ОБРАБОТКА КНОПОК ─────────────────────────────────────────────────────
@dp.callback_query()
async def handle_callback(callback_query):
    data = callback_query.payload
    
    await callback_query.answer("Ищу фильмы...")
    
    if data == "random":
        result = await get_recommendations("случайный хороший фильм")
    elif data == "romance":
        result = await get_recommendations("романтический фильм")
    elif data == "comedy":
        result = await get_recommendations("смешная комедия")
    elif data == "horror":
        result = await get_recommendations("страшный фильм ужасов")
    else:
        result = await get_recommendations(data)
    
    await bot.send_message(
        chat_id=callback_query.chat.chat_id,
        text=result
    )


# ── ЗАПУСК ────────────────────────────────────────────────────────────────
async def main():
    logger.info("КиноИщейка запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

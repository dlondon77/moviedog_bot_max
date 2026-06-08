"""
КиноИщейка Lite — подборки фильмов через DeepSeek (без API poiskkino)
"""

import asyncio
import logging
import os
import json
from openai import OpenAI
import httpx
from maxapi import Bot, Dispatcher
from maxapi.types import Message
from maxapi.filters import Command

# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────────
MAX_TOKEN = os.environ.get("MAX_TOKEN", "ВАШ_ТОКЕН_MAX")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "ВАШ_КЛЮЧ_DEEPSEEK")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=MAX_TOKEN)
dp = Dispatcher()

# Настройка клиента DeepSeek
http_client = httpx.Client(timeout=60.0, follow_redirects=True)
ai_client = OpenAI(
    api_key=DEEPSEEK_KEY,
    base_url="https://api.deepseek.com/v1",
    http_client=http_client,
)


# ── ФУНКЦИЯ ГЕНЕРАЦИИ ПОДБОРКИ ────────────────────────────────────────────
async def get_movie_recommendations(prompt: str) -> str:
    """
    Просит DeepSeek составить подборку фильмов
    """
    system_prompt = """Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём на хорошее кино.
Говори о себе в женском роде, с юмором и энтузиазмом.

Когда пользователь просит подборку фильмов:
1. Всегда предлагай 3-5 фильмов
2. Для каждого фильма укажи: название, год, рейтинг (вымышленный, но правдоподобный), краткое описание
3. В конце добавь короткую рекомендацию, что лучше посмотреть первым
4. Форматируй ответ красиво, с эмодзи
5. Фильмы должны быть реально существующими (из мировой киноклассики, популярных фильмов последних лет)

Отвечай по-русски, дружелюбно."""

    user_prompt = f"""Составь подборку фильмов по запросу: "{prompt}"

Требования к ответу:
- Используй эмодзи для украшения
- Каждый фильм в формате:
🎬 Название (Год) — ⭐ Рейтинг: X/10
📝 Краткое описание (1-2 предложения)

- В конце напиши "🐾 Первым советую посмотреть: [название]" 
и почему именно его"""

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
        logger.error(f"Ошибка DeepSeek: {e}")
        return "🐾 Гав! Что-то пошло не так. Попробуй переформулировать запрос!"


# ── ХЕНДЛЕРЫ ──────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🐾 <b>Привет! Я КиноИщейка!</b>\n\n"
        "Я помогу подобрать фильмы под твоё настроение!\n\n"
        "<b>Просто напиши что хочешь посмотреть, например:</b>\n"
        "• «подбери фильм на вечер»\n"
        "• «хочу что-то смешное»\n"
        "• «атмосферный триллер»\n"
        "• «любовная драма»\n"
        "• «что посмотреть с семьёй»\n\n"
        "Я составлю персональную подборку! 🎬",
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🐾 <b>Как я работаю:</b>\n\n"
        "Просто напиши мне, что хочешь посмотреть, и я:\n"
        "1️⃣ Спрошу DeepSeek о лучших фильмах\n"
        "2️⃣ Составлю подборку из 3-5 фильмов\n"
        "3️⃣ Добавлю описание и рейтинг\n"
        "4️⃣ Посоветую, с чего начать\n\n"
        "<b>Примеры запросов:</b>\n"
        "• «фантастика про космос»\n"
        "• «хороший детектив»\n"
        "• «мультфильм для детей»\n"
        "• «фильм под пиво»\n"
        "• «шедевры мирового кино»",
        parse_mode="HTML"
    )


@dp.message(Command("random"))
async def cmd_random(message: Message):
    await message.answer("🎲 Дай-ка подумаю, что тебе посмотреть...")
    recommendation = await get_movie_recommendations("случайный хороший фильм, который всем нравится")
    await message.answer(recommendation)


@dp.message()
async def handle_message(message: Message):
    """Обрабатывает любые сообщения как запрос на подборку"""
    user_message = message.body.text if message.body else ""
    if not user_message:
        return
    
    # Показываем, что бот думает
    await message.answer("🐾 Нюхаю свою базу знаний... 🎬")
    
    # Получаем подборку от DeepSeek
    recommendations = await get_movie_recommendations(user_message)
    
    # Отправляем результат
    await message.answer(recommendations)


# ── ЗАПУСК ────────────────────────────────────────────────────────────────
async def main():
    logger.info("КиноИщейка (DeepSeek version) запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

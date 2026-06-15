"""
КиноИщейка — подборки фильмов через DeepSeek с защитой от перерасхода
Для Bothost
"""

import asyncio
import logging
import os
from datetime import date, datetime

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated
from openai import OpenAI
import httpx

# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────────
MAX_TOKEN = os.environ.get("MAX_TOKEN", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")

if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан!")
if not DEEPSEEK_KEY:
    raise ValueError("DEEPSEEK_KEY не задан!")

# ID администратора (можно узнать через /start, он покажется в логах)
# Пока оставим None, но можно указать свой ID
YOUR_ADMIN_ID = None  # Замени на свой user_id, например: 7191208

# ── ОГРАНИЧЕНИЯ ДЛЯ ЗАЩИТЫ ────────────────────────────────────────────────
DAILY_LIMIT = 50          # Максимум 50 запросов в день (для тестирования)
MONTHLY_BUDGET = 100      # Бюджет в рублях (DeepSeek очень дешёвый)
WARNING_THRESHOLD = 80    # Предупреждение при 80% бюджета

# Для отслеживания лимитов (в реальном проекте используйте БД)
usage_today = 0
current_date = date.today().isoformat()
total_spent = 0.0

# DeepSeek цены (за 1M токенов)
INPUT_PRICE = 0.14        # $0.14 за 1M input токенов
OUTPUT_PRICE = 0.28       # $0.28 за 1M output токенов

# ── НАСТРОЙКА ЛОГГИРОВАНИЯ ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── НАСТРОЙКА DEEPSEEK ────────────────────────────────────────────────────
http_client = httpx.Client(timeout=60.0, follow_redirects=True)
ai_client = OpenAI(
    api_key=DEEPSEEK_KEY,
    base_url="https://api.deepseek.com/v1",
    http_client=http_client,
)

# ── БОТ ───────────────────────────────────────────────────────────────────
bot = Bot(MAX_TOKEN)
dp = Dispatcher()


def check_limit(user_id: int = None) -> tuple[bool, str]:
    """
    Проверяет, не превышены ли лимиты.
    Возвращает (можно_ли_использовать, сообщение_об_ошибке)
    """
    global usage_today, current_date, total_spent
    
    # Сброс дневного счётчика
    today = date.today().isoformat()
    if current_date != today:
        usage_today = 0
        current_date = today
        logger.info(f"Дневной счётчик сброшен. Новый день: {today}")
    
    # Проверка дневного лимита
    if usage_today >= DAILY_LIMIT:
        return False, f"❌ Достигнут дневной лимит ({DAILY_LIMIT} запросов). Попробуй завтра!"
    
    # Проверка бюджета
    if total_spent >= MONTHLY_BUDGET:
        return False, f"❌ Достигнут месячный бюджет ({MONTHLY_BUDGET} ₽). Обратись к администратору!"
    
    # Предупреждение о скором исчерпании бюджета
    if total_spent >= WARNING_THRESHOLD:
        remaining = MONTHLY_BUDGET - total_spent
        logger.warning(f"⚠️ Бюджет почти исчерпан! Осталось: {remaining:.2f} ₽")
    
    return True, ""


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Рассчитывает стоимость запроса в рублях (по текущему курсу $ ≈ 90₽)"""
    usd_cost = (input_tokens / 1_000_000) * INPUT_PRICE + (output_tokens / 1_000_000) * OUTPUT_PRICE
    rub_cost = usd_cost * 90  # Примерный курс
    return rub_cost


async def get_movie_recommendations(request: str, user_id: int = None) -> tuple[str, dict]:
    """
    Получает подборку фильмов от DeepSeek с учётом лимитов.
    Возвращает (текст_ответа, статистика_запроса)
    """
    global usage_today, total_spent
    
    # Проверяем лимиты
    can_use, error_msg = check_limit(user_id)
    if not can_use:
        return error_msg, {}
    
    system_prompt = """Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём на хорошее кино.
Говори о себе в женском роде, с юмором и энтузиазмом.

Когда пользователь просит подборку фильмов:
1. Предложи 3-5 фильмов
2. Для каждого: название (год), рейтинг (X/10), краткое описание (1-2 предложения)
3. В конце посоветуй, что посмотреть первым, и почему
4. Используй эмодзи для оформления (🎬, ⭐, 📝, 🐾)
5. Фильмы должны быть реальными (известные фильмы)

Не используй маркдаун, только обычный текст с эмодзи."""

    user_prompt = f"""Составь подборку из 3-5 фильмов по запросу: "{request}"

Формат для каждого фильма:
🎬 Название (Год) — ⭐ Рейтинг: X/10
📝 Краткое описание (1-2 предложения)

В конце добавь: 🐾 Первым советую посмотреть: [название] потому что..."""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            timeout=60,
        )
        
        # Получаем токены для расчёта стоимости
        usage = response.usage
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        total_tokens = input_tokens + output_tokens
        cost = calculate_cost(input_tokens, output_tokens)
        
        # Обновляем счётчики
        usage_today += 1
        total_spent += cost
        
        stats = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_rub": cost,
            "total_spent_rub": total_spent,
            "requests_today": usage_today,
        }
        
        result = response.choices[0].message.content.strip()
        
        # Добавляем информационный футер с расходами (для администратора)
        if YOUR_ADMIN_ID and user_id == YOUR_ADMIN_ID:
            result += f"\n\n---\n📊 Статистика: {total_tokens} токенов | {cost:.4f} ₽ | Сегодня: {usage_today}/{DAILY_LIMIT}"
        
        return result, stats
        
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return "🐾 Гав! Что-то пошло не так. Попробуй ещё раз!", {}


# ── КОМАНДЫ БОТА ─────────────────────────────────────────────────────────
@dp.bot_started()
async def bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='🐾 Привет! Я КиноИщейка!\nНапиши /start чтобы начать'
    )


@dp.message_created(Command("start"))
async def cmd_start(event: MessageCreated):
    # Используем parse_mode="html" (маленькими буквами!)
    await event.message.answer(
        "🐾 <b>Привет! Я КиноИщейка — твой кинопомощник!</b>\n\n"
        "Просто напиши, что хочешь посмотреть, и я составлю подборку:\n"
        "• «хочу что-то атмосферное на вечер»\n"
        "• «хороший детектив как Шерлок»\n"
        "• «смешную комедию для всей семьи»\n"
        "• «фильм под пиво»\n\n"
        "📊 <b>Доступные команды:</b>\n"
        "/start — это сообщение\n"
        "/ping — проверка связи\n"
        "/stats — статистика использования\n"
        "/limit — узнать текущие лимиты\n\n"
        "🎬 <i>Поехали! Просто напиши свой запрос...</i>",
        parse_mode="html"  # ← ИСПРАВЛЕНО: "html" вместо "HTML"
    )


@dp.message_created(Command("ping"))
async def cmd_ping(event: MessageCreated):
    await event.message.answer("🏓 Понг! Бот работает!")


@dp.message_created(Command("stats"))
async def cmd_stats(event: MessageCreated):
    """Показывает статистику использования"""
    global usage_today, total_spent
    
    remaining = MONTHLY_BUDGET - total_spent
    budget_status = "🟢" if remaining > 20 else "🟡" if remaining > 5 else "🔴"
    
    await event.message.answer(
        f"📊 <b>Статистика использования DeepSeek</b>\n\n"
        f"📅 Запросов сегодня: {usage_today}/{DAILY_LIMIT}\n"
        f"💰 Потрачено за месяц: {total_spent:.2f} ₽ / {MONTHLY_BUDGET} ₽ {budget_status}\n"
        f"💸 Осталось: {max(0, remaining):.2f} ₽\n\n"
        f"<i>Лимиты обновляются в полночь по МСК</i>",
        parse_mode="html"  # ← ИСПРАВЛЕНО
    )


@dp.message_created(Command("limit"))
async def cmd_limit(event: MessageCreated):
    """Показывает текущие лимиты"""
    await event.message.answer(
        f"🔒 <b>Текущие лимиты бота:</b>\n\n"
        f"📅 Дневной лимит: {DAILY_LIMIT} запросов\n"
        f"💰 Месячный бюджет: {MONTHLY_BUDGET} ₽\n"
        f"⚠️ Предупреждение при: {WARNING_THRESHOLD} ₽\n\n"
        f"<i>DeepSeek очень экономичный — 1 запрос стоит ~0.001-0.01 ₽</i>",
        parse_mode="html"  # ← ИСПРАВЛЕНО
    )


@dp.message_created()
async def handle_message(event: MessageCreated):
    """Обрабатывает текстовые сообщения как запросы на подборку"""
    user_text = event.message.body.text if event.message.body else ""
    
    if not user_text or user_text.startswith("/"):
        return
    
    # Уведомляем о начале обработки
    await event.message.answer("🐾 Нюхаю базу знаний... 🎬")
    
    # Получаем подборку
    recommendations, stats = await get_movie_recommendations(user_text, event.message.sender.user_id)
    
    # Отправляем результат
    await event.message.answer(recommendations)
    
    # Логируем расходы
    if stats:
        logger.info(f"Запрос: '{user_text[:50]}...' | Токены: {stats.get('total_tokens', 0)} | {stats.get('cost_rub', 0):.4f} ₽")


# ── ЗАПУСК ────────────────────────────────────────────────────────────────
async def main():
    logger.info("🚀 КиноИщейка запускается...")
    logger.info(f"Лимиты: {DAILY_LIMIT} запросов/день, {MONTHLY_BUDGET} ₽/месяц")
    
    if not DEEPSEEK_KEY:
        logger.error("❌ DEEPSEEK_KEY не задан! Подборки фильмов не будут работать.")
    
    await bot.delete_webhook()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

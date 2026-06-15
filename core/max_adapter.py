# core/max_adapter.py — с генерацией мнений через DeepSeek

import logging
import configparser
import os
import sys
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(BASE_DIR, 'core')

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

# Настраиваем логгер
logger = logging.getLogger(__name__)

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated
from openai import OpenAI
import httpx

# Пробуем импортировать клавиатуру (для будущего)
try:
    from maxapi.types import InlineKeyboardMarkup, InlineKeyboardButton
    HAS_KEYBOARD = True
except ImportError:
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url
    HAS_KEYBOARD = False

# Импорты из core
import user as user_module
import movie as movie_module
import db as db_module

register_user = user_module.register_user
get_user_limits = user_module.get_user_limits
get_user_stats = user_module.get_user_stats
increment_stat_counter = user_module.increment_stat_counter
record_user_opinion = user_module.record_user_opinion

get_random_movie_from_db = movie_module.get_random_movie_from_db
get_movie_details = movie_module.get_movie_details
format_movie_card = movie_module.format_movie_card
search_movies_in_db = movie_module.search_movies_in_db
search_movies_by_person_in_db = movie_module.search_movies_by_person_in_db
get_premier_movies_from_db = movie_module.get_premier_movies_from_db

# Функции для работы с кэшем мнений
def get_cached_opinion(movie_id: int):
    """Получает мнение из кэша"""
    conn = db_module.get_opinions_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT full_opinion FROM movie_opinions WHERE movie_id = ?',
            (int(movie_id),)
        )
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Ошибка получения кэша: {e}")
        return None
    finally:
        conn.close()


def save_opinion_cache(movie_id: int, full_opinion: str):
    """Сохраняет мнение в кэш"""
    conn = db_module.get_opinions_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO movie_opinions 
            (movie_id, full_opinion, short_opinion, created_at)
            VALUES (?, ?, ?, ?)
        ''', (int(movie_id), full_opinion, '', datetime.now().isoformat()))
        conn.commit()
        logger.info(f"Мнение для фильма {movie_id} сохранено в кэш")
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша: {e}")
    finally:
        conn.close()


def load_config():
    config_path = os.path.join(BASE_DIR, 'config', 'config.ini')
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    return config


# Настройка DeepSeek
config = load_config()
DEEPSEEK_KEY = os.environ.get('OPENAI_API_KEY') or config.get('OpenAI', 'api_key', fallback='')
if DEEPSEEK_KEY:
    http_client = httpx.Client(timeout=60.0, follow_redirects=True)
    ai_client = OpenAI(
        api_key=DEEPSEEK_KEY,
        base_url=config.get('OpenAI', 'base_url', fallback='https://api.deepseek.com/v1'),
        http_client=http_client,
    )
    logger.info("✅ DeepSeek клиент инициализирован")
else:
    ai_client = None
    logger.warning("⚠️ OPENAI_API_KEY не найден, мнения не будут работать")


class MaxAdapter:
    def __init__(self):
        self.config = load_config()
        self.token = os.environ.get('MAX_TOKEN') or self.config.get('Max', 'token', fallback='')
        
        if not self.token:
            raise ValueError("MAX_TOKEN не найден!")
        
        self.bot = Bot(token=self.token)
        self.dp = Dispatcher()
        self.user_context = {}
        
        self._register_handlers()
        logger.info(f"✅ MaxAdapter инициализирован")
        logger.info(f"   Поддержка кнопок: {'Да' if HAS_KEYBOARD else 'Нет'}")
        logger.info(f"   DeepSeek: {'Доступен' if ai_client else 'Недоступен'}")
    
    def _register_handlers(self):
        @self.dp.bot_started()
        async def on_bot_started(event: BotStarted):
            await event.bot.send_message(
                chat_id=event.chat_id,
                text="🐾 Привет! Я КиноИщейка!\nНапиши /start"
            )
        
        @self.dp.message_created(Command("start"))
        async def on_start(event: MessageCreated):
            await self._handle_start(event)
        
        @self.dp.message_created(Command("random"))
        async def on_random(event: MessageCreated):
            await self._handle_random(event)
        
        @self.dp.message_created(Command("search"))
        async def on_search(event: MessageCreated):
            user_id = event.message.sender.user_id
            self.user_context[user_id] = {'state': 'awaiting_search'}
            await event.message.answer("🔍 Введи название фильма:")
        
        @self.dp.message_created(Command("premiers"))
        async def on_premiers(event: MessageCreated):
            await self._handle_premiers(event)
        
        @self.dp.message_created(Command("person"))
        async def on_person(event: MessageCreated):
            user_id = event.message.sender.user_id
            self.user_context[user_id] = {'state': 'awaiting_person'}
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")
        
        @self.dp.message_created(Command("profile"))
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)
        
        @self.dp.message_created(Command("opinion"))
        async def on_opinion(event: MessageCreated):
            await self._handle_opinion_command(event)
        
        @self.dp.message_created(Command("help"))
        async def on_help(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Команды:</b>\n\n"
                "/start — приветствие\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
                "/premiers — ожидаемые премьеры\n"
                "/person — поиск по актёрам/режиссёрам\n"
                "/opinion [название или ID] — мнение о фильме\n"
                "/profile — мой профиль\n"
                "/help — это сообщение",
                parse_mode="html"
            )
        
        @self.dp.message_created()
        async def on_message(event: MessageCreated):
            await self._handle_message(event)
    
    async def _handle_start(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        username = getattr(event.message.sender, 'username', '') or ''
        first_name = getattr(event.message.sender, 'first_name', '') or ''
        last_name = getattr(event.message.sender, 'last_name', '') or ''
        
        try:
            register_user(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                platform='max'
            )
            logger.info(f"✅ Пользователь {user_id} зарегистрирован")
        except Exception as e:
            logger.error(f"Ошибка регистрации: {e}")
        
        limits = get_user_limits(user_id)
        
        welcome_text = (
            f"🐾 <b>Гав! Я КиноИщейка!</b>\n\n"
            f"📊 <b>Твой тариф:</b> {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 <b>Мнений сегодня:</b> 0/{limits.get('opinion_limit', 3)}\n\n"
            f"👇 <b>Команды:</b>\n"
            f"• /random — случайный фильм\n"
            f"• /search — поиск по названию\n"
            f"• /premiers — ожидаемые премьеры\n"
            f"• /person — поиск по актёрам/режиссёрам\n"
            f"• /opinion [название] — мнение о фильме\n"
            f"• /profile — мой профиль\n"
            f"• /help — помощь"
        )
        
        await event.message.answer(welcome_text, parse_mode="html")
    
    async def _handle_random(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        await event.message.answer("🎲 Ищу случайный фильм...")
        
        movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
        if not movie_data:
            await event.message.answer("😢 Не нашла фильмов.")
            return
        
        movie_details = get_movie_details(movie_data['id'])
        if not movie_details:
            await event.message.answer("😢 Не могу найти информацию.")
            return
        
        card_text, _ = format_movie_card(movie_details)
        if card_text:
            await event.message.answer(card_text, parse_mode='html')
        else:
            await event.message.answer("😢 Не могу показать карточку.")
    
    async def _handle_premiers(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        await event.message.answer("🎉 Ищу ожидаемые премьеры...")
        
        premiers_list = get_premier_movies_from_db()
        if not premiers_list:
            await event.message.answer("😢 Сейчас нет ожидаемых премьер.")
            return
        
        for movie_data in premiers_list[:5]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    await event.message.answer(card_text, parse_mode='html')
        
        if len(premiers_list) > 5:
            await event.message.answer(f"🐾 Нашла {len(premiers_list)} премьер. Показаны первые 5.")
    
    async def _handle_profile(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        await event.message.answer(
            f"👤 <b>Твой профиль</b>\n\n"
            f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 Мнений сегодня: {stats.get('opinion_count', 0)}/{limits.get('opinion_limit', 3)}\n"
            f"🔄 Свежих взглядов: {stats.get('regeneration_count', 0)}/{limits.get('regeneration_limit', 2)}\n\n"
            f"🐾 Функция баланса косточек в разработке.",
            parse_mode="html"
        )
    
    async def _handle_opinion_command(self, event: MessageCreated):
        """Обработка команды /opinion [название или ID]"""
        user_id = event.message.sender.user_id
        text = event.message.body.text.replace('/opinion', '').strip()
        
        if not text:
            await event.message.answer(
                "🐾 Укажи фильм:\n"
                "• /opinion 435 — по ID Кинопоиска\n"
                "• /opinion Зеленая миля — по названию"
            )
            return
        
        # Проверяем лимиты
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        if stats['opinion_count'] >= limits['opinion_limit']:
            await event.message.answer(
                f"🐾 Сегодня я уже высказала {stats['opinion_count']} мнений из {limits['opinion_limit']}.\n"
                f"Лимит обновится завтра!\n\n"
                f"Хочешь больше? Подписка снимет ограничения (скоро)."
            )
            return
        
        # Ищем фильм
        movie_details = None
        
        # Пробуем как ID
        if text.isdigit():
            movie_details = get_movie_details(int(text))
        
        # Если не нашли — ищем по названию
        if not movie_details:
            movies = search_movies_in_db(text, min_rating=0.0, max_rating=10.0)
            if movies:
                movie_details = get_movie_details(movies[0]['id'])
        
        if not movie_details:
            await event.message.answer(f"😢 Не нашла фильм '{text}'. Проверь название или ID.")
            return
        
        movie_id = movie_details['id']
        movie_name = movie_details.get('name', 'Без названия')
        movie_year = movie_details.get('year', '')
        
        # Проверяем кэш
        cached_opinion = get_cached_opinion(movie_id)
        if cached_opinion:
            await event.message.answer(
                f"🐾 Я уже смотрела <b>{movie_name}</b> ({movie_year}), вот что думаю:\n\n"
                f"{cached_opinion}\n\n🐾"
            )
            # Увеличиваем счётчик
            increment_stat_counter(user_id, 'opinion_count')
            record_user_opinion(user_id, movie_id)
            return
        
        # Генерируем новое мнение
        await event.message.answer(f"🐾 Смотрю <b>{movie_name}</b> ({movie_year}) в ускоренном режиме... 🎬")
        
        if not ai_client:
            await event.message.answer("😢 Генерация мнений временно недоступна. Попробуй позже.")
            return
        
        try:
            opinion = await self._generate_opinion(movie_details)
            
            if opinion:
                # Сохраняем в кэш
                save_opinion_cache(movie_id, opinion)
                # Увеличиваем счётчик
                increment_stat_counter(user_id, 'opinion_count')
                record_user_opinion(user_id, movie_id)
                
                await event.message.answer(
                    f"🐾 Я посмотрела <b>{movie_name}</b> ({movie_year}), и вот что думаю:\n\n"
                    f"{opinion}\n\n🐾"
                )
            else:
                await event.message.answer("😢 Не удалось сгенерировать мнение. Попробуй позже.")
                
        except Exception as e:
            logger.error(f"Ошибка генерации мнения: {e}")
            await event.message.answer("🐾 Гав! Кажется, я перегрызла провод... Попробуй позже!")
    
    async def _generate_opinion(self, movie_details: dict) -> str:
        """Генерирует мнение о фильме через DeepSeek"""
        
        title = movie_details.get('name', 'Без названия')
        year = movie_details.get('year', '')
        
        countries = movie_details.get('countries', [])
        countries_str = ', '.join(countries) if countries else 'неизвестно'
        
        genres = movie_details.get('genres', [])
        genres_str = ', '.join(genres) if genres else 'неизвестно'
        
        directors_list = movie_details.get('directors', [])
        if directors_list:
            director_names = []
            for director in directors_list[:2]:
                name = director.get('name') or director.get('enName')
                if name:
                    director_names.append(name)
            directors_str = ', '.join(director_names)
        else:
            directors_str = 'неизвестен'
        
        actors_list = movie_details.get('actors', [])[:5]
        if actors_list:
            actor_names = []
            for actor in actors_list:
                name = actor.get('name') or actor.get('enName')
                if name:
                    actor_names.append(name)
            actors_str = ', '.join(actor_names)
        else:
            actors_str = 'не указаны'
        
        rating = movie_details.get('rating', 0)
        description = movie_details.get('description', 'Описание отсутствует')
        if description and len(description) > 600:
            description = description[:600] + '...'
        
        prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём на хорошее кино.
Говори о себе в женском роде, с юмором и энтузиазмом.

Информация о фильме:
🎬 Название: {title} ({year})
🌍 Страна: {countries_str}
🎭 Жанр: {genres_str}
🎥 Режиссер: {directors_str}
⭐ Рейтинг Кинопоиска: {rating}
👥 В главных ролях: {actors_str}

📝 Сюжет:
{description}

Требования:
1. 8-10 предложений, без markdown
2. Сразу начинай с содержательной части
3. Расскажи о настроении, смысле, плюсах и минусах
4. В конце обязательно:
   Оценка: X/10 (краткий комментарий)
   Настроение: #Тег1 #Тег2 #Тег3
   Атмосфера: #Тег1 #Тег2 #Тег3"""

        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Отвечай по-русски, дружелюбно, с юмором, в женском роде."},
                {"role": "user", "content": prompt}
            ],
            timeout=60,
        )
        
        return response.choices[0].message.content.strip()
    
    async def _handle_message(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        
        if not text:
            return
        
        context = self.user_context.get(user_id, {})
        state = context.get('state')
        
        if state == 'awaiting_search':
            await self._perform_search(event, user_id, text)
        elif state == 'awaiting_person':
            await self._perform_person_search(event, user_id, text)
        else:
            await event.message.answer("🐾 Я не понимаю эту команду.\n\nИспользуй /start для списка команд.")
    
    async def _perform_search(self, event: MessageCreated, user_id: int, query: str):
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return
        
        await event.message.answer(f"🔍 Ищу: {query}...")
        
        movies_list = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
        else:
            for movie_data in movies_list[:5]:
                movie_details = get_movie_details(movie_data['id'])
                if movie_details:
                    card_text, _ = format_movie_card(movie_details)
                    if card_text:
                        await event.message.answer(card_text, parse_mode='html')
            
            if len(movies_list) > 5:
                await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.\n\nДля мнения используй /opinion [название]")
        
        self.user_context.pop(user_id, None)
    
    async def _perform_person_search(self, event: MessageCreated, user_id: int, query: str):
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return
        
        await event.message.answer(f"🎭 Ищу фильмы с участием: {query}...")
        
        movies_list = search_movies_by_person_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
        else:
            for movie_data in movies_list[:5]:
                movie_details = get_movie_details(movie_data['id'])
                if movie_details:
                    card_text, _ = format_movie_card(movie_details, is_person_search=True, query=query)
                    if card_text:
                        await event.message.answer(card_text, parse_mode='html')
            
            if len(movies_list) > 5:
                await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.\n\nДля мнения используй /opinion [название]")
        
        self.user_context.pop(user_id, None)
    
    async def run(self):
        logger.info("🚀 MaxAdapter запущен")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

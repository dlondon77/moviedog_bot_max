# core/max_adapter.py — версия с правильно работающими кнопками!

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

logger = logging.getLogger(__name__)

from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart
from maxapi.types import BotStarted, MessageCreated, InlineKeyboardMarkup, InlineKeyboardButton
from openai import OpenAI
import httpx

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


def get_cached_opinion(movie_id: int):
    conn = db_module.get_opinions_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT full_opinion FROM movie_opinions WHERE movie_id = ?', (int(movie_id),))
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Ошибка получения кэша: {e}")
        return None
    finally:
        conn.close()


def save_opinion_cache(movie_id: int, full_opinion: str):
    conn = db_module.get_opinions_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO movie_opinions (movie_id, full_opinion, short_opinion, created_at)
            VALUES (?, ?, ?, ?)
        ''', (int(movie_id), full_opinion, '', datetime.now().isoformat()))
        conn.commit()
        logger.info(f"Мнение для фильма {movie_id} сохранено")
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша: {e}")
    finally:
        conn.close()


def load_config():
    config_path = os.path.join(BASE_DIR, 'config', 'config.ini')
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    return config


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
    logger.warning("⚠️ OPENAI_API_KEY не найден")


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
        logger.info(f"✅ MaxAdapter инициализирован с поддержкой кнопок!")
    
    def _register_handlers(self):
        # Обработчик нажатия "Начать"
        @self.dp.bot_started()
        async def on_bot_started(event: BotStarted):
            await self.bot.send_message(
                chat_id=event.chat_id,
                text="🐾 Привет! Я КиноИщейка!\nНапиши /start"
            )
        
        # Обработчик /start с клавиатурой
        @self.dp.message_created(CommandStart())
        async def on_start(event: MessageCreated):
            await self._handle_start(event)
        
        # Обработчик команды /random
        @self.dp.message_created(F.message.body.text == "/random")
        async def on_random(event: MessageCreated):
            await self._handle_random(event)
        
        # Обработчик команды /search
        @self.dp.message_created(F.message.body.text == "/search")
        async def on_search(event: MessageCreated):
            user_id = event.message.sender.user_id
            self.user_context[user_id] = {'state': 'awaiting_search'}
            await event.message.answer("🔍 Введи название фильма:")
        
        # Обработчик команды /premiers
        @self.dp.message_created(F.message.body.text == "/premiers")
        async def on_premiers(event: MessageCreated):
            await self._handle_premiers(event)
        
        # Обработчик команды /person
        @self.dp.message_created(F.message.body.text == "/person")
        async def on_person(event: MessageCreated):
            user_id = event.message.sender.user_id
            self.user_context[user_id] = {'state': 'awaiting_person'}
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")
        
        # Обработчик команды /profile
        @self.dp.message_created(F.message.body.text == "/profile")
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)
        
        # Обработчик команды /opinion
        @self.dp.message_created(F.message.body.text.startswith("/opinion"))
        async def on_opinion(event: MessageCreated):
            await self._handle_opinion_command(event)
        
        # Обработчик команды /help
        @self.dp.message_created(F.message.body.text == "/help")
        async def on_help(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Команды:</b>\n\n"
                "/start — главное меню\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
                "/premiers — ожидаемые премьеры\n"
                "/person — поиск по актёрам\n"
                "/opinion [название] — мнение о фильме\n"
                "/profile — мой профиль\n"
                "/help — это сообщение",
                parse_mode="html"
            )
        
        # 👇 ГЛАВНОЕ: Обработчик нажатий на инлайн-кнопки!
        @self.dp.message_callback()
        async def on_callback(event):
            await self._handle_callback(event)
        
        # Обработчик обычных сообщений
        @self.dp.message_created(F.message.body.text)
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
        
        # Клавиатура с кнопками!
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Случайный фильм", callback_data="random")],
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")],
            [InlineKeyboardButton(text="🎉 Премьеры", callback_data="premiers")],
            [InlineKeyboardButton(text="🎭 Поиск по актёрам", callback_data="person")],
            [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
            [InlineKeyboardButton(text="🐾 Мнение о фильме", callback_data="opinion_prompt")],
        ])
        
        await event.message.answer(
            f"🐾 <b>Гав! Я КиноИщейка!</b>\n\n"
            f"📊 <b>Твой тариф:</b> {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 <b>Мнений сегодня:</b> 0/{limits.get('opinion_limit', 3)}\n\n"
            f"👇 <b>Выбери действие:</b>",
            parse_mode="html",
            reply_markup=keyboard  # ← кнопки!
        )
    
    async def _handle_callback(self, event):
        """Обработка нажатий на кнопки"""
        payload = event.callback.payload
        user_id = event.callback.user.id
        logger.info(f"Callback от {user_id}: {payload}")
        
        if payload == "random":
            # Отвечаем на callback
            await event.callback.answer()
            # Имитируем команду /random
            class MockMessage:
                sender = event.callback.user
                async def answer(self, text, **kwargs):
                    await self.bot.send_message(chat_id=user_id, text=text, **kwargs)
            mock_event = type('obj', (object,), {'message': MockMessage()})()
            await self._handle_random(mock_event)
        
        elif payload == "search":
            await event.callback.answer()
            self.user_context[user_id] = {'state': 'awaiting_search'}
            await self.bot.send_message(chat_id=user_id, text="🔍 Введи название фильма:")
        
        elif payload == "premiers":
            await event.callback.answer()
            await self._handle_premiers_mock(user_id)
        
        elif payload == "person":
            await event.callback.answer()
            self.user_context[user_id] = {'state': 'awaiting_person'}
            await self.bot.send_message(chat_id=user_id, text="🎭 Введи имя актёра или режиссёра:")
        
        elif payload == "profile":
            await event.callback.answer()
            await self._handle_profile_mock(user_id)
        
        elif payload == "opinion_prompt":
            await event.callback.answer()
            self.user_context[user_id] = {'state': 'awaiting_opinion'}
            await self.bot.send_message(chat_id=user_id, text="🐾 Введи ID или название фильма:")
        
        elif payload.startswith("opinion_"):
            await event.callback.answer()
            movie_id = int(payload.split("_")[1])
            await self._send_opinion_by_id(user_id, movie_id)
    
    async def _handle_random(self, event: MessageCreated):
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
            # Кнопка под карточкой
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🐾 Мнение о фильме", callback_data=f"opinion_{movie_details['id']}")]
            ])
            await event.message.answer(card_text, parse_mode='html', reply_markup=keyboard)
        else:
            await event.message.answer("😢 Не могу показать карточку.")
    
    async def _handle_premiers(self, event: MessageCreated):
        await self._send_premiers(event.message.answer)
    
    async def _handle_premiers_mock(self, user_id: int):
        await self._send_premiers(lambda text, **kwargs: self.bot.send_message(chat_id=user_id, text=text, **kwargs))
    
    async def _send_premiers(self, send_func):
        await send_func("🎉 Ищу ожидаемые премьеры...")
        
        premiers_list = get_premier_movies_from_db()
        if not premiers_list:
            await send_func("😢 Сейчас нет ожидаемых премьер.")
            return
        
        for movie_data in premiers_list[:5]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🐾 Мнение о фильме", callback_data=f"opinion_{movie_details['id']}")]
                    ])
                    await send_func(card_text, parse_mode='html', reply_markup=keyboard)
        
        if len(premiers_list) > 5:
            await send_func(f"🐾 Нашла {len(premiers_list)} премьер. Показаны первые 5.")
    
    async def _handle_profile(self, event: MessageCreated):
        await self._send_profile(event.message.answer, event.message.sender.user_id)
    
    async def _handle_profile_mock(self, user_id: int):
        await self._send_profile(lambda text, **kwargs: self.bot.send_message(chat_id=user_id, text=text, **kwargs), user_id)
    
    async def _send_profile(self, send_func, user_id: int):
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        await send_func(
            f"👤 <b>Твой профиль</b>\n\n"
            f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 Мнений сегодня: {stats.get('opinion_count', 0)}/{limits.get('opinion_limit', 3)}\n"
            f"🔄 Свежих взглядов: {stats.get('regeneration_count', 0)}/{limits.get('regeneration_limit', 2)}\n\n"
            f"🐾 Функция баланса косточек в разработке.",
            parse_mode="html"
        )
    
    async def _handle_opinion_command(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text.replace('/opinion', '').strip()
        
        if not text:
            await event.message.answer(
                "🐾 Укажи фильм:\n"
                "• /opinion 435 — по ID Кинопоиска\n"
                "• /opinion Зеленая миля — по названию"
            )
            return
        
        await self._process_opinion(user_id, text, event.message.answer)
    
    async def _send_opinion_by_id(self, user_id: int, movie_id: int):
        await self._process_opinion(user_id, str(movie_id), lambda text, **kwargs: self.bot.send_message(chat_id=user_id, text=text, **kwargs))
    
    async def _process_opinion(self, user_id: int, query: str, send_func):
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        if stats['opinion_count'] >= limits['opinion_limit']:
            await send_func(
                f"🐾 Сегодня я уже высказала {stats['opinion_count']} мнений из {limits['opinion_limit']}.\n"
                f"Лимит обновится завтра!"
            )
            return
        
        movie_details = None
        
        if query.isdigit():
            movie_details = get_movie_details(int(query))
        
        if not movie_details:
            movies = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)
            if movies:
                movie_details = get_movie_details(movies[0]['id'])
        
        if not movie_details:
            await send_func(f"😢 Не нашла фильм '{query}'. Проверь название или ID.")
            return
        
        movie_id = movie_details['id']
        movie_name = movie_details.get('name', 'Без названия')
        movie_year = movie_details.get('year', '')
        
        cached_opinion = get_cached_opinion(movie_id)
        if cached_opinion:
            await send_func(
                f"🐾 Я уже смотрела <b>{movie_name}</b> ({movie_year}), вот что думаю:\n\n"
                f"{cached_opinion}\n\n🐾",
                parse_mode="html"
            )
            increment_stat_counter(user_id, 'opinion_count')
            record_user_opinion(user_id, movie_id)
            return
        
        await send_func(f"🐾 Смотрю <b>{movie_name}</b> ({movie_year}) в ускоренном режиме... 🎬", parse_mode="html")
        
        if not ai_client:
            await send_func("😢 Генерация мнений временно недоступна.")
            return
        
        try:
            opinion = await self._generate_opinion(movie_details)
            if opinion:
                save_opinion_cache(movie_id, opinion)
                increment_stat_counter(user_id, 'opinion_count')
                record_user_opinion(user_id, movie_id)
                await send_func(
                    f"🐾 Я посмотрела <b>{movie_name}</b> ({movie_year}), и вот что думаю:\n\n"
                    f"{opinion}\n\n🐾",
                    parse_mode="html"
                )
            else:
                await send_func("😢 Не удалось сгенерировать мнение.")
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            await send_func("🐾 Гав! Что-то пошло не так. Попробуй позже!")
    
    async def _generate_opinion(self, movie_details: dict) -> str:
        title = movie_details.get('name', 'Без названия')
        year = movie_details.get('year', '')
        countries = ', '.join(movie_details.get('countries', [])) or 'неизвестно'
        genres = ', '.join(movie_details.get('genres', [])) or 'неизвестно'
        
        directors = movie_details.get('directors', [])
        directors_str = ', '.join([d.get('name') or d.get('enName') for d in directors[:2]]) or 'неизвестен'
        
        actors = movie_details.get('actors', [])[:5]
        actors_str = ', '.join([a.get('name') or a.get('enName') for a in actors]) or 'не указаны'
        
        rating = movie_details.get('rating', 0)
        description = movie_details.get('description', 'Описание отсутствует')[:600]
        
        prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик.
Говори о себе в женском роде, с юмором.

Фильм: {title} ({year})
Страна: {countries}
Жанр: {genres}
Режиссер: {directors_str}
Актеры: {actors_str}
Рейтинг: {rating}

Сюжет: {description}

Напиши мнение (8-10 предложений). В конце:
Оценка: X/10 (комментарий)
Настроение: #теги
Атмосфера: #теги"""

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
        elif state == 'awaiting_opinion':
            await self._process_opinion(user_id, text, event.message.answer)
            self.user_context.pop(user_id, None)
        else:
            await event.message.answer("🐾 Я не понимаю эту команду.\n\nИспользуй /start для меню.")
    
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
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🐾 Мнение о фильме", callback_data=f"opinion_{movie_details['id']}")]
                        ])
                        await event.message.answer(card_text, parse_mode='html', reply_markup=keyboard)
            
            if len(movies_list) > 5:
                await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.")
        
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
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🐾 Мнение о фильме", callback_data=f"opinion_{movie_details['id']}")]
                        ])
                        await event.message.answer(card_text, parse_mode='html', reply_markup=keyboard)
            
            if len(movies_list) > 5:
                await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.")
        
        self.user_context.pop(user_id, None)
    
    async def run(self):
        logger.info("🚀 MaxAdapter запущен с поддержкой кнопок!")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

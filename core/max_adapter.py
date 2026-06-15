# core/max_adapter.py
"""
Адаптер для платформы Max
По аналогии с VKAdapter, но для мессенджера Max
"""

import logging
import configparser
import os
import sys
from datetime import datetime

# Добавляем корневую директорию в путь
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Импорты из maxapi
from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated

# Импорты клавиатуры (если есть в вашей версии)
try:
    from maxapi import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    # Заглушки, если клавиатура не поддерживается
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
    
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

# Импорты из core (теперь работают благодаря __init__.py)
from core import user, movie, db
from core.user import register_user, get_user_limits, get_user_stats, increment_stat_counter
from core.movie import (
    get_random_movie_from_db, 
    get_movie_details, 
    format_movie_card,
    search_movies_in_db,
    search_movies_by_person_in_db,
    get_premier_movies_from_db
)

logger = logging.getLogger(__name__)


def load_config():
    """Загружает конфигурацию как в TG-версии"""
    config_path = os.path.join(BASE_DIR, 'config', 'config.ini')
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    return config


class MaxAdapter:
    """Адаптер для Max — обрабатывает события и вызывает core-функции"""
    
    def __init__(self):
        self.config = load_config()
        
        # Токен из переменной окружения или конфига
        self.token = os.environ.get('MAX_TOKEN') or self.config.get('Max', 'token', fallback='')
        
        if not self.token:
            raise ValueError("MAX_TOKEN не найден! Проверь config.ini или переменную окружения")
        
        # Пути к БД
        self.db_path = os.path.join(BASE_DIR, self.config.get('Data', 'db_path', fallback='./data/opinions.db'))
        self.movies_db_path = os.path.join(BASE_DIR, self.config.get('Data', 'movies_db_path', fallback='./data/movies.db'))
        
        # Инициализация бота
        self.bot = Bot(token=self.token)
        self.dp = Dispatcher()
        self.user_context = {}  # {user_id: {state, query, movies, page, ...}}
        
        # Регистрируем обработчики
        self._register_handlers()
        
        logger.info(f"✅ MaxAdapter инициализирован")
        logger.info(f"   Token: {self.token[:10]}...")
        logger.info(f"   DB: {self.db_path}")
    
    def _register_handlers(self):
        """Регистрирует все обработчики в диспетчере Max"""
        
        @self.dp.bot_started()
        async def on_bot_started(event: BotStarted):
            await self._handle_bot_started(event)
        
        @self.dp.message_created(Command("start"))
        async def on_start(event: MessageCreated):
            await self._handle_start(event)
        
        @self.dp.message_created(Command("random"))
        async def on_random(event: MessageCreated):
            await self._handle_random(event)
        
        @self.dp.message_created(Command("search"))
        async def on_search(event: MessageCreated):
            await self._handle_search_prompt(event)
        
        @self.dp.message_created(Command("premiers"))
        async def on_premiers(event: MessageCreated):
            await self._handle_premiers(event)
        
        @self.dp.message_created(Command("person"))
        async def on_person(event: MessageCreated):
            await self._handle_person_prompt(event)
        
        @self.dp.message_created(Command("profile"))
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)
        
        @self.dp.message_created(Command("help"))
        async def on_help(event: MessageCreated):
            await self._handle_help(event)
        
        @self.dp.message_created()
        async def on_message(event: MessageCreated):
            await self._handle_message(event)
        
        @self.dp.callback_query()
        async def on_callback(event):
            await self._handle_callback(event)
    
    # ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================
    
    async def _handle_bot_started(self, event: BotStarted):
        """При нажатии 'Начать' — отправляем приветствие"""
        await event.bot.send_message(
            chat_id=event.chat_id,
            text="🐾 Привет! Я КиноИщейка!\nНапиши /start чтобы начать работу"
        )
    
    async def _handle_start(self, event: MessageCreated):
        """Команда /start — регистрация пользователя и главное меню"""
        user_id = event.message.sender.user_id
        username = getattr(event.message.sender, 'username', '') or ''
        first_name = getattr(event.message.sender, 'first_name', '') or ''
        last_name = getattr(event.message.sender, 'last_name', '') or ''
        
        # Регистрируем пользователя с platform='max'
        try:
            register_user(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                platform='max'
            )
            logger.info(f"✅ Пользователь {user_id} зарегистрирован на платформе max")
        except Exception as e:
            logger.error(f"Ошибка регистрации пользователя {user_id}: {e}")
        
        # Получаем лимиты пользователя
        limits = get_user_limits(user_id)
        
        # Создаём клавиатуру
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎲 Случайный фильм", callback_data="random")],
                [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")],
                [InlineKeyboardButton(text="🎉 Премьеры", callback_data="premiers")],
                [InlineKeyboardButton(text="👤 Поиск по актёрам", callback_data="person")],
                [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
                [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
            ])
            reply_markup = keyboard
        except Exception as e:
            logger.warning(f"Клавиатура не поддерживается: {e}")
            reply_markup = None
        
        welcome_text = (
            f"🐾 <b>Гав! Я КиноИщейка!</b>\n\n"
            f"Я помогаю находить отличные фильмы и делюсь своим мнением о них.\n\n"
            f"📊 <b>Твой тариф:</b> {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 <b>Мнений сегодня:</b> 0/{limits.get('opinion_limit', 3)}\n\n"
            f"👇 <b>Доступные команды:</b>\n"
            f"• /random — случайный фильм\n"
            f"• /search — поиск по названию\n"
            f"• /premiers — ожидаемые премьеры\n"
            f"• /person — поиск по актёрам/режиссёрам\n"
            f"• /profile — мой профиль\n"
            f"• /help — помощь\n\n"
            f"🎬 Нажми на кнопку или введи команду!"
        )
        
        await event.message.answer(
            welcome_text,
            parse_mode="html",
            reply_markup=reply_markup
        )
    
    async def _handle_random(self, event: MessageCreated):
        """Случайный фильм"""
        await event.message.answer("🎲 Ищу случайный фильм...")
        
        movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
        
        if not movie_data:
            await event.message.answer("😢 Не нашла фильмов. Попробуй позже.")
            return
        
        movie_details = get_movie_details(movie_data['id'])
        if not movie_details:
            await event.message.answer("😢 Не могу найти информацию о фильме.")
            return
        
        card_text, reply_markup = format_movie_card(movie_details)
        
        if card_text:
            await event.message.answer(card_text, parse_mode='html', reply_markup=reply_markup)
        else:
            await event.message.answer("😢 Не могу показать карточку фильма.")
    
    async def _handle_search_prompt(self, event: MessageCreated):
        """Запрашивает название фильма для поиска"""
        user_id = event.message.sender.user_id
        self.user_context[user_id] = {'state': 'awaiting_search'}
        await event.message.answer("🔍 Введи название фильма для поиска:")
    
    async def _handle_search(self, event: MessageCreated, query: str):
        """Поиск фильмов по названию"""
        user_id = event.message.sender.user_id
        
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа для поиска.")
            return
        
        await event.message.answer(f"🔍 Ищу: {query}...")
        
        # Ищем фильмы
        movies_list = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)
        
        if not movies_list:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
            return
        
        # Сохраняем в контекст
        self.user_context[user_id] = {
            'state': 'search',
            'query': query,
            'movies': movies_list,
            'page': 0
        }
        
        await self._show_movies_page(event, user_id, 0)
    
    async def _show_movies_page(self, event: MessageCreated, user_id: int, page: int):
        """Показывает страницу с фильмами (по 5 штук)"""
        context = self.user_context.get(user_id, {})
        movies_list = context.get('movies', [])
        query = context.get('query', '')
        
        if not movies_list:
            await event.message.answer("😢 Нет фильмов для показа.")
            return
        
        items_per_page = 5
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies_list))
        
        # Отправляем заголовок
        await event.message.answer(
            f"📽 <b>Результаты поиска \"{query}\"</b>\n"
            f"Страница {page+1} из {total_pages}\n"
            f"Показаны фильмы {start_idx+1}-{end_idx}",
            parse_mode="html"
        )
        
        # Отправляем фильмы
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, reply_markup = format_movie_card(movie_details)
                if card_text:
                    await event.message.answer(card_text, parse_mode='html', reply_markup=reply_markup)
        
        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data=f"movies_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Следующая ➡️", callback_data=f"movies_page_{page+1}"))
        
        if nav_buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
            await event.message.answer("👇 Навигация:", reply_markup=keyboard)
    
    async def _handle_premiers(self, event: MessageCreated):
        """Ожидаемые премьеры"""
        user_id = event.message.sender.user_id
        
        await event.message.answer("🎉 Ищу ожидаемые премьеры...")
        
        premiers_list = get_premier_movies_from_db()
        
        if not premiers_list:
            await event.message.answer("😢 Сейчас нет ожидаемых премьер.")
            return
        
        self.user_context[user_id] = {
            'state': 'premiers',
            'movies': premiers_list,
            'page': 0
        }
        
        await self._show_premiers_page(event, user_id, 0)
    
    async def _show_premiers_page(self, event: MessageCreated, user_id: int, page: int):
        """Показывает страницу с премьерами"""
        context = self.user_context.get(user_id, {})
        movies_list = context.get('movies', [])
        
        if not movies_list:
            await event.message.answer("😢 Нет премьер для показа.")
            return
        
        items_per_page = 5
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies_list))
        
        await event.message.answer(
            f"🎉 <b>Ожидаемые премьеры</b>\n"
            f"Страница {page+1} из {total_pages}",
            parse_mode="html"
        )
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, reply_markup = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    await event.message.answer(card_text, parse_mode='html', reply_markup=reply_markup)
        
        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data=f"premiers_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Следующая ➡️", callback_data=f"premiers_page_{page+1}"))
        
        if nav_buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
            await event.message.answer("👇 Навигация:", reply_markup=keyboard)
    
    async def _handle_person_prompt(self, event: MessageCreated):
        """Запрашивает имя актёра или режиссёра"""
        user_id = event.message.sender.user_id
        self.user_context[user_id] = {'state': 'awaiting_person'}
        await event.message.answer("🎭 Введи имя актёра или режиссёра для поиска:")
    
    async def _handle_person_search(self, event: MessageCreated, query: str):
        """Поиск фильмов по актёрам/режиссёрам"""
        user_id = event.message.sender.user_id
        
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа для поиска.")
            return
        
        await event.message.answer(f"🎭 Ищу фильмы с участием: {query}...")
        
        movies_list = search_movies_by_person_in_db(query, min_rating=0.0, max_rating=10.0)
        
        if not movies_list:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
            return
        
        self.user_context[user_id] = {
            'state': 'person_search',
            'query': query,
            'movies': movies_list,
            'page': 0
        }
        
        await self._show_movies_page(event, user_id, 0)
    
    async def _handle_profile(self, event: MessageCreated):
        """Профиль пользователя"""
        user_id = event.message.sender.user_id
        limits = get_user_limits(user_id)
        
        await event.message.answer(
            f"👤 <b>Твой профиль</b>\n\n"
            f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 Мнений в сутки: {limits.get('opinion_limit', 3)}\n"
            f"🔄 Свежих взглядов: {limits.get('regeneration_limit', 2)}\n\n"
            f"🐾 Функция в разработке. Скоро здесь будет:\n"
            f"• Баланс косточек\n"
            f"• Любимые фильмы\n"
            f"• История поиска",
            parse_mode="html"
        )
    
    async def _handle_help(self, event: MessageCreated):
        """Помощь"""
        help_text = (
            "❓ <b>Помощь по командам</b>\n\n"
            "🎲 /random — случайный фильм\n"
            "🔍 /search — поиск по названию\n"
            "🎉 /premiers — ожидаемые премьеры\n"
            "🎭 /person — поиск по актёрам/режиссёрам\n"
            "👤 /profile — мой профиль\n"
            "❓ /help — это сообщение\n\n"
            "🐾 <b>Скоро появится:</b>\n"
            "• Мнение о фильме (через AI)\n"
            "• Платные подписки и косточки"
        )
        await event.message.answer(help_text, parse_mode="html")
    
    async def _handle_message(self, event: MessageCreated):
        """Обработка обычных текстовых сообщений"""
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        
        if not text:
            return
        
        # Проверяем состояние пользователя
        if user_id in self.user_context:
            state = self.user_context[user_id].get('state')
            
            if state == 'awaiting_search':
                await self._handle_search(event, text)
                return
            elif state == 'awaiting_person':
                await self._handle_person_search(event, text)
                return
        
        # Если не в режиме ожидания — отправляем в меню
        await event.message.answer(
            "🐾 Я не понимаю эту команду.\n\n"
            "Используй /start для списка команд или /help для помощи."
        )
    
    async def _handle_callback(self, event):
        """Обработка нажатий на инлайн-кнопки"""
        data = event.payload
        user_id = event.sender.user_id
        
        logger.info(f"Callback от {user_id}: {data}")
        
        # Создаём mock-событие для ответа
        class MockSender:
            user_id = user_id
        
        class MockMessage:
            sender = MockSender()
            async def answer(self, text, **kwargs):
                await event.bot.send_message(chat_id=event.chat.chat_id, text=text, **kwargs)
        
        mock_event = type('obj', (object,), {'message': MockMessage()})()
        
        # Обработка команд
        if data == "random":
            await self._handle_random(mock_event)
        
        elif data == "search":
            await self._handle_search_prompt(mock_event)
        
        elif data == "premiers":
            await self._handle_premiers(mock_event)
        
        elif data == "person":
            await self._handle_person_prompt(mock_event)
        
        elif data == "profile":
            await self._handle_profile(mock_event)
        
        elif data == "help":
            await self._handle_help(mock_event)
        
        elif data.startswith("movies_page_"):
            page = int(data.split("_")[2])
            await self._show_movies_page(mock_event, user_id, page)
        
        elif data.startswith("premiers_page_"):
            page = int(data.split("_")[2])
            await self._show_premiers_page(mock_event, user_id, page)
    
    # ==================== ЗАПУСК ====================
    
    async def run(self):
        """Запуск бота"""
        logger.info("🚀 MaxAdapter запущен, ожидаем сообщения...")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)

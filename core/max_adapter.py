# core/max_adapter.py
import logging
import configparser
import os
import sys

# Добавляем корневую директорию в путь
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Импорты из maxapi
from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated

# Пытаемся импортировать клавиатуру (если есть в вашей версии)
try:
    from maxapi import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    # Если нет — создаём заглушки
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
    
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

# Импорты из core (исправлено — импортируем модули по отдельности)
import core.user as user_module
import core.movie as movie_module
import core.db as db_module

# Для удобства создаём алиасы
register_user = user_module.register_user
get_user_limits = user_module.get_user_limits
get_user_stats = user_module.get_user_stats

get_random_movie_from_db = movie_module.get_random_movie_from_db
get_movie_details = movie_module.get_movie_details
format_movie_card = movie_module.format_movie_card

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
        
        # Создаём клавиатуру (если поддерживается)
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎲 Случайный фильм", callback_data="random")],
                [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")],
                [InlineKeyboardButton(text="🎉 Премьеры", callback_data="premiers")],
                [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
            ])
            reply_markup = keyboard
        except Exception as e:
            logger.warning(f"Клавиатура не поддерживается: {e}")
            reply_markup = None
        
        # Приветственное сообщение
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
            f"• /profile — мой профиль\n\n"
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
        
        # Форматируем карточку
        card_text, reply_markup = format_movie_card(movie_details)
        
        if card_text:
            await event.message.answer(card_text, parse_mode='html', reply_markup=reply_markup)
        else:
            await event.message.answer("😢 Не могу показать карточку фильма.")
    
    async def _handle_message(self, event: MessageCreated):
        """Обработка обычных текстовых сообщений"""
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        
        if not text:
            return
        
        # Проверяем, ждём ли поиск
        if user_id in self.user_context and self.user_context[user_id].get('state') == 'awaiting_search':
            await self._handle_search(event, text)
            return
        
        # Иначе — отправляем в меню
        await event.message.answer(
            "🐾 Я не понимаю эту команду.\n\n"
            "Используй /start для списка команд или /search для поиска фильмов."
        )
    
    async def _handle_search(self, event: MessageCreated, query: str):
        """Поиск фильмов (будет реализован позже)"""
        await event.message.answer(f"🔍 Ищу: {query}\n\n(Поиск будет добавлен в следующей части)")
    
    async def _handle_callback(self, event):
        """Обработка нажатий на инлайн-кнопки"""
        data = event.payload
        user_id = event.sender.user_id
        
        logger.info(f"Callback от {user_id}: {data}")
        
        if data == "random":
            # Создаём mock-событие для _handle_random
            class MockSender:
                user_id = user_id
            
            class MockMessage:
                sender = MockSender()
                async def answer(self, text, **kwargs):
                    await event.bot.send_message(chat_id=event.chat.chat_id, text=text, **kwargs)
            
            mock_event = type('obj', (object,), {'message': MockMessage()})()
            await self._handle_random(mock_event)
        
        elif data == "search":
            self.user_context[user_id] = {'state': 'awaiting_search'}
            await event.bot.send_message(
                chat_id=event.chat.chat_id,
                text="🔍 Введи название фильма для поиска:"
            )
        
        elif data == "premiers":
            await event.bot.send_message(
                chat_id=event.chat.chat_id,
                text="🎉 Премьеры будут добавлены в следующей части!"
            )
        
        elif data == "profile":
            limits = get_user_limits(user_id)
            await event.bot.send_message(
                chat_id=event.chat.chat_id,
                text=(
                    f"👤 <b>Твой профиль</b>\n\n"
                    f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
                    f"🎬 Мнений в сутки: {limits.get('opinion_limit', 3)}\n\n"
                    f"🐾 Функция в разработке. Скоро здесь будет:\n"
                    f"• Баланс косточек\n"
                    f"• Любимые фильмы\n"
                    f"• История поиска"
                ),
                parse_mode="html"
            )
    
    # ==================== ЗАПУСК ====================
    
    async def run(self):
        """Запуск бота"""
        logger.info("🚀 MaxAdapter запущен, ожидаем сообщения...")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)

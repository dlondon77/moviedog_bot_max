# core/max_adapter.py
import logging
import configparser
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(BASE_DIR, 'core')

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated

try:
    from maxapi import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

import user as user_module
import movie as movie_module

register_user = user_module.register_user
get_user_limits = user_module.get_user_limits
get_random_movie_from_db = movie_module.get_random_movie_from_db
get_movie_details = movie_module.get_movie_details
format_movie_card = movie_module.format_movie_card
search_movies_in_db = movie_module.search_movies_in_db

logger = logging.getLogger(__name__)

def load_config():
    config_path = os.path.join(BASE_DIR, 'config', 'config.ini')
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    return config

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
        logger.info(f"✅ MaxAdapter инициализирован, Token: {self.token[:10]}...")
    
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
        
        @self.dp.message_created(Command("help"))
        async def on_help(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Команды:</b>\n\n"
                "/start — приветствие\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
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
            f"• /help — помощь"
        )
        await event.message.answer(welcome_text, parse_mode="html")
    
    async def _handle_random(self, event: MessageCreated):
        await event.message.answer("🎲 Ищу случайный фильм...")
        
        movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
        
        if not movie_data:
            await event.message.answer("😢 Не нашла фильмов. Попробуй позже.")
            return
        
        movie_details = get_movie_details(movie_data['id'])
        if not movie_details:
            await event.message.answer("😢 Не могу найти информацию о фильме.")
            return
        
        card_text, _ = format_movie_card(movie_details)
        
        if card_text:
            await event.message.answer(card_text, parse_mode='html')
        else:
            await event.message.answer("😢 Не могу показать карточку.")
    
    async def _handle_message(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        
        if not text:
            return
        
        if user_id in self.user_context and self.user_context[user_id].get('state') == 'awaiting_search':
            query = text.strip()
            if len(query) < 2:
                await event.message.answer("🐾 Введи хотя бы 2 символа.")
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
                    await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.")
            
            self.user_context.pop(user_id, None)
    
    async def run(self):
        logger.info("🚀 MaxAdapter запущен")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)

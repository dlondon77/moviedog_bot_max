# core/max_adapter.py — рабочая версия + пробуем добавить кнопку

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

# Пробуем импортировать клавиатуру
try:
    from maxapi.types import InlineKeyboardMarkup, InlineKeyboardButton
    HAS_KEYBOARD = True
    logger.info("✅ InlineKeyboard поддерживается в maxapi")
except ImportError:
    # Создаём заглушки
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
    
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url
    HAS_KEYBOARD = False
    logger.warning("⚠️ InlineKeyboard НЕ поддерживается, используем заглушки")

import user as user_module
import movie as movie_module

register_user = user_module.register_user
get_user_limits = user_module.get_user_limits
get_random_movie_from_db = movie_module.get_random_movie_from_db
get_movie_details = movie_module.get_movie_details
format_movie_card = movie_module.format_movie_card
search_movies_in_db = movie_module.search_movies_in_db
search_movies_by_person_in_db = movie_module.search_movies_by_person_in_db
get_premier_movies_from_db = movie_module.get_premier_movies_from_db

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
        logger.info(f"✅ MaxAdapter инициализирован")
        logger.info(f"   Поддержка кнопок: {'Да' if HAS_KEYBOARD else 'Нет'}")
    
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
        
        @self.dp.message_created(Command("help"))
        async def on_help(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Команды:</b>\n\n"
                "/start — приветствие\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
                "/premiers — ожидаемые премьеры\n"
                "/person — поиск по актёрам/режиссёрам\n"
                "/profile — мой профиль\n"
                "/help — это сообщение",
                parse_mode="html"
            )
        
        # 👇 ПРОБУЕМ ОБРАБОТЧИК ДЛЯ КНОПОК (если поддерживается)
        if hasattr(self.dp, 'callback_query'):
            @self.dp.callback_query()
            async def on_callback(event):
                await self._handle_callback(event)
            logger.info("✅ Зарегистрирован обработчик callback_query")
        else:
            logger.warning("⚠️ callback_query не поддерживается в этой версии maxapi")
        
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
        
        # Пробуем отправить клавиатуру с кнопками
        keyboard = None
        if HAS_KEYBOARD:
            try:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎲 Случайный фильм", callback_data="random")],
                    [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")],
                    [InlineKeyboardButton(text="🎉 Премьеры", callback_data="premiers")],
                ])
            except Exception as e:
                logger.error(f"Ошибка создания клавиатуры: {e}")
                keyboard = None
        
        welcome_text = (
            f"🐾 <b>Гав! Я КиноИщейка!</b>\n\n"
            f"📊 <b>Твой тариф:</b> {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 <b>Мнений сегодня:</b> 0/{limits.get('opinion_limit', 3)}\n\n"
            f"👇 <b>Команды:</b>\n"
            f"• /random — случайный фильм\n"
            f"• /search — поиск по названию\n"
            f"• /premiers — ожидаемые премьеры\n"
            f"• /person — поиск по актёрам/режиссёрам\n"
            f"• /profile — мой профиль\n"
            f"• /help — помощь"
        )
        
        await event.message.answer(
            welcome_text,
            parse_mode="html",
            reply_markup=keyboard  # пробуем отправить с клавиатурой
        )
    
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
            # 👇 ПРОБУЕМ ДОБАВИТЬ КНОПКУ ПОД КАРТОЧКОЙ
            keyboard = None
            if HAS_KEYBOARD:
                try:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🐾 Мнение КиноИщейки", 
                            callback_data=f"opinion:{movie_details['id']}"
                        )]
                    ])
                except Exception as e:
                    logger.error(f"Ошибка создания кнопки мнения: {e}")
            
            await event.message.answer(
                card_text,
                parse_mode='html',
                reply_markup=keyboard
            )
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
                    # 👇 ТОЖЕ ДОБАВЛЯЕМ КНОПКУ
                    keyboard = None
                    if HAS_KEYBOARD:
                        try:
                            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(
                                    text="🐾 Мнение КиноИщейки", 
                                    callback_data=f"opinion:{movie_details['id']}"
                                )]
                            ])
                        except Exception:
                            pass
                    
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        reply_markup=keyboard
                    )
        
        if len(premiers_list) > 5:
            await event.message.answer(f"🐾 Нашла {len(premiers_list)} премьер. Показаны первые 5.")
    
    async def _handle_profile(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        limits = get_user_limits(user_id)
        
        await event.message.answer(
            f"👤 <b>Твой профиль</b>\n\n"
            f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 Мнений в сутки: {limits.get('opinion_limit', 3)}\n"
            f"🔄 Свежих взглядов: {limits.get('regeneration_limit', 2)}\n\n"
            f"🐾 Функция баланса косточек в разработке.",
            parse_mode="html"
        )
    
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
                        # 👇 ТОЖЕ КНОПКА
                        keyboard = None
                        if HAS_KEYBOARD:
                            try:
                                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(
                                        text="🐾 Мнение КиноИщейки", 
                                        callback_data=f"opinion:{movie_details['id']}"
                                    )]
                                ])
                            except Exception:
                                pass
                        
                        await event.message.answer(
                            card_text,
                            parse_mode='html',
                            reply_markup=keyboard
                        )
            
            if len(movies_list) > 5:
                await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.\n\nДля более точного поиска введи /search и уточни запрос.")
        
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
                        # 👇 ТОЖЕ КНОПКА
                        keyboard = None
                        if HAS_KEYBOARD:
                            try:
                                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(
                                        text="🐾 Мнение КиноИщейки", 
                                        callback_data=f"opinion:{movie_details['id']}"
                                    )]
                                ])
                            except Exception:
                                pass
                        
                        await event.message.answer(
                            card_text,
                            parse_mode='html',
                            reply_markup=keyboard
                        )
            
            if len(movies_list) > 5:
                await event.message.answer(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.\n\nДля более точного поиска введи /person и уточни запрос.")
        
        self.user_context.pop(user_id, None)
    
    # 👇 ОБРАБОТЧИК ДЛЯ НАЖАТИЙ НА КНОПКИ (экспериментальный)
    async def _handle_callback(self, event):
        """Обработчик нажатий на инлайн-кнопки"""
        try:
            # Пробуем получить данные из callback
            data = None
            if hasattr(event, 'payload'):
                data = event.payload
            elif hasattr(event, 'data'):
                data = event.data
            else:
                logger.warning(f"Не могу получить payload из callback: {dir(event)}")
                return
            
            user_id = event.sender.user_id if hasattr(event, 'sender') else event.user.id
            logger.info(f"Callback от {user_id}: {data}")
            
            if data and data.startswith("opinion:"):
                movie_id = data.split(":")[1]
                await event.message.answer(f"🐾 Мнение о фильме ID:{movie_id} — функция в разработке!")
            elif data == "random":
                await event.message.answer("🎲 Используй команду /random")
            elif data == "search":
                await event.message.answer("🔍 Используй команду /search")
            elif data == "premiers":
                await event.message.answer("🎉 Используй команду /premiers")
            else:
                await event.message.answer(f"🐾 Нажата кнопка: {data}")
                
        except Exception as e:
            logger.error(f"Ошибка в обработчике callback: {e}")
    
    async def run(self):
        logger.info("🚀 MaxAdapter запущен")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

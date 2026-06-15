# core/max_adapter.py
"""
Адаптер для Max с использованием библиотеки maxbot
Поддерживает инлайн-кнопки, callback'и и полную пагинацию
"""

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

from maxbot.bot import Bot
from maxbot.dispatcher import Dispatcher
from maxbot.types import (
    Message, 
    CallbackQuery,
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)

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
        
        self.bot = Bot(self.token)
        self.dp = Dispatcher(self.bot)
        self.user_context = {}  # {user_id: {'state': ..., 'query': ..., 'movies': ..., 'page': ...}}
        
        self._register_handlers()
        logger.info(f"✅ MaxAdapter (maxbot) инициализирован. Token: {self.token[:10]}...")
    
    def _register_handlers(self):
        """Регистрирует все обработчики"""
        
        # ===== КОМАНДЫ =====
        @self.dp.message(lambda m: m.text == "/start")
        async def on_start(message: Message):
            await self._handle_start(message)
        
        @self.dp.message(lambda m: m.text == "/random")
        async def on_random(message: Message):
            await self._handle_random(message)
        
        @self.dp.message(lambda m: m.text == "/search")
        async def on_search(message: Message):
            user_id = message.sender.id
            self.user_context[user_id] = {'state': 'awaiting_search'}
            await self.bot.send_message(
                chat_id=user_id,
                text="🔍 Введи название фильма для поиска:"
            )
        
        @self.dp.message(lambda m: m.text == "/premiers")
        async def on_premiers(message: Message):
            await self._handle_premiers(message)
        
        @self.dp.message(lambda m: m.text == "/person")
        async def on_person(message: Message):
            user_id = message.sender.id
            self.user_context[user_id] = {'state': 'awaiting_person'}
            await self.bot.send_message(
                chat_id=user_id,
                text="🎭 Введи имя актёра или режиссёра:"
            )
        
        @self.dp.message(lambda m: m.text == "/profile")
        async def on_profile(message: Message):
            await self._handle_profile(message)
        
        @self.dp.message(lambda m: m.text == "/help")
        async def on_help(message: Message):
            await self.bot.send_message(
                chat_id=message.sender.id,
                text=(
                    "❓ <b>Команды:</b>\n\n"
                    "/start — приветствие\n"
                    "/random — случайный фильм\n"
                    "/search — поиск по названию\n"
                    "/premiers — ожидаемые премьеры\n"
                    "/person — поиск по актёрам/режиссёрам\n"
                    "/profile — мой профиль\n"
                    "/help — это сообщение"
                ),
                parse_mode="html"
            )
        
        # ===== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ =====
        @self.dp.message()
        async def on_message(message: Message):
            await self._handle_message(message)
        
        # ===== ОБРАБОТЧИК НАЖАТИЙ НА КНОПКИ =====
        @self.dp.callback()
        async def on_callback(cb: CallbackQuery):
            await self._handle_callback(cb)
    
    # ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================
    
    async def _handle_start(self, message: Message):
        user_id = message.sender.id
        username = getattr(message.sender, 'username', '') or ''
        first_name = getattr(message.sender, 'first_name', '') or ''
        last_name = getattr(message.sender, 'last_name', '') or ''
        
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
        
        # Клавиатура с кнопками
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Случайный фильм", callback_data="random")],
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")],
            [InlineKeyboardButton(text="🎉 Премьеры", callback_data="premiers")],
            [InlineKeyboardButton(text="🎭 Поиск по актёрам", callback_data="person")],
            [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        ])
        
        welcome_text = (
            f"🐾 <b>Гав! Я КиноИщейка!</b>\n\n"
            f"📊 <b>Твой тариф:</b> {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 <b>Мнений сегодня:</b> 0/{limits.get('opinion_limit', 3)}\n\n"
            f"👇 <b>Нажми на кнопку:</b>"
        )
        
        await self.bot.send_message(
            chat_id=user_id,
            text=welcome_text,
            parse_mode="html",
            reply_markup=keyboard
        )
    
    async def _handle_random(self, message: Message):
        user_id = message.sender.id
        await self.bot.send_message(chat_id=user_id, text="🎲 Ищу случайный фильм...")
        
        movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
        if not movie_data:
            await self.bot.send_message(chat_id=user_id, text="😢 Не нашла фильмов.")
            return
        
        movie_details = get_movie_details(movie_data['id'])
        if not movie_details:
            await self.bot.send_message(chat_id=user_id, text="😢 Не могу найти информацию.")
            return
        
        card_text, _ = format_movie_card(movie_details)
        
        if card_text:
            # Кнопка для мнения
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🐾 Мнение КиноИщейки", 
                    callback_data=f"opinion:{movie_details['id']}"
                )]
            ])
            await self.bot.send_message(
                chat_id=user_id,
                text=card_text,
                parse_mode='html',
                reply_markup=keyboard
            )
        else:
            await self.bot.send_message(chat_id=user_id, text="😢 Не могу показать карточку.")
    
    async def _handle_premiers(self, message: Message):
        user_id = message.sender.id
        await self.bot.send_message(chat_id=user_id, text="🎉 Ищу ожидаемые премьеры...")
        
        premiers_list = get_premier_movies_from_db()
        if not premiers_list:
            await self.bot.send_message(chat_id=user_id, text="😢 Сейчас нет ожидаемых премьер.")
            return
        
        self.user_context[user_id] = {
            'state': 'premiers',
            'movies': premiers_list,
            'page': 0
        }
        await self._show_premiers_page(user_id)
    
    async def _show_premiers_page(self, user_id: int):
        context = self.user_context.get(user_id, {})
        movies_list = context.get('movies', [])
        page = context.get('page', 0)
        
        if not movies_list:
            await self.bot.send_message(chat_id=user_id, text="😢 Нет премьер для показа.")
            return
        
        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies_list))
        
        await self.bot.send_message(
            chat_id=user_id,
            text=f"🎉 <b>Ожидаемые премьеры</b>\nСтраница {page+1} из {total_pages}",
            parse_mode="html"
        )
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🐾 Мнение КиноИщейки", 
                            callback_data=f"opinion:{movie_details['id']}"
                        )]
                    ])
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=card_text,
                        parse_mode='html',
                        reply_markup=keyboard
                    )
        
        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"premiers_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"premiers_page_{page+1}"))
        
        if nav_buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
            await self.bot.send_message(
                chat_id=user_id,
                text="👇 Навигация:",
                reply_markup=keyboard
            )
    
    async def _handle_profile(self, message: Message):
        user_id = message.sender.id
        limits = get_user_limits(user_id)
        
        await self.bot.send_message(
            chat_id=user_id,
            text=(
                f"👤 <b>Твой профиль</b>\n\n"
                f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
                f"🎬 Мнений в сутки: {limits.get('opinion_limit', 3)}\n"
                f"🔄 Свежих взглядов: {limits.get('regeneration_limit', 2)}\n\n"
                f"🐾 Функция баланса косточек в разработке."
            ),
            parse_mode="html"
        )
    
    async def _handle_message(self, message: Message):
        user_id = message.sender.id
        text = message.text if message.text else ""
        
        if not text:
            return
        
        context = self.user_context.get(user_id, {})
        state = context.get('state')
        
        if state == 'awaiting_search':
            await self._perform_search(user_id, text)
        elif state == 'awaiting_person':
            await self._perform_person_search(user_id, text)
        else:
            await self.bot.send_message(
                chat_id=user_id,
                text="🐾 Я не понимаю эту команду.\n\nИспользуй /start для списка команд."
            )
    
    async def _perform_search(self, user_id: int, query: str):
        if len(query) < 2:
            await self.bot.send_message(chat_id=user_id, text="🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return
        
        await self.bot.send_message(chat_id=user_id, text=f"🔍 Ищу: {query}...")
        
        movies_list = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            await self.bot.send_message(chat_id=user_id, text=f"😢 По запросу '{query}' ничего не нашлось.")
        else:
            self.user_context[user_id] = {
                'state': 'search_results',
                'query': query,
                'movies': movies_list,
                'page': 0
            }
            await self._show_search_page(user_id)
        
        # Не удаляем контекст — он нужен для пагинации
    
    async def _show_search_page(self, user_id: int):
        context = self.user_context.get(user_id, {})
        movies_list = context.get('movies', [])
        query = context.get('query', '')
        page = context.get('page', 0)
        
        if not movies_list:
            await self.bot.send_message(chat_id=user_id, text="😢 Нет фильмов для показа.")
            return
        
        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies_list))
        
        await self.bot.send_message(
            chat_id=user_id,
            text=f"📽 <b>Результаты поиска \"{query}\"</b>\nСтраница {page+1} из {total_pages}",
            parse_mode="html"
        )
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details)
                if card_text:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🐾 Мнение КиноИщейки", 
                            callback_data=f"opinion:{movie_details['id']}"
                        )]
                    ])
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=card_text,
                        parse_mode='html',
                        reply_markup=keyboard
                    )
        
        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"search_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"search_page_{page+1}"))
        
        if nav_buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
            await self.bot.send_message(
                chat_id=user_id,
                text="👇 Навигация:",
                reply_markup=keyboard
            )
    
    async def _perform_person_search(self, user_id: int, query: str):
        if len(query) < 2:
            await self.bot.send_message(chat_id=user_id, text="🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return
        
        await self.bot.send_message(chat_id=user_id, text=f"🎭 Ищу фильмы с: {query}...")
        
        movies_list = search_movies_by_person_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            await self.bot.send_message(chat_id=user_id, text=f"😢 По запросу '{query}' ничего не нашлось.")
        else:
            self.user_context[user_id] = {
                'state': 'person_results',
                'query': query,
                'movies': movies_list,
                'page': 0
            }
            await self._show_person_page(user_id)
    
    async def _show_person_page(self, user_id: int):
        context = self.user_context.get(user_id, {})
        movies_list = context.get('movies', [])
        query = context.get('query', '')
        page = context.get('page', 0)
        
        if not movies_list:
            await self.bot.send_message(chat_id=user_id, text="😢 Нет фильмов для показа.")
            return
        
        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies_list))
        
        await self.bot.send_message(
            chat_id=user_id,
            text=f"🎭 <b>Фильмы с участием: {query}</b>\nСтраница {page+1} из {total_pages}",
            parse_mode="html"
        )
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_person_search=True, query=query)
                if card_text:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🐾 Мнение КиноИщейки", 
                            callback_data=f"opinion:{movie_details['id']}"
                        )]
                    ])
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=card_text,
                        parse_mode='html',
                        reply_markup=keyboard
                    )
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"person_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"person_page_{page+1}"))
        
        if nav_buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
            await self.bot.send_message(
                chat_id=user_id,
                text="👇 Навигация:",
                reply_markup=keyboard
            )
    
    # ==================== ОБРАБОТЧИК КНОПОК ====================
    
    async def _handle_callback(self, cb: CallbackQuery):
        user_id = cb.user.id
        data = cb.payload
        
        logger.info(f"Callback от {user_id}: {data}")
        
        # Обработка команд из главного меню
        if data == "random":
            await self.bot.send_message(chat_id=user_id, text="🎲 Ищу случайный фильм...")
            movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
            if movie_data:
                movie_details = get_movie_details(movie_data['id'])
                if movie_details:
                    card_text, _ = format_movie_card(movie_details)
                    if card_text:
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="🐾 Мнение КиноИщейки", 
                                callback_data=f"opinion:{movie_details['id']}"
                            )]
                        ])
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=card_text,
                            parse_mode='html',
                            reply_markup=keyboard
                        )
                        return
        
        elif data == "search":
            self.user_context[user_id] = {'state': 'awaiting_search'}
            await self.bot.send_message(chat_id=user_id, text="🔍 Введи название фильма:")
            return
        
        elif data == "premiers":
            await self._handle_premiers_btn(user_id)
            return
        
        elif data == "person":
            self.user_context[user_id] = {'state': 'awaiting_person'}
            await self.bot.send_message(chat_id=user_id, text="🎭 Введи имя актёра или режиссёра:")
            return
        
        elif data == "profile":
            limits = get_user_limits(user_id)
            await self.bot.send_message(
                chat_id=user_id,
                text=(
                    f"👤 <b>Твой профиль</b>\n\n"
                    f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
                    f"🎬 Мнений в сутки: {limits.get('opinion_limit', 3)}\n"
                    f"🔄 Свежих взглядов: {limits.get('regeneration_limit', 2)}"
                ),
                parse_mode="html"
            )
            return
        
        # Пагинация
        elif data.startswith("search_page_"):
            page = int(data.split("_")[2])
            if user_id in self.user_context:
                self.user_context[user_id]['page'] = page
                await self._show_search_page(user_id)
            return
        
        elif data.startswith("person_page_"):
            page = int(data.split("_")[2])
            if user_id in self.user_context:
                self.user_context[user_id]['page'] = page
                await self._show_person_page(user_id)
            return
        
        elif data.startswith("premiers_page_"):
            page = int(data.split("_")[2])
            if user_id in self.user_context:
                self.user_context[user_id]['page'] = page
                await self._show_premiers_page(user_id)
            return
        
        # Мнение о фильме (заглушка — будет реализовано позже)
        elif data.startswith("opinion:"):
            movie_id = int(data.split(":")[1])
            await self.bot.send_message(
                chat_id=user_id,
                text=f"🐾 Мнение о фильме ID:{movie_id} будет доступно в следующей версии!\n\nПока просто наслаждайся поиском 🎬"
            )
            return
        
        else:
            await self.bot.send_message(chat_id=user_id, text=f"🐾 Неизвестная команда: {data}")
    
    async def _handle_premiers_btn(self, user_id: int):
        await self.bot.send_message(chat_id=user_id, text="🎉 Ищу ожидаемые премьеры...")
        
        premiers_list = get_premier_movies_from_db()
        if not premiers_list:
            await self.bot.send_message(chat_id=user_id, text="😢 Сейчас нет ожидаемых премьер.")
            return
        
        self.user_context[user_id] = {
            'state': 'premiers',
            'movies': premiers_list,
            'page': 0
        }
        await self._show_premiers_page(user_id)
    
    # ==================== ЗАПУСК ====================
    
    async def run(self):
        logger.info("🚀 MaxAdapter (maxbot) запущен, ожидаем сообщения...")
        await self.dp.start_polling()


# Точка входа
if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

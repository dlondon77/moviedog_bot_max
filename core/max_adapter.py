# core/max_adapter.py — ФИНАЛЬНАЯ ВЕРСИЯ С ФИЛЬТРАМИ И ВЫБОРОМ ПЕРСОНЫ

import logging
import configparser
import os
import sys
from datetime import date, datetime
import re
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(BASE_DIR, 'core')

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

logger = logging.getLogger(__name__)

from maxapi import Bot, Dispatcher, F
from maxapi.types import BotStarted, MessageCreated
from openai import OpenAI
import httpx

# ==================== ИМПОРТЫ ИЗ CORE ====================
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
search_persons = movie_module.search_persons


# ==================== КЭШ МНЕНИЙ ====================
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


# ==================== КОНФИГ И DEEPSEEK ====================
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


# ==================== СВОЙ КЛАСС КЛАВИАТУРЫ ====================
class InlineKeyboardMarkup:
    def __init__(self, buttons):
        self.buttons = buttons

    def model_dump(self):
        return {
            "type": "inline_keyboard",
            "payload": {
                "buttons": self.buttons
            }
        }


# ==================== ФУНКЦИИ СОЗДАНИЯ КЛАВИАТУР ====================
def get_main_menu():
    buttons = [
        [
            {"type": "callback", "text": "🎲 Случайный фильм", "payload": "random"},
            {"type": "callback", "text": "🔍 Поиск", "payload": "search"}
        ],
        [
            {"type": "callback", "text": "🎉 Премьеры", "payload": "premiers"},
            {"type": "callback", "text": "🎭 Поиск по актёрам", "payload": "person"}
        ],
        [
            {"type": "callback", "text": "👤 Мой профиль", "payload": "profile"},
            {"type": "callback", "text": "🐾 Мнение о фильме", "payload": "opinion_prompt"}
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_opinion_button(movie_id: int):
    buttons = [
        [{"type": "callback", "text": "🐾 Мнение о фильме", "payload": f"opinion_{movie_id}"}]
    ]
    return InlineKeyboardMarkup(buttons)

def get_pagination_buttons(current_page: int, total_pages: int, prefix: str, query: str = ""):
    """Создаёт кнопки пагинации"""
    buttons = []
    row = []
    if current_page > 0:
        row.append({"type": "callback", "text": "◀️ Назад", "payload": f"{prefix}_page_{current_page-1}_{query}"})
    row.append({"type": "callback", "text": f"{current_page+1}/{total_pages}", "payload": "noop"})
    if current_page < total_pages - 1:
        row.append({"type": "callback", "text": "Вперёд ▶️", "payload": f"{prefix}_page_{current_page+1}_{query}"})
    buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def get_start_image_url():
    return "https://i.postimg.cc/Y0TkbYv0/Spring-Start-01.jpg"


def get_filter_keyboard(query, filters, total_count, has_more):
    """Создаёт клавиатуру с фильтрами (как в VK)"""
    buttons = []
    
    # Строка с рейтингом
    rating_row = []
    current_rating = filters.get('rating_range')
    rating_options = [
        ('new', '🆕 Новинки'), ('5-6', '⭐5-6'), ('6-7', '⭐6-7'),
        ('7-8', '⭐7-8'), ('8-9', '⭐8-9'), ('9-10', '⭐9-10')
    ]
    
    for value, label in rating_options:
        if current_rating == value:
            label = f"✓ {label}"
        rating_row.append({
            "type": "callback",
            "text": label[:40],
            "payload": f"filter_rating_{value}_{query}"
        })
        if len(rating_row) == 3:
            buttons.append(rating_row)
            rating_row = []
    if rating_row:
        buttons.append(rating_row)
    
    # Строка с десятилетиями
    decade_row = []
    current_decade = filters.get('decade')
    decade_options = [
        ('pre1980', '📽 До1980'), ('1980s', '📅1980-е'), ('1990s', '📅1990-е'),
        ('2000s', '📅2000-е'), ('2010s', '📅2010-е'), ('2020s', '📅2020-е')
    ]
    
    for value, label in decade_options:
        if current_decade == value:
            label = f"✓ {label}"
        decade_row.append({
            "type": "callback",
            "text": label[:40],
            "payload": f"filter_decade_{value}_{query}"
        })
        if len(decade_row) == 3:
            buttons.append(decade_row)
            decade_row = []
    if decade_row:
        buttons.append(decade_row)
    
    # Кнопка показа результатов
    if total_count > 0:
        button_text = f"🎬 Показать карточки ({total_count})" if not has_more else f"🎬 Показать первые {total_count}"
        buttons.append([{
            "type": "callback",
            "text": button_text[:40],
            "payload": f"filter_show_{query}"
        }])
    
    # Кнопка сброса
    if filters:
        buttons.append([{
            "type": "callback",
            "text": "🔄 Сбросить фильтры",
            "payload": f"filter_reset_{query}"
        }])
    
    # Кнопка нового поиска
    buttons.append([{
        "type": "callback",
        "text": "🆕 Новый поиск",
        "payload": "new_search"
    }])
    
    return InlineKeyboardMarkup(buttons)


def get_persons_keyboard(persons, page, total_pages, search_query):
    """Создаёт клавиатуру для выбора персоны (как в VK)"""
    buttons = []
    
    # Кнопки с номерами персон
    row = []
    start_idx = page * 5
    for i, person in enumerate(persons[start_idx:start_idx + 5], start_idx + 1):
        payload = f"select_person_{person['id']}_{person['raw_name']}"
        row.append({
            "type": "callback",
            "text": str(i),
            "payload": payload
        })
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    # Пагинация
    nav_row = []
    if page > 0:
        nav_row.append({
            "type": "callback",
            "text": "◀️ Назад",
            "payload": f"persons_page_{page-1}_{search_query}"
        })
    if page < total_pages - 1:
        nav_row.append({
            "type": "callback",
            "text": "Вперёд ▶️",
            "payload": f"persons_page_{page+1}_{search_query}"
        })
    if nav_row:
        buttons.append(nav_row)
    
    # Управление
    buttons.append([{
        "type": "callback",
        "text": "🔄 Новый поиск",
        "payload": "new_person_search"
    }])
    buttons.append([{
        "type": "callback",
        "text": "🏠 В меню",
        "payload": "back_to_menu"
    }])
    
    return InlineKeyboardMarkup(buttons)


# ==================== ОСНОВНОЙ КЛАСС АДАПТЕРА ====================
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
        logger.info("✅ MaxAdapter инициализирован с фильтрами и поиском по актёрам")

    def _register_handlers(self):
        @self.dp.bot_started()
        async def on_bot_started(event: BotStarted):
            await self.bot.send_message(
                chat_id=event.chat_id,
                text="🐾 Привет! Я КиноИщейка!\nНапиши /start чтобы увидеть меню."
            )

        @self.dp.message_created(F.message.body.text == "/start")
        async def on_start(event: MessageCreated):
            await self._handle_start(event)

        @self.dp.message_created(F.message.body.text == "/random")
        async def on_random(event: MessageCreated):
            await self._handle_random(event)

        @self.dp.message_created(F.message.body.text == "/search")
        async def on_search(event: MessageCreated):
            user_id = event.message.sender.user_id
            self._get_user_context(user_id)['state'] = 'awaiting_search'
            await event.message.answer("🔍 Введи название фильма:")

        @self.dp.message_created(F.message.body.text == "/premiers")
        async def on_premiers(event: MessageCreated):
            await self._handle_premiers(event)

        @self.dp.message_created(F.message.body.text == "/person")
        async def on_person(event: MessageCreated):
            user_id = event.message.sender.user_id
            self._get_user_context(user_id)['state'] = 'awaiting_person_name'
            await event.message.answer(
                "🎭 Введи имя актера или режиссера, и я найду фильмы с их участием!\n\n"
                "Например: Мэрил Стрип, Кристофер Нолан, Ди Каприо"
            )

        @self.dp.message_created(F.message.body.text == "/profile")
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)

        @self.dp.message_created(F.message.body.text.startswith("/opinion"))
        async def on_opinion(event: MessageCreated):
            await self._handle_opinion_command(event)

        @self.dp.message_created(F.message.body.text == "/help")
        async def on_help(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Команды:</b>\n\n"
                "/start — главное меню\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
                "/premiers — ожидаемые премьеры\n"
                "/person — поиск по актёрам/режиссёрам\n"
                "/opinion [название или ID] — мнение о фильме\n"
                "/profile — мой профиль\n"
                "/help — это сообщение",
                parse_mode="html"
            )

        @self.dp.message_callback()
        async def on_callback(event):
            await self._handle_callback(event)

        @self.dp.message_created()
        async def on_message(event: MessageCreated):
            await self._handle_message(event)

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================
    def _get_user_context(self, user_id: int) -> dict:
        if user_id not in self.user_context:
            self.user_context[user_id] = {}
        return self.user_context[user_id]

    def _apply_filters_to_movies(self, movies, filters):
        """Применяет фильтры к списку фильмов"""
        if not filters:
            return movies
        
        filtered = movies.copy()
        
        rating_filter = filters.get('rating_range')
        if rating_filter:
            if rating_filter == 'new':
                filtered = [m for m in filtered if m.get('is_new_release', False)]
            else:
                try:
                    min_rating, max_rating = map(float, rating_filter.split('-'))
                    filtered = [m for m in filtered if m.get('rating', 0) >= min_rating and m.get('rating', 0) <= max_rating]
                except:
                    pass
        
        decade_filter = filters.get('decade')
        if decade_filter:
            if decade_filter == 'pre1980':
                filtered = [m for m in filtered if m.get('year', 0) < 1980]
            elif decade_filter == '1980s':
                filtered = [m for m in filtered if 1980 <= m.get('year', 0) <= 1989]
            elif decade_filter == '1990s':
                filtered = [m for m in filtered if 1990 <= m.get('year', 0) <= 1999]
            elif decade_filter == '2000s':
                filtered = [m for m in filtered if 2000 <= m.get('year', 0) <= 2009]
            elif decade_filter == '2010s':
                filtered = [m for m in filtered if 2010 <= m.get('year', 0) <= 2019]
            elif decade_filter == '2020s':
                filtered = [m for m in filtered if m.get('year', 0) >= 2020]
        
        return filtered

    # ==================== СТАРТ ====================
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

        start_text = (
            "🐾 <b>Гав! Я - КиноИщейка!</b> Добро пожаловать в мир кино! 🎬\n\n"
            "Я помогу тебе найти фильмы, сериалы и мультфильмы на Кинопоиске, которые ты точно полюбишь.\n\n"
            "📊 <b>Твой тариф:</b> {tariff}\n"
            "🎬 <b>Мнений сегодня:</b> 0/{limit}\n\n"
            "<b>Вот что я умею:</b>\n\n"
            "🎲 <b>Случайный фильм</b> — найду следы случайного фильма\n"
            "🔍 <b>Поиск</b> — найду отборные фильмы по названию\n"
            "🎉 <b>Премьеры</b> — учуяю свежие ожидаемые премьеры\n"
            "🎭 <b>Поиск по актёрам</b> — найду фильмы по имени актёра или режиссёра\n"
            "🐾 <b>Мнение о фильме</b> — расскажу о смысле фильма, его настроении и атмосфере, укажу на плюсы и минусы и поставлю оценку\n\n"
            "👇 <b>Выбери действие в меню ниже:</b>"
        ).format(
            tariff=limits.get('tariff_name', 'Щенячий азарт'),
            limit=limits.get('opinion_limit', 3)
        )

        photo_url = get_start_image_url()

        try:
            await event.message.answer(
                start_text,
                parse_mode="html",
                attachments=[
                    {"type": "photo", "payload": {"url": photo_url}},
                    get_main_menu()
                ]
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить с фото, отправляем текст: {e}")
            await event.message.answer(
                start_text,
                parse_mode="html",
                attachments=[get_main_menu()]
            )

    # ==================== ОБРАБОТЧИК КНОПОК ====================
    async def _handle_callback(self, event):
        payload = event.callback.payload
        user_id = event.callback.user.user_id
        logger.info(f"Callback от {user_id}: {payload}")

        try:
            await event.callback.ack()
        except AttributeError:
            try:
                await event.callback.send_answer()
            except AttributeError:
                pass

        # ===== ФИЛЬТРЫ =====
        if payload.startswith("filter_rating_"):
            parts = payload.split("_")
            value = parts[2]
            query = "_".join(parts[3:]) if len(parts) > 3 else ""
            await self._handle_filter(event, user_id, query, 'rating_range', value)
            return

        if payload.startswith("filter_decade_"):
            parts = payload.split("_")
            value = parts[2]
            query = "_".join(parts[3:]) if len(parts) > 3 else ""
            await self._handle_filter(event, user_id, query, 'decade', value)
            return

        if payload.startswith("filter_show_"):
            query = payload.replace("filter_show_", "")
            await self._handle_filter_show(event, user_id, query)
            return

        if payload.startswith("filter_reset_"):
            query = payload.replace("filter_reset_", "")
            await self._handle_filter_reset(event, user_id, query)
            return

        # ===== ПАГИНАЦИЯ ПОИСКА =====
        if payload.startswith("search_page_"):
            parts = payload.split("_")
            page = int(parts[2])
            query = "_".join(parts[3:]) if len(parts) > 3 else ""
            await self._show_search_page(event, user_id, page, query)
            return

        if payload.startswith("premiers_page_"):
            parts = payload.split("_")
            page = int(parts[2])
            await self._show_premiers_page(event, user_id, page)
            return

        # ===== ПЕРСОНЫ =====
        if payload.startswith("persons_page_"):
            parts = payload.split("_")
            page = int(parts[2])
            query = "_".join(parts[3:]) if len(parts) > 3 else ""
            await self._show_persons_list(event, user_id, page, query)
            return

        if payload.startswith("select_person_"):
            parts = payload.split("_")
            person_id = int(parts[2])
            person_name = "_".join(parts[3:]) if len(parts) > 3 else ""
            await self._handle_person_selection(event, user_id, person_id, person_name)
            return

        if payload.startswith("person_page_"):
            parts = payload.split("_")
            page = int(parts[2])
            query = "_".join(parts[3:]) if len(parts) > 3 else ""
            await self._show_person_movies_page(event, user_id, page, query)
            return

        # ===== НАВИГАЦИЯ =====
        if payload == "noop":
            return

        if payload == "back_to_menu":
            self.user_context.pop(user_id, None)
            await event.message.answer("🐾 Возвращаюсь в главное меню", attachments=[get_main_menu()])
            return

        if payload == "new_search":
            self.user_context.pop(user_id, None)
            await event.message.answer("🔍 Введи название фильма:")
            self._get_user_context(user_id)['state'] = 'awaiting_search'
            return

        if payload == "new_person_search":
            self.user_context.pop(user_id, None)
            await event.message.answer("🎭 Введи имя актера или режиссера:")
            self._get_user_context(user_id)['state'] = 'awaiting_person_name'
            return

        # ===== ОСНОВНЫЕ КОМАНДЫ =====
        if payload == "random":
            await event.message.answer("🎲 Ищу случайный фильм...")
            await self._send_random_result(event.message.answer)
        elif payload == "search":
            self._get_user_context(user_id)['state'] = 'awaiting_search'
            await event.message.answer("🔍 Введи название фильма:")
        elif payload == "premiers":
            await event.message.answer("🎉 Ищу ожидаемые премьеры...")
            await self._handle_premiers_search(event, user_id)
        elif payload == "person":
            self._get_user_context(user_id)['state'] = 'awaiting_person_name'
            await event.message.answer("🎭 Введи имя актера или режиссера:")
        elif payload == "profile":
            await self._send_profile(event.message.answer, user_id)
        elif payload == "opinion_prompt":
            self._get_user_context(user_id)['state'] = 'awaiting_opinion'
            await event.message.answer("🐾 Введи ID или название фильма:")
        elif payload.startswith("opinion_"):
            movie_id = int(payload.split("_")[1])
            await self._send_opinion_by_id(event, user_id, movie_id)
        else:
            await event.message.answer(f"🐾 Неизвестная команда: {payload}")

    # ==================== ФИЛЬТРЫ ====================
    async def _handle_filter(self, event, user_id, query, filter_type, value):
        context = self._get_user_context(user_id)
        filters = context.get('filters', {})
        
        if filters.get(filter_type) == value:
            filters.pop(filter_type, None)
        else:
            filters[filter_type] = value
        
        context['filters'] = filters
        
        # Проверяем, есть ли результаты в контексте
        full_list = context.get('full_list', [])
        if not full_list:
            await event.message.answer("😢 Начни поиск заново.")
            return
        
        filtered = self._apply_filters_to_movies(full_list, filters)
        context['filtered_list'] = filtered
        
        total_count = len(filtered)
        has_more = total_count >= 100
        
        text = f"🔍 Поиск: {query}\n\n"
        if filters:
            text += "Активные фильтры:\n"
            if filters.get('rating_range'):
                rating_names = {
                    'new': '🆕 Новинки',
                    '5-6': '⭐5-6',
                    '6-7': '⭐6-7',
                    '7-8': '⭐7-8',
                    '8-9': '⭐8-9',
                    '9-10': '⭐9-10'
                }
                text += f"• {rating_names.get(filters['rating_range'], filters['rating_range'])}\n"
            if filters.get('decade'):
                decade_names = {
                    'pre1980': '📽 До1980',
                    '1980s': '📅1980-е',
                    '1990s': '📅1990-е',
                    '2000s': '📅2000-е',
                    '2010s': '📅2010-е',
                    '2020s': '📅2020-е'
                }
                text += f"• {decade_names.get(filters['decade'], filters['decade'])}\n"
            text += "\n"
        
        text += f"Найдено фильмов: {'>' if has_more else ''}{total_count}\n\n"
        text += "Настрой фильтры и нажми 'Показать карточки'"
        
        keyboard = get_filter_keyboard(query, filters, total_count, has_more)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    async def _handle_filter_show(self, event, user_id, query):
        context = self._get_user_context(user_id)
        filtered = context.get('filtered_list', [])
        full_list = context.get('full_list', [])
        
        if not filtered and full_list:
            filtered = full_list
            context['filtered_list'] = filtered
        
        if not filtered:
            await event.message.answer("😢 Нет фильмов для показа. Начни поиск заново.")
            return
        
        context['movies'] = filtered
        context['query'] = query
        await self._show_search_page(event, user_id, 0, query)

    async def _handle_filter_reset(self, event, user_id, query):
        context = self._get_user_context(user_id)
        context['filters'] = {}
        context['filtered_list'] = []
        
        full_list = context.get('full_list', [])
        if not full_list:
            await event.message.answer("😢 Начни поиск заново.")
            return
        
        total_count = len(full_list)
        has_more = total_count >= 100
        
        text = f"🔍 Поиск: {query}\n\n"
        text += f"Найдено фильмов: {'>' if has_more else ''}{total_count}\n\n"
        text += "Настрой фильтры и нажми 'Показать карточки'"
        
        keyboard = get_filter_keyboard(query, {}, total_count, has_more)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    # ==================== ПАГИНАЦИЯ ====================
    async def _show_search_page(self, event, user_id, page, query):
        context = self._get_user_context(user_id)
        movies_list = context.get('movies', [])
        current_query = context.get('query', query)

        if not movies_list:
            await event.message.answer("😢 Результаты поиска устарели. Начни заново.")
            return

        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page

        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0

        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies_list))

        await event.message.answer(
            f"📽 <b>Результаты поиска \"{current_query}\"</b>\n"
            f"Страница {page+1} из {total_pages}\n"
            f"Показаны фильмы {start_idx+1}-{end_idx}",
            parse_mode="html"
        )

        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details)
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[get_opinion_button(movie_details['id'])]
                    )

        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", current_query)
            await event.message.answer("👇 Навигация:", attachments=[pagination])

    async def _show_premiers_page(self, event, user_id, page):
        context = self._get_user_context(user_id)
        movies_list = context.get('premiers', [])

        if not movies_list:
            await event.message.answer("😢 Список премьер устарел. Начни заново.")
            return

        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page

        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0

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
                card_text, _ = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[get_opinion_button(movie_details['id'])]
                    )

        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "premiers", "")
            await event.message.answer("👇 Навигация:", attachments=[pagination])

    # ==================== ПОИСК ПО АКТЁРАМ (С ВЫБОРОМ ПЕРСОНЫ) ====================
    async def _show_persons_list(self, event, user_id, page, query):
        context = self._get_user_context(user_id)
        persons = context.get('persons', [])
        
        if not persons:
            await event.message.answer("😢 Список персон устарел. Начни поиск заново.")
            return
        
        items_per_page = 5
        total_pages = (len(persons) + items_per_page - 1) // items_per_page
        
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(persons))
        
        text = f"🎭 Нашла {len(persons)} персон (стр. {page+1}/{total_pages})\n\n"
        text += "Выбери номер персоны:\n\n"
        
        for i, person in enumerate(persons[start_idx:end_idx], start_idx + 1):
            name = person['name'][:40] + ('...' if len(person['name']) > 40 else '')
            type_icon = "🎬" if person['type'] == 'director' else "🎭"
            text += f"{i}. {type_icon} {name}\n"
        
        keyboard = get_persons_keyboard(persons, page, total_pages, query)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    async def _handle_person_selection(self, event, user_id, person_id, person_name):
        logger.info(f"🎭 Выбрана персона: ID={person_id}, имя={person_name}")
        
        await event.message.answer(f"🎭 Ищу фильмы с {person_name}...")
        
        movies_list = search_movies_by_person_in_db(person_name, min_rating=0.0, max_rating=10.0)
        
        if not movies_list:
            await event.message.answer(f"😢 Не нашла фильмов с {person_name}.")
            return
        
        context = self._get_user_context(user_id)
        context['movies'] = movies_list
        context['query'] = person_name
        context['full_list'] = movies_list
        context['filters'] = {}
        context['filtered_list'] = []
        
        await self._show_search_page(event, user_id, 0, person_name)

    # ==================== ОБРАБОТЧИКИ КОМАНД ====================
    async def _handle_random(self, event: MessageCreated):
        await event.message.answer("🎲 Ищу случайный фильм...")
        await self._send_random_result(event.message.answer)

    async def _send_random_result(self, send_func):
        movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
        if not movie_data:
            await send_func("😢 Не нашла фильмов.")
            return

        movie_details = get_movie_details(movie_data['id'])
        if not movie_details:
            await send_func("😢 Не могу найти информацию о фильме.")
            return

        card_text, _ = format_movie_card(movie_details)
        if card_text:
            await send_func(
                card_text,
                parse_mode='html',
                attachments=[get_opinion_button(movie_details['id'])]
            )
        else:
            await send_func("😢 Не могу показать карточку.")

    async def _handle_premiers(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        await event.message.answer("🎉 Ищу ожидаемые премьеры...")
        await self._handle_premiers_search(event, user_id)

    async def _handle_premiers_search(self, event, user_id):
        premiers_list = get_premier_movies_from_db()
        if not premiers_list:
            await event.message.answer("😢 Сейчас нет ожидаемых премьер.")
            return

        context = self._get_user_context(user_id)
        context['premiers'] = premiers_list
        await self._show_premiers_page(event, user_id, 0)

    async def _handle_profile(self, event: MessageCreated):
        await self._send_profile(event.message.answer, event.message.sender.user_id)

    async def _send_profile(self, send_func, user_id):
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

    # ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
    async def _handle_message(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        if not text or text.startswith("/"):
            return

        context = self._get_user_context(user_id)
        state = context.get('state')

        if state == 'awaiting_search':
            await self._perform_search(event, user_id, text)
        elif state == 'awaiting_person_name':
            await self._perform_person_search(event, user_id, text)
        elif state == 'awaiting_opinion':
            await self._process_opinion(event, user_id, text, event.message.answer)
            self.user_context.pop(user_id, None)
        else:
            # По умолчанию — поиск (как в TG)
            await self._perform_search(event, user_id, text)

    async def _perform_search(self, event: MessageCreated, user_id, query):
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return

        await event.message.answer(f"🔍 Ищу: {query}...")
        
        # Получаем результаты
        total_count, has_more = movie_module.search_movies_with_filters(query, filters=None, count_only=True)
        
        if total_count == 0:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
            self.user_context.pop(user_id, None)
            return
        
        full_list = movie_module.search_movies_with_filters(query, filters=None, count_only=False)
        
        context = self._get_user_context(user_id)
        context['full_list'] = full_list
        context['query'] = query
        context['filters'] = {}
        context['filtered_list'] = []
        context['movies'] = full_list
        context['state'] = 'search_results'
        
        text = f"🔍 Поиск: {query}\n\n"
        text += f"Найдено фильмов: {'>' if has_more else ''}{total_count}\n\n"
        text += "Настрой фильтры и нажми 'Показать карточки'"
        
        keyboard = get_filter_keyboard(query, {}, total_count, has_more)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    async def _perform_person_search(self, event: MessageCreated, user_id, query):
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return

        await event.message.answer(f"🎭 Ищу персон по запросу '{query}'...")
        
        persons = search_persons(query, limit=30)
        
        if not persons:
            await event.message.answer(f"😢 Не нашла персон по запросу '{query}'. Попробуй другое имя.")
            self.user_context.pop(user_id, None)
            return
        
        context = self._get_user_context(user_id)
        context['persons'] = persons
        context['state'] = 'persons_list'
        
        await self._show_persons_list(event, user_id, 0, query)

    # ==================== МНЕНИЕ О ФИЛЬМЕ ====================
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
        await self._process_opinion(event, user_id, text, event.message.answer)

    async def _send_opinion_by_id(self, event, user_id, movie_id):
        await self._process_opinion(event, user_id, str(movie_id), event.message.answer)

    async def _process_opinion(self, event, user_id, query, send_func):
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

        cached = get_cached_opinion(movie_id)
        if cached:
            formatted_opinion = self._format_opinion(cached, movie_name, movie_year, movie_id)
            await send_func(formatted_opinion, parse_mode="html")
            increment_stat_counter(user_id, 'opinion_count')
            record_user_opinion(user_id, movie_id)
            return

        await send_func(f"🐾 Смотрю <b>{movie_name}</b> ({movie_year}) в ускоренном режиме... 🎬", parse_mode="html")

        if not ai_client:
            await send_func("😢 Генерация мнений временно недоступна.")
            return

        try:
            opinion_data = await self._generate_opinion(movie_details)
            if opinion_data:
                full_opinion = opinion_data['full_opinion']
                save_opinion_cache(movie_id, full_opinion)
                increment_stat_counter(user_id, 'opinion_count')
                record_user_opinion(user_id, movie_id)
                formatted_opinion = self._format_opinion(full_opinion, movie_name, movie_year, movie_id)
                await send_func(formatted_opinion, parse_mode="html")
            else:
                await send_func("😢 Не удалось сгенерировать мнение.")
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            await send_func("🐾 Гав! Что-то пошло не так. Попробуй позже!")

    def _format_opinion(self, opinion, movie_name, movie_year, movie_id):
        kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"
        title_with_link = f"<a href='{kp_url}'><b>{movie_name}</b></a> ({movie_year})"
        return f"Я посмотрела {title_with_link}, и вот что думаю:\n\n{opinion}\n\n🐾"

    async def _generate_opinion(self, movie_details):
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
        full_response = response.choices[0].message.content.strip()
        return {'full_opinion': full_response}

    # ==================== ЗАПУСК ====================
    async def run(self):
        logger.info("🚀 MaxAdapter запущен с фильтрами и поиском по актёрам")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

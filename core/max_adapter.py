# core/max_adapter.py — ПОЛНАЯ ВЕРСИЯ (БЕЗ PAYMENT)
# + Исправлены премьеры (выбор месяца)
# + Исправлены ссылки в подборках и карточках
# + Исправлены любимые фильмы
# + Исправлен профиль
# + ВСЁ, ЧТО СВЯЗАНО С PAYMENT — УДАЛЕНО

import logging
import configparser
import os
import sys
import re
import asyncio
from datetime import date, datetime

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

# ==================== КОНСТАНТЫ ====================
ADMIN_IDS = [7191208]

# ==================== ИМПОРТЫ ИЗ CORE ====================
import user as user_module
import movie as movie_module
import db as db_module
from core.agent import run_agent, clear_chat_history, extract_movie_ids, CHAT_SYSTEM_PROMPT

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
search_movies_with_filters = movie_module.search_movies_with_filters
search_movies_by_description = movie_module.search_movies_by_description

# ==================== ЛЮБИМЫЕ ФИЛЬМЫ ====================
def is_favorite(user_id: int, movie_id: int) -> bool:
    """Проверяет, есть ли фильм в любимых"""
    conn = db_module.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM favorite_movies 
        WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_favorite(user_id: int, movie_id: int) -> bool:
    """Добавляет фильм в любимые"""
    conn = db_module.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO favorite_movies (user_id, movie_id, added_at)
            VALUES (?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления в любимые: {e}")
        return False
    finally:
        conn.close()

def remove_favorite(user_id: int, movie_id: int) -> bool:
    """Удаляет фильм из любимых"""
    conn = db_module.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            DELETE FROM favorite_movies 
            WHERE user_id = ? AND movie_id = ?
        ''', (user_id, movie_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка удаления из любимых: {e}")
        return False
    finally:
        conn.close()

def get_favorites(user_id: int, limit: int = 10, offset: int = 0) -> list:
    """Получает список любимых фильмов"""
    conn = db_module.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT fm.movie_id, fm.added_at, m.name, m.year, m.rating
        FROM favorite_movies fm
        JOIN movies m ON fm.movie_id = m.id
        WHERE fm.user_id = ?
        ORDER BY fm.added_at DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    movies = cursor.fetchall()
    conn.close()
    return [{'movie_id': row[0], 'added_at': row[1], 'name': row[2], 'year': row[3], 'rating': row[4]} for row in movies]

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

# ==================== СОХРАНЕНИЕ ОБРАТНОЙ СВЯЗИ ====================
def save_feedback(user_id, feedback_type, movie_id, message):
    conn = db_module.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO feedback (user_id, type, movie_id, message, status, created_at)
    VALUES (?, ?, ?, ?, 'new', ?)
    ''', (user_id, feedback_type, movie_id if movie_id else None, message, datetime.now().isoformat()))
    conn.commit()
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
    http_client = httpx.Client(timeout=180.0, follow_redirects=True)
    ai_client = OpenAI(
        api_key=DEEPSEEK_KEY,
        base_url=config.get('OpenAI', 'base_url', fallback='https://api.deepseek.com/v1'),
        http_client=http_client,
    )
    logger.info("✅ DeepSeek клиент инициализирован")
else:
    ai_client = None
    logger.warning("⚠️ OPENAI_API_KEY не найден")


# ==================== КЛАСС КЛАВИАТУРЫ ====================
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
            {"type": "callback", "text": "🎭 Поиск по персонам", "payload": "person"}
        ],
        [
            {"type": "callback", "text": "🐺 КиноЛогово", "payload": "agent_menu"},
            {"type": "callback", "text": "💬 Пообщаться", "payload": "chat"}
        ],
        [
            {"type": "callback", "text": "👤 Мой профиль", "payload": "profile"},
            {"type": "callback", "text": "❤️ Любимые фильмы", "payload": "favorites"}
        ],
        [
            {"type": "callback", "text": "❓ FAQ", "payload": "faq"},
            {"type": "callback", "text": "📝 Обратная связь", "payload": "feedback"}
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_agent_menu():
    buttons = [
        [
            {"type": "callback", "text": "🎬 Подобрать фильм", "payload": "agent_recommend"},
            {"type": "callback", "text": "🐾 Актёрский нюх", "payload": "agent_actor"}
        ],
        [
            {"type": "callback", "text": "⭐ Сравнить фильмы", "payload": "agent_compare"},
            {"type": "callback", "text": "🔎 По сюжету", "payload": "agent_plot_search"}
        ],
        [
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_pagination_buttons(current_page: int, total_pages: int, prefix: str, query: str = ""):
    buttons = []
    row = []
    if current_page > 0:
        row.append({"type": "callback", "text": "◀️ Назад", "payload": f"{prefix}_page_{current_page-1}_{query}"})
    row.append({"type": "callback", "text": f"Стр. {current_page+1} из {total_pages}", "payload": "noop"})
    if current_page < total_pages - 1:
        row.append({"type": "callback", "text": "Вперёд ▶️", "payload": f"{prefix}_page_{current_page+1}_{query}"})
    buttons.append(row)
    buttons.append([
        {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
    ])
    return InlineKeyboardMarkup(buttons)

def get_action_keyboard(action_name: str = None, action_payload: str = None, extra_buttons: list = None):
    buttons = []
    if action_name and action_payload:
        buttons.append([
            {"type": "callback", "text": f"🔄 Ещё {action_name}", "payload": action_payload}
        ])
    if extra_buttons:
        for row in extra_buttons:
            buttons.append(row)
    buttons.append([
        {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
    ])
    return InlineKeyboardMarkup(buttons)

def get_feedback_menu():
    buttons = [
        [
            {"type": "callback", "text": "🐛 Сообщить об ошибке", "payload": "feedback_error"},
            {"type": "callback", "text": "📢 Оставить отзыв", "payload": "feedback_review"}
        ],
        [
            {"type": "callback", "text": "📋 Мои обращения", "payload": "feedback_list"}
        ],
        [
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_faq_menu():
    buttons = [
        [
            {"type": "callback", "text": "🔍 Как найти фильм?", "payload": "faq_search"},
            {"type": "callback", "text": "💬 Как узнать мнение?", "payload": "faq_opinion"}
        ],
        [
            {"type": "callback", "text": "⚠️ Какие есть лимиты?", "payload": "faq_limits"},
            {"type": "callback", "text": "📢 Предложить улучшение", "payload": "faq_suggest"}
        ],
        [
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_feedback_pagination_buttons(page: int, total_pages: int):
    buttons = []
    row = []
    if page > 0:
        row.append({"type": "callback", "text": "⬅️ Назад", "payload": f"fb_page_{page-1}"})
    row.append({"type": "callback", "text": f"Стр. {page+1} из {total_pages}", "payload": "noop"})
    if page < total_pages - 1:
        row.append({"type": "callback", "text": "Вперёд ➡️", "payload": f"fb_page_{page+1}"})
    if row:
        buttons.append(row)
    buttons.append([
        {"type": "callback", "text": "📝 В меню обратной связи", "payload": "feedback_back"}
    ])
    buttons.append([
        {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
    ])
    return InlineKeyboardMarkup(buttons)

def get_filter_keyboard(query, filters, total_count, has_more):
    buttons = []
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
    if total_count > 0:
        button_text = f"🎬 Показать карточки ({total_count})" if not has_more else f"🎬 Показать первые {total_count}"
        buttons.append([{
            "type": "callback",
            "text": button_text[:40],
            "payload": f"filter_show_{query}"
        }])
    if filters:
        buttons.append([{
            "type": "callback",
            "text": "🔄 Сбросить фильтры",
            "payload": f"filter_reset_{query}"
        }])
    buttons.append([{
        "type": "callback",
            "text": "🆕 Новый поиск",
        "payload": "new_search"
    }])
    return InlineKeyboardMarkup(buttons)

def get_month_keyboard():
    """Клавиатура для выбора месяца (премьеры)"""
    month_names = {
        1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр",
        5: "Май", 6: "Июн", 7: "Июл", 8: "Авг",
        9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек"
    }
    buttons = []
    row = []
    for month in range(1, 13):
        row.append({
            "type": "callback",
            "text": month_names[month],
            "payload": f"premiers_month_{month}"
        })
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
    ])
    return InlineKeyboardMarkup(buttons)


# ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================
def _is_search_intent(text: str) -> bool:
    keywords = ['найди', 'поищи', 'ищи', 'покажи', 'фильм с', 'актёр', 'режиссёр', 'найти', 'подбери']
    return any(kw in text.lower() for kw in keywords)

def _is_premium_tariff(tariff_name: str) -> bool:
    return tariff_name in ['Ищейка', 'Вожак']

def _format_opinion_with_buttons(opinion, movie_name, movie_year, movie_id, source, user_id, is_premium):
    """Форматирует мнение с кнопками прямо в одном сообщении"""
    kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"
    
    text = f"🐾 Я посмотрела <b>{movie_name}</b> ({movie_year}), и вот что думаю:\n\n{opinion}\n\n🔗 <a href='{kp_url}'>Кинопоиск</a>\n\n🐾"
    
    buttons = []
    
    if is_premium:
        buttons.append([
            {"type": "callback", "text": "🔄 Свежий взгляд", "payload": f"regenerate_{movie_id}_{source}"}
        ])
    
    # Кнопка "В любимые"
    is_fav = is_favorite(user_id, movie_id)
    fav_text = "💔 Убрать" if is_fav else "❤️ В любимые"
    fav_payload = f"favorite_remove_{movie_id}" if is_fav else f"favorite_add_{movie_id}"
    
    if source == "random":
        buttons.append([
            {"type": "callback", "text": "🎲 Ещё случайный", "payload": "random"},
            {"type": "callback", "text": fav_text, "payload": fav_payload},
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    elif source == "search":
        buttons.append([
            {"type": "callback", "text": "🔄 Ещё поиск", "payload": "search"},
            {"type": "callback", "text": fav_text, "payload": fav_payload},
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    elif source == "person":
        buttons.append([
            {"type": "callback", "text": "🔄 Ещё поиск по персонам", "payload": "person"},
            {"type": "callback", "text": fav_text, "payload": fav_payload},
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    elif source == "premiers":
        buttons.append([
            {"type": "callback", "text": "🔄 Ещё премьеры", "payload": "premiers"},
            {"type": "callback", "text": fav_text, "payload": fav_payload},
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    else:
        buttons.append([
            {"type": "callback", "text": fav_text, "payload": fav_payload},
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    
    keyboard = InlineKeyboardMarkup(buttons)
    return text, keyboard


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
        logger.info("✅ MaxAdapter инициализирован (с любимыми фильмами)")

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
            await event.message.answer(
                "📅 <b>Выбери месяц для премьер:</b>",
                parse_mode="html",
                attachments=[get_month_keyboard()]
            )

        @self.dp.message_created(F.message.body.text == "/person")
        async def on_person(event: MessageCreated):
            user_id = event.message.sender.user_id
            self._get_user_context(user_id)['state'] = 'awaiting_person'
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")

        @self.dp.message_created(F.message.body.text == "/profile")
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)

        @self.dp.message_created(F.message.body.text == "/favorites")
        async def on_favorites(event: MessageCreated):
            await self._handle_favorites(event)

        @self.dp.message_created(F.message.body.text.startswith("/opinion"))
        async def on_opinion(event: MessageCreated):
            await self._handle_opinion_command(event)

        @self.dp.message_created(F.message.body.text == "/faq")
        async def on_faq(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Часто задаваемые вопросы</b>\n\nВыбери вопрос из меню ниже:",
                parse_mode="html",
                attachments=[get_faq_menu()]
            )

        @self.dp.message_created(F.message.body.text == "/feedback")
        async def on_feedback(event: MessageCreated):
            await event.message.answer(
                "📝 <b>Обратная связь</b>\n\nВыбери тип обращения:",
                parse_mode="html",
                attachments=[get_feedback_menu()]
            )

        @self.dp.message_created(F.message.body.text == "/help")
        async def on_help(event: MessageCreated):
            await event.message.answer(
                "❓ <b>Команды:</b>\n\n"
                "/start — главное меню\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
                "/premiers — премьеры по месяцам\n"
                "/person — поиск по персонам\n"
                "/opinion [название или ID] — мнение о фильме\n"
                "/profile — мой профиль\n"
                "/favorites — любимые фильмы\n"
                "/faq — частые вопросы\n"
                "/feedback — обратная связь\n"
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

    def _get_movie_buttons(self, movie_id: int, source: str, user_id: int):
        """Создаёт кнопки для карточки фильма с учётом любимых"""
        is_fav = is_favorite(user_id, movie_id)
        
        buttons = [
            {"type": "callback", "text": "🐾 Мнение", "payload": f"opinion_{movie_id}_{source}"}
        ]
        
        if is_fav:
            buttons.append({"type": "callback", "text": "💔 Убрать", "payload": f"favorite_remove_{movie_id}"})
        else:
            buttons.append({"type": "callback", "text": "❤️ В любимые", "payload": f"favorite_add_{movie_id}"})
        
        return InlineKeyboardMarkup([buttons])

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

        start_text = (
            "🐾 <b>Гав! Я - КиноИщейка!</b> Добро пожаловать в мир кино! 🎬\n\n"
            "Я помогу тебе найти фильмы, сериалы и мультфильмы на Кинопоиске, которые ты точно полюбишь.\n\n"
            "<b>Вот что я умею:</b>\n\n"
            "🎲 <b>Случайный фильм</b> — найду следы случайного фильма\n"
            "🔍 <b>Поиск</b> — найду отборные фильмы по названию (с фильтрами!)\n"
            "🎉 <b>Премьеры</b> — выбирай месяц и смотри премьеры\n"
            "🎭 <b>Поиск по персонам</b> — найду фильмы по имени актёра или режиссёра\n"
            "❤️ <b>Любимые фильмы</b> — сохраняй фильмы, чтобы не забыть\n"
            "🐾 <b>Мнение о фильме</b> — расскажу о смысле фильма, его настроении и атмосфере\n"
            "🔄 <b>Свежий взгляд</b> — перегенерирую мнение (для тарифов Ищейка и Вожак)\n"
            "🐺 <b>КиноЛогово</b> — умные подборки, анализ ролей, поиск по сюжету\n"
            "💬 <b>Пообщаться</b> — короткие факты и лёгкий диалог\n"
            "❓ <b>FAQ</b> — ответы на частые вопросы\n"
            "📝 <b>Обратная связь</b> — сообщить об ошибке или оставить отзыв\n\n"
            "👇 <b>Выбери действие в меню ниже:</b>"
        )

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

        # ===== ПРЕМЬЕРЫ =====
        if payload == "premiers":
            await event.message.answer(
                "📅 <b>Выбери месяц для премьер:</b>",
                parse_mode="html",
                attachments=[get_month_keyboard()]
            )
            return

        if payload.startswith("premiers_month_"):
            month = int(payload.split("_")[2])
            await self._handle_premiers_by_month(event, user_id, month)
            return

        # ===== ЛЮБИМЫЕ ФИЛЬМЫ =====
        if payload == "favorites":
            await self._handle_favorites(event)
            return

        if payload.startswith("favorite_add_"):
            movie_id = int(payload.split("_")[2])
            await self._handle_favorite_add(event, user_id, movie_id)
            return

        if payload.startswith("favorite_remove_"):
            movie_id = int(payload.split("_")[2])
            await self._handle_favorite_remove(event, user_id, movie_id)
            return

        # ===== ПРОФИЛЬ =====
        if payload == "profile":
            await self._send_profile(event.message.answer, user_id)
            return

        # ===== МЕНЮ КиноЛогово =====
        if payload == "agent_menu":
            await event.message.answer(
                "🐺 <b>КиноЛогово</b> — мой умный режим!\n\n"
                "Я умею не просто искать, а думать и советовать.\n\n"
                "🎬 <b>Подобрать фильм</b> — расскажи, что хочешь посмотреть, я подберу лучшее\n"
                "🐾 <b>Актёрский нюх</b> — анализ ролей актёра или режиссёра\n"
                "⭐ <b>Сравнить фильмы</b> — сравню два фильма и скажу, что лучше\n"
                "🔎 <b>По сюжету</b> — найду фильмы по описанию\n\n"
                "📅 Премьеры по месяцам теперь в базовой команде /premiers!",
                parse_mode="html",
                attachments=[get_agent_menu()]
            )
            return

        # ===== СЦЕНАРИИ КиноЛогово =====
        if payload == "agent_recommend":
            self._get_user_context(user_id)['agent_mode'] = 'recommend'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🎬 Отлично! Расскажи, что ты хочешь посмотреть.\n\n"
                "Например:\n"
                "• Жанр — комедия, драма, триллер, ужасы...\n"
                "• Настроение — весёлое, грустное, напряжённое...\n"
                "• Любимые фильмы — чтобы я поняла твой вкус\n\n"
                "Просто напиши, и я найду для тебя лучшие варианты!",
                parse_mode="html"
            )
            return

        if payload == "agent_actor":
            self._get_user_context(user_id)['agent_mode'] = 'actor'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🐾 <b>Актёрский нюх</b>\n\n"
                "Напиши имя актёра или режиссёра, и я сделаю разбор:\n"
                "• Лучшие роли\n"
                "• Самые недооценённые фильмы\n"
                "• Рекомендации\n\n"
                "Например: «Мэрил Стрип», «Кристофер Нолан», «Фильмы с Ди Каприо после 2010»",
                parse_mode="html"
            )
            return

        if payload == "agent_compare":
            self._get_user_context(user_id)['agent_mode'] = 'compare'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "⭐ Ого, сравнение! Это моя любимая игра.\n\n"
                "Напиши два фильма, которые хочешь сравнить.\n"
                "Я покажу их рейтинги, жанры, актёров и режиссёров.\n\n"
                "Например: «Сравни Матрицу и Начало»",
                parse_mode="html"
            )
            return

        if payload == "agent_plot_search":
            self._get_user_context(user_id)['agent_mode'] = 'plot_search'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🔎 <b>Поиск по сюжету</b>\n\n"
                "Опиши, что ты ищешь, и я найду подходящие фильмы!\n\n"
                "Например:\n"
                "• «Фильм про путешествие во времени»\n"
                "• «Человек теряет память и ищет себя»\n"
                "• «Фильм, где есть неожиданный поворот»\n\n"
                "Я поищу в своей базе и подберу 3 лучших варианта! 🐾",
                parse_mode="html"
            )
            return

        # ===== СВОБОДНЫЙ ДИАЛОГ =====
        if payload == "chat":
            clear_chat_history(user_id)
            self._get_user_context(user_id)['agent_mode'] = 'chat'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "💬 Отлично! Я готова поболтать о кино.\n\n"
                "Спрашивай что угодно — я дам короткий, интересный ответ!\n"
                "Факты, шутки, забавные детали о фильмах и актёрах.\n\n"
                "А если захочешь найти фильм — я предложу нужные команды.\n\n"
                "Я запоминаю наш разговор, так что можно уточнять и развивать тему!",
                parse_mode="html"
            )
            return

        # ===== АГЕНТ — ПОКАЗ КАРТОЧЕК =====
        if payload == "agent_show_cards":
            await self._handle_agent_show_cards(event, user_id)
            return

        # ===== FAQ =====
        if payload == "faq" or payload.startswith("faq_"):
            await self._handle_faq_callback(event, user_id, payload)
            return

        # ===== FEEDBACK =====
        if payload == "feedback" or payload.startswith("feedback_"):
            await self._handle_feedback_callback(event, user_id, payload)
            return

        # ===== ПАГИНАЦИЯ ОБРАЩЕНИЙ =====
        if payload.startswith("fb_page_"):
            page = int(payload.split("_")[2])
            await self._show_user_feedback(event, user_id, page)
            return

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

        # ===== НАВИГАЦИЯ =====
        if payload == "back_to_menu":
            self.user_context.pop(user_id, None)
            await event.message.answer(
                "🐾 Поняла, возвращаемся на тропу! Гав, я здесь, выбирай!",
                attachments=[get_main_menu()]
            )
            return

        if payload == "noop":
            return

        if payload == "new_search":
            self.user_context.pop(user_id, None)
            await event.message.answer("🔍 Введи название фильма:")
            self._get_user_context(user_id)['state'] = 'awaiting_search'
            return

        # ===== ПАГИНАЦИЯ =====
        if payload.startswith("search_page_"):
            parts = payload.split("_")
            page = int(parts[2])
            query = "_".join(parts[3:]) if len(parts) > 3 else ""
            
            context = self._get_user_context(user_id)
            if context.get('is_person_search', False):
                await self._show_person_search_page(event, user_id, page, query)
            else:
                await self._show_search_page(event, user_id, page, query)
            return

        # ===== МНЕНИЕ =====
        if payload.startswith("opinion_"):
            parts = payload.split("_")
            movie_id = int(parts[1])
            source = parts[2] if len(parts) > 2 else "search"
            await self._send_opinion_by_id(event, user_id, movie_id, source)
            return

        # ===== СВЕЖИЙ ВЗГЛЯД =====
        if payload.startswith("regenerate_"):
            parts = payload.split("_")
            movie_id = int(parts[1])
            source = parts[2] if len(parts) > 2 else "search"
            await self._handle_regenerate(event, user_id, movie_id, source)
            return

        # ===== ОСНОВНЫЕ КОМАНДЫ =====
        if payload == "random":
            await event.message.answer("🎲 Ищу случайный фильм...")
            await self._send_random_result(event.message.answer)
        elif payload == "search":
            self._get_user_context(user_id)['state'] = 'awaiting_search'
            await event.message.answer("🔍 Введи название фильма:")
        elif payload == "person":
            self._get_user_context(user_id)['state'] = 'awaiting_person'
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")
        else:
            await event.message.answer(f"🐾 Хм... Я не поняла, что ты хочешь. Давай начнём сначала — выбери кнопку в меню!")

    # ==================== ЛЮБИМЫЕ ФИЛЬМЫ ====================
    async def _handle_favorites(self, event):
        user_id = event.message.sender.user_id if event.message else event.sender.user_id
        
        favorites = get_favorites(user_id, limit=20)
        
        if not favorites:
            await event.message.answer(
                "🐾 У тебя пока нет любимых фильмов.\n\n"
                "Чтобы добавить фильм, нажми кнопку «❤️ В любимые» под карточкой фильма!"
            )
            return
        
        text = "❤️ <b>Твои любимые фильмы</b>\n\n"
        for i, fav in enumerate(favorites, 1):
            rating_display = f"⭐ {fav['rating']:.1f}" if fav['rating'] else "нет рейтинга"
            text += f"{i}. <b>{fav['name']}</b> ({fav['year']}) — {rating_display}\n"
            text += f"   🔗 <a href='https://www.kinopoisk.ru/film/{fav['movie_id']}/'>Кинопоиск</a>\n"
        
        text += f"\n🐾 Всего {len(favorites)} фильмов"
        
        buttons = [
            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    async def _handle_favorite_add(self, event, user_id, movie_id):
        if add_favorite(user_id, movie_id):
            movie_details = get_movie_details(movie_id)
            movie_name = movie_details.get('name', 'Фильм') if movie_details else f"ID {movie_id}"
            await event.message.answer(f"❤️ <b>{movie_name}</b> добавлен в любимые!", parse_mode="html")
        else:
            await event.message.answer("😢 Не удалось добавить фильм в любимые.")

    async def _handle_favorite_remove(self, event, user_id, movie_id):
        if remove_favorite(user_id, movie_id):
            movie_details = get_movie_details(movie_id)
            movie_name = movie_details.get('name', 'Фильм') if movie_details else f"ID {movie_id}"
            await event.message.answer(f"💔 <b>{movie_name}</b> удалён из любимых.", parse_mode="html")
        else:
            await event.message.answer("😢 Не удалось удалить фильм из любимых.")

    # ==================== ПРЕМЬЕРЫ ПО МЕСЯЦАМ ====================
    async def _handle_premiers_by_month(self, event, user_id, month):
        await event.message.answer(f"📅 Загружаю премьеры за {month} месяц...")
        
        premiers_list = get_premier_movies_from_db()
        
        filtered = []
        for movie in premiers_list:
            premiere_date = movie.get('premiere_russia') or movie.get('premiere_world')
            if premiere_date:
                try:
                    d = datetime.strptime(premiere_date[:10], "%Y-%m-%d")
                    if d.month == month:
                        filtered.append(movie)
                except:
                    pass
        
        if not filtered:
            await event.message.answer(f"😢 Нет премьер за этот месяц.")
            return
        
        context = self._get_user_context(user_id)
        context['premiers'] = filtered
        await self._show_premiers_page(event, user_id, 0)

    # ==================== ПРОФИЛЬ ====================
    async def _handle_profile(self, event: MessageCreated):
        await self._send_profile(event.message.answer, event.message.sender.user_id)

    async def _send_profile(self, send_func, user_id):
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        tariff_icons = {
            'Щенячий азарт': '🐶',
            'Охотничий': '🐕',
            'Ищейка': '🕵️',
            'Вожак': '🐺'
        }
        icon = tariff_icons.get(limits['tariff_name'], '🐾')
        
        regeneration_limit = limits.get('regeneration_limit', 0)
        regeneration_used = stats.get('regeneration_count', 0)
        regeneration_text = f"{regeneration_used}/{regeneration_limit}" if regeneration_limit > 0 else "∞"
        
        favorites_count = len(get_favorites(user_id, limit=1000))
        
        text = (
            f"{icon} <b>Твой тариф: {limits['tariff_name']}</b>\n\n"
            f"📊 <b>Лимиты на сегодня:</b>\n"
            f"• Мнений: {stats['opinion_count']}/{limits['opinion_limit']}\n"
            f"• Свежих взглядов: {regeneration_text}\n"
            f"❤️ Любимых фильмов: {favorites_count}\n\n"
            f"📅 Действует до: {limits['tariff_end_date'][:10]}\n\n"
            f"🐾 Лимиты обновляются в полночь!"
        )
        
        buttons = [
            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        
        await send_func(text, parse_mode="html", attachments=[keyboard])

    # ==================== ПОИСК И ПАГИНАЦИЯ ====================
    async def _perform_search(self, event, user_id, query):
        if len(query) < 2:
            await event.message.answer("🐾 Введи не менее 2 символов для поиска.")
            return

        await event.message.answer("🔍 <i>Гав-гав! Взяла след по вашему запросу...</i>", parse_mode="html")
        
        full_list = search_movies_with_filters(query, filters=None, count_only=False)
        context = self._get_user_context(user_id)
        context['full_list'] = full_list
        context['query'] = query
        context['filters'] = {}
        context['filtered_list'] = full_list
        
        total_count = len(full_list)
        has_more = total_count >= 100
        
        if total_count == 0:
            await event.message.answer("🐾 Не нашла фильмов. Попробуй уточнить название.")
            return
        
        text = f"🔍 <b>Поиск: {query}</b>\n\n"
        if has_more:
            text += f"Найдено фильмов: <b>>{total_count}</b>\n\n"
        else:
            text += f"Найдено фильмов: <b>{total_count}</b>\n\n"
        text += "Используй фильтры для уточнения, затем нажми 'Показать карточки'"
        
        keyboard = get_filter_keyboard(query, {}, total_count, has_more)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    async def _perform_person_search(self, event, user_id, query):
        if len(query) < 2:
            await event.message.answer("🐾 Введи не менее 2 символов для поиска.")
            return

        await event.message.answer("🕵️‍♀️ <i>Мой собачий нюх уже работает...</i>", parse_mode="html")
        
        movies_list = search_movies_by_person_in_db(query, min_rating=0.0, max_rating=10.0)
        
        if not movies_list:
            await event.message.answer("🐾 Не нашла фильмов с этой персоной. Попробуй уточнить запрос.")
            return
        
        if len(movies_list) > 100:
            await event.message.answer("🐾 Вау! Нашла много фильмов! Покажу топ-100.")
            movies_list = movies_list[:100]
        
        context = self._get_user_context(user_id)
        context['movies'] = movies_list
        context['query'] = query
        context['is_person_search'] = True
        
        await event.message.answer(f"Нашла {len(movies_list)} фильмов.")
        await self._show_person_search_page(event, user_id, 0, query)

    async def _show_search_page(self, event, user_id, page, query):
        context = self._get_user_context(user_id)
        movies_list = context.get('filtered_list') or context.get('full_list', [])
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
            f"📽 <b>Результаты поиска \"{query}\"</b>\n"
            f"Стр. {page+1} из {total_pages}\n"
            f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {len(movies_list)} 👍",
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
                        attachments=[self._get_movie_buttons(movie_details['id'], "search", user_id)]
                    )
        
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", query)
            await event.message.answer("🐾 Куда бежим дальше?", attachments=[pagination])
        else:
            await event.message.answer("🐾 Куда бежим дальше?", attachments=[get_action_keyboard("поиск", "search")])

    async def _show_person_search_page(self, event, user_id, page, query):
        context = self._get_user_context(user_id)
        movies_list = context.get('movies', [])
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
            f"🎭 <b>Фильмы с участием: {query}</b>\n"
            f"Стр. {page+1} из {total_pages}\n"
            f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {len(movies_list)} 👍",
            parse_mode="html"
        )
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_person_search=True, query=query)
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[self._get_movie_buttons(movie_details['id'], "person", user_id)]
                    )
        
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", query)
            await event.message.answer("🐾 Куда бежим дальше?", attachments=[pagination])
        else:
            await event.message.answer("🐾 Куда бежим дальше?", attachments=[get_action_keyboard("поиск по персонам", "person")])

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
            f"🎉 <b>Премьеры</b>\n"
            f"Стр. {page+1} из {total_pages}\n"
            f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {len(movies_list)} 👍",
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
                        attachments=[self._get_movie_buttons(movie_details['id'], "premiers", user_id)]
                    )
        
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "premiers", "")
            await event.message.answer("🐾 Куда бежим дальше?", attachments=[pagination])
        else:
            await event.message.answer("🐾 Куда бежим дальше?", attachments=[get_action_keyboard("премьеры", "premiers")])

    # ==================== СЛУЧАЙНЫЙ ФИЛЬМ ====================
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
        
        movie_id = movie_details.get('id')
        card_text, _ = format_movie_card(movie_details)
        if card_text:
            buttons = [
                [{"type": "callback", "text": "🐾 Мнение", "payload": f"opinion_{movie_id}_random"}],
                [{"type": "callback", "text": "🎲 Ещё случайный", "payload": "random"}],
                [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
            ]
            keyboard = InlineKeyboardMarkup(buttons)
            await send_func(card_text, parse_mode='html', attachments=[keyboard])
        else:
            await send_func("😢 Не могу показать карточку.")

    # ==================== МНЕНИЯ ====================
    async def _send_opinion_by_id(self, event, user_id, movie_id, source):
        movie_details = get_movie_details(movie_id)
        if not movie_details:
            await event.message.answer("😢 Не могу найти этот фильм.")
            return
        
        movie_name = movie_details.get('name', 'Без названия')
        movie_year = movie_details.get('year', '')
        
        # Проверяем лимиты
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        if stats['opinion_count'] >= limits['opinion_limit']:
            await event.message.answer(
                f"🐾 Гав! Сегодня я уже высказала максимальное количество мнений.\n"
                f"Ты использовал: {stats['opinion_count']} из {limits['opinion_limit']} доступных мнений.\n\n"
                f"Лимиты обновятся в полночь!"
            )
            return
        
        # Проверяем кэш
        cached = get_cached_opinion(movie_id)
        if cached:
            record_user_opinion(user_id, movie_id)
            increment_stat_counter(user_id, 'opinion_count')
            
            is_premium = limits['tariff_name'] in ['Ищейка', 'Вожак']
            text, keyboard = _format_opinion_with_buttons(
                cached, movie_name, movie_year, movie_id, source, user_id, is_premium
            )
            await event.message.answer(text, parse_mode="html", attachments=[keyboard])
            return
        
        # Генерируем новое мнение
        await event.message.answer(f"🎬 Смотрю фильм в ускоренном режиме... это займёт несколько секунд.")
        
        if not ai_client:
            await event.message.answer("😢 Генерация мнения временно недоступна.")
            return
        
        try:
            prompt = self._build_opinion_prompt(movie_details)
            
            response = ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Твои ответы должны быть дружелюбными, с юмором, но при этом информативными. Обязательно используй женский род."},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                timeout=60
            )
            
            opinion = response.choices[0].message.content
            
            save_opinion_cache(movie_id, opinion)
            record_user_opinion(user_id, movie_id)
            increment_stat_counter(user_id, 'opinion_count')
            
            is_premium = limits['tariff_name'] in ['Ищейка', 'Вожак']
            text, keyboard = _format_opinion_with_buttons(
                opinion, movie_name, movie_year, movie_id, source, user_id, is_premium
            )
            await event.message.answer(text, parse_mode="html", attachments=[keyboard])
            
        except Exception as e:
            logger.error(f"Ошибка генерации мнения: {e}")
            await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")

    def _build_opinion_prompt(self, movie_details):
        title = movie_details.get('name', 'Без названия')
        year = movie_details.get('year', '')
        countries = ', '.join(movie_details.get('countries', []))
        genres = ', '.join(movie_details.get('genres', []))
        
        directors_list = movie_details.get('directors', [])
        directors_str = ', '.join([d.get('name') or d.get('enName') for d in directors_list if d.get('name') or d.get('enName')])
        
        actors_list = movie_details.get('actors', [])[:7]
        actors_str = '\n'.join([f"• {a.get('name') or a.get('enName')}" for a in actors_list if a.get('name') or a.get('enName')])
        
        rating = movie_details.get('rating', 0)
        description = movie_details.get('description', 'Описание отсутствует')
        if description and len(description) > 800:
            description = description[:800] + '...'
        
        return f"""Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьем на хорошее кино.

Информация о фильме:
🎬 Название: {title} ({year})
🌍 Страна: {countries}
🎭 Жанр: {genres}
🎥 Режиссер: {directors_str}
⭐ Рейтинг Кинопоиска: {rating}
👥 В главных ролях:
{actors_str}

📝 Сюжет:
{description}

Требования к ответу:
1. Объем: 10-12 предложений
2. Без markdown-разметки
3. Только обычный текст
4. Разделяй части мнения переносами строк
5. Добавь собачий юмор
6. Говори о себе в женском роде
7. НЕ используй вводные фразы типа "Я посмотрела фильм и вот что думаю" - сразу начинай с содержательной части

Расскажи о:
- Настроении и смысле фильма
- Наградах (если знаешь точно)
- Особенностях
- Почему стоит посмотреть
- Плюсах и минусах

В конце обязательно добавь:
Оценка: от 5 до 10 (краткий комментарий почему)

После оценки добавь:
Настроение: 5 хэштегов (например #Радость #Грусть)
Атмосфера: 5 хэштегов (например #Мрачность #Яркость)"""

    # ==================== АГЕНТ ====================
    async def _handle_agent_show_cards(self, event, user_id):
        context = self._get_user_context(user_id)
        movies_list = context.get('movies', [])
        if not movies_list:
            await event.message.answer("😢 Нет фильмов для показа.")
            return
        
        await event.message.answer(f"🎬 Показываю {len(movies_list)} фильмов...")
        for movie_data in movies_list:
            card_text, _ = format_movie_card(movie_data)
            if card_text:
                await event.message.answer(
                    card_text,
                    parse_mode='html',
                    attachments=[self._get_movie_buttons(movie_data.get('id'), "search", user_id)]
                )
        
        buttons = [
            [{"type": "callback", "text": "🐺 Ещё КиноЛогово", "payload": "agent_menu"}],
            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await event.message.answer("🐾 Что дальше?", attachments=[keyboard])

    # ==================== ОБРАБОТЧИК СООБЩЕНИЙ ====================
    async def _handle_message(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        if not text or text.startswith("/"):
            return

        context = self._get_user_context(user_id)
        state = context.get('state')

        if state == 'awaiting_feedback_movie_id':
            await self._process_feedback_movie_id(event, user_id, text)
            return

        if state == 'awaiting_feedback_message':
            await self._process_feedback_message(event, user_id, text)
            return

        if state == 'awaiting_feedback_review':
            await self._process_feedback_review(event, user_id, text)
            return

        if state == 'awaiting_agent':
            await self._handle_agent(event, user_id, text)
            return

        if state == 'awaiting_search':
            await self._perform_search(event, user_id, text)
        elif state == 'awaiting_person':
            await self._perform_person_search(event, user_id, text)
        else:
            await self._perform_search(event, user_id, text)

    # ==================== FEEDBACK: ОБРАБОТКА ====================
    async def _process_feedback_movie_id(self, event, user_id, text):
        context = self._get_user_context(user_id)
        
        if text.lower() == 'нет':
            context['feedback_movie_id'] = None
        elif text.isdigit() and 2 < len(text) <= 10:
            context['feedback_movie_id'] = text
        else:
            await event.message.answer(
                "🐾 ID фильма должен быть числом от 3 до 10 цифр. Попробуй еще раз или введи 'нет':"
            )
            return
        
        context['state'] = 'awaiting_feedback_message'
        await event.message.answer("🐾 Теперь опиши подробнее что волнует:")

    async def _process_feedback_message(self, event, user_id, text):
        context = self._get_user_context(user_id)
        feedback_type = context.get('feedback_type', 1)
        movie_id = context.get('feedback_movie_id')
        
        save_feedback(user_id, feedback_type, movie_id, text)
        
        await event.message.answer(
            "🐾 Гав-гав! Спасибо за бдительность!\n\n"
            "Я записала твое сообщение и уже бегу разбираться. "
            "Мои тренеры проверят информацию и обязательно всё исправят!\n\n"
            "А пока можешь продолжить поиски отличного кино - мой нюх никогда не подводит! 🍿",
            attachments=[get_main_menu()]
        )
        
        context.pop('state', None)
        context.pop('feedback_type', None)
        context.pop('feedback_movie_id', None)

    async def _process_feedback_review(self, event, user_id, text):
        save_feedback(user_id, 2, None, text)
        
        await event.message.answer(
            "🐾 Спасибо за отзыв! Очень ценно твое мнение.",
            attachments=[get_main_menu()]
        )
        
        self.user_context.pop(user_id, None)

    # ==================== FEEDBACK: ПОКАЗ ====================
    async def _handle_feedback_callback(self, event, user_id, payload):
        if payload == "feedback" or payload == "feedback_back":
            await event.message.answer(
                "📝 <b>Обратная связь</b>\n\nВыбери тип обращения:",
                parse_mode="html",
                attachments=[get_feedback_menu()]
            )
            return
        
        if payload == "feedback_error":
            context = self._get_user_context(user_id)
            context['feedback_type'] = 1
            context['state'] = 'awaiting_feedback_movie_id'
            text = (
                "🐾 <b>Помоги мне исправить ошибку!</b>\n\n"
                "Для быстрого решения укажи ID фильма одним из способов:\n\n"
                "🔹 <b>Способ 1</b> — В карточке фильма в боте:\n"
                "   Найди ссылку https://www.kinopoisk.ru/film/23200/\n"
                "   Цифры в конце — это ID (в примере: 23200)\n\n"
                "🔹 <b>Способ 2</b> — На сайте Кинопоиска:\n"
                "   Открой карточку фильма, ID в адресной строке\n\n"
                "📌 ID всегда число от 1 до 10 цифр\n\n"
                "Если ошибка не связана с фильмом, напиши «нет»"
            )
            await event.message.answer(text, parse_mode="html")
            return
        
        if payload == "feedback_review":
            context = self._get_user_context(user_id)
            context['feedback_type'] = 2
            context['state'] = 'awaiting_feedback_review'
            await event.message.answer("🐾 Напиши свой отзыв о моих навыках:")
            return
        
        if payload == "feedback_list":
            await self._show_user_feedback(event, user_id, 0)
            return

    async def _show_user_feedback(self, event, user_id, page=0):
        items_per_page = 5
        conn = db_module.get_opinions_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, type, movie_id, message, status, created_at, admin_comment
            FROM feedback 
            WHERE user_id = ? AND status != 'archive'
            ORDER BY created_at DESC
        ''', (user_id,))
        all_feedback = cursor.fetchall()
        conn.close()
        
        if not all_feedback:
            await event.message.answer(
                "🐾 У тебя пока нет обращений.",
                attachments=[get_feedback_menu()]
            )
            return
        
        total_items = len(all_feedback)
        total_pages = (total_items + items_per_page - 1) // items_per_page
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        feedback_list = all_feedback[start_idx:end_idx]
        
        status_icons = {'new': '🆕', 'in_progress': '🔄', 'resolved': '✅'}
        type_names = {1: '🐛 Ошибка', 2: '📢 Отзыв'}
        
        text = f"📝 <b>Твои обращения</b> (Стр. {page+1} из {total_pages})\n\n"
        for fb in feedback_list:
            fb_id, fb_type, movie_id, message, status, created_at, comment = fb
            status_icon = status_icons.get(status, '📌')
            type_name = type_names.get(fb_type, '📝')
            created_date = created_at[:10] if created_at else "неизвестно"
            message_preview = message[:100] + ('...' if len(message) > 100 else '')
            text += f"{status_icon} #{fb_id} {type_name}\n"
            text += f"📅 {created_date}\n"
            if movie_id:
                text += f"🎬 Фильм: {movie_id}\n"
            text += f"💬 {message_preview}\n"
            if comment:
                text += f"📝 Ответ: {comment[:100]}\n"
            text += "\n"
        
        pagination = get_feedback_pagination_buttons(page, total_pages)
        await event.message.answer(text, parse_mode="html", attachments=[pagination])

    # ==================== FAQ ====================
    async def _handle_faq_callback(self, event, user_id, payload):
        if payload == "faq" or payload == "faq_back":
            text = "❓ <b>Часто задаваемые вопросы</b>\n\nВыбери вопрос из меню ниже:"
            await event.message.answer(text, parse_mode="html", attachments=[get_faq_menu()])
            return
        
        if payload == "faq_search":
            text = (
                "🔍 <b>Как найти фильм?</b>\n\n"
                "1. Нажми кнопку «🔍 Поиск» в главном меню\n"
                "2. Введи название фильма\n"
                "3. Используй фильтры для уточнения\n"
                "4. Нажми «Показать карточки»\n\n"
                "Также можно искать по персонам кнопкой «🎭 Поиск по персонам»"
            )
        elif payload == "faq_opinion":
            text = (
                "💬 <b>Как узнать мнение о фильме?</b>\n\n"
                "После того как я покажу карточку фильма, нажми кнопку «🐾 Мнение».\n"
                "Я посмотрю фильм в ускоренном режиме и поделюсь впечатлениями!\n\n"
                "Лимит: 5 мнений в день для бесплатного тарифа."
            )
        elif payload == "faq_limits":
            text = (
                "⚠️ <b>Лимиты бота</b>\n\n"
                "У меня есть суточные лимиты на запросы:\n"
                "• 🐶 Щенячий азарт: 5 мнений в день (бесплатно)\n"
                "• 🐕 Охотничий: 10 мнений в день\n"
                "• 🕵️ Ищейка: 30 мнений в день + 5 свежих взглядов\n"
                "• 🐺 Вожак: безлимит + безлимит свежих взглядов\n\n"
                "Лимиты сбрасываются в полночь!"
            )
        elif payload == "faq_suggest":
            text = (
                "📢 <b>Предложить улучшение</b>\n\n"
                "Если у тебя есть идеи, как сделать меня лучше, воспользуйся кнопкой «📝 Обратная связь»\n"
                "Я люблю апдейты и новые тренировки, как косточки! 🦴"
            )
        else:
            text = "🐾 Выбери вопрос из меню"
        await event.message.answer(text, parse_mode="html", attachments=[get_faq_menu()])

    # ==================== ФИЛЬТРЫ ====================
    async def _handle_filter(self, event, user_id, query, filter_type, value):
        context = self._get_user_context(user_id)
        filters = context.get('filters', {})
        if filters.get(filter_type) == value:
            filters.pop(filter_type, None)
        else:
            filters[filter_type] = value
        context['filters'] = filters
        
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
            rating_names = {
                'new': '🆕 Новинки', '5-6': '⭐5-6', '6-7': '⭐6-7',
                '7-8': '⭐7-8', '8-9': '⭐8-9', '9-10': '⭐9-10'
            }
            decade_names = {
                'pre1980': '📽 До1980', '1980s': '📅1980-е', '1990s': '📅1990-е',
                '2000s': '📅2000-е', '2010s': '📅2010-е', '2020s': '📅2020-е'
            }
            if filters.get('rating_range'):
                text += f"• {rating_names.get(filters['rating_range'], filters['rating_range'])}\n"
            if filters.get('decade'):
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

    # ==================== АГЕНТ (Chat) ====================
    async def _handle_agent(self, event: MessageCreated, user_id: int, query: str):
        context = self._get_user_context(user_id)
        agent_mode = context.get('agent_mode', 'chat')
        
        if user_id not in ADMIN_IDS:
            limits = get_user_limits(user_id)
            stats = get_user_stats(user_id, date.today().isoformat())
            if stats.get('opinion_count', 0) >= limits.get('opinion_limit', 5):
                await event.message.answer(
                    f"🐾 Сегодня у тебя уже использовано {stats['opinion_count']} мнений.\n"
                    f"КиноЛогово — платная фишка!\n\n"
                    f"💰 Оформи подписку для безлимита!"
                )
                return

        if agent_mode == 'chat':
            if _is_search_intent(query):
                buttons = [
                    [{"type": "callback", "text": "🔍 Поиск по названию", "payload": "search"}],
                    [{"type": "callback", "text": "🎭 Поиск по персонам", "payload": "person"}],
                    [{"type": "callback", "text": "🎲 Случайный фильм", "payload": "random"}],
                    [{"type": "callback", "text": "🐺 КиноЛогово", "payload": "agent_menu"}]
                ]
                keyboard = InlineKeyboardMarkup(buttons)
                await event.message.answer(
                    "🐾 Ой, я чувствую, что тут пахнет поиском! 🔍\n\n"
                    "Для этого у меня есть специальные команды.\n"
                    "Выбери, что нужно:",
                    attachments=[keyboard]
                )
                return
            
            thinking_msg = await event.message.answer("💬 Дай-ка подумаю... 🐾")
            
            async def delete_after_delay():
                await asyncio.sleep(2)
                try:
                    await thinking_msg.delete()
                except Exception:
                    pass
            
            asyncio.create_task(delete_after_delay())
            
            enhanced_query = f"Ответь коротко (2-3 предложения) и интересно: {query}"
            
            if not ai_client:
                await event.message.answer("😢 Генерация временно недоступна.")
                return
            
            try:
                response = await run_agent(enhanced_query, user_id, ai_client, agent_mode, chat_mode=True)
                
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
                
                keyboard = InlineKeyboardMarkup([
                    [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
                ])
                await event.message.answer(response, attachments=[keyboard])
                
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")
            return

        # ===== АКТЁРСКИЙ НЮХ =====
        if agent_mode == 'actor':
            enhanced_query = f"""
            Ты — КиноИщейка, кинокритик с отличным нюхом на таланты. 🐕

            Пользователь спрашивает о персоне: {query}

            Найди в базе этого актёра или режиссёра и сделай разбор:
            1. Лучшие роли/работы (с рейтингом и кратким объяснением почему)
            2. Самые недооценённые фильмы (те, где он сыграл гениально, но прошли незамеченными)
            3. Если указан период (например "после 2010"), учти это
            4. Если указан жанр — учти и его
            5. Укажи общее количество фильмов с этой персоной

            В конце дай рекомендацию — какой фильм посмотреть первым.

            ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате ссылки в названии.
            """
            await event.message.answer("🐾 Нюхаю лучшие роли...")
            
            if not ai_client:
                await event.message.answer("😢 Генерация временно недоступна.")
                return
            
            try:
                response = await run_agent(enhanced_query, user_id, ai_client, agent_mode)
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
                
                movie_ids = extract_movie_ids(response)
                logger.info(f"Найдено ID в ответе агента: {movie_ids}")
                
                if movie_ids:
                    movies_list = []
                    for movie_id in movie_ids[:10]:
                        movie_details = get_movie_details(movie_id)
                        if movie_details:
                            movies_list.append(movie_details)
                        else:
                            logger.warning(f"Фильм с ID {movie_id} не найден в БД")
                    
                    if movies_list:
                        context['movies'] = movies_list
                        context['query'] = f'актёрский нюх: {query[:30]}...'
                        
                        keyboard = InlineKeyboardMarkup([
                            [{"type": "callback", "text": f"🎬 Показать карточки ({len(movies_list)})", "payload": "agent_show_cards"}],
                            [{"type": "callback", "text": "🐾 Ещё актёрский нюх", "payload": "agent_actor"}],
                            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
                        ])
                        await event.message.answer(response, attachments=[keyboard])
                        return
                
                keyboard = get_action_keyboard("актёрский нюх", "agent_actor")
                await event.message.answer(response, attachments=[keyboard])
                
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")
            return

        # ===== ПО СЮЖЕТУ =====
        if agent_mode == 'plot_search':
            enhanced_query = f"""
            Ты — КиноИщейка, собака-девочка с отличным нюхом на сюжеты. 🐕

            Пользователь описал, что хочет посмотреть: {query}

            Твоя задача:
            1. Найди в базе 3 фильма, которые лучше всего подходят под это описание
            2. Для каждого: название (год), рейтинг, краткое объяснение, почему он подходит под описание
            3. В конце посоветуй, с какого начать

            ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате ссылки в названии.
            """
            await event.message.answer("🔎 Нюхаю сюжеты...")
            
            if not ai_client:
                await event.message.answer("😢 Генерация временно недоступна.")
                return
            
            try:
                response = await run_agent(enhanced_query, user_id, ai_client, agent_mode)
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
                
                movie_ids = extract_movie_ids(response)
                if movie_ids:
                    movies_list = []
                    for movie_id in movie_ids[:10]:
                        movie_details = get_movie_details(movie_id)
                        if movie_details:
                            movies_list.append(movie_details)
                    
                    if movies_list:
                        context['movies'] = movies_list
                        context['query'] = f'по сюжету: {query[:30]}...'
                        
                        keyboard = InlineKeyboardMarkup([
                            [{"type": "callback", "text": f"🎬 Показать карточки ({len(movies_list)})", "payload": "agent_show_cards"}],
                            [{"type": "callback", "text": "🔎 Ещё поиск по сюжету", "payload": "agent_plot_search"}],
                            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
                        ])
                        await event.message.answer(response, attachments=[keyboard])
                        return
                
                keyboard = get_action_keyboard("поиск по сюжету", "agent_plot_search")
                await event.message.answer(response, attachments=[keyboard])
                
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")
            return

        # ===== ПОДОБРАТЬ ФИЛЬМ =====
        if agent_mode == 'recommend':
            enhanced_query = f"""
            Ты — КиноИщейка, собака-девочка с отличным чутьем на хорошее кино. 🐕

            Пользователь хочет подобрать фильм: {query}

            Найди в базе 5 лучших фильмов, которые подходят под описание.
            Для каждого: название (год), рейтинг, краткое объяснение почему он подходит.
            В конце дай совет, с чего начать.

            ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате ссылки в названии.
            """
            await event.message.answer("🎬 Нюхаю лучшие фильмы для тебя...")
            
            if not ai_client:
                await event.message.answer("😢 Генерация временно недоступна.")
                return
            
            try:
                response = await run_agent(enhanced_query, user_id, ai_client, agent_mode)
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
                
                movie_ids = extract_movie_ids(response)
                if movie_ids:
                    movies_list = []
                    for movie_id in movie_ids[:10]:
                        movie_details = get_movie_details(movie_id)
                        if movie_details:
                            movies_list.append(movie_details)
                    
                    if movies_list:
                        context['movies'] = movies_list
                        context['query'] = f'подборка: {query[:30]}...'
                        
                        keyboard = InlineKeyboardMarkup([
                            [{"type": "callback", "text": f"🎬 Показать карточки ({len(movies_list)})", "payload": "agent_show_cards"}],
                            [{"type": "callback", "text": "🎬 Ещё подборку", "payload": "agent_recommend"}],
                            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
                        ])
                        await event.message.answer(response, attachments=[keyboard])
                        return
                
                keyboard = get_action_keyboard("подборку", "agent_recommend")
                await event.message.answer(response, attachments=[keyboard])
                
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")
            return

        # ===== СРАВНИТЬ =====
        if agent_mode == 'compare':
            await event.message.answer("⭐ Сравниваю фильмы...")
            
            enhanced_query = f"""
            Ты — КиноИщейка, кинокритик. Сравни два фильма: {query}

            Сравни по:
            1. Рейтингу
            2. Жанрам
            3. Главным актёрам
            4. Режиссёру
            5. Сюжету и атмосфере

            В конце скажи, что лучше и почему.

            ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате ссылки в названии.
            """
            
            if not ai_client:
                await event.message.answer("😢 Генерация временно недоступна.")
                return
            
            try:
                response = await run_agent(enhanced_query, user_id, ai_client, agent_mode)
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
                
                keyboard = get_action_keyboard("сравнение", "agent_compare")
                await event.message.answer(response, attachments=[keyboard])
                
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")
            return

    # ==================== РЕГЕНЕРАЦИЯ МНЕНИЯ ====================
    async def _handle_regenerate(self, event, user_id, movie_id, source):
        movie_details = get_movie_details(movie_id)
        if not movie_details:
            await event.message.answer("😢 Не могу найти этот фильм.")
            return
        
        movie_name = movie_details.get('name', 'Без названия')
        movie_year = movie_details.get('year', '')
        
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        if limits['tariff_name'] not in ['Ищейка', 'Вожак']:
            await event.message.answer(
                "🔄 Свежий взгляд доступен только на тарифах «Ищейка» и «Вожак».\n\n"
                "💰 Оформи подписку, чтобы перегенерировать мнения!"
            )
            return
        
        if stats['regeneration_count'] >= limits.get('regeneration_limit', 0):
            await event.message.answer(
                f"🐾 Сегодня ты уже использовал {stats['regeneration_count']} свежих взглядов.\n"
                f"Доступно: {limits['regeneration_limit']}.\n\n"
                f"Лимиты обновятся в полночь!"
            )
            return
        
        if not ai_client:
            await event.message.answer("😢 Генерация временно недоступна.")
            return
        
        await event.message.answer("🔄 Пересматриваю фильм с новым взглядом...")
        
        try:
            prompt = self._build_opinion_prompt(movie_details) + "\n\nСделай свежий взгляд — новое мнение, не повторяйся."
            
            response = ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Ты уже смотрела этот фильм, теперь посмотри свежим взглядом."},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                timeout=60
            )
            
            opinion = response.choices[0].message.content
            
            save_opinion_cache(movie_id, opinion)
            increment_stat_counter(user_id, 'regeneration_count')
            
            is_premium = True
            text, keyboard = _format_opinion_with_buttons(
                opinion, movie_name, movie_year, movie_id, source, user_id, is_premium
            )
            await event.message.answer(text, parse_mode="html", attachments=[keyboard])
            
        except Exception as e:
            logger.error(f"Ошибка регенерации: {e}")
            await event.message.answer("🐾 Гав! Что-то пошло не так. Попробуй позже!")

    # ==================== ОПИНИОН КОМАНДА ====================
    async def _handle_opinion_command(self, event: MessageCreated):
        text = event.message.body.text
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await event.message.answer("🐾 Укажи название или ID фильма. Например: /opinion 435")
            return
        
        query = parts[1].strip()
        
        if query.isdigit():
            movie_id = int(query)
            await self._send_opinion_by_id(event, event.message.sender.user_id, movie_id, "opinion")
            return
        
        # Поиск по названию
        results = search_movies_in_db(query, limit=5)
        if not results:
            await event.message.answer("🐾 Не нашла фильмов с таким названием.")
            return
        
        if len(results) == 1:
            await self._send_opinion_by_id(event, event.message.sender.user_id, results[0]['id'], "opinion")
            return
        
        # Несколько результатов
        text = "🐾 Нашла несколько фильмов. Уточни ID:\n\n"
        for movie in results[:5]:
            text += f"<b>{movie['name']}</b> ({movie['year']}) — ID: <code>{movie['id']}</code>\n"
        text += "\nНапример: /opinion 435"
        await event.message.answer(text, parse_mode="html")

    # ==================== RUN ====================
    def run(self):
        logger.info("🚀 Запускаю MaxAdapter...")
        self.dp.run_polling(self.bot)

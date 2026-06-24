# core/max_adapter.py - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ С ПОДДЕРЖКОЙ ЗАГЛУШЕК
# + Карточки-заглушки для фильмов, которых нет в БД
# + Извлечение ID из ссылок Кинопоиска
# + Уточнение подборок (1 раз бесплатно)
# + Сообщения о начале работы в КиноЛогово

import logging
import configparser
import os
import sys
import re
import asyncio
from datetime import date, datetime, timedelta
from typing import List, Dict

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
ADMIN_IDS = [7191208]  # Замените на свой ID
logger.info(f"👑 Администраторы: {ADMIN_IDS}")

# ==================== ИМПОРТЫ ИЗ CORE ====================
import user as user_module
import movie as movie_module
import db as db_module
from core.agent import run_agent, clear_chat_history, extract_movie_ids

register_user = user_module.register_user
get_user_limits = user_module.get_user_limits
get_user_stats = user_module.get_user_stats
increment_stat_counter = user_module.increment_stat_counter
record_user_opinion = user_module.record_user_opinion

get_random_movie_from_db = movie_module.get_random_movie_from_db
get_movie_details = movie_module.get_movie_details
format_movie_card = movie_module.format_movie_card
format_missing_movie_card = movie_module.format_missing_movie_card
search_movies_in_db = movie_module.search_movies_in_db
search_movies_by_person_in_db = movie_module.search_movies_by_person_in_db
get_premier_movies_from_db = movie_module.get_premier_movies_from_db
search_movies_with_filters = movie_module.search_movies_with_filters


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
            {"type": "callback", "text": "❓ FAQ", "payload": "faq"}
        ],
        [
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

def get_opinion_button(movie_id: int, source: str = "search"):
    buttons = [
        [{"type": "callback", "text": "🐾 Мнение о фильме", "payload": f"opinion_{movie_id}_{source}"}]
    ]
    return InlineKeyboardMarkup(buttons)

def get_pagination_buttons(current_page: int, total_pages: int, prefix: str, query: str = ""):
    buttons = []
    row = []
    if current_page > 0:
        row.append({"type": "callback", "text": "◀️ Назад", "payload": f"{prefix}_page_{current_page-1}_{query}"})
    row.append({"type": "callback", "text": f"📄 Стр. {current_page+1} из {total_pages}", "payload": "noop"})
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
    row.append({"type": "callback", "text": f"📄 Стр. {page+1} из {total_pages}", "payload": "noop"})
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


def get_month_year_keyboard():
    """Клавиатура для выбора месяца и года (премьеры) - 12 месяцев, начиная с 3 месяцев назад"""
    current_date = datetime.now()
    current_year = current_date.year
    current_month = current_date.month
    
    month_names = {
        1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр",
        5: "Май", 6: "Июн", 7: "Июл", 8: "Авг",
        9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек"
    }
    
    buttons = []
    
    for i in range(12):
        month = current_month - 3 + i
        year = current_year
        if month <= 0:
            month += 12
            year -= 1
        elif month > 12:
            month -= 12
            year += 1
        
        row_index = i // 4
        if len(buttons) <= row_index:
            buttons.append([])
        buttons[row_index].append({
            "type": "callback",
            "text": f"{month_names[month]} {year}",
            "payload": f"premiers_month_{month}_{year}"
        })
    
    buttons.append([
        {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
    ])
    return InlineKeyboardMarkup(buttons)


def _format_opinion_with_buttons(opinion, movie_name, movie_year, movie_id, source, user_id, is_premium):
    """Форматирует мнение с кнопками прямо в одном сообщении"""
    kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"
    title_with_link = f"<a href='{kp_url}'><b>{movie_name}</b></a> ({movie_year})"
    
    footer = (
        "\n\n🐾 <a href='https://shortmax.ru/Movie_dog_channel'>КиноИщейка в Max</a>\n"
        "🤖 <a href='https://max.ru/id503111716818_1_bot'>Кинобот в Max</a>"
    )
    
    text = f"🐾 Я посмотрела {title_with_link}, и вот что думаю:\n\n{opinion}\n\n🔗 {kp_url}{footer}\n\n🐾"
    
    buttons = []
    
    if is_premium:
        buttons.append([
            {"type": "callback", "text": "🔄 Свежий взгляд", "payload": f"regenerate_{movie_id}_{source}"}
        ])
    
    if source == "random":
        buttons.append([
            {"type": "callback", "text": "🎲 Новый случайный", "payload": "random"}
        ])
        buttons.append([
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    elif source == "search":
        buttons.append([
            {"type": "callback", "text": "🔍 Новый поиск", "payload": "search"}
        ])
        buttons.append([
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    elif source == "person":
        buttons.append([
            {"type": "callback", "text": "🎭 Новые персоны", "payload": "person"}
        ])
        buttons.append([
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    elif source == "premiers":
        buttons.append([
            {"type": "callback", "text": "🎉 Новые премьеры", "payload": "premiers"}
        ])
        buttons.append([
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    else:
        buttons.append([
            {"type": "callback", "text": "🐺 КиноЛогово", "payload": "agent_menu"}
        ])
        buttons.append([
            {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
        ])
    
    keyboard = InlineKeyboardMarkup(buttons)
    return text, keyboard


# ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================
def _is_search_intent(text: str) -> bool:
    keywords = ['найди', 'поищи', 'ищи', 'покажи', 'фильм с', 'актёр', 'режиссёр', 'найти', 'подбери']
    return any(kw in text.lower() for kw in keywords)


def _is_premium_tariff(tariff_name: str) -> bool:
    return tariff_name in ['Ищейка', 'Вожак']


def _extract_movie_name_from_response(response: str, movie_id: int) -> str:
    """Пытается извлечь название фильма из ответа DeepSeek по ID"""
    if not response:
        return None
    
    # Ищем ссылку с этим ID и извлекаем текст между <a> и </a>
    pattern = rf'<a\s+href=[\'"]?https?://www\.kinopoisk\.ru/film/{movie_id}/[\'"]?>(.*?)</a>'
    match = re.search(pattern, response, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Если не нашли — ищем (ID: число) с названием рядом
    pattern2 = rf'([^\(]+?)\s*\(ID:\s*{movie_id}\)'
    match2 = re.search(pattern2, response, re.IGNORECASE)
    if match2:
        return match2.group(1).strip()
    
    return None


def _prepare_movies_with_placeholders(movie_ids: List[int], response: str = "") -> List[Dict]:
    """
    Подготавливает список фильмов, заменяя отсутствующие на заглушки
    Возвращает список с полями: id, name, year, details, is_missing
    """
    movies_list = []
    
    for movie_id in movie_ids:
        movie_details = get_movie_details(movie_id)
        
        if movie_details:
            movies_list.append({
                'id': movie_id,
                'name': movie_details.get('name', f'Фильм {movie_id}'),
                'year': movie_details.get('year', ''),
                'details': movie_details,
                'is_missing': False
            })
        else:
            name = _extract_movie_name_from_response(response, movie_id)
            movies_list.append({
                'id': movie_id,
                'name': name or f'Фильм {movie_id}',
                'year': '',
                'details': None,
                'is_missing': True
            })
    
    return movies_list


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
        logger.info("✅ MaxAdapter инициализирован (с поддержкой заглушек)")

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
                "📅 <b>Выбери месяц и год для премьер:</b>",
                parse_mode="html",
                attachments=[get_month_year_keyboard()]
            )

        @self.dp.message_created(F.message.body.text == "/person")
        async def on_person(event: MessageCreated):
            user_id = event.message.sender.user_id
            self._get_user_context(user_id)['state'] = 'awaiting_person'
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")

        @self.dp.message_created(F.message.body.text == "/profile")
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)

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
        if payload.startswith("premiers_month_"):
            parts = payload.split("_")
            month = int(parts[2])
            year = int(parts[3]) if len(parts) > 3 else datetime.now().year
            await self._handle_premiers_by_month_year(event, user_id, month, year)
            return

        if payload == "premiers":
            await event.message.answer(
                "📅 <b>Выбери месяц и год для премьер:</b>",
                parse_mode="html",
                attachments=[get_month_year_keyboard()]
            )
            return

        if payload.startswith("premiers_page_"):
            parts = payload.split("_")
            page = int(parts[2])
            await self._show_premiers_page(event, user_id, page)
            return

        if payload.startswith("premiers_year_"):
            year = int(payload.split("_")[2])
            await event.message.answer(
                "📅 <b>Выбери месяц для премьер:</b>",
                parse_mode="html",
                attachments=[get_month_year_keyboard()]
            )
            return

        # ===== МЕНЮ КиноЛогово =====
        if payload == "agent_menu":
            await event.message.answer(
                "🐺 <b>КиноЛогово</b> — мой умный режим!\n\n"
                "Я умею не просто искать, а думать и советовать.\n\n"
                "🎬 <b>Подобрать фильм</b> — расскажи, что хочешь посмотреть, я подберу лучшее\n"
                "🐾 <b>Актёрский нюх</b> — анализ ролей актёра или режиссёра\n"
                "⭐ <b>Сравнить фильмы</b> — сравню два фильма и скажу, что лучше\n"
                "🔎 <b>По сюжету</b> — найду фильмы по описанию",
                parse_mode="html",
                attachments=[get_agent_menu()]
            )
            return

        # ===== СЦЕНАРИИ КиноЛогово =====
        if payload == "agent_recommend":
            self._get_user_context(user_id)['agent_mode'] = 'recommend'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🎬 <b>Подобрать фильм</b>\n\n"
                "Расскажи, что ты хочешь посмотреть, и я подберу идеальные варианты!\n\n"
                "📌 <b>Что можно указать:</b>\n"
                "• Жанр: комедия, драма, триллер, ужасы, фантастика...\n"
                "• Настроение: весёлое, грустное, напряжённое, романтичное...\n"
                "• Эпоху или стиль: 80-е, ретро, киберпанк, костюмная драма...\n"
                "• Любимые фильмы: например, «как Титаник» или «что-то похожее на Интерстеллар»\n"
                "• Актёра или режиссёра: например, «с Ди Каприо» или «как у Тарантино»\n\n"
                "📝 <b>Примеры запросов:</b>\n"
                "🔹 «Драма про любовь, как в Дневнике памяти»\n"
                "🔹 «Что-то смешное и лёгкое на вечер»\n"
                "🔹 «Фантастика с глубоким смыслом»\n"
                "🔹 «Фильм, похожий на Бойцовский клуб»\n\n"
                "Просто напиши, и я подберу для тебя лучшие варианты! 🐾",
                parse_mode="html"
            )
            return

        if payload == "agent_actor":
            self._get_user_context(user_id)['agent_mode'] = 'actor'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🐾 <b>Актёрский нюх</b>\n\n"
                "Я проанализирую карьеру актёра или режиссёра и покажу его лучшие работы!\n\n"
                "📌 <b>Что можно указать:</b>\n"
                "• Имя актёра: «Брэд Питт», «Мэрил Стрип»\n"
                "• Имя режиссёра: «Кристофер Нолан», «Квентин Тарантино»\n"
                "• Период: «фильмы Ди Каприо после 2010»\n"
                "• Жанр: «боевики с Джейсоном Стэтхэмом»\n\n"
                "📝 <b>Примеры запросов:</b>\n"
                "🔹 «Том Хэнкс»\n"
                "🔹 «Фильмы с Джимом Керри в 90-х»\n"
                "🔹 «Лучшие роли Кейт Бланшетт»\n"
                "🔹 «Что посмотреть с Аль Пачино»\n\n"
                "Напиши имя, и я сделаю разбор с душой! 🐾",
                parse_mode="html"
            )
            return

        if payload == "agent_compare":
            self._get_user_context(user_id)['agent_mode'] = 'compare'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "⭐ <b>Сравнить фильмы</b>\n\n"
                "Напиши два фильма, и я сравню их по всем параметрам!\n\n"
                "📌 <b>Что можно сравнить:</b>\n"
                "• Два любых фильма: «Матрица и Начало»\n"
                "• Фильмы одного жанра: «Лучшие комедии 90-х»\n"
                "• Фильмы одного режиссёра: «Интерстеллар и Довод»\n"
                "• Фильмы с одним актёром: «Остров проклятых и Волк с Уолл-стрит»\n\n"
                "📝 <b>Примеры запросов:</b>\n"
                "🔹 «Сравни Гладиатора и Трою»\n"
                "🔹 «Что лучше: Терминатор или Робокоп?»\n"
                "🔹 «Начало против Матрицы»\n"
                "🔹 «Сравни Титаник и Аватар»\n\n"
                "Напиши, и я разложу всё по косточкам! 🐾",
                parse_mode="html"
            )
            return

        if payload == "agent_plot_search":
            self._get_user_context(user_id)['agent_mode'] = 'plot_search'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🔎 <b>Поиск по сюжету</b>\n\n"
                "Опиши, что ты хочешь увидеть, и я найду фильмы по описанию!\n\n"
                "📌 <b>Что можно указать:</b>\n"
                "• Ключевые события: «путешествие во времени», «побег из тюрьмы»\n"
                "• Настроение: «чтобы было страшно», «чтобы поплакать»\n"
                "• Особенности: «неожиданный поворот», «открытый финал»\n"
                "• Персонажи: «одинокий герой», «команда неудачников»\n\n"
                "📝 <b>Примеры запросов:</b>\n"
                "🔹 «Фильм про путешествие во времени с романтикой»\n"
                "🔹 «Человек теряет память и ищет себя»\n"
                "🔹 «Фильм, где есть неожиданный поворот в конце»\n"
                "🔹 «История о выживании в открытом море»\n\n"
                "Я поищу в своей базе и подберу лучшие варианты! 🐾",
                parse_mode="html"
            )
            return

        # ===== СВОБОДНЫЙ ДИАЛОГ =====
        if payload == "chat":
            clear_chat_history(user_id)
            self._get_user_context(user_id)['agent_mode'] = 'chat'
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "💬 <b>Пообщаться с КиноИщейкой</b>\n\n"
                "Задай любой вопрос про кино, и я отвечу коротко и интересно!\n\n"
                "📌 <b>О чём можно спросить:</b>\n"
                "• Факты о фильмах и актёрах\n"
                "• Забавные детали со съёмок\n"
                "• Смысл фильма или концовки\n"
                "• Личное мнение о фильме\n"
                "• Кто снимался и в чём ещё\n"
                "• Любопытные киноляпы\n\n"
                "📝 <b>Примеры вопросов:</b>\n"
                "🔹 «Почему в Матрице всё зелёное?»\n"
                "🔹 «Сколько длился съёмки Властелина колец?»\n"
                "🔹 «Какой фильм самый дорогой в истории?»\n"
                "🔹 «Что значит финал Начала?»\n\n"
                "💡 <b>Важно:</b> если захочешь найти фильм — я предложу нужные команды!\n\n"
                "Пиши, я готова поболтать! 🐾",
                parse_mode="html"
            )
            return

        # ===== УТОЧНЕНИЕ ПОДБОРКИ =====
        if payload.startswith("agent_refine_"):
            mode = payload.replace("agent_refine_", "")
            context = self._get_user_context(user_id)
            
            # Проверяем, не уточняли ли уже
            if context.get('refined', False):
                await event.message.answer(
                    "🐾 Ты уже уточнял эту подборку. Могу предложить начать новую!",
                    attachments=[get_agent_menu()]
                )
                return
            
            context['refine_mode'] = mode
            context['state'] = 'awaiting_refine'
            await event.message.answer(
                "🔄 Напиши, что изменить в подборке:\n\n"
                "Например:\n"
                "• «Убери старые фильмы»\n"
                "• «Добавь больше комедий»\n"
                "• «Я уже смотрел эти фильмы»\n"
                "• «Сделай более мрачную атмосферу»"
            )
            return

        # ===== АГЕНТ — ПОКАЗ КАРТОЧЕК =====
        if payload == "agent_show_cards":
            await self._handle_agent_show_cards(event, user_id)
            return

        # ===== ЗАГЛУШКИ В ПРОФИЛЕ =====
        if payload == "favorites_soon":
            await event.message.answer(
                "❤️ <b>Любимые фильмы</b>\n\n"
                "Эта функция скоро появится!\n"
                "Ты сможешь сохранять фильмы в любимые и возвращаться к ним в любой момент.",
                parse_mode="html",
                attachments=[get_action_keyboard(None, None, None)]
            )
            return

        # ===== ПОИСК НА ДРУГИХ ПРОСТОРАХ =====
        if payload.startswith("search_elsewhere_"):
            movie_id = int(payload.split("_")[2])
            await event.message.answer(
                f"🔍 Ищу фильм ID: {movie_id} в других источниках...\n\n"
                "Сейчас я могу предложить:\n"
                f"• <a href='https://www.kinopoisk.ru/film/{movie_id}/'>Кинопоиск</a>\n"
                "• <a href='https://www.imdb.com/find?q='>IMDb</a> (в разработке)\n\n"
                "Скоро я смогу загружать фильмы напрямую из API! 🐾",
                parse_mode="html"
            )
            return
        
        if payload == "feedback_soon":
            await event.message.answer(
                "📝 <b>Мои обращения</b>\n\n"
                "Эта функция скоро появится!\n"
                "Ты сможешь видеть все свои обращения к тренерам и их ответы.",
                parse_mode="html",
                attachments=[get_action_keyboard(None, None, None)]
            )
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
        elif payload == "profile":
            await self._handle_profile(event)
        else:
            await event.message.answer(f"🐾 Хм... Я не поняла, что ты хочешь. Давай начнём сначала — выбери кнопку в меню!")

    # ==================== ПРЕМЬЕРЫ ПО МЕСЯЦУ + ГОДУ ====================
    async def _handle_premiers_by_month_year(self, event, user_id, month, year):
        await event.message.answer(f"📅 Загружаю премьеры за {month}.{year}...")
        
        all_premiers = get_premier_movies_from_db()
        
        filtered = []
        for movie in all_premiers:
            premiere_date = movie.get('premiere_russia') or movie.get('premiere_world')
            if premiere_date:
                try:
                    d = datetime.strptime(premiere_date[:10], "%Y-%m-%d")
                    if d.month == month and d.year == year:
                        filtered.append(movie)
                except:
                    pass
        
        if not filtered:
            await event.message.answer(f"😢 Нет премьер за {month}.{year}.")
            return
        
        context = self._get_user_context(user_id)
        context['premiers'] = filtered
        await self._show_premiers_page(event, user_id, 0)

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
                "После того как я покажу карточку фильма, нажми кнопку «🐾 Мнение о фильме».\n"
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

    # ==================== FEEDBACK ====================
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
        await event.message.answer("🐾 Возвращаюсь в меню обратной связи", attachments=[get_feedback_menu()])

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
                "🐾 У тебя пока нет обращений.\n\n"
                "Ты можешь оставить отзыв или сообщить об ошибке через кнопку «📝 Обратная связь»",
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
        text = f"📝 <b>Твои обращения</b> (📄 Стр. {page+1} из {total_pages})\n\n"
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
        total_movies = len(movies_list)
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_movies)
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details)
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[get_opinion_button(movie_details['id'], "search")]
                    )
        
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", current_query)
            await event.message.answer(
                f"📽 <b>Результаты поиска \"{current_query}\"</b>\n"
                f"📄 Стр. {page+1} из {total_pages}\n"
                f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {total_movies} ☝️\n\nКуда бежим дальше?",
                parse_mode="html",
                attachments=[pagination]
            )
        else:
            await event.message.answer(
                f"📽 <b>Результаты поиска \"{current_query}\"</b>\n"
                f"📄 Стр. {page+1} из {total_pages}\n"
                f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {total_movies} ☝️\n\nКуда бежим дальше?",
                parse_mode="html",
                attachments=[get_action_keyboard("поиск", "search")]
            )

    async def _show_premiers_page(self, event, user_id, page):
        context = self._get_user_context(user_id)
        movies_list = context.get('premiers', [])
        if not movies_list:
            await event.message.answer("😢 Список премьер устарел. Начни заново.")
            return
        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        total_movies = len(movies_list)
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_movies)
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[get_opinion_button(movie_details['id'], "premiers")]
                    )
        
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "premiers", "")
            await event.message.answer(
                f"🎉 <b>Премьеры</b>\n"
                f"📄 Стр. {page+1} из {total_pages}\n"
                f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {total_movies} ☝️\n\nКуда бежим дальше?",
                parse_mode="html",
                attachments=[pagination]
            )
        else:
            await event.message.answer(
                f"🎉 <b>Премьеры</b>\n"
                f"📄 Стр. {page+1} из {total_pages}\n"
                f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {total_movies} ☝️\n\nКуда бежим дальше?",
                parse_mode="html",
                attachments=[get_action_keyboard("премьеры", "premiers")]
            )

    async def _show_person_search_page(self, event, user_id, page, query):
        context = self._get_user_context(user_id)
        movies_list = context.get('movies', [])
        if not movies_list:
            await event.message.answer("😢 Результаты поиска устарели. Начни заново.")
            return
        items_per_page = 3
        total_pages = (len(movies_list) + items_per_page - 1) // items_per_page
        total_movies = len(movies_list)
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, total_movies)
        
        for movie_data in movies_list[start_idx:end_idx]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_person_search=True, query=query)
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[get_opinion_button(movie_details['id'], "person")]
                    )
        
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", query)
            await event.message.answer(
                f"🎭 <b>Фильмы с участием: {query}</b>\n"
                f"📄 Стр. {page+1} из {total_pages}\n"
                f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {total_movies} ☝️\n\nКуда бежим дальше?",
                parse_mode="html",
                attachments=[pagination]
            )
        else:
            await event.message.answer(
                f"🎭 <b>Фильмы с участием: {query}</b>\n"
                f"📄 Стр. {page+1} из {total_pages}\n"
                f"🐾 Показаны фильмы {start_idx+1}-{end_idx} из {total_movies} ☝️\n\nКуда бежим дальше?",
                parse_mode="html",
                attachments=[get_action_keyboard("поиск по персонам", "person")]
            )

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
        
        movie_id = movie_details.get('id')
        
        card_text, _ = format_movie_card(movie_details)
        if card_text:
            buttons = [
                [{"type": "callback", "text": "🐾 Мнение о фильме", "payload": f"opinion_{movie_id}_random"}],
                [{"type": "callback", "text": "🎲 Новый случайный", "payload": "random"}],
                [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
            ]
            keyboard = InlineKeyboardMarkup(buttons)
            await send_func(card_text, parse_mode='html', attachments=[keyboard])
        else:
            await send_func("😢 Не могу показать карточку.")

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
        
        text = (
            f"{icon} <b>Твой тариф: {limits['tariff_name']}</b>\n\n"
            f"📊 <b>Лимиты на сегодня:</b>\n"
            f"• Мнений: {stats['opinion_count']}/{limits['opinion_limit']}\n"
            f"• Свежих взглядов: {regeneration_text}\n\n"
            f"📅 Действует до: {limits['tariff_end_date'][:10]}\n"
            f"🐾 Лимиты обновляются в полночь!\n\n"
            f"❤️ <b>Любимые фильмы</b> — скоро здесь появится список твоих любимых фильмов!\n"
            f"📝 <b>Мои обращения</b> — скоро здесь появятся твои обращения к тренерам!"
        )
        
        buttons = [
            [{"type": "callback", "text": "❤️ Любимые фильмы (скоро)", "payload": "favorites_soon"}],
            [{"type": "callback", "text": "📝 Мои обращения (скоро)", "payload": "feedback_soon"}],
            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await send_func(text, parse_mode="html", attachments=[keyboard])

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

        if state == 'awaiting_refine':
            await self._handle_refine(event, user_id, text)
            return

        if state == 'awaiting_agent':
            await self._handle_agent(event, user_id, text)
            return

        if state == 'awaiting_search':
            await self._perform_search(event, user_id, text)
        elif state == 'awaiting_person':
            await self._perform_person_search(event, user_id, text)
        elif state == 'awaiting_opinion':
            await self._process_opinion(event, user_id, text, event.message.answer)
            self.user_context.pop(user_id, None)
        else:
            await self._perform_search(event, user_id, text)

    # ===== УТОЧНЕНИЕ ПОДБОРКИ =====
    async def _handle_refine(self, event, user_id, text):
        context = self._get_user_context(user_id)
        mode = context.get('refine_mode', 'recommend')
        original_query = context.get('last_query', '')
        
        # Формируем запрос с уточнением
        refine_query = f"{original_query}\n\nУточнение: {text}"
        
        # Отправляем сообщение о начале уточнения
        await event.message.answer("🔄 Уточняю подборку с учётом твоих пожеланий... 🐾")
        
        try:
            # Вызываем агента (лимит не тратится)
            response = await run_agent(refine_query, user_id, ai_client, agent_mode=mode)
            
            # Помечаем, что уточнение уже использовано
            context['refined'] = True
            
            # Извлекаем ID из ссылок
            movie_ids = extract_movie_ids(response)[:7]
            movies_list = _prepare_movies_with_placeholders(movie_ids, response)
            movies_list = movies_list[:5]
            
            # Считаем реальные фильмы
            real_movies = [m for m in movies_list if not m['is_missing']]
            missing_movies = [m for m in movies_list if m['is_missing']]
            
            # Если есть отсутствующие фильмы — сообщаем
            if missing_movies:
                await event.message.answer(
                    f"🐾 Нашла {len(real_movies)} фильмов в своей базе, "
                    f"а {len(missing_movies)} фильмов пока не загружены. "
                    "Но я покажу их с ссылками на Кинопоиск!"
                )
            
            # Формируем кнопки (без уточнения)
            buttons = []
            if movies_list:
                buttons.append([
                    {"type": "callback", "text": f"🎬 Показать карточки ({len(movies_list)})", "payload": "agent_show_cards"}
                ])
            
            # Кнопка "Ещё" в зависимости от режима
            mode_buttons = {
                'recommend': ('🎬 Ещё подобрать', 'agent_recommend'),
                'actor': ('🐾 Ещё актёрский нюх', 'agent_actor'),
                'plot_search': ('🔎 Ещё по сюжету', 'agent_plot_search'),
                'compare': ('⭐ Ещё сравнить', 'agent_compare'),
            }
            if mode in mode_buttons:
                text_btn, payload = mode_buttons[mode]
                buttons.append([
                    {"type": "callback", "text": text_btn, "payload": payload}
                ])
            
            buttons.append([
                {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
            ])
            
            keyboard = InlineKeyboardMarkup(buttons)
            await event.message.answer(response, parse_mode='html', attachments=[keyboard])
            
            if movies_list:
                context['movies'] = movies_list
            
        except Exception as e:
            logger.error(f"Ошибка уточнения: {e}")
            await event.message.answer(
                "🐾 Что-то пошло не так при уточнении. Попробуй начать новую подборку!",
                attachments=[get_agent_menu()]
            )

    # ===== КиноЛогово и Пообщаться =====
    async def _handle_agent(self, event: MessageCreated, user_id: int, query: str):
        context = self._get_user_context(user_id)
        agent_mode = context.get('agent_mode', 'chat')
        
        # Сохраняем исходный запрос для уточнений
        context['last_query'] = query
        context['refined'] = False
        
        # Проверка лимитов
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

        if not ai_client:
            await event.message.answer("😢 Генерация временно недоступна.")
            return

        # ===== УНИВЕРСАЛЬНЫЕ СООБЩЕНИЯ ДЛЯ РЕЖИМОВ =====
        mode_messages = {
            'recommend': "🎬 Отбираю фильмы под твой вкус... Это займёт пару минут, я внимательно принюхиваюсь! 🐕‍🦺",
            'actor': "🐾 Бегу по следам великой личности... 🔍",
            'plot_search': "🔎 Нюхаю сюжеты... Дай мне пару минут, я найду самые интересные варианты! 🐕",
            'compare': "⭐ Сравниваю фильмы... Сейчас разложу всё по полочкам! 🧐",
            'chat': "💬 Дай-ка подумаю... 🐾"
        }
        
        start_message = mode_messages.get(agent_mode, "🐾 Дай-ка подумаю... 🐾")
        await event.message.answer(start_message)

        # ===== РЕЖИМ "ПООБЩАТЬСЯ" =====
        if agent_mode == 'chat':
            # Проверяем, не хочет ли пользователь найти фильм
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
            
            # Проверяем, не хочет ли пользователь подборку
            if any(kw in query.lower() for kw in ['подбери', 'посоветуй', 'рекомендуй', 'какой фильм', 'что посмотреть']):
                buttons = [
                    [{"type": "callback", "text": "🎬 Подобрать фильм", "payload": "agent_recommend"}],
                    [{"type": "callback", "text": "🐾 Актёрский нюх", "payload": "agent_actor"}],
                    [{"type": "callback", "text": "🔎 По сюжету", "payload": "agent_plot_search"}],
                    [{"type": "callback", "text": "⭐ Сравнить фильмы", "payload": "agent_compare"}]
                ]
                keyboard = InlineKeyboardMarkup(buttons)
                await event.message.answer(
                    "🐾 Ой, я чувствую, что тут пахнет подборкой! 🎬\n\n"
                    "Для этого у меня есть специальные режимы в КиноЛогово.\n"
                    "Выбери, что нужно:",
                    attachments=[keyboard]
                )
                return
            
            # Обычный режим — короткий ответ
            thinking_msg = await event.message.answer("💬 Дай-ка подумаю... 🐾")
            
            async def delete_after_delay():
                await asyncio.sleep(2)
                try:
                    await thinking_msg.delete()
                except Exception:
                    pass
            
            asyncio.create_task(delete_after_delay())
            
            try:
                response = await run_agent(query, user_id, ai_client, agent_mode='chat', chat_mode=True)
                
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
                
                keyboard = InlineKeyboardMarkup([
                    [{"type": "callback", "text": "💬 Ещё поболтать", "payload": "chat"}],
                    [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
                ])
                await event.message.answer(response, parse_mode='html', attachments=[keyboard])
                
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                await event.message.answer(
                    "🐾 Я слишком долго думала... Попробуй переформулировать запрос или задай его по частям!",
                    attachments=[get_agent_menu()]
                )
            return

        # ===== ВСЕ РЕЖИМЫ КИНОЛОГОВО =====
        try:
            response = await run_agent(query, user_id, ai_client, agent_mode=agent_mode)
            
            if user_id not in ADMIN_IDS:
                increment_stat_counter(user_id, 'opinion_count')
            
            # Извлекаем ID из ссылок (самый надёжный способ)
            movie_ids = extract_movie_ids(response)[:7]
            movies_list = _prepare_movies_with_placeholders(movie_ids, response)
            movies_list = movies_list[:5]
            
            # Считаем реальные фильмы
            real_movies = [m for m in movies_list if not m['is_missing']]
            missing_movies = [m for m in movies_list if m['is_missing']]
            
            # Если есть отсутствующие фильмы — сообщаем
            if missing_movies:
                await event.message.answer(
                    f"🐾 Нашла {len(real_movies)} фильмов в своей базе, "
                    f"а {len(missing_movies)} фильмов пока не загружены. "
                    "Но я покажу их с ссылками на Кинопоиск!"
                )
            
            # Формируем кнопки
            buttons = []
            if movies_list:
                buttons.append([
                    {"type": "callback", "text": f"🎬 Показать карточки ({len(movies_list)})", "payload": "agent_show_cards"}
                ])
            
            # Кнопка уточнения — только если ещё не уточняли
            if not context.get('refined', False) and movies_list:
                buttons.append([
                    {"type": "callback", "text": "🔄 Уточнить подборку", "payload": f"agent_refine_{agent_mode}"}
                ])
            
            # Кнопка "Ещё" в зависимости от режима
            mode_buttons = {
                'recommend': ('🎬 Ещё подобрать', 'agent_recommend'),
                'actor': ('🐾 Ещё актёрский нюх', 'agent_actor'),
                'plot_search': ('🔎 Ещё по сюжету', 'agent_plot_search'),
                'compare': ('⭐ Ещё сравнить', 'agent_compare'),
            }
            if agent_mode in mode_buttons:
                text_btn, payload = mode_buttons[agent_mode]
                buttons.append([
                    {"type": "callback", "text": text_btn, "payload": payload}
                ])
            
            buttons.append([
                {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
            ])
            
            keyboard = InlineKeyboardMarkup(buttons)
            await event.message.answer(response, parse_mode='html', attachments=[keyboard])
            
            if movies_list:
                context['movies'] = movies_list
            
        except Exception as e:
            logger.error(f"Ошибка агента: {e}")
            await event.message.answer(
                "🐾 Я слишком долго думала... Попробуй переформулировать запрос или задай его по частям!",
                attachments=[get_agent_menu()]
            )

    # ===== ПОКАЗ КАРТОЧЕК АГЕНТА =====
    async def _handle_agent_show_cards(self, event, user_id):
        context = self._get_user_context(user_id)
        movies_list = context.get('movies', [])
        
        if not movies_list:
            await event.message.answer("😢 Нет фильмов для показа. Попробуй снова.")
            return
        
        for movie_data in movies_list[:5]:
            if movie_data.get('is_missing'):
                # Показываем заглушку
                card = format_missing_movie_card(
                    movie_data['id'],
                    movie_data.get('name')
                )
                # Кнопка для поиска
                buttons = [
                    [{"type": "callback", "text": "🔍 Поискать на других просторах", "payload": f"search_elsewhere_{movie_data['id']}"}],
                    [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
                ]
                keyboard = InlineKeyboardMarkup(buttons)
                await event.message.answer(card, parse_mode='html', attachments=[keyboard])
            else:
                # Показываем нормальную карточку
                card_text, _ = format_movie_card(movie_data['details'])
                if card_text:
                    await event.message.answer(
                        card_text,
                        parse_mode='html',
                        attachments=[get_opinion_button(movie_data['id'], "search")]
                    )
        
        context['movies'] = []
        context['query'] = ''
        
        buttons = [
            [{"type": "callback", "text": "🐺 КиноЛогово", "payload": "agent_menu"}],
            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await event.message.answer(
            "🐾 Вот карточки фильмов! Хочешь ещё что-то найти?",
            attachments=[keyboard]
        )

    # ===== МНЕНИЕ =====
    async def _handle_opinion_command(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text
        
        if user_id not in ADMIN_IDS:
            limits = get_user_limits(user_id)
            stats = get_user_stats(user_id, date.today().isoformat())
            if stats.get('opinion_count', 0) >= limits.get('opinion_limit', 5):
                await event.message.answer(
                    f"🐾 Сегодня ты уже использовал {stats['opinion_count']} мнений из {limits['opinion_limit']}.\n"
                    f"💰 Оформи подписку для безлимита!"
                )
                return
        
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            self._get_user_context(user_id)['state'] = 'awaiting_opinion'
            await event.message.answer("🐾 Напиши название или ID фильма, о котором хочешь узнать мнение:")
            return
        
        query = parts[1].strip()
        await self._process_opinion(event, user_id, query, event.message.answer)

    async def _process_opinion(self, event, user_id: int, query: str, send_func):
        movie_id = None
        try:
            movie_id = int(query)
        except ValueError:
            pass
        
        if movie_id:
            movie_details = get_movie_details(movie_id)
            if movie_details:
                await self._send_opinion_by_id(event, user_id, movie_id, "search", send_func)
                return
        
        search_results = search_movies_in_db(query)
        if len(search_results) > 5:
            search_results = search_results[:5]
        
        if not search_results:
            await send_func(f"😢 Не нашла фильм «{query}». Попробуй уточнить название.")
            return
        
        if len(search_results) == 1:
            await self._send_opinion_by_id(event, user_id, search_results[0]['id'], "search", send_func)
        else:
            text = "🐾 Нашла несколько фильмов. Выбери нужный ID:\n\n"
            for movie in search_results[:5]:
                text += f"🎬 {movie['name']} ({movie['year']}) — ID: {movie['id']}\n"
            text += "\nНапиши ID фильма, о котором хочешь узнать мнение."
            await send_func(text)

    async def _send_opinion_by_id(self, event, user_id: int, movie_id: int, source: str, send_func=None):
        if send_func is None:
            send_func = event.message.answer
        
        cached = get_cached_opinion(movie_id)
        if cached:
            movie_details = get_movie_details(movie_id)
            if movie_details:
                await self._send_formatted_opinion(
                    send_func, user_id, movie_id, movie_details, cached, source
                )
                return
        
        movie_details = get_movie_details(movie_id)
        if not movie_details:
            await send_func(f"😢 Не нашла фильм с ID {movie_id}.")
            return
        
        if not ai_client:
            await send_func("😢 Генерация мнения временно недоступна.")
            return
        
        movie_title = movie_details.get('name', 'Неизвестно')
        movie_year = movie_details.get('year', '')
        await send_func(f"🎬 Смотрю фильм {movie_title} ({movie_year}) в ускоренном режиме...\n\nЭто займёт несколько секунд.")
        
        try:
            opinion = await self._generate_opinion(movie_details)
            if opinion:
                save_opinion_cache(movie_id, opinion)
                await self._send_formatted_opinion(
                    send_func, user_id, movie_id, movie_details, opinion, source
                )
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'opinion_count')
            else:
                await send_func("😢 Не удалось сгенерировать мнение.")
            
        except Exception as e:
            logger.error(f"Ошибка генерации мнения: {e}")
            await send_func("🐾 Гав! Я запуталась в проводах. Попробуй позже!")

    async def _send_formatted_opinion(self, send_func, user_id, movie_id, movie_details, opinion, source):
        limits = get_user_limits(user_id)
        is_premium = _is_premium_tariff(limits.get('tariff_name', ''))
        
        movie_name = movie_details.get('name', 'Неизвестно')
        movie_year = movie_details.get('year', 'Неизвестно')
        
        text, keyboard = _format_opinion_with_buttons(
            opinion,
            movie_name,
            movie_year,
            movie_id,
            source,
            user_id,
            is_premium
        )
        
        await send_func(text, parse_mode='html', attachments=[keyboard])

    async def _handle_regenerate(self, event, user_id, movie_id, source):
        limits = get_user_limits(user_id)
        if not _is_premium_tariff(limits.get('tariff_name', '')):
            await event.message.answer(
                "🐾 Свежий взгляд доступен только на тарифах «Ищейка» и «Вожак»!\n"
                "💰 Оформи подписку и получи безлимитные перегенерации!"
            )
            return
        
        stats = get_user_stats(user_id, date.today().isoformat())
        regen_limit = limits.get('regeneration_limit', 0)
        regen_used = stats.get('regeneration_count', 0)
        
        if regen_limit > 0 and regen_used >= regen_limit:
            await event.message.answer(
                f"🐾 Сегодня ты уже использовал {regen_used} свежих взглядов из {regen_limit}.\n"
                "Лимит обновится в полночь!"
            )
            return
        
        movie_details = get_movie_details(movie_id)
        if not movie_details:
            await event.message.answer(f"😢 Не нашла фильм с ID {movie_id}.")
            return
        
        if not ai_client:
            await event.message.answer("😢 Генерация мнения временно недоступна.")
            return
        
        await event.message.answer("🔄 Генерирую свежий взгляд...")
        
        try:
            opinion = await self._generate_opinion(movie_details, force_regenerate=True)
            if opinion:
                save_opinion_cache(movie_id, opinion)
                if user_id not in ADMIN_IDS:
                    increment_stat_counter(user_id, 'regeneration_count')
                await self._send_formatted_opinion(
                    event.message.answer, user_id, movie_id, movie_details, opinion, source
                )
            else:
                await event.message.answer("😢 Не удалось сгенерировать новое мнение.")
            
        except Exception as e:
            logger.error(f"Ошибка перегенерации: {e}")
            await event.message.answer("🐾 Гав! Я запуталась в проводах. Попробуй позже!")

    async def _generate_opinion(self, movie_details, force_regenerate=False):
        """Генерирует мнение о фильме через DeepSeek (НЕ через run_agent)"""
        title = movie_details.get('name', 'Без названия')
        year = movie_details.get('year', '')
        
        countries = movie_details.get('countries', [])
        countries_str = ', '.join(countries) if countries else 'неизвестно'
        
        genres = movie_details.get('genres', [])
        genres_str = ', '.join(genres) if genres else 'неизвестно'
        
        directors_list = movie_details.get('directors', [])
        if directors_list:
            director_names = []
            for director in directors_list:
                name = director.get('name') or director.get('enName')
                if name:
                    director_names.append(name)
            directors_str = ', '.join(director_names)
        else:
            directors_str = 'неизвестен'
        
        actors_list = movie_details.get('actors', [])[:7]
        if actors_list:
            actor_names = []
            for actor in actors_list:
                name = actor.get('name') or actor.get('enName')
                if name:
                    actor_names.append(name)
            actors_str = '\n'.join([f"• {name}" for name in actor_names])
        else:
            actors_str = 'не указаны'
        
        rating = movie_details.get('rating', 0)
        description = movie_details.get('description', 'Описание отсутствует')
        if description and len(description) > 800:
            description = description[:800] + '...'

        prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьем на хорошее кино. Ты смотришь фильмы и делишься своим мнением с юмором и энтузиазмом. Говори о себе в женском роде.

Информация о фильме:
🎬 Название: {title} ({year})
🌍 Страна: {countries_str}
🎭 Жанр: {genres_str}
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
8. Не благодари за замечания и не упоминай, что это исправленная версия - просто напиши новое мнение

Расскажи о:
- Настроении и смысле фильма
- Наградах (с учетом страны производства, если знаешь точно, а если нет - просто не упоминай, не выдумывай!)
- Особенностях
- Почему стоит посмотреть
- Плюсах и минусах

В конце обязательно добавь:
Оценка: от 5 до 10 (краткий комментарий почему)

После оценки добавь:
Настроение: 5 хэштегов (например #Радость #Грусть #Вдохновение #Ностальгия #Уют)
Атмосфера: 5 хэштегов (например #Мрачность #Яркость #Теплота #Напряжение #Сюрреализм)"""

        if force_regenerate:
            prompt += "\n\n⚠️ Это свежий взгляд на тот же фильм. Постарайся найти новые детали, которые не упоминались в предыдущем мнении. Сделай акцент на других аспектах фильма, персонажах, режиссёрских приёмах или скрытых смыслах. Не повторяй то, что уже было сказано."

        try:
            response = ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Твои ответы должны быть дружелюбными, с юмором, но при этом информативными. Обязательно используй женский род: 'я посмотрела', 'мне понравилось', 'я нашла' и т.д."},
                    {"role": "user", "content": prompt}
                ],
                timeout=180
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Ошибка генерации мнения: {e}")
            return None

    # ===== ПОИСК =====
    async def _perform_search(self, event, user_id, query):
        await event.message.answer(f"🔍 Ищу фильмы по запросу: {query}...")
        
        movies = search_movies_in_db(query)
        if len(movies) > 20:
            movies = movies[:20]
        
        if not movies:
            await event.message.answer(f"😢 Не нашла фильмов по запросу «{query}».\nПопробуй уточнить название.")
            self.user_context.pop(user_id, None)
            return
        
        context = self._get_user_context(user_id)
        context['full_list'] = movies
        context['movies'] = movies
        context['query'] = query
        context['filters'] = {}
        context['filtered_list'] = []
        context['state'] = 'search_results'
        
        total_count = len(movies)
        has_more = total_count >= 20
        
        text = f"🔍 Поиск: {query}\n\n"
        text += f"Найдено фильмов: {'>' if has_more else ''}{total_count}\n\n"
        text += "Настрой фильтры и нажми 'Показать карточки'"
        
        keyboard = get_filter_keyboard(query, {}, total_count, has_more)
        await event.message.answer(text, parse_mode="html", attachments=[keyboard])

    async def _perform_person_search(self, event, user_id, query):
        await event.message.answer(f"🎭 Ищу фильмы с участием: {query}...")
        
        movies = search_movies_by_person_in_db(query)
        
        if not movies:
            await event.message.answer(
                f"😢 Не нашла фильмов с участием «{query}».",
                attachments=[get_main_menu()]
            )
            self.user_context.pop(user_id, None)
            return
        
        context = self._get_user_context(user_id)
        context['movies'] = movies
        context['query'] = query
        context['is_person_search'] = True
        context['state'] = 'search_results'
        
        await self._show_person_search_page(event, user_id, 0, query)

    # ===== FEEDBACK =====
    async def _process_feedback_movie_id(self, event, user_id, text):
        context = self._get_user_context(user_id)
        
        if text.lower() == 'нет':
            context['state'] = 'awaiting_feedback_message'
            await event.message.answer("🐾 Опиши проблему подробно. Что именно не работает?")
            return
        
        try:
            movie_id = int(text)
            context['feedback_movie_id'] = movie_id
            context['state'] = 'awaiting_feedback_message'
            await event.message.answer(f"🐾 Спасибо! Фильм ID: {movie_id}\n\nОпиши, что именно не так:")
        except ValueError:
            await event.message.answer("🐾 Пожалуйста, введи корректный ID фильма (число) или напиши «нет».")

    async def _process_feedback_message(self, event, user_id, text):
        context = self._get_user_context(user_id)
        feedback_type = context.get('feedback_type', 1)
        movie_id = context.get('feedback_movie_id')
        
        save_feedback(user_id, feedback_type, movie_id, text)
        
        context.pop('feedback_type', None)
        context.pop('feedback_movie_id', None)
        context.pop('state', None)
        
        await event.message.answer(
            "🐾 Спасибо! Я передала твоё обращение тренерам.\n"
            "Они разберутся и свяжутся с тобой при необходимости.",
            attachments=[get_feedback_menu()]
        )

    async def _process_feedback_review(self, event, user_id, text):
        context = self._get_user_context(user_id)
        
        save_feedback(user_id, 2, None, text)
        
        context.pop('feedback_type', None)
        context.pop('state', None)
        
        await event.message.answer(
            "🐾 Спасибо за твой отзыв! Я обязательно учту его в своей работе.\n"
            "Ты помогаешь мне становиться лучше! 🐕",
            attachments=[get_feedback_menu()]
        )

    # ==================== ЗАПУСК ====================
    async def run(self):
        """Запускает бота"""
        logger.info("🚀 Запуск Max-бота...")
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
            raise
        finally:
            await self.bot.close()

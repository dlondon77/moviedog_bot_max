# core/max_adapter.py — ТОЛЬКО АДАПТЕР
# Вся логика агента вынесена в core/agent.py

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
from maxapi.types import BotStarted, MessageCreated
from openai import OpenAI
import httpx

# ==================== ИМПОРТЫ ИЗ CORE ====================
import user as user_module
import movie as movie_module
import db as db_module
from core.agent import run_agent  # ← агент импортируется как библиотека

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

# ==================== КОНСТАНТЫ ====================
ADMIN_IDS = [7191208]  # пользователи с безлимитным доступом

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
    http_client = httpx.Client(timeout=120.0, follow_redirects=True)
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
            {"type": "callback", "text": "🎭 Поиск по актёрам", "payload": "person"}
        ],
        [
            {"type": "callback", "text": "👤 Мой профиль", "payload": "profile"},
            {"type": "callback", "text": "🤖 ИИ-агент", "payload": "agent"}
        ],
        [
            {"type": "callback", "text": "❓ FAQ", "payload": "faq"},
            {"type": "callback", "text": "📝 Обратная связь", "payload": "feedback"}
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_opinion_button(movie_id: int):
    buttons = [
        [{"type": "callback", "text": "🐾 Мнение о фильме", "payload": f"opinion_{movie_id}"}]
    ]
    return InlineKeyboardMarkup(buttons)

def get_pagination_buttons(current_page: int, total_pages: int, prefix: str, query: str = ""):
    buttons = []
    row = []
    if current_page > 0:
        row.append({"type": "callback", "text": "◀️ Назад", "payload": f"{prefix}_page_{current_page-1}_{query}"})
    row.append({"type": "callback", "text": f"{current_page+1}/{total_pages}", "payload": "noop"})
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
        logger.info("✅ MaxAdapter инициализирован")

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
            self._get_user_context(user_id)['state'] = 'awaiting_person'
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")

        @self.dp.message_created(F.message.body.text == "/profile")
        async def on_profile(event: MessageCreated):
            await self._handle_profile(event)

        @self.dp.message_created(F.message.body.text.startswith("/opinion"))
        async def on_opinion(event: MessageCreated):
            await self._handle_opinion_command(event)

        @self.dp.message_created(F.message.body.text == "/agent")
        async def on_agent(event: MessageCreated):
            user_id = event.message.sender.user_id
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🤖 <b>ИИ-агент КиноИщейки</b>\n\n"
                "Задай любой вопрос о кино, и я найду ответ!\n\n"
                "<b>Примеры запросов:</b>\n"
                "• «Найди фильм с Брэдом Питтом, похожий на Бойцовский клуб»\n"
                "• «Посоветуй хороший триллер на вечер»\n"
                "• «Какие фильмы с Ди Каприо вышли после 2010 года?»\n"
                "• «Сравни Матрицу и Начало»\n"
                "• «Что выходит в июне?»\n"
                "• «Посоветуй что-то на основе моих любимых фильмов»\n\n"
                "🐾 <i>Это может занять 10-15 секунд</i>",
                parse_mode="html"
            )

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
                "/premiers — ожидаемые премьеры\n"
                "/person — поиск по актёрам/режиссёрам\n"
                "/opinion [название или ID] — мнение о фильме\n"
                "/profile — мой профиль\n"
                "/agent — ИИ-агент\n"
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
            "🎉 <b>Премьеры</b> — учуяю свежие ожидаемые премьеры\n"
            "🎭 <b>Поиск по актёрам</b> — найду фильмы по имени актёра или режиссёра\n"
            "🐾 <b>Мнение о фильме</b> — расскажу о смысле фильма, его настроении и атмосфере, укажу на плюсы и минусы и поставлю оценку\n"
            "🤖 <b>ИИ-агент</b> — задай любой вопрос о кино, я сам найду ответ!\n"
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

        if payload == "faq" or payload.startswith("faq_"):
            await self._handle_faq_callback(event, user_id, payload)
            return

        if payload == "feedback" or payload.startswith("feedback_"):
            await self._handle_feedback_callback(event, user_id, payload)
            return

        if payload == "agent":
            self._get_user_context(user_id)['state'] = 'awaiting_agent'
            await event.message.answer(
                "🤖 <b>ИИ-агент КиноИщейки</b>\n\n"
                "Задай любой вопрос о кино, и я найду ответ!\n\n"
                "<b>Примеры запросов:</b>\n"
                "• «Найди фильм с Брэдом Питтом, похожий на Бойцовский клуб»\n"
                "• «Посоветуй хороший триллер на вечер»\n"
                "• «Какие фильмы с Ди Каприо вышли после 2010 года?»\n"
                "• «Сравни Матрицу и Начало»\n"
                "• «Что выходит в июне?»\n"
                "• «Посоветуй что-то на основе моих любимых фильмов»\n\n"
                "🐾 <i>Это может занять 10-15 секунд</i>",
                parse_mode="html"
            )
            return

        if payload.startswith("fb_page_"):
            page = int(payload.split("_")[2])
            await self._show_user_feedback(event, user_id, page)
            return

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

        if payload == "back_to_menu":
            self.user_context.pop(user_id, None)
            await event.message.answer(
                "🐾 Возвращаюсь в главное меню",
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
            self._get_user_context(user_id)['state'] = 'awaiting_person'
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")
        elif payload == "profile":
            await self._send_profile(event.message.answer, user_id)
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
                "Также можно искать по актёрам кнопкой «🎭 Поиск по актёрам»"
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
                "У меня есть суточные лимиты на запросы мнений:\n"
                "• 🐶 Щенячий азарт: 5 мнений в день (бесплатно)\n"
                "• 🐕 Охотничий: 10 мнений в день\n"
                "• 🕵️ Ищейка: 30 мнений в день\n"
                "• 🐺 Вожак: безлимит\n\n"
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
        await event.message.answer(
            f"📽 <b>Результаты поиска \"{current_query}\"</b>\n"
            f"Страница {page+1} из {total_pages}\n"
            f"Показаны фильмы {start_idx+1}-{end_idx} из {total_movies}",
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
        else:
            await event.message.answer(
                "🏠 В главное меню",
                attachments=[get_action_keyboard(None, None, None)]
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
        await event.message.answer(
            f"🎉 <b>Ожидаемые премьеры</b>\n"
            f"Страница {page+1} из {total_pages}\n"
            f"Показаны фильмы {start_idx+1}-{end_idx} из {total_movies}",
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
        else:
            await event.message.answer(
                "🏠 В главное меню",
                attachments=[get_action_keyboard(None, None, None)]
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
        await event.message.answer(
            f"🎭 <b>Фильмы с участием: {query}</b>\n"
            f"Страница {page+1} из {total_pages}\n"
            f"Показаны фильмы {start_idx+1}-{end_idx} из {total_movies}",
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
                        attachments=[get_opinion_button(movie_details['id'])]
                    )
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", query)
            await event.message.answer("👇 Навигация:", attachments=[pagination])
        else:
            await event.message.answer(
                "🏠 В главное меню",
                attachments=[get_action_keyboard(None, None, None)]
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
        card_text, _ = format_movie_card(movie_details)
        if card_text:
            extra_buttons = [[
                {"type": "callback", "text": "🐾 Мнение о фильме", "payload": f"opinion_{movie_details['id']}"}
            ]]
            keyboard = get_action_keyboard("случайный фильм", "random", extra_buttons)
            await send_func(card_text, parse_mode='html', attachments=[keyboard])
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
        tariff_icons = {
            'Щенячий азарт': '🐶',
            'Охотничий': '🐕',
            'Ищейка': '🕵️',
            'Вожак': '🐺'
        }
        icon = tariff_icons.get(limits['tariff_name'], '🐾')
        await send_func(
            f"{icon} <b>Твой тариф: {limits['tariff_name']}</b>\n\n"
            f"📊 <b>Лимиты на сегодня:</b>\n"
            f"• Мнений: {stats['opinion_count']}/{limits['opinion_limit']}\n"
            f"• Свежих взглядов: {stats['regeneration_count']}/{limits['regeneration_limit']}\n\n"
            f"📅 Действует до: {limits['tariff_end_date'][:10]}\n\n"
            f"🐾 Лимиты обновляются в полночь!",
            parse_mode="html"
        )

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
        elif state == 'awaiting_opinion':
            await self._process_opinion(event, user_id, text, event.message.answer)
            self.user_context.pop(user_id, None)
        else:
            await self._perform_search(event, user_id, text)

    # ===== АГЕНТ =====
    async def _handle_agent(self, event: MessageCreated, user_id: int, query: str):
        """Обработка запросов к ИИ-агенту"""
        
        # Для админов — безлимит
        if user_id not in ADMIN_IDS:
            limits = get_user_limits(user_id)
            stats = get_user_stats(user_id, date.today().isoformat())
            
            if stats.get('opinion_count', 0) >= limits.get('opinion_limit', 5):
                await event.message.answer(
                    f"🐾 Сегодня у тебя уже использовано {stats['opinion_count']} мнений из {limits['opinion_limit']}.\n"
                    f"Агент — это платная фишка!\n\n"
                    f"💰 Оформи подписку, чтобы снять ограничения:\n"
                    f"• 🐕 Охотничий (199 ₽) — 5 запросов в день\n"
                    f"• 🕵️ Ищейка (399 ₽) — 20 запросов в день\n"
                    f"• 🐺 Вожак (999 ₽) — безлимит"
                )
                return
    
        await event.message.answer("🤖 Думаю... (это может занять 10-15 секунд)")
    
        if not ai_client:
            await event.message.answer("😢 Генерация временно недоступна. Попробуй позже.")
            return
    
        try:
            response = await run_agent(query, user_id, ai_client)
            # Считаем только для обычных пользователей
            if user_id not in ADMIN_IDS:
                increment_stat_counter(user_id, 'opinion_count')
            await event.message.answer(response)
        except Exception as e:
            logger.error(f"Ошибка агента: {e}")
            await event.message.answer("🐾 Гав! Что-то пошло не так. Попробуй позже!")

    # ===== ОБРАБОТЧИКИ FEEDBACK (текст) =====
    async def _process_feedback_movie_id(self, event, user_id, text):
        context = self._get_user_context(user_id)
        if text.lower() == 'нет':
            context['movie_id'] = None
            context['state'] = 'awaiting_feedback_message'
            await event.message.answer("🐾 Теперь опиши подробнее что волнует:")
            return
        if text.isdigit() and 2 < len(text) <= 10 and int(text) != 0:
            context['movie_id'] = int(text)
            context['state'] = 'awaiting_feedback_message'
            await event.message.answer("🐾 Теперь опиши что не так с этим фильмом:")
            return
        await event.message.answer(
            "🐾 ID фильма должен быть числом от 3 до 10 цифр.\n"
            "Попробуй еще раз или введи «нет»:"
        )

    async def _process_feedback_message(self, event, user_id, text):
        context = self._get_user_context(user_id)
        movie_id = context.get('movie_id')
        feedback_type = context.get('feedback_type', 1)
        save_feedback(user_id, feedback_type, movie_id, text)
        context.pop('state', None)
        context.pop('feedback_stage', None)
        context.pop('movie_id', None)
        await event.message.answer(
            "🐾 Гав-гав! Спасибо за бдительность!\n\n"
            "Я записала твоё сообщение и уже бегу разбираться.\n\n"
            "А пока можешь продолжить поиски отличного кино! 🍿",
            attachments=[get_feedback_menu()]
        )

    async def _process_feedback_review(self, event, user_id, text):
        context = self._get_user_context(user_id)
        feedback_type = context.get('feedback_type', 2)
        save_feedback(user_id, feedback_type, None, text)
        context.pop('state', None)
        await event.message.answer(
            "🐾 Спасибо за отзыв! Очень ценно твое мнение.\n\n"
            "Я передала его своим тренерам!",
            attachments=[get_feedback_menu()]
        )

    # ===== ПОИСК =====
    async def _perform_search(self, event: MessageCreated, user_id, query):
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return
        await event.message.answer(f"🔍 Ищу: {query}...")
        total_count, has_more = search_movies_with_filters(query, filters=None, count_only=True)
        if total_count == 0:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
            self.user_context.pop(user_id, None)
            return
        full_list = search_movies_with_filters(query, filters=None, count_only=False)
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
        await event.message.answer(f"🎭 Ищу фильмы с участием: {query}...")
        movies_list = search_movies_by_person_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            await event.message.answer(f"😢 Не нашла фильмов с '{query}'.")
            self.user_context.pop(user_id, None)
            return
        context = self._get_user_context(user_id)
        context['movies'] = movies_list
        context['query'] = query
        context['is_person_search'] = True
        await self._show_person_search_page(event, user_id, 0, query)

    # ==================== МНЕНИЕ ====================
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
        kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"
        await send_func(kp_url)
        cached = get_cached_opinion(movie_id)
        if cached:
            formatted_opinion = self._format_opinion(cached, movie_name, movie_year)
            await send_func(formatted_opinion, parse_mode="html")
            increment_stat_counter(user_id, 'opinion_count')
            record_user_opinion(user_id, movie_id)
            await send_func("🏠", attachments=[get_action_keyboard(None, None, None)])
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
                formatted_opinion = self._format_opinion(opinion, movie_name, movie_year)
                await send_func(formatted_opinion, parse_mode="html")
                await send_func("🏠", attachments=[get_action_keyboard(None, None, None)])
            else:
                await send_func("😢 Не удалось сгенерировать мнение.")
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            await send_func("🐾 Гав! Что-то пошло не так. Попробуй позже!")

    def _format_opinion(self, opinion, movie_name, movie_year):
        return f"Я посмотрела <b>{movie_name}</b> ({movie_year}), и вот что думаю:\n\n{opinion}\n\n🐾"

    async def _generate_opinion(self, movie_details):
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

Расскажи о:
- Настроении и смысле фильма
- Наградах (с учетом страны производства, если знаешь точно, а если нет - просто не упоминай, не выдумывай!)
- Особенностях
- Почему стоит посмотреть
- Плюсах и минусах

В конце обязательно добавь:
Оценка: от 5 до 10 (краткий комментарий почему)

После оценки добавь:
Настроение: 5 хэштегов (например #Радость #Грусть)
Атмосфера: 5 хэштегов (например #Мрачность #Яркость)"""
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Твои ответы должны быть дружелюбными, с юмором, но при этом информативными. Обязательно используй женский род: 'я посмотрела', 'мне понравилось', 'я нашла' и т.д."},
                {"role": "user", "content": prompt}
            ],
            timeout=60
        )
        full_response = response.choices[0].message.content.strip()
        return full_response

    # ==================== ЗАПУСК ====================
    async def run(self):
        logger.info("🚀 MaxAdapter запущен")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

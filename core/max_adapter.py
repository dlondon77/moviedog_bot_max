# core/max_adapter.py — ИСПРАВЛЕННАЯ ВЕРСИЯ
# + Кнопка "В главное меню" на всех страницах
# + Исправлены FAQ и Feedback
# + Убрана кнопка "Мнение" из главного меню

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
            {"type": "callback", "text": "❓ FAQ", "payload": "faq"}
        ],
        [
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
    # Добавляем кнопку "В главное меню" под пагинацией
    buttons.append([
        {"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}
    ])
    return InlineKeyboardMarkup(buttons)

def get_action_keyboard(action_name: str = None, action_payload: str = None, extra_buttons: list = None):
    """Создаёт клавиатуру с кнопкой повтора действия и возвратом в меню"""
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
        logger.info("✅ MaxAdapter инициализирован (с FAQ, Feedback, кнопками Ещё)")

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
                "📝 <b>Обратная связь</b>\n\n"
                "Выбери тип обращения:",
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
            "🐾 <b>Мнение о фильме</b> — расскажу о смысле фильма, его настроении и атмосфере, укажу на плюсы и минусы и поставлю оценку\n"
            "❓ <b>FAQ</b> — ответы на частые вопросы\n"
            "📝 <b>Обратная связь</b> — сообщить об ошибке или оставить отзыв\n\n"
            "👇 <b>Выбери действие в меню ниже:</b>"
        ).format(
            tariff=limits.get('tariff_name', 'Щенячий азарт'),
            limit=limits.get('opinion_limit', 3)
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

        # ===== FAQ =====
        if payload == "faq" or payload.startswith("faq_"):
            await self._handle_faq_callback(event, user_id, payload)
            return

        # ===== FEEDBACK =====
        if payload == "feedback" or payload.startswith("feedback_"):
            await self._handle_feedback_callback(event, user_id, payload)
            return

        # ===== НАВИГАЦИЯ =====
        if payload == "back_to_menu":
            self.user_context.pop(user_id, None)
            await event.message.answer(
                "🐾 Возвращаюсь в главное меню",
                attachments=[get_main_menu()]
            )
            return

        if payload == "noop":
            return

        # ===== ПАГИНАЦИЯ =====
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
            self._get_user_context(user_id)['state'] = 'awaiting_person'
            await event.message.answer("🎭 Введи имя актёра или режиссёра:")
        elif payload == "profile":
            await self._send_profile(event.message.answer, user_id)
        elif payload.startswith("opinion_"):
            movie_id = int(payload.split("_")[1])
            await self._send_opinion_by_id(event, user_id, movie_id)
        else:
            await event.message.answer(f"🐾 Неизвестная команда: {payload}")

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
                "3. Я покажу результаты\n\n"
                "Также можно искать по актёрам кнопкой «🎭 Поиск по актёрам»"
            )
        elif payload == "faq_opinion":
            text = (
                "💬 <b>Как узнать мнение о фильме?</b>\n\n"
                "После того как я покажу карточку фильма, нажми кнопку «🐾 Мнение о фильме».\n"
                "Я посмотрю фильм в ускоренном режиме и поделюсь впечатлениями!\n\n"
                "Лимит: 3 мнения в день для бесплатного тарифа."
            )
        elif payload == "faq_limits":
            text = (
                "⚠️ <b>Лимиты бота</b>\n\n"
                "У меня есть суточные лимиты на запросы мнений:\n"
                "• 🆓 Бесплатный тариф: 3 мнения в день\n"
                "• 🐕 Охотничий: 10 мнений в день (199 ₽/мес)\n"
                "• 🕵️ Ищейка: 30 мнений в день (399 ₽/мес)\n"
                "• 🐺 Вожак: безлимит (999 ₽/мес)\n\n"
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

        await event.message.answer(
            text,
            parse_mode="html",
            attachments=[get_faq_menu()]
        )

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
            self._get_user_context(user_id)['feedback_type'] = 1
            self._get_user_context(user_id)['feedback_stage'] = 'awaiting_movie_id'
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
        elif payload == "feedback_review":
            self._get_user_context(user_id)['feedback_type'] = 2
            self._get_user_context(user_id)['feedback_stage'] = 'awaiting_review'
            await event.message.answer("🐾 Напиши свой отзыв о моих навыках:")
        elif payload == "feedback_list":
            await self._show_user_feedback(event, user_id)
        else:
            await event.message.answer("🐾 Возвращаюсь в меню обратной связи", attachments=[get_feedback_menu()])

    async def _show_user_feedback(self, event, user_id):
        conn = db_module.get_opinions_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, type, movie_id, message, status, created_at, admin_comment
            FROM feedback 
            WHERE user_id = ? AND status != 'archive'
            ORDER BY created_at DESC
            LIMIT 10
        ''', (user_id,))
        feedback_list = cursor.fetchall()
        conn.close()

        if not feedback_list:
            await event.message.answer(
                "🐾 У тебя пока нет обращений.\n\n"
                "Ты можешь оставить отзыв или сообщить об ошибке через кнопку «📝 Обратная связь»",
                attachments=[get_feedback_menu()]
            )
            return

        status_icons = {'new': '🆕', 'in_progress': '🔄', 'resolved': '✅'}
        type_names = {1: '🐛 Ошибка', 2: '📢 Отзыв'}

        text = "📝 <b>Твои обращения</b>\n\n"
        for fb in feedback_list[:5]:
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

        if len(feedback_list) > 5:
            text += f"... и ещё {len(feedback_list) - 5} обращений\n\n"

        text += "Чтобы оставить новое обращение, нажми кнопку «📝 Обратная связь» в главном меню"

        await event.message.answer(text, parse_mode="html", attachments=[get_feedback_menu()])

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

        # Пагинация с кнопкой "В главное меню"
        if total_pages > 1:
            pagination = get_pagination_buttons(page, total_pages, "search", current_query)
            await event.message.answer("👇 Навигация:", attachments=[pagination])
        else:
            # Если всего одна страница — сразу кнопка "В главное меню"
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
        await send_func(
            f"👤 <b>Твой профиль</b>\n\n"
            f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 Мнений сегодня: {stats.get('opinion_count', 0)}/{limits.get('opinion_limit', 3)}\n"
            f"🔄 Свежих взглядов: {stats.get('regeneration_count', 0)}/{limits.get('regeneration_limit', 2)}\n\n"
            f"🐾 Функция баланса косточек в разработке.",
            parse_mode="html"
        )

    # ==================== ПОИСК ПО АКТЁРАМ ====================
    async def _handle_message(self, event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text if event.message.body else ""
        if not text or text.startswith("/"):
            return

        context = self._get_user_context(user_id)
        state = context.get('state')

        # Обработка обратной связи
        if state == 'awaiting_movie_id':
            await self._process_feedback_movie_id(event, user_id, text)
            return
        if state == 'awaiting_review':
            await self._process_feedback_review(event, user_id, text)
            return
        if state == 'awaiting_feedback_message':
            await self._process_feedback_message(event, user_id, text)
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

    async def _process_feedback_movie_id(self, event, user_id, text):
        context = self._get_user_context(user_id)
        if text.lower() == 'нет':
            context['movie_id'] = None
            context['feedback_stage'] = 'awaiting_feedback_message'
            await event.message.answer("🐾 Теперь опиши подробнее что волнует:")
        elif text.isdigit() and 2 < len(text) <= 10 and int(text) != 0:
            context['movie_id'] = int(text)
            context['feedback_stage'] = 'awaiting_feedback_message'
            await event.message.answer("🐾 Теперь опиши что не так с этим фильмом:")
        else:
            await event.message.answer("🐾 ID фильма должен быть числом от 3 до 10 цифр. Попробуй еще раз или введи 'нет':")

    async def _process_feedback_review(self, event, user_id, text):
        context = self._get_user_context(user_id)
        feedback_type = context.get('feedback_type', 2)
        save_feedback(user_id, feedback_type, None, text)
        context.pop('feedback_stage', None)
        await event.message.answer(
            "🐾 Спасибо за отзыв! Очень ценно твое мнение.\n\nЯ передала его своим тренерам!",
            attachments=[get_feedback_menu()]
        )

    async def _process_feedback_message(self, event, user_id, text):
        context = self._get_user_context(user_id)
        movie_id = context.get('movie_id')
        feedback_type = context.get('feedback_type', 1)
        save_feedback(user_id, feedback_type, movie_id, text)
        context.pop('feedback_stage', None)
        await event.message.answer(
            "🐾 Гав-гав! Спасибо за бдительность!\n\nЯ записала твоё сообщение и уже бегу разбираться.",
            attachments=[get_feedback_menu()]
        )

    async def _perform_search(self, event: MessageCreated, user_id, query):
        if len(query) < 2:
            await event.message.answer("🐾 Введи хотя бы 2 символа.")
            self.user_context.pop(user_id, None)
            return

        await event.message.answer(f"🔍 Ищу: {query}...")
        movies_list = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)

        if not movies_list:
            await event.message.answer(f"😢 По запросу '{query}' ничего не нашлось.")
            self.user_context.pop(user_id, None)
            return

        context = self._get_user_context(user_id)
        context['movies'] = movies_list
        context['query'] = query
        await self._show_search_page(event, user_id, 0, query)

    async def _perform_person_search(self, event: MessageCreated, user_id, query):
        """Поиск по актёрам/режиссёрам с передачей query для ссылок"""
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
            f"Страница {page+1} из {total_pages}",
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
            # После мнения — только "В главное меню"
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
                formatted_opinion = self._format_opinion(opinion, movie_name, movie_year, movie_id)
                await send_func(formatted_opinion, parse_mode="html")
                # После мнения — только "В главное меню"
                await send_func("🏠", attachments=[get_action_keyboard(None, None, None)])
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
                {
                    "role": "system", 
                    "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Твои ответы должны быть дружелюбными, с юмором, но при этом информативными. Обязательно используй женский род: 'я посмотрела', 'мне понравилось', 'я нашла' и т.д."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            timeout=60
        )

        full_response = response.choices[0].message.content.strip()
        return full_response

    # ==================== ЗАПУСК ====================
    async def run(self):
        logger.info("🚀 MaxAdapter запущен (с FAQ, Feedback, кнопками Ещё)")
        await self.bot.delete_webhook()
        await self.dp.start_polling(self.bot)


if __name__ == "__main__":
    import asyncio
    adapter = MaxAdapter()
    asyncio.run(adapter.run())

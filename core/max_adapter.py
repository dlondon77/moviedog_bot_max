# core/max_adapter.py — версия на maxgram с кнопками

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

# Настраиваем логгер
logger = logging.getLogger(__name__)

# Импорты из maxgram
try:
    from maxgram import Bot
    from maxgram.keyboards import InlineKeyboard
    HAS_MAXGRAM = True
    logger.info("✅ maxgram успешно загружен")
except ImportError as e:
    logger.error(f"❌ maxgram не установлен: {e}")
    HAS_MAXGRAM = False
    # Создаём заглушку
    class Bot:
        def __init__(self, token):
            self.token = token
        def run(self):
            pass

# Импорты из core
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

# Функции для работы с кэшем мнений
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

def load_config():
    config_path = os.path.join(BASE_DIR, 'config', 'config.ini')
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    return config

# Настройка DeepSeek
config = load_config()
DEEPSEEK_KEY = os.environ.get('OPENAI_API_KEY') or config.get('OpenAI', 'api_key', fallback='')

if DEEPSEEK_KEY:
    from openai import OpenAI
    import httpx
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


class MaxAdapter:
    def __init__(self):
        self.config = load_config()
        self.token = os.environ.get('MAX_TOKEN') or self.config.get('Max', 'token', fallback='')
        
        if not self.token:
            raise ValueError("MAX_TOKEN не найден!")
        
        if not HAS_MAXGRAM:
            raise ImportError("maxgram не установлен! Установи: pip install maxgram")
        
        self.bot = Bot(self.token)
        self.user_context = {}  # {user_id: {'state': ..., 'query': ...}}
        
        self._register_handlers()
        logger.info(f"✅ MaxAdapter (maxgram) инициализирован")
    
    def _register_handlers(self):
        """Регистрирует все обработчики maxgram"""
        
        # Главная клавиатура
        self.main_keyboard = InlineKeyboard([
            [{"text": "🎲 Случайный фильм", "callback": "random"}],
            [{"text": "🔍 Поиск", "callback": "search"}],
            [{"text": "🎉 Премьеры", "callback": "premiers"}],
            [{"text": "🎭 Поиск по актёрам", "callback": "person"}],
            [{"text": "👤 Мой профиль", "callback": "profile"}],
            [{"text": "🐾 Мнение о фильме", "callback": "opinion_prompt"}],
        ])
        
        @self.bot.command("start")
        def start_command(context):
            user_id = context.user_id
            username = getattr(context, 'username', '') or ''
            first_name = getattr(context, 'first_name', '') or ''
            last_name = getattr(context, 'last_name', '') or ''
            
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
            
            context.reply(
                f"🐾 <b>Гав! Я КиноИщейка!</b>\n\n"
                f"📊 <b>Твой тариф:</b> {limits.get('tariff_name', 'Щенячий азарт')}\n"
                f"🎬 <b>Мнений сегодня:</b> 0/{limits.get('opinion_limit', 3)}\n\n"
                f"👇 <b>Выбери действие:</b>",
                parse_mode="html",
                keyboard=self.main_keyboard
            )
        
        @self.bot.command("help")
        def help_command(context):
            context.reply(
                "❓ <b>Команды:</b>\n\n"
                "/start — главное меню\n"
                "/random — случайный фильм\n"
                "/search — поиск по названию\n"
                "/premiers — ожидаемые премьеры\n"
                "/person — поиск по актёрам\n"
                "/opinion [название] — мнение о фильме\n"
                "/profile — мой профиль\n"
                "/help — это сообщение",
                parse_mode="html"
            )
        
        @self.bot.command("random")
        def random_command(context):
            self._handle_random_command(context)
        
        @self.bot.command("search")
        def search_command(context):
            self.user_context[context.user_id] = {'state': 'awaiting_search'}
            context.reply("🔍 Введи название фильма:")
        
        @self.bot.command("premiers")
        def premiers_command(context):
            self._handle_premiers_command(context)
        
        @self.bot.command("person")
        def person_command(context):
            self.user_context[context.user_id] = {'state': 'awaiting_person'}
            context.reply("🎭 Введи имя актёра или режиссёра:")
        
        @self.bot.command("opinion")
        def opinion_command(context):
            # Получаем текст после /opinion
            text = context.message.text.replace('/opinion', '').strip()
            if text:
                self._handle_opinion(context, text)
            else:
                context.reply(
                    "🐾 Укажи фильм:\n"
                    "• /opinion 435 — по ID Кинопоиска\n"
                    "• /opinion Зеленая миля — по названию"
                )
        
        @self.bot.command("profile")
        def profile_command(context):
            self._handle_profile_command(context)
        
        @self.bot.on("message_callback")
        def handle_callback(context):
            """Обработка нажатий на инлайн-кнопки"""
            payload = context.payload
            user_id = context.user_id
            logger.info(f"Callback от {user_id}: {payload}")
            
            if payload == "random":
                self._handle_random_command(context)
            elif payload == "search":
                self.user_context[user_id] = {'state': 'awaiting_search'}
                context.reply_callback("🔍 Введи название фильма:", is_current=True)
            elif payload == "premiers":
                self._handle_premiers_command(context)
            elif payload == "person":
                self.user_context[user_id] = {'state': 'awaiting_person'}
                context.reply_callback("🎭 Введи имя актёра или режиссёра:", is_current=True)
            elif payload == "profile":
                self._handle_profile_command(context)
            elif payload == "opinion_prompt":
                context.reply_callback("🐾 Введи ID или название фильма:", is_current=True)
                self.user_context[user_id] = {'state': 'awaiting_opinion'}
            else:
                context.reply_callback(f"🐾 Неизвестная команда", is_current=True)
        
        @self.bot.on("message")
        def handle_message(context):
            """Обработка текстовых сообщений"""
            user_id = context.user_id
            text = context.text
            state = self.user_context.get(user_id, {}).get('state')
            
            if state == 'awaiting_search':
                self._handle_search(context, text)
                self.user_context.pop(user_id, None)
            elif state == 'awaiting_person':
                self._handle_person_search(context, text)
                self.user_context.pop(user_id, None)
            elif state == 'awaiting_opinion':
                self._handle_opinion(context, text)
                self.user_context.pop(user_id, None)
            else:
                context.reply("🐾 Используй /start для меню или /help для списка команд")
    
    # ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================
    
    def _handle_random_command(self, context):
        context.reply_callback("🎲 Ищу случайный фильм...", is_current=True)
        
        movie_data = get_random_movie_from_db(min_rating=7.0, is_new_only=False)
        if not movie_data:
            context.reply("😢 Не нашла фильмов.")
            return
        
        movie_details = get_movie_details(movie_data['id'])
        if not movie_details:
            context.reply("😢 Не могу найти информацию.")
            return
        
        card_text, _ = format_movie_card(movie_details)
        if card_text:
            # Добавляем кнопку для мнения
            keyboard = InlineKeyboard([
                [{"text": "🐾 Мнение о фильме", "callback": f"opinion_{movie_details['id']}"}]
            ])
            context.reply(card_text, parse_mode="html", keyboard=keyboard)
        else:
            context.reply("😢 Не могу показать карточку.")
    
    def _handle_premiers_command(self, context):
        context.reply_callback("🎉 Ищу ожидаемые премьеры...", is_current=True)
        
        premiers_list = get_premier_movies_from_db()
        if not premiers_list:
            context.reply("😢 Сейчас нет ожидаемых премьер.")
            return
        
        for movie_data in premiers_list[:5]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_premiers=True)
                if card_text:
                    context.reply(card_text, parse_mode="html")
        
        if len(premiers_list) > 5:
            context.reply(f"🐾 Нашла {len(premiers_list)} премьер. Показаны первые 5.")
    
    def _handle_profile_command(self, context):
        user_id = context.user_id
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        context.reply(
            f"👤 <b>Твой профиль</b>\n\n"
            f"📊 Тариф: {limits.get('tariff_name', 'Щенячий азарт')}\n"
            f"🎬 Мнений сегодня: {stats.get('opinion_count', 0)}/{limits.get('opinion_limit', 3)}\n"
            f"🔄 Свежих взглядов: {stats.get('regeneration_count', 0)}/{limits.get('regeneration_limit', 2)}\n\n"
            f"🐾 Функция баланса косточек в разработке.",
            parse_mode="html"
        )
    
    def _handle_search(self, context, query):
        if len(query) < 2:
            context.reply("🐾 Введи хотя бы 2 символа.")
            return
        
        context.reply(f"🔍 Ищу: {query}...")
        
        movies_list = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            context.reply(f"😢 По запросу '{query}' ничего не нашлось.")
            return
        
        for movie_data in movies_list[:5]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details)
                if card_text:
                    keyboard = InlineKeyboard([
                        [{"text": "🐾 Мнение о фильме", "callback": f"opinion_{movie_details['id']}"}]
                    ])
                    context.reply(card_text, parse_mode="html", keyboard=keyboard)
        
        if len(movies_list) > 5:
            context.reply(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.")
    
    def _handle_person_search(self, context, query):
        if len(query) < 2:
            context.reply("🐾 Введи хотя бы 2 символа.")
            return
        
        context.reply(f"🎭 Ищу фильмы с участием: {query}...")
        
        movies_list = search_movies_by_person_in_db(query, min_rating=0.0, max_rating=10.0)
        if not movies_list:
            context.reply(f"😢 По запросу '{query}' ничего не нашлось.")
            return
        
        for movie_data in movies_list[:5]:
            movie_details = get_movie_details(movie_data['id'])
            if movie_details:
                card_text, _ = format_movie_card(movie_details, is_person_search=True, query=query)
                if card_text:
                    keyboard = InlineKeyboard([
                        [{"text": "🐾 Мнение о фильме", "callback": f"opinion_{movie_details['id']}"}]
                    ])
                    context.reply(card_text, parse_mode="html", keyboard=keyboard)
        
        if len(movies_list) > 5:
            context.reply(f"🐾 Нашла {len(movies_list)} фильмов. Показаны первые 5.")
    
    def _handle_opinion(self, context, text):
        user_id = context.user_id
        
        # Проверяем лимиты
        limits = get_user_limits(user_id)
        stats = get_user_stats(user_id, date.today().isoformat())
        
        if stats['opinion_count'] >= limits['opinion_limit']:
            context.reply(
                f"🐾 Сегодня я уже высказала {stats['opinion_count']} мнений из {limits['opinion_limit']}.\n"
                f"Лимит обновится завтра!"
            )
            return
        
        # Ищем фильм
        movie_details = None
        
        if text.isdigit():
            movie_details = get_movie_details(int(text))
        
        if not movie_details:
            movies = search_movies_in_db(text, min_rating=0.0, max_rating=10.0)
            if movies:
                movie_details = get_movie_details(movies[0]['id'])
        
        if not movie_details:
            context.reply(f"😢 Не нашла фильм '{text}'. Проверь название или ID.")
            return
        
        movie_id = movie_details['id']
        movie_name = movie_details.get('name', 'Без названия')
        movie_year = movie_details.get('year', '')
        
        # Проверяем кэш
        cached_opinion = get_cached_opinion(movie_id)
        if cached_opinion:
            context.reply(
                f"🐾 Я уже смотрела <b>{movie_name}</b> ({movie_year}), вот что думаю:\n\n"
                f"{cached_opinion}\n\n🐾",
                parse_mode="html"
            )
            increment_stat_counter(user_id, 'opinion_count')
            record_user_opinion(user_id, movie_id)
            return
        
        # Генерируем новое мнение
        context.reply(f"🐾 Смотрю <b>{movie_name}</b> ({movie_year}) в ускоренном режиме... 🎬", parse_mode="html")
        
        if not ai_client:
            context.reply("😢 Генерация мнений временно недоступна.")
            return
        
        try:
            opinion = self._generate_opinion(movie_details)
            if opinion:
                save_opinion_cache(movie_id, opinion)
                increment_stat_counter(user_id, 'opinion_count')
                record_user_opinion(user_id, movie_id)
                context.reply(
                    f"🐾 Я посмотрела <b>{movie_name}</b> ({movie_year}), и вот что думаю:\n\n"
                    f"{opinion}\n\n🐾",
                    parse_mode="html"
                )
            else:
                context.reply("😢 Не удалось сгенерировать мнение.")
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            context.reply("🐾 Гав! Что-то пошло не так. Попробуй позже!")
    
    def _generate_opinion(self, movie_details: dict) -> str:
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
        return response.choices[0].message.content.strip()
    
    def run(self):
        logger.info("🚀 MaxAdapter (maxgram) запущен")
        self.bot.run()


if __name__ == "__main__":
    adapter = MaxAdapter()
    adapter.run()

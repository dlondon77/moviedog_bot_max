"""
КиноИщейка для мессенджера Max — v2
ИИ-ассистент + poiskkino.dev + подписки через Тинькофф

Установка:
    pip install maxapi openai aiohttp

Структура файлов:
    moviedog_max_v2.py   — этот файл
    data/users.db        — создаётся автоматически

Токены:
    MAX_TOKEN       — от @MasterBot в мессенджере Max
    DEEPSEEK_KEY    — sk-... от DeepSeek
    POISKKINO_KEY   — от @poiskkinodev_bot в Telegram
    TINKOFF_TERM    — TerminalKey от Тинькофф
    TINKOFF_PASS    — Password от Тинькофф
"""

import asyncio
import sqlite3
import logging
import os
import hashlib
import json
import aiohttp
from datetime import date, datetime
from openai import OpenAI
import httpx

from maxapi import Bot, Dispatcher
from maxapi.types import Message, CallbackQuery
from maxapi.types.keyboard import InlineKeyboardMarkup, InlineKeyboardButton
from maxapi.filters import Command

# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────────────
MAX_TOKEN      = os.environ.get("MAX_TOKEN", "ВАШ_ТОКЕН_MAX")
DEEPSEEK_KEY   = os.environ.get("DEEPSEEK_KEY", "ВАШ_КЛЮЧ_DEEPSEEK")
POISKKINO_KEY  = os.environ.get("POISKKINO_KEY", "ВАШ_КЛЮЧ_POISKKINO")
TINKOFF_TERM   = os.environ.get("TINKOFF_TERM", "ВАШ_TERMINAL_KEY")
TINKOFF_PASS   = os.environ.get("TINKOFF_PASS", "ВАШ_PASSWORD")

POISKKINO_BASE = "https://api.poiskkino.dev/v1.4"
TINKOFF_BASE   = "https://securepay.tinkoff.ru/v2"
DB_PATH        = "data/users.db"

# Лимиты бесплатного плана
FREE_OPINIONS_PER_DAY = 3

# Тарифы
PLANS = {
    "basic": {"price": 10000, "label": "Базовый — 100 ₽/мес"},  # цена в копейках
    "pro":   {"price": 30000, "label": "Про — 300 ₽/мес"},
}
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=MAX_TOKEN)
dp  = Dispatcher()

http_client = httpx.Client(timeout=60.0, follow_redirects=True)
ai_client = OpenAI(
    api_key=DEEPSEEK_KEY,
    base_url="https://api.deepseek.com/v1",
    http_client=http_client,
)

# Хранение истории диалога в памяти: {user_id: [{"role": ..., "content": ...}]}
dialog_history: dict[int, list] = {}
MAX_HISTORY_LEN = 10  # последних сообщений


# ── БД — юзеры, подписки, кеш мнений ────────────────────────────────────────
def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY,
            plan           TEXT    DEFAULT 'free',
            plan_expires   INTEGER DEFAULT 0,
            rebill_id      TEXT    DEFAULT '',
            opinions_today INTEGER DEFAULT 0,
            opinions_date  TEXT    DEFAULT ''
        )
    """)
    # Кеш мнений: один раз сгенерировали — храним навсегда
    conn.execute("""
        CREATE TABLE IF NOT EXISTS opinions_cache (
            movie_id   INTEGER PRIMARY KEY,
            opinion    TEXT    NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_cached_opinion(movie_id: int) -> str | None:
    """Возвращает мнение из кеша, если оно есть."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT opinion FROM opinions_cache WHERE movie_id = ?", (movie_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_opinion_cache(movie_id: int, opinion: str):
    """Сохраняет сгенерированное мнение в кеш."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO opinions_cache (movie_id, opinion, created_at) VALUES (?, ?, ?)",
        (movie_id, opinion, int(datetime.now().timestamp()))
    )
    conn.commit()
    conn.close()


def get_user(user_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row)


def is_subscribed(user: dict) -> bool:
    if user["plan"] == "free":
        return False
    return user["plan_expires"] > datetime.now().timestamp()


def can_get_opinion(user: dict) -> bool:
    """Проверяет лимит мнений для бесплатного плана."""
    if is_subscribed(user):
        return True
    today = date.today().isoformat()
    if user["opinions_date"] != today:
        return True  # новый день — счётчик сбросится
    return user["opinions_today"] < FREE_OPINIONS_PER_DAY


def increment_opinion_count(user_id: int):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    user = dict(conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone())
    if user["opinions_date"] != today:
        conn.execute(
            "UPDATE users SET opinions_today = 1, opinions_date = ? WHERE user_id = ?",
            (today, user_id)
        )
    else:
        conn.execute(
            "UPDATE users SET opinions_today = opinions_today + 1 WHERE user_id = ?",
            (user_id,)
        )
    conn.commit()
    conn.close()


def save_rebill(user_id: int, rebill_id: str, plan: str, expires_ts: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE users SET rebill_id = ?, plan = ?, plan_expires = ? WHERE user_id = ?",
        (rebill_id, plan, expires_ts, user_id)
    )
    conn.commit()
    conn.close()


# ── poiskkino.dev API ─────────────────────────────────────────────────────────
async def api_random_movie(min_rating: float = 7.0) -> dict | None:
    """Случайный фильм через API."""
    params = {
        "rating.imdb": f"{min_rating}-10",
        "type": "movie",
        "notNullFields": "name,description,rating.imdb,poster.url",
    }
    headers = {"X-API-KEY": POISKKINO_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{POISKKINO_BASE}/movie/random",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.error(f"API random movie error: {e}")
    return None


async def api_search_movies(query_params: dict, limit: int = 5) -> list[dict]:
    """
    Поиск фильмов по параметрам.
    query_params может содержать: genres.name, year, rating.imdb, type, etc.
    """
    headers = {"X-API-KEY": POISKKINO_KEY}
    params = {
        "limit": limit,
        "notNullFields": "name,description,rating.imdb",
        **query_params
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{POISKKINO_BASE}/movie",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("docs", [])
    except Exception as e:
        logger.error(f"API search error: {e}")
    return []


async def api_search_by_title(title: str) -> list[dict]:
    """Поиск по названию."""
    headers = {"X-API-KEY": POISKKINO_KEY}
    params = {"query": title, "limit": 5}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{POISKKINO_BASE}/movie/search",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("docs", [])
    except Exception as e:
        logger.error(f"API title search error: {e}")
    return []


# ── Форматирование карточки ───────────────────────────────────────────────────
def format_movie_card(m: dict, show_opinion_btn: bool = True) -> tuple[str, InlineKeyboardMarkup | None]:
    movie_id = m.get("id", "")
    name     = m.get("name") or m.get("alternativeName") or "Без названия"
    year     = m.get("year", "—")
    rating   = m.get("rating", {})
    kp_r     = rating.get("kp") or rating.get("imdb") or "—"
    genres   = ", ".join(g["name"] for g in m.get("genres", [])[:3]) or "—"
    countries = ", ".join(c["name"] for c in m.get("countries", [])[:2]) or "—"
    desc     = m.get("description") or ""
    if len(desc) > 350:
        desc = desc[:350] + "…"
    kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"

    text = (
        f"🎬 <b>{name}</b> ({year})\n"
        f"⭐ Рейтинг КП: {kp_r}\n"
        f"🎭 Жанр: {genres}\n"
        f"🌍 Страна: {countries}\n\n"
        f"{desc}\n\n"
        f"🔗 <a href='{kp_url}'>Кинопоиск</a>"
    )

    keyboard = None
    if show_opinion_btn and movie_id:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🐾 Мнение КиноИщейки",
                callback_data=f"opinion:{movie_id}"
            )
        ]])
    return text, keyboard


# ── DeepSeek: генерация мнения ────────────────────────────────────────────────
def generate_opinion_sync(m: dict) -> str:
    name      = m.get("name") or "Без названия"
    year      = m.get("year", "")
    genres    = ", ".join(g["name"] for g in m.get("genres", [])[:3])
    countries = ", ".join(c["name"] for c in m.get("countries", [])[:2])
    rating    = (m.get("rating") or {}).get("kp") or (m.get("rating") or {}).get("imdb") or "—"
    desc      = (m.get("description") or "")[:800]

    prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём на хорошее кино.
Говори о себе в женском роде, с юмором и энтузиазмом.

Информация о фильме:
🎬 Название: {name} ({year})
🌍 Страна: {countries}
🎭 Жанр: {genres}
⭐ Рейтинг КП: {rating}
📝 Сюжет: {desc}

Требования:
- 10-12 предложений, без markdown-разметки
- Сразу начинай с содержательной части
- Расскажи о настроении, смысле, плюсах и минусах
- В конце обязательно:
  Оценка: X/10 (краткий комментарий)
  Настроение: #Тег1 #Тег2 #Тег3
  Атмосфера: #Тег1 #Тег2 #Тег3"""

    response = ai_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Отвечай по-русски, дружелюбно, с юмором."},
            {"role": "user", "content": prompt}
        ],
        timeout=60,
    )
    return response.choices[0].message.content.strip()


# ── DeepSeek: ИИ-ассистент ────────────────────────────────────────────────────
def assistant_sync(user_id: int, user_message: str) -> dict:
    """
    Роутер + ассистент в одном вызове.
    DeepSeek решает: искать фильм, составить подборку или просто ответить.
    Возвращает {"action": "search"|"random"|"chat", "params": {...}, "reply": "..."}
    """
    history = dialog_history.get(user_id, [])

    system = """Ты — КиноИщейка, собака-девочка, кинокритик и ИИ-ассистент по кино.
Говори в женском роде, с юмором и теплотой.

Когда пользователь просит фильм или подборку — отвечай ТОЛЬКО в JSON:
{
  "action": "search",
  "params": {
    "genres.name": "триллер",
    "rating.imdb": "7-10",
    "year": "2010-2023",
    "type": "movie"
  },
  "reply": "Сейчас понюхаю базу... 🐾"
}

Для случайного фильма (без конкретики):
{"action": "random", "params": {}, "reply": "Ловлю первое попавшееся! 🎲"}

Для разговора, вопросов, благодарностей — обычный текст (не JSON):
{"action": "chat", "reply": "Твой ответ здесь"}

Доступные жанры: аниме, биография, боевик, драма, документальный, комедия, криминал, мелодрама,
мультфильм, мюзикл, приключения, семейный, спорт, триллер, ужасы, фантастика, фэнтези.
Параметры API: genres.name, rating.imdb (например "7-10"), year (например "2015-2023"), type (movie/tv-series).
Отвечай ТОЛЬКО валидным JSON."""

    messages = [{"role": "system", "content": system}]
    messages += history[-MAX_HISTORY_LEN:]
    messages.append({"role": "user", "content": user_message})

    response = ai_client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        timeout=60,
    )
    raw = response.choices[0].message.content.strip()

    # Сохраняем в историю
    if user_id not in dialog_history:
        dialog_history[user_id] = []
    dialog_history[user_id].append({"role": "user", "content": user_message})
    dialog_history[user_id].append({"role": "assistant", "content": raw})
    if len(dialog_history[user_id]) > MAX_HISTORY_LEN * 2:
        dialog_history[user_id] = dialog_history[user_id][-MAX_HISTORY_LEN * 2:]

    # Парсим JSON
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        return {"action": "chat", "reply": raw}


# ── Тинькофф платежи ──────────────────────────────────────────────────────────
def tinkoff_sign(params: dict) -> str:
    """Генерация подписи для Тинькофф."""
    check = {**params, "Password": TINKOFF_PASS}
    sorted_vals = "".join(str(v) for k, v in sorted(check.items()) if k not in ("Receipt", "DATA", "Token"))
    return hashlib.sha256(sorted_vals.encode()).hexdigest()


async def tinkoff_init(user_id: int, plan: str, order_id: str) -> str | None:
    """Инициализация первого платежа. Возвращает URL для оплаты."""
    amount = PLANS[plan]["price"]
    params = {
        "TerminalKey": TINKOFF_TERM,
        "Amount": amount,
        "OrderId": order_id,
        "Description": f"КиноИщейка — {PLANS[plan]['label']}",
        "Recurrent": "Y",
        "CustomerKey": str(user_id),
    }
    params["Token"] = tinkoff_sign(params)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{TINKOFF_BASE}/Init", json=params) as resp:
                data = await resp.json()
                if data.get("Success"):
                    return data.get("PaymentURL")
    except Exception as e:
        logger.error(f"Tinkoff Init error: {e}")
    return None


async def tinkoff_charge(user_id: int, rebill_id: str, plan: str, order_id: str) -> bool:
    """Рекуррентное списание."""
    amount = PLANS[plan]["price"]
    # Сначала Init
    init_params = {
        "TerminalKey": TINKOFF_TERM,
        "Amount": amount,
        "OrderId": order_id,
        "CustomerKey": str(user_id),
    }
    init_params["Token"] = tinkoff_sign(init_params)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{TINKOFF_BASE}/Init", json=init_params) as resp:
                init_data = await resp.json()
                if not init_data.get("Success"):
                    return False
                payment_id = init_data["PaymentId"]

            # Затем Charge
            charge_params = {
                "TerminalKey": TINKOFF_TERM,
                "PaymentId": str(payment_id),
                "RebillId": rebill_id,
            }
            charge_params["Token"] = tinkoff_sign(charge_params)
            async with session.post(f"{TINKOFF_BASE}/Charge", json=charge_params) as resp:
                data = await resp.json()
                return data.get("Success", False)
    except Exception as e:
        logger.error(f"Tinkoff Charge error: {e}")
    return False


# ── Хендлеры ─────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = get_user(message.sender.user_id)
    plan_label = "🆓 Бесплатный план" if not is_subscribed(user) else f"⭐ Подписка активна"
    await message.answer(
        f"🐾 Гав! Я — КиноИщейка!\n\n"
        f"Помогу найти фильм с собачьим чутьём 🎬\n\n"
        f"<b>Просто напиши что хочешь посмотреть</b> — я всё пойму:\n"
        f"«хочу что-то атмосферное на вечер»\n"
        f"«триллер как Исчезнувшая»\n"
        f"«смешной фильм для всей семьи»\n\n"
        f"Или используй команды:\n"
        f"/random — случайный фильм\n"
        f"/subscribe — подписка (безлимит ИИ)\n"
        f"/status — мой тариф\n\n"
        f"{plan_label}",
        parse_mode="HTML"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    user = get_user(message.sender.user_id)
    if is_subscribed(user):
        exp = datetime.fromtimestamp(user["plan_expires"]).strftime("%d.%m.%Y")
        text = f"⭐ Подписка активна до {exp}\nТариф: {user['plan']}\n\nМнения: безлимит 🐾"
    else:
        today = date.today().isoformat()
        used = user["opinions_today"] if user["opinions_date"] == today else 0
        left = max(0, FREE_OPINIONS_PER_DAY - used)
        text = (
            f"🆓 Бесплатный план\n"
            f"Мнений сегодня осталось: {left}/{FREE_OPINIONS_PER_DAY}\n\n"
            f"Хочешь безлимит? /subscribe 🐾"
        )
    await message.answer(text)


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Базовый — 100 ₽/мес", callback_data="pay:basic")],
        [InlineKeyboardButton(text="🚀 Про — 300 ₽/мес",     callback_data="pay:pro")],
    ])
    await message.answer(
        "🐾 Выбери тариф:\n\n"
        "<b>Базовый (100 ₽/мес)</b>\n"
        "— Безлимит мнений\n"
        "— ИИ-ассистент\n\n"
        "<b>Про (300 ₽/мес)</b>\n"
        "— Всё из базового\n"
        "— Подборки по настроению\n"
        "— Приоритетная генерация\n",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@dp.message(Command("random"))
async def cmd_random(message: Message):
    await message.answer("🎲 Ищу случайный фильм...")
    loop = asyncio.get_event_loop()
    movie = await api_random_movie()
    if not movie:
        await message.answer("🐾 Что-то пошло не так с API. Попробуй ещё раз!")
        return
    text, keyboard = format_movie_card(movie)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


# ── Главный хендлер: ИИ-ассистент ────────────────────────────────────────────
@dp.message()
async def handle_message(message: Message):
    user_id = message.sender.user_id
    user = get_user(user_id)
    text = message.body.text if message.body else ""
    if not text:
        return

    # Бесплатные пользователи могут пользоваться ассистентом,
    # но мнения лимитированы (проверяется при нажатии кнопки)
    await message.answer("🐾 Думаю...")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, assistant_sync, user_id, text)

    action = result.get("action", "chat")
    reply  = result.get("reply", "🐾")
    params = result.get("params", {})

    if action == "random":
        await message.answer(reply)
        movie = await api_random_movie()
        if movie:
            card_text, keyboard = format_movie_card(movie)
            await message.answer(card_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.answer("🐾 API не отвечает, попробуй позже")

    elif action == "search":
        await message.answer(reply)
        movies = await api_search_movies(params, limit=3)
        if not movies:
            await message.answer("🐾 Ничего не нашла по таким параметрам. Попробуй переформулировать!")
            return
        for movie in movies:
            card_text, keyboard = format_movie_card(movie)
            await message.answer(card_text, parse_mode="HTML", reply_markup=keyboard)

    else:  # chat
        await message.answer(reply)


# ── Callback: мнение + оплата ─────────────────────────────────────────────────
@dp.on.callback_query()
async def handle_callback(callback: CallbackQuery):
    data = callback.payload
    user_id = callback.sender.user_id
    user = get_user(user_id)

    # ── Мнение о фильме ───────────────────────────────────────────────────────
    if data and data.startswith("opinion:"):
        if not can_get_opinion(user):
            await callback.answer(
                f"🐾 Лимит {FREE_OPINIONS_PER_DAY} мнения в день исчерпан!\n"
                f"Подписка снимает ограничение — /subscribe",
                show_alert=True
            )
            return

        movie_id = int(data.split(":")[1])
        await callback.answer("Смотрю в ускоренном режиме... 🎬")

        # Получаем полные данные о фильме
        headers = {"X-API-KEY": POISKKINO_KEY}
        movie = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{POISKKINO_BASE}/movie/{movie_id}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        movie = await resp.json()
        except Exception as e:
            logger.error(f"Movie fetch error: {e}")

        if not movie:
            await bot.send_message(
                chat_id=callback.chat.chat_id,
                text="🐾 Не смогла загрузить данные о фильме. Попробуй позже!"
            )
            return

        # Сначала смотрим в кеш — зачем платить дважды?
        opinion = get_cached_opinion(movie_id)
        if opinion:
            logger.info(f"Opinion cache HIT for movie {movie_id}")
        else:
            logger.info(f"Opinion cache MISS for movie {movie_id}, generating...")
            loop = asyncio.get_event_loop()
            try:
                opinion = await loop.run_in_executor(None, generate_opinion_sync, movie)
                save_opinion_cache(movie_id, opinion)
            except Exception as e:
                logger.error(f"Opinion error: {e}")
                await bot.send_message(
                    chat_id=callback.chat.chat_id,
                    text="🐾 Гав! Кажется, я перегрызла провод... Попробуй позже!"
                )
                return

        increment_opinion_count(user_id)
        name = movie.get("name") or "фильм"
        year = movie.get("year", "")
        kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"

        await bot.send_message(
            chat_id=callback.chat.chat_id,
            text=(
                f"Я посмотрела <a href='{kp_url}'>{name}</a> ({year}), вот что думаю:\n\n"
                f"{opinion}\n\n🐾"
            ),
            parse_mode="HTML"
        )

    # ── Оплата подписки ───────────────────────────────────────────────────────
    elif data and data.startswith("pay:"):
        plan = data.split(":")[1]
        if plan not in PLANS:
            await callback.answer("Неизвестный тариф")
            return

        order_id = f"{user_id}_{plan}_{int(datetime.now().timestamp())}"
        await callback.answer("Создаю ссылку для оплаты...")

        pay_url = await tinkoff_init(user_id, plan, order_id)
        if not pay_url:
            await bot.send_message(
                chat_id=callback.chat.chat_id,
                text="🐾 Не удалось создать платёж. Попробуй позже или напиши в поддержку."
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💳 Оплатить", url=pay_url)
        ]])
        await bot.send_message(
            chat_id=callback.chat.chat_id,
            text=(
                f"🐾 Ссылка для оплаты готова!\n\n"
                f"Тариф: {PLANS[plan]['label']}\n"
                f"После оплаты подписка активируется автоматически."
            ),
            reply_markup=keyboard
        )


# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    init_db()
    logger.info("КиноИщейка v2 запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

# core/agent.py — ОПТИМИЗИРОВАННАЯ ВЕРСИЯ
# Вся ИИ-логика вынесена сюда. max_adapter.py только вызывает run_agent()
# + Режимные промпты (recommend, actor, plot_search, compare, chat)
# + format_response() — скрывает ID в HTML-комментарии
# + extract_movie_ids() — извлекает ID из скрытых комментариев
# + Запрет на "сохранить в любимые"
# + Мнение о фильме НЕ ЗДЕСЬ (остаётся в max_adapter.py)

import json
import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from core import movie as movie_module
from core import user as user_module

logger = logging.getLogger(__name__)

# ==================== ИСТОРИЯ ДИАЛОГОВ ====================
CHAT_HISTORY: Dict[int, List[Dict[str, str]]] = {}
MAX_HISTORY_LENGTH = 10

def clear_chat_history(user_id: int):
    if user_id in CHAT_HISTORY:
        CHAT_HISTORY[user_id] = []

def get_chat_history(user_id: int) -> list:
    return CHAT_HISTORY.get(user_id, [])

def add_to_history(user_id: int, role: str, content: str):
    """Добавляет сообщение в историю диалога"""
    CHAT_HISTORY.setdefault(user_id, []).append({"role": role, "content": content})
    if len(CHAT_HISTORY[user_id]) > MAX_HISTORY_LENGTH * 2:
        CHAT_HISTORY[user_id] = CHAT_HISTORY[user_id][-MAX_HISTORY_LENGTH * 2:]


# ==================== СИСТЕМНЫЙ ПРОМПТ ====================

SYSTEM_PROMPT = """Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём на хорошее кино! 🐕🎬

ВАЖНО: ОТВЕЧАЙ ТОЛЬКО ОБЫЧНЫМ ТЕКСТОМ С HTML-ССЫЛКАМИ!
НЕ используй маркдаун-разметку (** для жирного, * для курсива).
НЕ используй длинные линии-разделители (━, —, ─, ===, ***).
НЕ пиши служебные фразы: "Сначала найду ID", "Отлично! Теперь сравню", "Ого, какие данные".
НЕ ПРЕДЛАГАЙ СОХРАНЯТЬ ФИЛЬМЫ В ЛЮБИМЫЕ — этой функции пока нет в боте!

КОГДА ДАЁШЬ СПИСОК ФИЛЬМОВ — ВСЕГДА УКАЗЫВАЙ ID В ФОРМАТЕ (ID: число)!
ID должен быть в конце строки с фильмом, после ссылки.
ЭТО ОБЯЗАТЕЛЬНО для работы кнопки "Показать карточки"!

Формат ссылки на фильм:
<a href='https://www.kinopoisk.ru/film/[ID]/'>Название фильма</a> (Год) ⭐ Рейтинг (ID: число)

Пример правильного ответа:
🎬 <a href='https://www.kinopoisk.ru/film/447301/'>Начало</a> (2010) ⭐ 8.6 (ID: 447301)

Говори о себе в женском роде, с юмором и энтузиазмом.
Используй переносы строк для структуры.
Всегда старайся дать полезные и конкретные рекомендации.
НЕ спрашивай пользователя, хочет ли он сохранить фильм в любимые.
НЕ предлагай сохранять фильмы в любимые."""


CHAT_SYSTEM_PROMPT = """Ты — КиноИщейка, собака-девочка, кинокритик. 🐕

Ты в режиме "Пообщаться" — это лёгкий, быстрый диалог.
ОТВЕЧАЙ КОРОТКО (2-3 предложения)!
Давай интересные факты, шутки, забавные детали о фильмах и актёрах.

НЕ делай подборки и сравнения — это не твоя задача сейчас.
НЕ предлагай сохранять фильмы в любимые — этой функции пока нет!

Если пользователь просит найти фильм, подобрать по жанру или сравнить — скажи, что для этого есть специальные команды, и предложи выбрать нужную.

Пример ответа, если запрос похож на стандартную функцию:
"Ой, я чувствую, что тут пахнет поиском! 🔍 Для поиска фильмов лучше использовать /search, а для поиска по актёрам — /person. Хочешь, я подскажу что-то интересное о кино вместо этого?"
"""


# ==================== РЕЖИМНЫЕ ПРОМПТЫ ====================

def get_recommend_prompt(query: str, exclude_ids: List[int] = None, context: str = None) -> str:
    """Формирует промпт для режима 'Подобрать фильм'"""
    exclude_text = ""
    if exclude_ids:
        exclude_text = f"\n\n🚫 НЕ ПРЕДЛАГАЙ фильмы с этими ID: {exclude_ids}\nЭти фильмы уже показывали пользователю. Предложи новые, другие варианты!"
    
    context_text = ""
    if context:
        context_text = f"\n\n📝 Контекст предыдущего диалога:\n{context}\n\nУчитывай, что мы уже обсуждали, и не повторяйся."
    
    return f"""
Ты — КиноИщейка, собака-девочка, кинокритик. 🐕

Пользователь просит подборку фильмов: {query}
{context_text}
{exclude_text}

Твоя задача:
1. Найди от 3 до 5 фильмов, которые идеально подходят под запрос
2. Для каждого: название (год), рейтинг, почему он подходит
3. Учти жанр, настроение, стиль, если пользователь указал
4. В конце дай совет, с какого фильма начать

ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате (ID: число) в конце строки!
НЕ используй длинные линии-разделители.
НЕ предлагай сохранять фильмы в любимые — этой функции пока нет!
Форматируй ответ красиво, с эмодзи и переносами строк.
"""


def get_actor_prompt(query: str, exclude_ids: List[int] = None, context: str = None) -> str:
    """Формирует промпт для режима 'Актёрский нюх'"""
    exclude_text = ""
    if exclude_ids:
        exclude_text = f"\n\n🚫 НЕ ПРЕДЛАГАЙ фильмы с этими ID: {exclude_ids}\nЭти фильмы уже показывали пользователю. Предложи новые, другие варианты!"
    
    context_text = ""
    if context:
        context_text = f"\n\n📝 Контекст предыдущего диалога:\n{context}\n\nУчитывай, что мы уже обсуждали, и не повторяйся."
    
    return f"""
Ты — КиноИщейка, кинокритик с отличным нюхом на таланты. 🐕

Пользователь спрашивает о персоне: {query}
{context_text}
{exclude_text}

Найди в базе этого актёра или режиссёра и сделай разбор:
1. Лучшие роли/работы (с рейтингом и кратким объяснением)
2. Самые недооценённые фильмы
3. Учти период и жанр, если указаны
4. В конце дай рекомендацию

ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате (ID: число) в конце строки!
НЕ используй длинные линии-разделители.
НЕ предлагай сохранять фильмы в любимые — этой функции пока нет!
Форматируй ответ красиво, с эмодзи и переносами строк.
"""


def get_plot_prompt(query: str, exclude_ids: List[int] = None, context: str = None) -> str:
    """Формирует промпт для режима 'По сюжету'"""
    exclude_text = ""
    if exclude_ids:
        exclude_text = f"\n\n🚫 НЕ ПРЕДЛАГАЙ фильмы с этими ID: {exclude_ids}\nЭти фильмы уже показывали пользователю. Предложи новые, другие варианты!"
    
    context_text = ""
    if context:
        context_text = f"\n\n📝 Контекст предыдущего диалога:\n{context}\n\nУчитывай, что мы уже обсуждали, и не повторяйся."
    
    return f"""
Ты — КиноИщейка, собака-девочка с отличным нюхом на сюжеты. 🐕

Пользователь описал, что хочет посмотреть: {query}
{context_text}
{exclude_text}

Найди 3 фильма, которые лучше всего подходят под это описание.
Для каждого: название (год), рейтинг, краткое объяснение, почему он подходит.
В конце посоветуй, с какого начать.

ОБЯЗАТЕЛЬНО указывай ID каждого фильма в формате (ID: число) в конце строки!
НЕ используй длинные линии-разделители.
НЕ предлагай сохранять фильмы в любимые — этой функции пока нет!
Форматируй ответ красиво, с эмодзи и переносами строк.
"""


def get_compare_prompt(query: str, exclude_ids: List[int] = None, context: str = None) -> str:
    """Формирует промпт для режима 'Сравнить фильмы'"""
    exclude_text = ""
    if exclude_ids:
        exclude_text = f"\n\n🚫 НЕ ПРЕДЛАГАЙ фильмы с этими ID: {exclude_ids}\nЭти фильмы уже показывали пользователю. Предложи новые, другие варианты!"
    
    context_text = ""
    if context:
        context_text = f"\n\n📝 Контекст предыдущего диалога:\n{context}\n\nУчитывай, что мы уже обсуждали, и не повторяйся."
    
    return f"""
Ты — КиноИщейка. Сравни фильмы: {query}
{context_text}
{exclude_text}

Важно:
- НЕ пиши "Сначала найду ID", "Отлично! Теперь сравню", "Ого, какие данные"
- НЕ используй линии-разделители
- НЕ предлагай сохранять фильмы в любимые — этой функции пока нет!
- Сразу переходи к сравнению
- Укажи ID фильмов в формате (ID: число) в конце строки!
- В конце добавь рекомендацию

Сравни: рейтинги, жанры, режиссёров, актёров, какой лучше и почему.
"""


def get_chat_prompt(query: str) -> str:
    return f"Ответь коротко (2-3 предложения) и интересно. НЕ предлагай сохранять фильмы в любимые — этой функции пока нет: {query}"


# ==================== ФОРМАТИРОВАНИЕ ОТВЕТА ====================

def format_response(response: str) -> str:
    """Форматирует ответ агента — скрывает ID, убирает дубли"""
    if not response:
        return response
    
    # Убираем множественные переносы
    response = re.sub(r'\n{3,}', '\n\n', response)
    
    # Скрываем ID в HTML-комментарии
    response = re.sub(r'\(ID:\s*(\d+)\)', r'<!--ID:\1-->', response)
    
    # Убираем служебные фразы для сравнения
    response = re.sub(r'Сначала найду ID[^.]*\.', '', response)
    response = re.sub(r'Отлично! Теперь сравню[^.]*\.', '', response)
    response = re.sub(r'Ого, какие данные[^.]*\.', '', response)
    
    # Убираем длинные линии
    response = re.sub(r'━{3,}', '', response)
    response = re.sub(r'—{3,}', '', response)
    response = re.sub(r'─{3,}', '', response)
    response = re.sub(r'_{3,}', '', response)
    response = re.sub(r'\*{3,}', '', response)
    
    # Убираем дублирование рекомендаций
    if "Мой совет" in response and "Мой вердикт" in response:
        совет_pos = response.find("Мой совет")
        вердикт_pos = response.find("Мой вердикт")
        if вердикт_pos > совет_pos:
            before_verdict = response[:вердикт_pos].strip()
            after_verdict = response[вердикт_pos:].strip()
            if len(after_verdict) < 50 or "---" in after_verdict:
                response = before_verdict
    
    # Чистим лишние переносы после удаления
    response = re.sub(r'\n{3,}', '\n\n', response)
    
    return response.strip()


def extract_movie_ids(text: str) -> List[int]:
    """Извлекает ID фильмов из ответа агента — приоритет у ссылок"""
    ids = []
    
    # ПАТТЕРН 1: ссылка на Кинопоиск (film или series)
    pattern_link = r'https?://www\.kinopoisk\.ru/(?:film|series)/(\d+)/'
    link_matches = re.findall(pattern_link, text)
    for m in link_matches:
        ids.append(int(m))
    
    # Если нашли ID в ссылках — возвращаем их
    if ids:
        return list(set(ids))
    
    # ПАТТЕРН 2: скрытые ID в HTML-комментариях <!--ID:123-->
    pattern_comment = r'<!--ID:(\d+)-->'
    matches = re.findall(pattern_comment, text)
    for m in matches:
        ids.append(int(m))
    
    # ПАТТЕРН 3: (ID: 123)
    pattern = r'\(ID:\s*(\d+)\)'
    matches = re.findall(pattern, text)
    for m in matches:
        ids.append(int(m))
    
    return list(set(ids))


# ==================== ИНСТРУМЕНТЫ ====================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_movie_by_title",
            "description": "Ищет фильмы по названию. Возвращает список с ID, названием, годом, рейтингом, жанрами.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название фильма"},
                    "min_rating": {"type": "number", "description": "Минимальный рейтинг (по умолчанию 0)"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_actor_by_name",
            "description": "Ищет актёра или режиссёра по имени.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Имя актёра или режиссёра"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_movies_by_actor",
            "description": "Возвращает фильмы с участием актёра или режиссёра.",
            "parameters": {
                "type": "object",
                "properties": {
                    "actor_name": {"type": "string", "description": "Полное имя"},
                    "min_rating": {"type": "number", "description": "Минимальный рейтинг (по умолчанию 0)"}
                },
                "required": ["actor_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_movie_details_by_id",
            "description": "Полная информация о фильме по ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "movie_id": {"type": "integer", "description": "ID фильма"}
                },
                "required": ["movie_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_random_movie",
            "description": "Случайный фильм с рейтингом выше указанного.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_rating": {"type": "number", "description": "Минимальный рейтинг (по умолчанию 7.0)"},
                    "is_new": {"type": "boolean", "description": "Только новинки (по умолчанию False)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_premieres",
            "description": "Ожидаемые премьеры.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_premieres_by_month",
            "description": "Премьеры по месяцу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Номер месяца (1-12)"},
                    "year": {"type": "integer", "description": "Год (по умолчанию текущий)"}
                },
                "required": ["month"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_movies_by_genre",
            "description": "Ищет фильмы по жанру.",
            "parameters": {
                "type": "object",
                "properties": {
                    "genre": {"type": "string", "description": "Жанр (комедия, драма, боевик и т.д.)"},
                    "min_rating": {"type": "number", "description": "Минимальный рейтинг (по умолчанию 5)"}
                },
                "required": ["genre"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_movies_by_year",
            "description": "Ищет фильмы по диапазону лет.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year_from": {"type": "integer", "description": "Начальный год"},
                    "year_to": {"type": "integer", "description": "Конечный год"},
                    "min_rating": {"type": "number", "description": "Минимальный рейтинг (по умолчанию 0)"}
                },
                "required": ["year_from", "year_to"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_similar_movies",
            "description": "Находит похожие фильмы на основе жанров.",
            "parameters": {
                "type": "object",
                "properties": {
                    "movie_id": {"type": "integer", "description": "ID фильма-образца"},
                    "limit": {"type": "integer", "description": "Максимум результатов (по умолчанию 5)"}
                },
                "required": ["movie_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_movies",
            "description": "Сравнивает два фильма по рейтингу, жанрам, актёрам и режиссёрам.",
            "parameters": {
                "type": "object",
                "properties": {
                    "movie_id1": {"type": "integer", "description": "ID первого фильма"},
                    "movie_id2": {"type": "integer", "description": "ID второго фильма"}
                },
                "required": ["movie_id1", "movie_id2"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_favorites",
            "description": "Любимые фильмы пользователя.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recommendations_by_preferences",
            "description": "Рекомендации на основе любимых фильмов пользователя.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_to_favorites",
            "description": "Сохраняет фильм в любимые.",
            "parameters": {
                "type": "object",
                "properties": {
                    "movie_id": {"type": "integer", "description": "ID фильма"},
                    "movie_name": {"type": "string", "description": "Название фильма"}
                },
                "required": ["movie_id", "movie_name"]
            }
        }
    }
]


# ==================== РЕАЛИЗАЦИЯ ФУНКЦИЙ ====================

def _search_movie_by_title(title: str, min_rating: float = 0.0) -> List[Dict]:
    movies = movie_module.search_movies_in_db(title, min_rating=min_rating, max_rating=10.0)
    return [
        {
            "id": m.get("id"),
            "name": m.get("name"),
            "year": m.get("year"),
            "rating": m.get("rating"),
            "genres": m.get("genres", [])[:3],
            "actors": [a.get("name") or a.get("enName") for a in m.get("actors", [])[:3]]
        }
        for m in movies[:10]
    ]


def _search_actor_by_name(name: str) -> Optional[Dict]:
    persons = movie_module.search_persons(name, limit=3)
    if not persons:
        return None
    return {
        "id": persons[0].get("id"),
        "name": persons[0].get("name"),
        "type": persons[0].get("type", "actor"),
    }


def _get_movies_by_actor(actor_name: str, min_rating: float = 0.0) -> List[Dict]:
    movies = movie_module.search_movies_by_person_in_db(actor_name, min_rating=min_rating, max_rating=10.0)
    return [
        {"id": m.get("id"), "name": m.get("name"), "year": m.get("year"), "rating": m.get("rating")}
        for m in movies[:10]
    ]


def _get_movie_details_by_id(movie_id: int) -> Optional[Dict]:
    movie = movie_module.get_movie_details(movie_id)
    if not movie:
        return None
    return {
        "id": movie.get("id"),
        "name": movie.get("name"),
        "year": movie.get("year"),
        "rating": movie.get("rating"),
        "description": movie.get("description"),
        "genres": movie.get("genres", []),
        "directors": [d.get("name") for d in movie.get("directors", [])],
        "actors": [a.get("name") for a in movie.get("actors", [])[:5]]
    }


def _get_random_movie(min_rating: float = 7.0, is_new: bool = False) -> Optional[Dict]:
    movie_data = movie_module.get_random_movie_from_db(min_rating=min_rating, is_new_only=is_new)
    if not movie_data:
        return None
    return {
        "id": movie_data.get("id"),
        "name": movie_data.get("name"),
        "year": movie_data.get("year"),
        "rating": movie_data.get("rating"),
        "genres": movie_data.get("genres", [])[:3],
    }


def _get_premieres() -> List[Dict]:
    movies = movie_module.get_premier_movies_from_db()
    return [
        {"id": m.get("id"), "name": m.get("name"), "year": m.get("year"), "rating": m.get("rating")}
        for m in movies[:10]
    ]


def _get_premieres_by_month(month: int, year: int = None) -> List[Dict]:
    if year is None:
        year = datetime.now().year
    movies = movie_module.get_premier_movies_from_db()
    result = []
    for m in movies:
        premiere = m.get("premiere_russia") or m.get("premiere_world")
        if premiere:
            try:
                d = datetime.strptime(premiere[:10], "%Y-%m-%d")
                if d.month == month and d.year == year:
                    result.append(m)
            except:
                pass
    return [
        {"id": m.get("id"), "name": m.get("name"), "rating": m.get("rating")}
        for m in result[:10]
    ]


def _search_movies_by_genre(genre: str, min_rating: float = 5.0) -> List[Dict]:
    movies = movie_module.search_movies_in_db("", min_rating=min_rating, max_rating=10.0)
    result = []
    for m in movies:
        if any(genre.lower() in g.lower() for g in m.get("genres", [])):
            result.append(m)
        if len(result) >= 10:
            break
    return [
        {"id": m.get("id"), "name": m.get("name"), "year": m.get("year"), "rating": m.get("rating")}
        for m in result[:10]
    ]


def _search_movies_by_year(year_from: int, year_to: int, min_rating: float = 0.0) -> List[Dict]:
    movies = movie_module.search_movies_in_db("", min_rating=min_rating, max_rating=10.0)
    result = []
    for m in movies:
        year = m.get("year")
        if year and year_from <= year <= year_to:
            result.append(m)
        if len(result) >= 10:
            break
    return [
        {"id": m.get("id"), "name": m.get("name"), "year": m.get("year"), "rating": m.get("rating")}
        for m in result[:10]
    ]


def _search_similar_movies(movie_id: int, limit: int = 5) -> List[Dict]:
    movie = movie_module.get_movie_details(movie_id)
    if not movie:
        return []
    genres = movie.get("genres", [])
    similar = []
    for genre in genres[:2]:
        movies = movie_module.search_movies_in_db("", min_rating=5.0, max_rating=10.0)
        for m in movies:
            if genre in m.get("genres", []) and m.get("id") != movie_id:
                if m not in similar:
                    similar.append(m)
            if len(similar) >= limit:
                break
        if len(similar) >= limit:
            break
    return [
        {"id": m.get("id"), "name": m.get("name"), "year": m.get("year"), "rating": m.get("rating")}
        for m in similar[:limit]
    ]


def _compare_movies(movie_id1: int, movie_id2: int) -> Dict:
    m1 = movie_module.get_movie_details(movie_id1)
    m2 = movie_module.get_movie_details(movie_id2)
    if not m1 or not m2:
        return {"error": "Один из фильмов не найден"}
    
    actors1 = [a.get("name") for a in m1.get("actors", [])[:5] if a.get("name")]
    actors2 = [a.get("name") for a in m2.get("actors", [])[:5] if a.get("name")]
    
    return {
        "movie1": {
            "name": m1.get("name"),
            "year": m1.get("year"),
            "rating": m1.get("rating"),
            "genres": m1.get("genres", [])[:3],
            "directors": [d.get("name") for d in m1.get("directors", [])[:2]]
        },
        "movie2": {
            "name": m2.get("name"),
            "year": m2.get("year"),
            "rating": m2.get("rating"),
            "genres": m2.get("genres", [])[:3],
            "directors": [d.get("name") for d in m2.get("directors", [])[:2]]
        },
        "common_actors": list(set(actors1) & set(actors2))
    }


def _get_user_favorites(user_id: int) -> List[Dict]:
    return movie_module.get_favorite_movies(user_id, limit=10)


def _get_recommendations_by_preferences(user_id: int) -> List[Dict]:
    favorites = movie_module.get_favorite_movies(user_id, limit=5)
    if not favorites:
        return []
    genres = {}
    for fav in favorites:
        movie = movie_module.get_movie_details(fav["movie_id"])
        if movie:
            for g in movie.get("genres", []):
                genres[g] = genres.get(g, 0) + 1
    top_genres = sorted(genres.items(), key=lambda x: -x[1])[:2]
    result = []
    for genre, _ in top_genres:
        movies = movie_module.search_movies_in_db("", min_rating=7.0, max_rating=10.0)
        for m in movies:
            if genre in m.get("genres", []):
                result.append({
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "year": m.get("year"),
                    "rating": m.get("rating")
                })
    return result[:5]


def _save_to_favorites(user_id: int, movie_id: int, movie_name: str) -> bool:
    try:
        return movie_module.add_favorite_movie(user_id, movie_id)
    except Exception as e:
        logger.error(f"Ошибка сохранения в любимые: {e}")
        return False


# ==================== ДИСПЕТЧЕР ====================

FUNCTION_MAP = {
    "search_movie_by_title": _search_movie_by_title,
    "search_actor_by_name": _search_actor_by_name,
    "get_movies_by_actor": _get_movies_by_actor,
    "get_movie_details_by_id": _get_movie_details_by_id,
    "get_random_movie": _get_random_movie,
    "get_premieres": _get_premieres,
    "get_premieres_by_month": _get_premieres_by_month,
    "search_movies_by_genre": _search_movies_by_genre,
    "search_movies_by_year": _search_movies_by_year,
    "search_similar_movies": _search_similar_movies,
    "compare_movies": _compare_movies,
    "get_user_favorites": _get_user_favorites,
    "get_recommendations_by_preferences": _get_recommendations_by_preferences,
    "save_to_favorites": _save_to_favorites,
}


async def execute_tool(func_name: str, func_args: dict, user_id: int = None) -> dict:
    logger.info(f"🔧 Вызов функции: {func_name}")
    if func_name not in FUNCTION_MAP:
        return {"error": f"Неизвестная функция: {func_name}"}
    try:
        func = FUNCTION_MAP[func_name]
        if func_name in ["save_to_favorites", "get_user_favorites", "get_recommendations_by_preferences"]:
            result = func(user_id, **func_args) if func_name == "save_to_favorites" else func(user_id)
        else:
            result = func(**func_args)
        if result is None:
            return {"result": None, "message": "Ничего не найдено"}
        return {"result": result}
    except Exception as e:
        logger.error(f"Ошибка выполнения функции {func_name}: {e}")
        return {"error": str(e)}


# ==================== ОЧИСТКА И ИЗВЛЕЧЕНИЕ ID ====================

def _clean_markdown(text: str) -> str:
    """Удаляет маркдаун-разметку, сохраняя структуру"""
    if not text:
        return text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


def _build_context_from_history(user_id: int, max_messages: int = 4) -> str:
    """Строит контекст из истории диалога для передачи в промпт"""
    history = CHAT_HISTORY.get(user_id, [])
    if not history:
        return ""
    
    recent = history[-max_messages:] if len(history) > max_messages else history
    
    context_lines = []
    for msg in recent:
        role = "Пользователь" if msg["role"] == "user" else "КиноИщейка"
        context_lines.append(f"{role}: {msg['content'][:200]}...")
    
    return "\n".join(context_lines)


# ==================== ГЛАВНЫЙ ЦИКЛ ====================

async def run_agent(
    user_query: str, 
    user_id: int, 
    ai_client, 
    agent_mode: str = 'chat', 
    chat_mode: bool = False,
    exclude_ids: List[int] = None,
    use_context: bool = True
) -> str:
    """
    Запускает агента с учётом режима.
    
    Режимы:
    - recommend: подборка фильмов
    - actor: актёрский нюх
    - plot_search: поиск по сюжету
    - compare: сравнение фильмов
    - chat: свободный диалог (короткие ответы)
    
    Параметры:
    - exclude_ids: ID фильмов, которые уже показывали (запрет повтора)
    - use_context: использовать ли историю диалога
    """
    context_text = ""
    if use_context:
        context_text = _build_context_from_history(user_id, max_messages=4)
    
    if agent_mode == 'chat' or chat_mode:
        system_prompt = CHAT_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT
    
    if agent_mode == 'recommend':
        final_query = get_recommend_prompt(user_query, exclude_ids, context_text)
    elif agent_mode == 'actor':
        final_query = get_actor_prompt(user_query, exclude_ids, context_text)
    elif agent_mode == 'plot_search':
        final_query = get_plot_prompt(user_query, exclude_ids, context_text)
    elif agent_mode == 'compare':
        final_query = get_compare_prompt(user_query, exclude_ids, context_text)
    elif agent_mode == 'chat' or chat_mode:
        final_query = get_chat_prompt(user_query)
    else:
        final_query = user_query
    
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    if agent_mode != 'chat' and not chat_mode:
        history = CHAT_HISTORY.get(user_id, [])
        if history:
            messages.extend(history[-MAX_HISTORY_LENGTH:])
    
    messages.append({"role": "user", "content": final_query})
    
    max_iterations = 15
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        try:
            response = ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.7,
            )
        except Exception as e:
            logger.error(f"Ошибка вызова DeepSeek: {e}")
            return "🐾 Гав! Что-то пошло не так с моей нейросетью. Попробуй позже!"
        
        message = response.choices[0].message
        
        if message.tool_calls:
            logger.info(f"🔄 DeepSeek запросил {len(message.tool_calls)} вызовов функций (итерация {iteration})")
            messages.append(message)
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}
                result = await execute_tool(func_name, func_args, user_id)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
        else:
            raw_response = message.content
            clean_response = _clean_markdown(raw_response)
            formatted_response = format_response(clean_response)
            
            add_to_history(user_id, "user", user_query)
            add_to_history(user_id, "assistant", formatted_response)
            
            return formatted_response
    
    return "🐾 Я слишком долго думала... Попробуй переформулировать запрос или задай его по частям!"

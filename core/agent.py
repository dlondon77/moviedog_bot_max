# core/agent.py — ОБНОВЛЁННАЯ ВЕРСИЯ
# + Поддержка режимов (recommend, actor, compare, premieres, chat)
# + Запрет маркдауна в ответах
# + Улучшенный системный промпт

import json
import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from core import movie as movie_module

logger = logging.getLogger(__name__)


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
        "common_actors": list(set(
            [a.get("name") for a in m1.get("actors", [])[:5]] &
            [a.get("name") for a in m2.get("actors", [])[:5]]
        ))
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


# ==================== СИСТЕМНЫЙ ПРОМПТ ====================

SYSTEM_PROMPT = """Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём на хорошее кино! 🐕🎬

ВАЖНО: ОТВЕЧАЙ ТОЛЬКО ОБЫЧНЫМ ТЕКСТОМ БЕЗ МАРКДАУН-РАЗМЕТКИ!
НЕ используй звёздочки (*), подчёркивания (_) и backticks (`) для выделения.
Используй эмодзи и переносы строк для структуры.

Ты умеешь:
1. Искать фильмы по названию, жанру, году, актёрам
2. Находить похожие фильмы
3. Сравнивать фильмы
4. Показывать премьеры (все и по месяцам)
5. Давать рекомендации на основе любимых фильмов пользователя
6. Сохранять фильмы в любимые

Говори о себе в женском роде, с юмором и энтузиазмом.
Используй собачьи метафоры: "обнюхала базу", "мой нюх подсказывает", "взяла след", "хвост трубой".
Отвечай по-русски, дружелюбно.

Всегда старайся дать 3-5 конкретных рекомендаций.
Если пользователь спрашивает, что посмотреть — предложи несколько вариантов и объясни почему они подходят."""


# ==================== ГЛАВНЫЙ ЦИКЛ ====================

async def run_agent(user_query: str, user_id: int, ai_client) -> str:
    """
    Главный цикл агента с очисткой ответа от маркдауна
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query}
    ]
    
    max_iterations = 7
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
            logger.info(f"🔄 DeepSeek запросил {len(message.tool_calls)} вызовов функций")
            messages.append(message)
            
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}
                    logger.error(f"Ошибка парсинга аргументов для {func_name}")
                
                result = await execute_tool(func_name, func_args, user_id)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
        else:
            # Получаем ответ и очищаем от маркдауна
            raw_response = message.content or "🐾 Я не нашла ответ на твой вопрос."
            clean_response = _clean_markdown(raw_response)
            return clean_response
    
    return "🐾 Я слишком долго думала... Попробуй переформулировать запрос!"


def _clean_markdown(text: str) -> str:
    """
    Очищает текст от маркдаун-разметки:
    - убирает звёздочки (*)
    - убирает подчёркивания (_)
    - убирает backticks (`)
    - убирает маркдаун-заголовки (#)
    """
    if not text:
        return text
    
    # Убираем маркдаун-заголовки
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    
    # Убираем звёздочки (жирный, курсив)
    text = text.replace('*', '')
    
    # Убираем подчёркивания (курсив)
    text = text.replace('_', '')
    
    # Убираем backticks (код)
    text = text.replace('`', '')
    
    # Убираем маркдаун-ссылки [текст](url) → текст
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Убираем множественные пробелы
    text = re.sub(r'\s+', ' ', text)
    
    # Убираем пустые строки в начале и конце
    text = text.strip()
    
    return text

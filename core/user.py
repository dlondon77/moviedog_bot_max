# core/user.py
import logging
import sqlite3
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import json

from core import db
from core import movie as movie_module

logger = logging.getLogger(__name__)

# ==================== ОСНОВНЫЕ ФУНКЦИИ ПОЛЬЗОВАТЕЛЯ ====================

def register_user(user_id: int, username: str = '', first_name: str = '', last_name: str = '', platform: str = 'max'):
    """Регистрирует пользователя"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, platform, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, platform, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user_id}: {e}")
    finally:
        conn.close()

def get_user_limits(user_id: int) -> Dict:
    """Возвращает лимиты пользователя на основе тарифа"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tariff_name, tariff_end_date 
        FROM users 
        WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {
            'tariff_name': 'Щенячий азарт',
            'tariff_end_date': 'бессрочно',
            'opinion_limit': 5,
            'regeneration_limit': 0,
            'agent_limit': 1
        }
    
    tariff_name = row[0] or 'Щенячий азарт'
    tariff_end_date = row[1] or 'бессрочно'
    
    tariff_limits = {
        'Щенячий азарт': {'opinion_limit': 5, 'regeneration_limit': 0, 'agent_limit': 1},
        'Охотничий': {'opinion_limit': 10, 'regeneration_limit': 0, 'agent_limit': 5},
        'Ищейка': {'opinion_limit': 30, 'regeneration_limit': 5, 'agent_limit': 20},
        'Вожак': {'opinion_limit': 999999, 'regeneration_limit': 999999, 'agent_limit': 999999},
    }
    
    limits = tariff_limits.get(tariff_name, tariff_limits['Щенячий азарт'])
    limits['tariff_name'] = tariff_name
    limits['tariff_end_date'] = tariff_end_date
    
    return limits

def get_user_stats(user_id: int, date_str: str) -> Dict:
    """Возвращает статистику пользователя за день"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT opinion_count, regeneration_count, agent_query_count
        FROM user_stats 
        WHERE user_id = ? AND date = ?
    ''', (user_id, date_str))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {
            'opinion_count': 0,
            'regeneration_count': 0,
            'agent_query_count': 0
        }
    
    return {
        'opinion_count': row[0] or 0,
        'regeneration_count': row[1] or 0,
        'agent_query_count': row[2] or 0
    }

def increment_stat_counter(user_id: int, stat_type: str):
    """Увеличивает счётчик статистики пользователя"""
    today = date.today().isoformat()
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO user_stats (user_id, date, opinion_count, regeneration_count, agent_query_count)
        VALUES (?, ?, 0, 0, 0)
    ''', (user_id, today))
    
    if stat_type == 'opinion_count':
        cursor.execute('''
            UPDATE user_stats 
            SET opinion_count = opinion_count + 1 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
    elif stat_type == 'regeneration_count':
        cursor.execute('''
            UPDATE user_stats 
            SET regeneration_count = regeneration_count + 1 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
    elif stat_type == 'agent_query_count':
        cursor.execute('''
            UPDATE user_stats 
            SET agent_query_count = agent_query_count + 1 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
    
    conn.commit()
    conn.close()

def record_user_opinion(user_id: int, movie_id: int):
    """Записывает, что пользователь запросил мнение о фильме"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO user_opinions (user_id, movie_id, created_at)
        VALUES (?, ?, ?)
    ''', (user_id, movie_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def record_user_query(user_id: int, query: str, agent_mode: str = 'search'):
    """Записывает историю запросов пользователя"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO user_query_history (user_id, query, agent_mode, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, query[:200], agent_mode, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка записи истории запросов: {e}")
    finally:
        conn.close()

def get_user_query_history(user_id: int, limit: int = 50) -> List[Dict]:
    """Получает историю запросов пользователя"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT query, agent_mode, created_at
        FROM user_query_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {'query': row[0], 'agent_mode': row[1], 'created_at': row[2]}
        for row in rows
    ]


# ==================== СПИСКИ ФИЛЬМОВ ====================

# ---- ЛЮБИМЫЕ ФИЛЬМЫ ----

def add_favorite_movie(user_id: int, movie_id: int) -> bool:
    """Добавляет фильм в любимые"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO favorite_movies (user_id, movie_id, added_at)
            VALUES (?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat()))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка добавления в любимые: {e}")
        return False
    finally:
        conn.close()

def remove_favorite_movie(user_id: int, movie_id: int) -> bool:
    """Удаляет фильм из любимых"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            DELETE FROM favorite_movies WHERE user_id = ? AND movie_id = ?
        ''', (user_id, movie_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка удаления из любимых: {e}")
        return False
    finally:
        conn.close()

def is_favorite(user_id: int, movie_id: int) -> bool:
    """Проверяет, есть ли фильм в любимых"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM favorite_movies WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_favorite_movies(user_id: int, limit: int = 20) -> List[Dict]:
    """Получает список любимых фильмов"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT fm.movie_id, fm.added_at, m.name, m.year, m.rating
        FROM favorite_movies fm
        JOIN movies m ON fm.movie_id = m.id
        WHERE fm.user_id = ?
        ORDER BY fm.added_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {'movie_id': row[0], 'added_at': row[1], 'name': row[2], 'year': row[3], 'rating': row[4]}
        for row in rows
    ]

def get_favorite_movie_ids(user_id: int) -> List[int]:
    """Получает список ID любимых фильмов"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT movie_id FROM favorite_movies WHERE user_id = ?
    ''', (user_id,))
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids


# ---- БУДУ СМОТРЕТЬ ----

def add_to_watchlist(user_id: int, movie_id: int, status: str = 'planned') -> bool:
    """Добавляет фильм в список 'Буду смотреть'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO watchlist (user_id, movie_id, added_at, status)
            VALUES (?, ?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat(), status))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка добавления в watchlist: {e}")
        return False
    finally:
        conn.close()

def remove_from_watchlist(user_id: int, movie_id: int) -> bool:
    """Удаляет фильм из списка 'Буду смотреть'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            DELETE FROM watchlist WHERE user_id = ? AND movie_id = ?
        ''', (user_id, movie_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка удаления из watchlist: {e}")
        return False
    finally:
        conn.close()

def is_in_watchlist(user_id: int, movie_id: int) -> bool:
    """Проверяет, есть ли фильм в списке 'Буду смотреть'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM watchlist WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_watchlist(user_id: int, limit: int = 20) -> List[Dict]:
    """Получает список 'Буду смотреть'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.movie_id, w.added_at, w.status, m.name, m.year, m.rating
        FROM watchlist w
        JOIN movies m ON w.movie_id = m.id
        WHERE w.user_id = ?
        ORDER BY w.added_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {'movie_id': row[0], 'added_at': row[1], 'status': row[2], 'name': row[3], 'year': row[4], 'rating': row[5]}
        for row in rows
    ]


# ---- НЕ ПОНРАВИЛИСЬ ----

def add_disliked_movie(user_id: int, movie_id: int, reason: str = None) -> bool:
    """Добавляет фильм в список 'Не понравились'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO disliked_movies (user_id, movie_id, added_at, reason)
            VALUES (?, ?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat(), reason))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка добавления в disliked: {e}")
        return False
    finally:
        conn.close()

def remove_disliked_movie(user_id: int, movie_id: int) -> bool:
    """Удаляет фильм из списка 'Не понравились'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            DELETE FROM disliked_movies WHERE user_id = ? AND movie_id = ?
        ''', (user_id, movie_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка удаления из disliked: {e}")
        return False
    finally:
        conn.close()

def is_disliked(user_id: int, movie_id: int) -> bool:
    """Проверяет, есть ли фильм в списке 'Не понравились'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM disliked_movies WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_disliked_movie_ids(user_id: int) -> List[int]:
    """Получает список ID фильмов, которые не понравились"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT movie_id FROM disliked_movies WHERE user_id = ?
    ''', (user_id,))
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids


# ==================== АНАЛИТИКА ДЛЯ КИНОПРОФИЛЯ ====================

def get_user_cinema_stats(user_id: int) -> Dict:
    """Собирает статистику для кинопрофиля"""
    stats = get_user_stats(user_id, date.today().isoformat())
    favorites = get_favorite_movies(user_id, limit=20)
    history = get_user_query_history(user_id, limit=50)
    
    return {
        'total_queries': len(history),
        'favorites_count': len(favorites),
        'agent_queries': stats.get('agent_query_count', 0),
        'opinions_count': stats.get('opinion_count', 0)
    }

def analyze_user_genres(user_id: int) -> List[Tuple[str, int]]:
    """Анализирует жанры из любимых фильмов"""
    favorites = get_favorite_movies(user_id, limit=20)
    genre_count = {}
    
    for fav in favorites:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            for genre in movie.get('genres', []):
                genre_count[genre] = genre_count.get(genre, 0) + 1
    
    return sorted(genre_count.items(), key=lambda x: -x[1])[:5]

def analyze_user_actors(user_id: int) -> List[Tuple[str, int]]:
    """Анализирует актёров из любимых фильмов"""
    favorites = get_favorite_movies(user_id, limit=20)
    actor_count = {}
    
    for fav in favorites:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            for actor in movie.get('actors', [])[:5]:
                name = actor.get('name') or actor.get('enName')
                if name:
                    actor_count[name] = actor_count.get(name, 0) + 1
    
    return sorted(actor_count.items(), key=lambda x: -x[1])[:5]

def analyze_user_directors(user_id: int) -> List[Tuple[str, int]]:
    """Анализирует режиссёров из любимых фильмов"""
    favorites = get_favorite_movies(user_id, limit=20)
    director_count = {}
    
    for fav in favorites:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            for director in movie.get('directors', []):
                name = director.get('name') or director.get('enName')
                if name:
                    director_count[name] = director_count.get(name, 0) + 1
    
    return sorted(director_count.items(), key=lambda x: -x[1])[:5]

def get_user_achievements(user_id: int, genres: List[Tuple], stats: Dict) -> List[str]:
    """Формирует список достижений пользователя"""
    achievements = []
    
    fav_count = stats.get('favorites_count', 0)
    if fav_count >= 20:
        achievements.append("🏅 КиноКоллекционер — 20+ любимых фильмов")
    elif fav_count >= 10:
        achievements.append("🏅 КиноМан — 10+ любимых фильмов")
    elif fav_count >= 5:
        achievements.append("🏅 КиноЛюбитель — 5+ любимых фильмов")
    
    total_queries = stats.get('total_queries', 0)
    if total_queries >= 100:
        achievements.append("🏅 КиноГуру — 100+ запросов")
    elif total_queries >= 50:
        achievements.append("🏅 КиноЭксперт — 50+ запросов")
    elif total_queries >= 20:
        achievements.append("🏅 КиноИскатель — 20+ запросов")
    
    genre_names = [g[0] for g in genres[:3]]
    if 'драма' in genre_names:
        achievements.append("🏅 КиноГурман — любишь драмы")
    if any(g in genre_names for g in ['фантастика', 'фэнтези']):
        achievements.append("🏅 Звездочёт — любишь фантастику")
    if 'комедия' in genre_names:
        achievements.append("🏅 КиноКлоун — любишь комедии")
    if any(g in genre_names for g in ['ужасы', 'триллер']):
        achievements.append("🏅 КиноСмельчак — любишь ужасы и триллеры")
    
    return achievements


# ==================== ОБНОВЛЕНИЕ ТАРИФА ====================

def update_user_tariff(user_id: int, tariff_name: str, duration_days: int = 30):
    """Обновляет тариф пользователя"""
    end_date = (datetime.now() + timedelta(days=duration_days)).isoformat()
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE users 
            SET tariff_name = ?, tariff_end_date = ?
            WHERE user_id = ?
        ''', (tariff_name, end_date, user_id))
        conn.commit()
        logger.info(f"✅ Тариф пользователя {user_id} обновлён на {tariff_name}")
    except Exception as e:
        logger.error(f"Ошибка обновления тарифа: {e}")
    finally:
        conn.close()

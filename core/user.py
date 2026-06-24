# core/user.py
import logging
import sqlite3
import json
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from collections import Counter

from core import db
from core import movie as movie_module

logger = logging.getLogger(__name__)

# ==================== КОНСТАНТЫ ====================

TARIFFS = {
    'Щенячий азарт': {
        'opinion_limit': 5,
        'regeneration_limit': 0,
        'agent_limit': 1,
        'price': 0,
        'icon': '🐶'
    },
    'Охотничий': {
        'opinion_limit': 10,
        'regeneration_limit': 0,
        'agent_limit': 5,
        'price': 199,
        'icon': '🐕'
    },
    'Ищейка': {
        'opinion_limit': 30,
        'regeneration_limit': 5,
        'agent_limit': 20,
        'price': 399,
        'icon': '🕵️'
    },
    'Вожак': {
        'opinion_limit': -1,
        'regeneration_limit': -1,
        'agent_limit': -1,
        'price': 999,
        'icon': '🐺'
    }
}

DEFAULT_TARIFF = 'Щенячий азарт'


# ==================== ПОЛЬЗОВАТЕЛИ ====================

def register_user(user_id: int, username: str = '', first_name: str = '', last_name: str = '', platform: str = 'max') -> bool:
    """Регистрирует нового пользователя"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, platform, tariff_name, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username[:50], first_name[:50], last_name[:50], platform, DEFAULT_TARIFF, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user_id}: {e}")
        return False
    finally:
        conn.close()

def get_user_tariff(user_id: int) -> str:
    """Возвращает тариф пользователя"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tariff_name FROM users WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0] or DEFAULT_TARIFF
    return DEFAULT_TARIFF

def set_user_tariff(user_id: int, tariff_name: str, duration_days: int = 30) -> bool:
    """Устанавливает тариф пользователю"""
    if tariff_name not in TARIFFS:
        return False
    
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
        return True
    except Exception as e:
        logger.error(f"Ошибка установки тарифа: {e}")
        return False
    finally:
        conn.close()

def get_user_limits(user_id: int) -> Dict:
    """Возвращает лимиты пользователя на сегодня"""
    tariff_name = get_user_tariff(user_id)
    tariff = TARIFFS.get(tariff_name, TARIFFS[DEFAULT_TARIFF])
    
    return {
        'tariff_name': tariff_name,
        'opinion_limit': tariff['opinion_limit'],
        'regeneration_limit': tariff['regeneration_limit'],
        'agent_limit': tariff['agent_limit'],
        'price': tariff['price'],
        'icon': tariff['icon'],
        'tariff_end_date': _get_tariff_end_date(user_id)
    }

def _get_tariff_end_date(user_id: int) -> str:
    """Возвращает дату окончания тарифа"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tariff_end_date FROM users WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return 'бессрочно'

def get_user_stats(user_id: int, stat_date: str = None) -> Dict:
    """Возвращает статистику пользователя за день"""
    if stat_date is None:
        stat_date = date.today().isoformat()
    
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT opinion_count, regeneration_count, agent_count
        FROM user_stats
        WHERE user_id = ? AND stat_date = ?
    ''', (user_id, stat_date))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'opinion_count': row[0] or 0,
            'regeneration_count': row[1] or 0,
            'agent_count': row[2] or 0
        }
    return {'opinion_count': 0, 'regeneration_count': 0, 'agent_count': 0}

def increment_stat_counter(user_id: int, stat_type: str) -> bool:
    """Увеличивает счётчик статистики"""
    stat_date = date.today().isoformat()
    valid_types = ['opinion_count', 'regeneration_count', 'agent_count']
    
    if stat_type not in valid_types:
        return False
    
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f'''
            INSERT INTO user_stats (user_id, stat_date, {stat_type})
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, stat_date) DO UPDATE SET
                {stat_type} = {stat_type} + 1
        ''', (user_id, stat_date))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления статистики: {e}")
        return False
    finally:
        conn.close()

def record_user_opinion(user_id: int, movie_id: int, opinion_text: str = '') -> bool:
    """Записывает мнение пользователя о фильме"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO user_movie_opinions (user_id, movie_id, opinion_text, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, movie_id, opinion_text, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка записи мнения пользователя: {e}")
        return False
    finally:
        conn.close()


# ==================== ЛЮБИМЫЕ ФИЛЬМЫ ====================

def add_favorite_movie(user_id: int, movie_id: int, rating: int = 0, review: str = '') -> bool:
    """Добавляет фильм в любимые"""
    movie = movie_module.get_movie_details(movie_id)
    if not movie:
        logger.warning(f"Фильм {movie_id} не найден в БД")
        return False
    
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO favorite_movies (user_id, movie_id, added_at, user_rating, review)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat(), rating, review))
        conn.commit()
        return True
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

def is_favorite(user_id: int, movie_id: int) -> bool:
    """Проверяет, есть ли фильм в любимых"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM favorite_movies 
        WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_favorite_movies(user_id: int, limit: int = 20, offset: int = 0) -> List[Dict]:
    """Получает список любимых фильмов с деталями"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT fm.movie_id, fm.added_at, fm.user_rating, fm.review,
               m.name, m.year, m.rating
        FROM favorite_movies fm
        JOIN movies m ON fm.movie_id = m.id
        WHERE fm.user_id = ?
        ORDER BY fm.added_at DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'movie_id': row[0],
            'added_at': row[1],
            'user_rating': row[2],
            'review': row[3],
            'name': row[4],
            'year': row[5],
            'rating': row[6]
        })
    return result

def get_favorite_movies_count(user_id: int) -> int:
    """Количество любимых фильмов"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM favorite_movies WHERE user_id = ?
    ''', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_favorite_ids(user_id: int) -> List[int]:
    """Получает только ID любимых фильмов"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT movie_id FROM favorite_movies WHERE user_id = ?
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ==================== СПИСОК "БУДУ СМОТРЕТЬ" ====================

def add_to_watchlist(user_id: int, movie_id: int, status: str = 'planned') -> bool:
    """Добавляет фильм в список 'Буду смотреть'"""
    movie = movie_module.get_movie_details(movie_id)
    if not movie:
        logger.warning(f"Фильм {movie_id} не найден в БД")
        return False
    
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO watchlist (user_id, movie_id, added_at, status)
            VALUES (?, ?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat(), status))
        conn.commit()
        return True
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
        SELECT 1 FROM watchlist 
        WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_watchlist(user_id: int, limit: int = 20, offset: int = 0) -> List[Dict]:
    """Получает список 'Буду смотреть' с деталями"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.movie_id, w.added_at, w.status,
               m.name, m.year, m.rating
        FROM watchlist w
        JOIN movies m ON w.movie_id = m.id
        WHERE w.user_id = ?
        ORDER BY w.added_at DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    rows = cursor.fetchall()
    conn.close()
    
    status_labels = {
        'planned': '📌 Запланировано',
        'watching': '▶️ Смотрю',
        'watched': '✅ Посмотрено'
    }
    
    result = []
    for row in rows:
        result.append({
            'movie_id': row[0],
            'added_at': row[1],
            'status': row[2],
            'status_label': status_labels.get(row[2], row[2]),
            'name': row[3],
            'year': row[4],
            'rating': row[5]
        })
    return result

def get_watchlist_count(user_id: int) -> int:
    """Количество фильмов в списке 'Буду смотреть'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM watchlist WHERE user_id = ?
    ''', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_watchlist_ids(user_id: int) -> List[int]:
    """Получает только ID фильмов из списка 'Буду смотреть'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT movie_id FROM watchlist WHERE user_id = ?
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ==================== "НЕ ПОНРАВИЛОСЬ" ====================

def add_disliked_movie(user_id: int, movie_id: int, reason: str = '') -> bool:
    """Добавляет фильм в список 'Не понравилось'"""
    movie = movie_module.get_movie_details(movie_id)
    if not movie:
        logger.warning(f"Фильм {movie_id} не найден в БД")
        return False
    
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO disliked_movies (user_id, movie_id, added_at, reason)
            VALUES (?, ?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat(), reason))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления в 'Не понравилось': {e}")
        return False
    finally:
        conn.close()

def remove_disliked_movie(user_id: int, movie_id: int) -> bool:
    """Удаляет фильм из списка 'Не понравилось'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            DELETE FROM disliked_movies WHERE user_id = ? AND movie_id = ?
        ''', (user_id, movie_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка удаления из 'Не понравилось': {e}")
        return False
    finally:
        conn.close()

def is_disliked(user_id: int, movie_id: int) -> bool:
    """Проверяет, есть ли фильм в списке 'Не понравилось'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM disliked_movies 
        WHERE user_id = ? AND movie_id = ?
    ''', (user_id, movie_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_disliked_movies(user_id: int, limit: int = 20, offset: int = 0) -> List[Dict]:
    """Получает список 'Не понравилось' с деталями"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.movie_id, d.added_at, d.reason,
               m.name, m.year, m.rating
        FROM disliked_movies d
        JOIN movies m ON d.movie_id = m.id
        WHERE d.user_id = ?
        ORDER BY d.added_at DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'movie_id': row[0],
            'added_at': row[1],
            'reason': row[2],
            'name': row[3],
            'year': row[4],
            'rating': row[5]
        })
    return result

def get_disliked_count(user_id: int) -> int:
    """Количество фильмов в списке 'Не понравилось'"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM disliked_movies WHERE user_id = ?
    ''', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_disliked_ids(user_id: int) -> List[int]:
    """Получает только ID фильмов из списка 'Не понравилось' (для исключения)"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT movie_id FROM disliked_movies WHERE user_id = ?
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ==================== ИСТОРИЯ ПРОСМОТРОВ ====================

def add_to_watch_history(user_id: int, movie_id: int) -> bool:
    """Добавляет фильм в историю просмотров"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO watch_history (user_id, movie_id, watched_at)
            VALUES (?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления в историю: {e}")
        return False
    finally:
        conn.close()

def get_watch_history(user_id: int, limit: int = 20) -> List[Dict]:
    """Получает историю просмотров"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT wh.movie_id, wh.watched_at,
               m.name, m.year, m.rating
        FROM watch_history wh
        JOIN movies m ON wh.movie_id = m.id
        WHERE wh.user_id = ?
        ORDER BY wh.watched_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'movie_id': row[0],
            'watched_at': row[1],
            'name': row[2],
            'year': row[3],
            'rating': row[4]
        })
    return result

def get_watch_history_count(user_id: int) -> int:
    """Количество просмотренных фильмов"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM watch_history WHERE user_id = ?
    ''', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


# ==================== КИНОПРОФИЛЬ ====================

def get_cinema_profile(user_id: int) -> Dict:
    """Получает кинопрофиль пользователя"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT profile_json, last_updated FROM user_cinema_profile WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        try:
            profile = json.loads(row[0])
            profile['last_updated'] = row[1]
            return profile
        except:
            return _create_empty_profile(user_id)
    
    return _create_empty_profile(user_id)


def _create_empty_profile(user_id: int) -> Dict:
    """Создаёт пустой профиль"""
    profile = {
        'user_id': user_id,
        'favorite_genres': [],
        'favorite_actors': [],
        'favorite_directors': [],
        'disliked_genres': [],
        'disliked_actors': [],
        'disliked_directors': [],
        'preferred_eras': [],
        'preferred_mood': [],
        'top_movies': [],
        'watch_history': [],
        'statistics': {
            'total_queries': 0,
            'total_recommendations': 0,
            'total_opinions': 0,
            'favorite_count': 0,
            'disliked_count': 0,
            'watchlist_count': 0
        },
        'genre_stats': {},
        'actor_stats': {},
        'director_stats': {},
        'era_stats': {},
        'mood_stats': {},
        'patterns': {},
        'version': 1
    }
    _save_cinema_profile(user_id, profile)
    return profile


def _save_cinema_profile(user_id: int, profile: Dict) -> bool:
    """Сохраняет кинопрофиль в БД"""
    profile['last_updated'] = datetime.now().isoformat()
    profile['user_id'] = user_id
    
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO user_cinema_profile (user_id, profile_json, last_updated, version)
            VALUES (?, ?, ?, ?)
        ''', (user_id, json.dumps(profile, ensure_ascii=False), profile['last_updated'], profile.get('version', 1)))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения профиля: {e}")
        return False
    finally:
        conn.close()


def update_cinema_profile_from_movie(user_id: int, movie_id: int, action: str = 'watched') -> Dict:
    """
    Обновляет профиль на основе фильма
    action: 'favorite', 'disliked', 'watchlist', 'watched', 'opinion'
    """
    profile = get_cinema_profile(user_id)
    movie = movie_module.get_movie_details(movie_id)
    
    if not movie:
        return profile
    
    genres = movie.get('genres', [])
    actors = [a.get('name') for a in movie.get('actors', [])[:5] if a.get('name')]
    directors = [d.get('name') for d in movie.get('directors', []) if d.get('name')]
    rating = movie.get('rating', 0)
    year = movie.get('year', 0)
    name = movie.get('name', '')
    
    era = _get_era(year) if year else None
    
    # Обновляем статистику
    stats = profile.get('statistics', {})
    if action == 'favorite':
        stats['favorite_count'] = stats.get('favorite_count', 0) + 1
        for genre in genres:
            if genre not in profile['favorite_genres']:
                profile['favorite_genres'].append(genre)
            profile['genre_stats'][genre] = profile['genre_stats'].get(genre, {'count': 0})
            profile['genre_stats'][genre]['count'] += 1
            profile['genre_stats'][genre]['last_used'] = datetime.now().isoformat()
        for actor in actors:
            if actor not in profile['favorite_actors']:
                profile['favorite_actors'].append(actor)
            profile['actor_stats'][actor] = profile['actor_stats'].get(actor, {'count': 0})
            profile['actor_stats'][actor]['count'] += 1
            profile['actor_stats'][actor]['last_used'] = datetime.now().isoformat()
        for director in directors:
            if director not in profile['favorite_directors']:
                profile['favorite_directors'].append(director)
            profile['director_stats'][director] = profile['director_stats'].get(director, {'count': 0})
            profile['director_stats'][director]['count'] += 1
            profile['director_stats'][director]['last_used'] = datetime.now().isoformat()
        if era and era not in profile['preferred_eras']:
            profile['preferred_eras'].append(era)
        profile['era_stats'][era] = profile['era_stats'].get(era, {'count': 0})
        profile['era_stats'][era]['count'] += 1
        
        if movie_id not in [m.get('id') for m in profile['top_movies']]:
            profile['top_movies'].append({
                'id': movie_id,
                'name': name,
                'year': year,
                'rating': rating,
                'added_at': datetime.now().isoformat()
            })
        profile['top_movies'] = sorted(profile['top_movies'], key=lambda x: x.get('rating', 0), reverse=True)[:10]
    
    elif action == 'disliked':
        stats['disliked_count'] = stats.get('disliked_count', 0) + 1
        for genre in genres:
            if genre not in profile['disliked_genres']:
                profile['disliked_genres'].append(genre)
        for actor in actors:
            if actor not in profile['disliked_actors']:
                profile['disliked_actors'].append(actor)
        for director in directors:
            if director not in profile['disliked_directors']:
                profile['disliked_directors'].append(director)
    
    elif action == 'watchlist':
        stats['watchlist_count'] = stats.get('watchlist_count', 0) + 1
    
    elif action == 'watched' or action == 'opinion':
        if movie_id not in profile['watch_history']:
            profile['watch_history'].append(movie_id)
            if len(profile['watch_history']) > 50:
                profile['watch_history'] = profile['watch_history'][-50:]
    
    profile['statistics'] = stats
    
    # Ограничиваем списки
    profile['favorite_genres'] = profile['favorite_genres'][:10]
    profile['favorite_actors'] = profile['favorite_actors'][:10]
    profile['favorite_directors'] = profile['favorite_directors'][:10]
    profile['disliked_genres'] = profile['disliked_genres'][:10]
    profile['disliked_actors'] = profile['disliked_actors'][:10]
    profile['disliked_directors'] = profile['disliked_directors'][:10]
    profile['preferred_eras'] = profile['preferred_eras'][:5]
    profile['preferred_mood'] = profile['preferred_mood'][:5]
    
    # Обновляем паттерны
    profile['patterns'] = _analyze_patterns(profile)
    
    _save_cinema_profile(user_id, profile)
    return profile


def update_cinema_profile_from_query(user_id: int, query: str, agent_mode: str = None) -> Dict:
    """
    Обновляет профиль на основе запроса пользователя
    """
    profile = get_cinema_profile(user_id)
    query_lower = query.lower()
    
    # Обновляем статистику запросов
    stats = profile.get('statistics', {})
    stats['total_queries'] = stats.get('total_queries', 0) + 1
    if agent_mode:
        stats['total_recommendations'] = stats.get('total_recommendations', 0) + 1
    profile['statistics'] = stats
    
    # Извлекаем жанры из запроса
    genre_keywords = {
        'комеди': 'Комедия',
        'драм': 'Драма',
        'триллер': 'Триллер',
        'ужас': 'Ужасы',
        'фантастик': 'Фантастика',
        'боевик': 'Боевик',
        'мелодрам': 'Мелодрама',
        'вестерн': 'Вестерн',
        'мюзикл': 'Мюзикл',
        'анимац': 'Анимация',
        'приключен': 'Приключения',
        'детектив': 'Детектив'
    }
    
    found_genres = []
    for key, genre in genre_keywords.items():
        if key in query_lower:
            found_genres.append(genre)
    
    for genre in found_genres:
        if genre not in profile['favorite_genres']:
            profile['favorite_genres'].append(genre)
        profile['genre_stats'][genre] = profile['genre_stats'].get(genre, {'count': 0})
        profile['genre_stats'][genre]['count'] += 1
    
    # Извлекаем эпоху
    if any(w in query_lower for w in ['современн', '2000', '2010', '2020']):
        era = 'Современное'
        if era not in profile['preferred_eras']:
            profile['preferred_eras'].append(era)
        profile['era_stats'][era] = profile['era_stats'].get(era, {'count': 0})
        profile['era_stats'][era]['count'] += 1
    if any(w in query_lower for w in ['90-е', 'девяност']):
        era = '90-е'
        if era not in profile['preferred_eras']:
            profile['preferred_eras'].append(era)
        profile['era_stats'][era] = profile['era_stats'].get(era, {'count': 0})
        profile['era_stats'][era]['count'] += 1
    if any(w in query_lower for w in ['80-е', 'восьмидесят']):
        era = '80-е'
        if era not in profile['preferred_eras']:
            profile['preferred_eras'].append(era)
        profile['era_stats'][era] = profile['era_stats'].get(era, {'count': 0})
        profile['era_stats'][era]['count'] += 1
    
    # Извлекаем настроение
    mood_keywords = {
        'весёл': 'Весёлое',
        'смешн': 'Весёлое',
        'грустн': 'Грустное',
        'трогательн': 'Грустное',
        'напряжён': 'Напряжённое',
        'романтичн': 'Романтичное',
        'страшн': 'Страшное',
        'вдохновляющ': 'Вдохновляющее',
        'душевн': 'Душевное',
        'лёгк': 'Лёгкое',
        'глубок': 'Глубокое'
    }
    
    for key, mood in mood_keywords.items():
        if key in query_lower:
            if mood not in profile['preferred_mood']:
                profile['preferred_mood'].append(mood)
            profile['mood_stats'][mood] = profile['mood_stats'].get(mood, {'count': 0})
            profile['mood_stats'][mood]['count'] += 1
    
    # Обновляем паттерны
    profile['patterns'] = _analyze_patterns(profile)
    
    _save_cinema_profile(user_id, profile)
    return profile


def _get_era(year: int) -> str:
    """Определяет эпоху по году"""
    if year < 1950:
        return 'Классика'
    elif year < 1980:
        return '70-е и старше'
    elif year < 1990:
        return '80-е'
    elif year < 2000:
        return '90-е'
    elif year < 2010:
        return '2000-е'
    elif year < 2020:
        return '2010-е'
    else:
        return 'Современное'


def _analyze_patterns(profile: Dict) -> Dict:
    """Анализирует профиль и выявляет паттерны"""
    patterns = {}
    
    # Любит ли сюжетные повороты?
    if 'Триллер' in profile.get('favorite_genres', []) and 'Драма' in profile.get('favorite_genres', []):
        patterns['loves_plot_twists'] = True
    
    # Предпочитает высокие рейтинги?
    top_movies = profile.get('top_movies', [])
    if top_movies:
        avg_rating = sum(m.get('rating', 0) for m in top_movies) / len(top_movies)
        patterns['avg_rating'] = round(avg_rating, 1)
        patterns['prefers_high_rating'] = avg_rating > 7.5
    
    # Избегает романтики?
    if 'Мелодрама' in profile.get('disliked_genres', []) or 'Романтика' in profile.get('disliked_genres', []):
        patterns['avoids_romance'] = True
    
    # Любит интеллектуальное кино?
    if 'Драма' in profile.get('favorite_genres', []) and 'Фантастика' in profile.get('favorite_genres', []):
        patterns['prefers_intellectual'] = True
    
    # Предпочитает современное или классику?
    if 'Современное' in profile.get('preferred_eras', []):
        patterns['prefers_modern'] = True
    elif 'Классика' in profile.get('preferred_eras', []):
        patterns['prefers_classic'] = True
    
    return patterns


# ==================== ФОРМАТИРОВАНИЕ ПРОФИЛЯ ====================

def format_profile_for_prompt(user_id: int) -> str:
    """
    Форматирует кинопрофиль для передачи в промпт
    """
    profile = get_cinema_profile(user_id)
    
    lines = []
    lines.append("\n\n🎯 <b>КИНОПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:</b>")
    
    if profile.get('favorite_genres'):
        lines.append(f"• Любимые жанры: {', '.join(profile['favorite_genres'][:5])}")
    
    if profile.get('favorite_actors'):
        lines.append(f"• Любимые актёры: {', '.join(profile['favorite_actors'][:5])}")
    
    if profile.get('favorite_directors'):
        lines.append(f"• Любимые режиссёры: {', '.join(profile['favorite_directors'][:5])}")
    
    if profile.get('disliked_genres'):
        lines.append(f"• Не любит жанры: {', '.join(profile['disliked_genres'][:3])}")
    
    if profile.get('disliked_actors'):
        lines.append(f"• Не любит актёров: {', '.join(profile['disliked_actors'][:3])}")
    
    if profile.get('preferred_mood'):
        lines.append(f"• Предпочитает настроение: {', '.join(profile['preferred_mood'][:3])}")
    
    if profile.get('top_movies'):
        top_names = [m.get('name') for m in profile['top_movies'][:3] if m.get('name')]
        if top_names:
            lines.append(f"• Топ фильмов: {', '.join(top_names)}")
    
    patterns = profile.get('patterns', {})
    if patterns.get('loves_plot_twists'):
        lines.append("• 🧠 Любит неожиданные повороты сюжета")
    if patterns.get('prefers_high_rating'):
        lines.append(f"• ⭐ Предпочитает фильмы с высоким рейтингом ({patterns.get('avg_rating', 0)} в среднем)")
    if patterns.get('avoids_romance'):
        lines.append("• 🚫 Избегает романтических фильмов")
    
    lines.append("\n📌 <b>Учитывай эти предпочтения при подборе фильмов!</b>")
    
    return '\n'.join(lines)


def format_profile_for_display(user_id: int) -> str:
    """
    Форматирует кинопрофиль для отображения пользователю (компактный)
    """
    profile = get_cinema_profile(user_id)
    
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🎯 <b>ТВОЙ КИНОПРОФИЛЬ</b>")
    
    if profile.get('favorite_genres'):
        genres = ', '.join(profile['favorite_genres'][:5])
        lines.append(f"🎭 <b>Любимые жанры:</b> {genres}")
    else:
        lines.append("🎭 <b>Любимые жанры:</b> пока не определены")
    
    if profile.get('favorite_actors'):
        actors = ', '.join(profile['favorite_actors'][:5])
        lines.append(f"⭐ <b>Любимые актёры:</b> {actors}")
    
    if profile.get('favorite_directors'):
        directors = ', '.join(profile['favorite_directors'][:5])
        lines.append(f"🎥 <b>Любимые режиссёры:</b> {directors}")
    
    if profile.get('disliked_genres'):
        genres = ', '.join(profile['disliked_genres'][:3])
        lines.append(f"🚫 <b>Не нравятся жанры:</b> {genres}")
    
    if profile.get('disliked_actors'):
        actors = ', '.join(profile['disliked_actors'][:3])
        lines.append(f"🚫 <b>Не нравятся актёры:</b> {actors}")
    
    if profile.get('top_movies'):
        top_names = [m.get('name') for m in profile['top_movies'][:3] if m.get('name')]
        if top_names:
            lines.append(f"🎬 <b>Топ фильмов:</b> {', '.join(top_names)}")
    
    patterns = profile.get('patterns', {})
    if patterns.get('loves_plot_twists'):
        lines.append("🧠 <b>Любит неожиданные повороты сюжета</b>")
    if patterns.get('prefers_high_rating'):
        lines.append(f"⭐ <b>Предпочитает высокий рейтинг</b>")
    if patterns.get('avoids_romance'):
        lines.append("🚫 <b>Избегает романтических фильмов</b>")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Профиль обновляется автоматически на основе твоих действий</i>")
    
    return '\n'.join(lines)


# ==================== ГЕНЕРАЦИЯ ЛИЧНОСТИ ====================

def generate_cinema_personality(user_id: int) -> str:
    """
    Генерирует смешное описание кинопрофиля пользователя
    """
    profile = get_cinema_profile(user_id)
    
    personality_type = _detect_personality_type(profile)
    
    lines = []
    lines.append("🐾 Гав! Я проанализировала твои запросы и предпочтения.")
    lines.append("Знакомься — твой КИНОПРОФИЛЬ! 🎬🐕")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"🎭 {personality_type['title']}")
    lines.append("")
    lines.append(personality_type['description'])
    lines.append("")
    
    # Любимые актёры
    actors = profile.get('favorite_actors', [])[:3]
    if actors:
        actor_lines = []
        for actor in actors:
            count = profile.get('actor_stats', {}).get(actor, {}).get('count', 0)
            actor_lines.append(f"🎬 {actor} — {count} фильм{'а' if count > 1 else ''} в твоём списке")
        lines.append("⭐ ТВОИ ГЕРОИ:")
        lines.extend(actor_lines)
        lines.append("")
    
    # Режиссёры
    directors = profile.get('favorite_directors', [])[:2]
    if directors:
        director_lines = []
        for director in directors:
            count = profile.get('director_stats', {}).get(director, {}).get('count', 0)
            director_lines.append(f"🎥 {director} — твой режиссёр-ориентир ({count} фильм{'а' if count > 1 else ''})")
        lines.append(" ".join(director_lines))
        lines.append("")
    
    # Нелюбимое
    disliked_actors = profile.get('disliked_actors', [])[:2]
    disliked_genres = profile.get('disliked_genres', [])[:2]
    if disliked_actors or disliked_genres:
        lines.append("🚫 НЕ ТВОЁ:")
        if disliked_actors:
            lines.append(f"👎 {', '.join(disliked_actors)} (ты явно дал понять!)")
        if disliked_genres:
            lines.append(f"👎 {', '.join(disliked_genres)} (не твоя тема)")
        lines.append("")
    
    # Паттерны
    patterns = profile.get('patterns', {})
    if patterns:
        lines.append("🧠 ТВОЙ СТИЛЬ:")
        if patterns.get('loves_plot_twists'):
            lines.append("✓ Обожаешь неожиданные повороты сюжета")
        if patterns.get('prefers_high_rating'):
            avg = patterns.get('avg_rating', 0)
            lines.append(f"✓ Предпочитаешь фильмы с высоким рейтингом (средний: {avg:.1f})")
        if patterns.get('avoids_romance'):
            lines.append("✓ Избегаешь романтики (ты не одинок!)")
        if patterns.get('prefers_intellectual'):
            lines.append("✓ Тянется к интеллектуальному кино")
        lines.append("")
    
    # Топ-3 фильма
    top_movies = profile.get('top_movies', [])[:3]
    if top_movies:
        lines.append("🎬 ТОП-3 ФИЛЬМА (по твоему выбору):")
        for i, movie in enumerate(top_movies, 1):
            name = movie.get('name', '')
            year = movie.get('year', '')
            rating = movie.get('rating', 0)
            lines.append(f"{i}. {name} ({year}) ⭐ {rating}")
        lines.append("")
    
    # Статистика
    stats = profile.get('statistics', {})
    if stats:
        lines.append("📊 СТАТИСТИКА:")
        lines.append(f"• Всего запросов: {stats.get('total_queries', 0)}")
        lines.append(f"• Подборок получено: {stats.get('total_recommendations', 0)}")
        lines.append(f"• Мнений запрошено: {stats.get('total_opinions', 0)}")
        lines.append(f"• Любимых фильмов: {stats.get('favorite_count', 0)}")
        lines.append(f"• Не понравилось: {stats.get('disliked_count', 0)}")
        lines.append("")
    
    # Персональное сообщение
    lines.append("💡 Я ЗНАЮ ТЕБЯ ЛУЧШЕ:")
    lines.append(f"«{_get_personal_message(profile)}»")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    return '\n'.join(lines)


def _detect_personality_type(profile: Dict) -> Dict:
    """Определяет тип кинозрителя"""
    genres = profile.get('favorite_genres', [])
    patterns = profile.get('patterns', {})
    
    types = [
        {
            'title': 'ТЫ — «ИСКАТЕЛЬ СМЫСЛОВ»',
            'description': 'Ты не просто смотришь кино — ты ищешь в нём глубину. Драмы, фантастика и триллеры — твоя стихия. Ты готов простить фильму медленный темп, если в нём есть что-то, что заставит думать даже после титров.',
            'keywords': ['драм', 'фантастик', 'триллер', 'глубок', 'смысл']
        },
        {
            'title': 'ТЫ — «ЭКШН-МАНИЯК»',
            'description': 'Ты любишь, когда всё взрывается, летает и стреляет! Боевики, фантастика и приключения — твой хлеб. Ты не ищешь философию — ты ищешь адреналин!',
            'keywords': ['боевик', 'экшн', 'приключен', 'взрыв', 'адреналин']
        },
        {
            'title': 'ТЫ — «РОМАНТИК В ДУШЕ»',
            'description': 'Ты веришь в любовь, даже если она заканчивается плохо. Мелодрамы, романтика и душевные истории — твоя стихия. Ты плачешь над фильмами и не стесняешься этого!',
            'keywords': ['мелодрам', 'романтик', 'любовь', 'душевн']
        },
        {
            'title': 'ТЫ — «КОМЕДИЙНЫЙ БАЛАГУР»',
            'description': 'Ты не любишь серьёзные фильмы — ты хочешь смеяться! Комедии — твой выбор. Ты — тот человек, который знает все шутки из «Джентльменов» и цитирует их в любой ситуации.',
            'keywords': ['комеди', 'смешн', 'балагур', 'юмор', 'весёл']
        },
        {
            'title': 'ТЫ — «ХОРРОР-ЭКСПЕРТ»',
            'description': 'Ты обожаешь, когда мурашки бегут по коже. Ужасы, триллеры и мистика — твой конёк. Ты смотришь фильмы в тёмной комнате и не боишься!',
            'keywords': ['ужас', 'хоррор', 'мистик', 'страшн']
        },
        {
            'title': 'ТЫ — «УНИВЕРСАЛЬНЫЙ ЗРИТЕЛЬ»',
            'description': 'Ты готов смотреть всё! От драм до фантастики, от ужасов до комедий. Ты — человек, который ценит качество, а не жанр. Твой вкус широк, как моя собачья душа!',
            'keywords': []
        }
    ]
    
    if genres and patterns:
        genre_text = ' '.join(genres).lower()
        pattern_text = ' '.join(str(patterns).lower())
        combined = genre_text + ' ' + pattern_text
        
        scores = {}
        for t in types:
            score = 0
            for keyword in t.get('keywords', []):
                if keyword in combined:
                    score += 1
            scores[t['title']] = score
        
        if scores:
            best_type = max(scores, key=scores.get)
            for t in types:
                if t['title'] == best_type:
                    return t
    
    for t in types:
        if t['title'] == 'ТЫ — «УНИВЕРСАЛЬНЫЙ ЗРИТЕЛЬ»':
            return t
    
    return {
        'title': 'ТЫ — «ЗАГАДОЧНЫЙ ЗРИТЕЛЬ»',
        'description': 'Твой вкус — загадка, которую я ещё разгадываю. Но это делает процесс ещё интереснее! Давай посмотрим больше фильмов вместе и я точно пойму твою душу! 🐾'
    }


def _get_personal_message(profile: Dict) -> str:
    """Генерирует персональное сообщение для пользователя"""
    messages = [
        "Ты — тот человек, который пересматривает «Начало», чтобы понять, крутится ли волчок. Ты ищешь кино, которое оставляет след. И я обожаю твой вкус! 🐕✨",
        "Ты не боишься сложных фильмов. Ты готов разбирать сюжет по кадрам, как я — по запахам. Настоящий кинолюбитель! 🎬🐾",
        "Твои запросы такие разные, что я каждый раз удивляюсь! Ты — человек, который никогда не заскучает. Продолжай удивлять меня! 🐕💫",
        "Я вижу, ты знаешь толк в хорошем кино. Твой вкус — как идеальный поводок: крепкий и стильный! Продолжай в том же духе! 🐾🔥",
        "Ты — тот зритель, ради которого я и работаю. Спасибо, что выбираешь меня! Твои запросы — моё вдохновение! 🐕❤️",
    ]
    
    if profile.get('patterns', {}).get('loves_plot_twists'):
        messages.insert(0, "Ты любишь, когда всё переворачивается с ног на голову. Сюжетные повороты — твоя слабость, и я это обожаю! 🧠🐾")
    elif profile.get('favorite_genres') and 'фантастик' in ' '.join(profile['favorite_genres']).lower():
        messages.insert(0, "Ты мечтаешь о космосе и новых мирах. Фантастика — твой билет в неизведанное, и я с радостью стану твоим проводником! 🚀🐕")
    elif profile.get('disliked_genres') and 'ужас' in ' '.join(profile['disliked_genres']).lower():
        messages.insert(0, "Ты не любишь, когда страшно, и я тебя понимаю! Давай лучше посмотрим что-то тёплое и душевное, чтобы хвост вилял! 🐾💕")
    
    return random.choice(messages)


# ==================== ПРЕДПОЧТЕНИЯ ====================

def get_user_preferences(user_id: int) -> Dict:
    """
    Собирает предпочтения пользователя для персонализации (используется в agent.py)
    """
    profile = get_cinema_profile(user_id)
    
    prefs = {
        'favorite_genres': profile.get('favorite_genres', []),
        'favorite_actors': profile.get('favorite_actors', []),
        'favorite_directors': profile.get('favorite_directors', []),
        'favorite_movies': profile.get('top_movies', [])[:5],
        'watchlist_movies': get_watchlist_ids(user_id),
        'disliked_movies': get_disliked_ids(user_id),
        'preferred_mood': profile.get('preferred_mood', []),
        'preferred_eras': profile.get('preferred_eras', []),
        'patterns': profile.get('patterns', {})
    }
    
    return prefs


def format_preferences_text(preferences: Dict) -> str:
    """
    Форматирует предпочтения в текст для промпта
    """
    if not preferences:
        return ""
    
    lines = []
    lines.append("\n\n📌 УЧИЫВАЙ ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ:")
    
    if preferences.get('favorite_genres'):
        lines.append(f"• Любимые жанры: {', '.join(preferences['favorite_genres'][:5])}")
    
    if preferences.get('favorite_actors'):
        lines.append(f"• Любимые актёры: {', '.join(preferences['favorite_actors'][:5])}")
    
    if preferences.get('favorite_directors'):
        lines.append(f"• Любимые режиссёры: {', '.join(preferences['favorite_directors'][:5])}")
    
    if preferences.get('favorite_movies'):
        fav_movies = []
        for m in preferences['favorite_movies'][:3]:
            name = m.get('name', '')
            year = m.get('year', '')
            fav_movies.append(f"{name} ({year})" if year else name)
        if fav_movies:
            lines.append(f"• Любимые фильмы: {', '.join(fav_movies)}")
    
    if preferences.get('preferred_mood'):
        lines.append(f"• Любимое настроение: {', '.join(preferences['preferred_mood'][:3])}")
    
    if preferences.get('preferred_eras'):
        lines.append(f"• Предпочитает эпохи: {', '.join(preferences['preferred_eras'][:3])}")
    
    if preferences.get('watchlist_movies'):
        lines.append(f"• В списке «Буду смотреть»: {len(preferences['watchlist_movies'])} фильмов")
    
    if preferences.get('disliked_movies'):
        lines.append(f"• 🚫 НЕ ПРЕДЛАГАЙ фильмы с этими ID: {preferences['disliked_movies'][:5]}")
        lines.append("  Эти фильмы пользователю НЕ понравились. Исключи их из рекомендаций полностью!")
    
    patterns = preferences.get('patterns', {})
    if patterns.get('loves_plot_twists'):
        lines.append("• 🧠 Пользователь любит неожиданные повороты сюжета")
    if patterns.get('prefers_high_rating'):
        lines.append(f"• ⭐ Предпочитает фильмы с высоким рейтингом ({patterns.get('avg_rating', 0)} в среднем)")
    if patterns.get('avoids_romance'):
        lines.append("• 🚫 Избегает романтических фильмов")
    
    lines.append("\nСтарайся учитывать эти предпочтения при подборе фильмов. Если пользователь любит определённые жанры или актёров — предлагай похожее. Если есть фильмы, которые не понравились — исключи их и старайся предлагать противоположные по стилю.")
    
    return '\n'.join(lines)

# core/user.py
import logging
import sqlite3
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

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
        'opinion_limit': -1,  # -1 = безлимит
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
    # Проверяем, есть ли фильм в БД
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
    # Защита от неправильных типов
    if not isinstance(user_id, int) or not isinstance(movie_id, int):
        logger.warning(f"Некорректные типы: user_id={user_id} (тип: {type(user_id)}), movie_id={movie_id}")
        return False
    
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
    if not isinstance(user_id, int) or not isinstance(movie_id, int):
        logger.warning(f"Некорректные типы: user_id={user_id}, movie_id={movie_id}")
        return False
    
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
    if not isinstance(user_id, int) or not isinstance(movie_id, int):
        logger.warning(f"Некорректные типы: user_id={user_id}, movie_id={movie_id}")
        return False
    
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


# ==================== ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ ====================

def get_user_preferences(user_id: int) -> Dict:
    """
    Собирает предпочтения пользователя для персонализации
    """
    prefs = {
        'favorite_genres': [],
        'favorite_actors': [],
        'favorite_directors': [],
        'favorite_movies': [],
        'watchlist_movies': [],
        'disliked_movies': []
    }
    
    # 1. Любимые жанры (из любимых фильмов)
    favorites = get_favorite_movies(user_id, limit=20)
    genre_count = {}
    for fav in favorites:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            for genre in movie.get('genres', []):
                if genre:
                    genre_count[genre] = genre_count.get(genre, 0) + 1
    
    if genre_count:
        sorted_genres = sorted(genre_count.items(), key=lambda x: -x[1])
        prefs['favorite_genres'] = [g for g, _ in sorted_genres[:3] if g]
    
    # 2. Любимые актёры и режиссёры
    actor_count = {}
    director_count = {}
    for fav in favorites:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            for actor in movie.get('actors', [])[:5]:
                name = actor.get('name') or actor.get('enName')
                if name:
                    actor_count[name] = actor_count.get(name, 0) + 1
            for director in movie.get('directors', []):
                name = director.get('name') or director.get('enName')
                if name:
                    director_count[name] = director_count.get(name, 0) + 1
    
    if actor_count:
        sorted_actors = sorted(actor_count.items(), key=lambda x: -x[1])
        prefs['favorite_actors'] = [a for a, _ in sorted_actors[:3] if a]
    
    if director_count:
        sorted_directors = sorted(director_count.items(), key=lambda x: -x[1])
        prefs['favorite_directors'] = [d for d, _ in sorted_directors[:3] if d]
    
    # 3. Любимые фильмы (первые 5)
    for fav in favorites[:5]:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            prefs['favorite_movies'].append({
                'id': fav['movie_id'],
                'name': movie.get('name', ''),
                'year': movie.get('year', '')
            })
    
    # 4. Список "Буду смотреть"
    prefs['watchlist_movies'] = get_watchlist_ids(user_id)
    
    # 5. Список "Не понравилось"
    prefs['disliked_movies'] = get_disliked_ids(user_id)
    
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
        lines.append(f"• Любимые жанры: {', '.join(preferences['favorite_genres'])}")
    
    if preferences.get('favorite_actors'):
        lines.append(f"• Любимые актёры: {', '.join(preferences['favorite_actors'])}")
    
    if preferences.get('favorite_directors'):
        lines.append(f"• Любимые режиссёры: {', '.join(preferences['favorite_directors'])}")
    
    if preferences.get('favorite_movies'):
        fav_movies = []
        for m in preferences['favorite_movies'][:3]:
            name = m.get('name', '')
            year = m.get('year', '')
            fav_movies.append(f"{name} ({year})" if year else name)
        if fav_movies:
            lines.append(f"• Любимые фильмы: {', '.join(fav_movies)}")
    
    if preferences.get('watchlist_movies'):
        lines.append(f"• В списке «Буду смотреть»: {len(preferences['watchlist_movies'])} фильмов")
    
    if preferences.get('disliked_movies'):
        lines.append(f"• 🚫 НЕ ПРЕДЛАГАЙ фильмы с этими ID: {preferences['disliked_movies']}")
        lines.append("  Эти фильмы пользователю НЕ понравились. Исключи их из рекомендаций полностью!")
    
    lines.append("\nСтарайся учитывать эти предпочтения при подборе фильмов. Если пользователь любит определённые жанры или актёров — предлагай похожее. Если есть фильмы, которые не понравились — исключи их и старайся предлагать противоположные по стилю.")
    
    return '\n'.join(lines)

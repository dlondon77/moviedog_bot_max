# core/movie.py — ДОПОЛНЕННАЯ ВЕРСИЯ (добавлена функция format_missing_movie_card)

import sqlite3
import logging
import random
from datetime import datetime, timedelta
from core import db

logger = logging.getLogger('core.movie')

# ==================== ПОИСК ФИЛЬМОВ ====================

def search_movies_in_db(query: str, min_rating: float = 0.0, max_rating: float = 10.0) -> list:
    """Надежный поиск фильмов по названию"""
    conn = db.get_movies_db_connection()
    try:
        query_clean = db.clean_text(query, for_sql=True).strip()
        if not query_clean:
            return []

        words = query_clean.split()
        if len(words) > 3:
            words = words[:3]
        
        word_variants = []
        for word in words:
            variants = [
                word,
                word.lower(),
                word.capitalize(),
                word.upper()
            ]
            word_variants.append(list(set(variants)))

        from itertools import product
        query_variants = [' '.join(combo) for combo in product(*word_variants)]
        
        variants = []
        for qv in query_variants:
            variants.extend([
                f"{qv}%",
                f"%{qv}%",
            ])

        variants = list(set(variants))

        sql = """
        SELECT id FROM movies
        WHERE (
            """ + " OR ".join([f"(name LIKE ? COLLATE NOCASE)"] * len(variants)) + """
        )
        AND rating BETWEEN ? AND ?
        ORDER BY
            CASE
                WHEN name = ? THEN 0
                """ + "\n".join([f"WHEN name LIKE ? COLLATE NOCASE THEN {i+1}" 
                               for i in range(len(variants))]) + """
                ELSE """ + str(len(variants)+1) + """
            END,
            rating DESC
        LIMIT 100
        """

        exact_match = query_clean
        params = variants + [min_rating, max_rating, exact_match] + variants

        cursor = conn.cursor()
        cursor.execute(sql, params)
        
        return [get_movie_details(row[0]) for row in cursor.fetchall() if row[0]]
        
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return []
    finally:
        conn.close()

def search_movies_by_person_in_db(query: str, min_rating: float = 0.0, max_rating: float = 10.0) -> list:
    """Улучшенный поиск по персонам"""
    conn = db.get_movies_db_connection()
    try:
        query_clean = db.clean_text(query, for_sql=True).strip()
        if not query_clean or len(query_clean) < 2:
            return []

        search_terms = [term.strip() for term in query_clean.split() if term.strip()]
        
        if len(search_terms) == 1:
            term = search_terms[0]
            patterns = [
                f"%{term.capitalize()}%",
            ]
        else:
            first_terms = [t.capitalize() for t in search_terms[:-1]]
            last_term = search_terms[-1].capitalize()
            
            patterns = [
                ' '.join(first_terms + [last_term]) + '%',
                ' '.join(first_terms) + ' %' + last_term + '%',
                '% ' + ' '.join(first_terms) + ' %' + last_term + '%',
            ]
        
        return search_person_matches(patterns, min_rating, max_rating)
        
    except Exception as e:
        logger.error(f"Ошибка поиска по персонам: {e}")
        return []
    finally:
        conn.close()

def search_person_matches(patterns: list, min_rating: float, max_rating: float) -> list:
    """Поиск персон по заданным шаблонам"""
    conn = db.get_movies_db_connection()
    try:
        conditions = []
        params = []
        
        for pattern in patterns:
            conditions.append("""
                (EXISTS (
                    SELECT 1 FROM movie_actors ma 
                    JOIN actors a ON ma.actor_id = a.id 
                    WHERE ma.movie_id = m.id AND (
                        a.name LIKE ? OR 
                        a.enName LIKE ?
                    )
                ) OR EXISTS (
                    SELECT 1 FROM movie_directors md 
                    JOIN directors d ON md.director_id = d.id 
                    WHERE md.movie_id = m.id AND (
                        d.name LIKE ? OR 
                        d.enName LIKE ?
                    )
                ))
            """)
            params.extend([pattern]*4)
        
        where_clause = " OR ".join(conditions) if conditions else "1=0"
        
        sql = f"""
        SELECT DISTINCT m.id 
        FROM movies m
        WHERE ({where_clause})
        AND m.rating BETWEEN ? AND ?
        ORDER BY m.rating DESC
        LIMIT 100
        """
        
        params += [min_rating, max_rating]
        
        cursor = conn.cursor()
        cursor.execute(sql, params)
        
        return [get_movie_details(row[0]) for row in cursor.fetchall() if row[0]]
    finally:
        conn.close()

def get_movie_details(movie_id: int) -> dict:
    """Получение полной информации о фильме с актерами и режиссерами"""
    conn = db.get_movies_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
            
        columns = [column[0] for column in cursor.description]
        movie = dict(zip(columns, row))
        
        cursor.execute("SELECT genre FROM genres WHERE movie_id = ?", (movie_id,))
        movie['genres'] = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT country FROM countries WHERE movie_id = ?", (movie_id,))
        movie['countries'] = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("""
        SELECT a.id, a.name, a.enName 
        FROM actors a
        JOIN movie_actors ma ON a.id = ma.actor_id
        WHERE ma.movie_id = ?
        LIMIT 10
        """, (movie_id,))
        movie['actors'] = [dict(zip(['id', 'name', 'enName'], row)) for row in cursor.fetchall()]
        
        cursor.execute("""
        SELECT d.id, d.name, d.enName 
        FROM directors d
        JOIN movie_directors md ON d.id = md.director_id
        WHERE md.movie_id = ?
        """, (movie_id,))
        movie['directors'] = [dict(zip(['id', 'name', 'enName'], row)) for row in cursor.fetchall()]
        
        return movie
    except Exception as e:
        logger.error(f"Ошибка получения деталей фильма (ID: {movie_id}): {e}")
        return None
    finally:
        conn.close()

def get_random_movie_from_db(min_rating: float = 7.0, max_rating: float = 10.0, is_new_only: bool = False) -> dict:
    """Получение случайного фильма из объединенного кэша"""
    conn = db.get_movies_db_connection()
    cursor = conn.cursor()
    
    try:
        use_new_releases = random.random() < 0.2
        
        if use_new_releases:
            sql = """
            SELECT id FROM movies 
            WHERE rating >= 5 AND rating <= 7
            AND is_new_release = 1
            ORDER BY RANDOM() LIMIT 1
            """
            cursor.execute(sql)
            row = cursor.fetchone()
            
            if row:
                return get_movie_details(row[0])
        
        sql = """
        SELECT id FROM movies 
        WHERE rating >= ? AND rating <= ?
        """
        params = [min_rating, max_rating]
        
        if is_new_only:
            sql += " AND is_new_release = 1"
        
        sql += " ORDER BY RANDOM() LIMIT 1"
        
        cursor.execute(sql, params)
        row = cursor.fetchone()
        
        if row:
            return get_movie_details(row[0])
            
        return None
            
    except Exception as e:
        logger.error(f"Ошибка получения случайного фильма: {e}")
        return None
    finally:
        conn.close()

def get_premier_movies_from_db() -> list:
    """Получение списка премьерных фильмов за последний месяц и будущих"""
    conn = db.get_movies_db_connection()
    cursor = conn.cursor()
    
    try:
        one_month_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        sql = """
        SELECT id FROM movies 
        WHERE is_new_release = 1 AND 
            (premiere_russia >= ? OR premiere_world >= ?)
        ORDER BY 
            COALESCE(premiere_russia, premiere_world) ASC,
            await_count DESC
        LIMIT 100
        """
        cursor.execute(sql, (one_month_ago, one_month_ago))
        movie_ids = [row[0] for row in cursor.fetchall()]
        
        movies_with_details = []
        for movie_id in movie_ids:
            movie_details = get_movie_details(movie_id)
            if movie_details:
                movies_with_details.append(movie_details)
        
        return movies_with_details
    except Exception as e:
        logger.error(f"Ошибка получения премьерных фильмов: {e}")
        return []
    finally:
        conn.close()

def format_movie_card(movie, is_premiers=False, query=None, is_person_search=False):
    """Форматирует карточку фильма для отправки пользователю с правильной ссылкой на Кинопоиск"""
    if not movie or not isinstance(movie, dict):
        return None, None

    try:
        title = movie.get('name', 'Без названия') or 'отсутствует'
        year = str(movie.get('year', '')) if movie.get('year') else 'отсутствует'
        is_new = movie.get('is_new_release', False)
        movie_id = str(movie.get('id', '')) if movie.get('id') else ''
        
        year_display = f"({year}) 🆕" if is_new else f"({year})"
        
        content_type = movie.get('movie_type', 'movie')
        type_mapping = {
            'movie': 'фильм',
            'tv-series': 'сериал',
            'mini-series': 'мини-сериал',
            'cartoon': 'мультфильм'
        }
        type_text = type_mapping.get(content_type, 'фильм')
        
        rating = round(movie.get('rating', 0), 1) if movie.get('rating') else "отсутствует"
        countries = ', '.join(movie.get('countries', [])) if movie.get('countries') else 'отсутствует'
        genres = ', '.join(movie.get('genres', [])) if movie.get('genres') else 'отсутствует'
        description = movie.get('description', 'отсутствует') or 'отсутствует'
        
        directors_list = []
        for director in movie.get('directors', []):
            director_name = director.get('name', '') or director.get('enName', '')
            director_id = director.get('id', '')
            
            if director_name:
                if is_person_search and director_id and query and query.lower() in director_name.lower():
                    director_url = f"https://www.kinopoisk.ru/name/{director_id}/"
                    director_name = f"<a href='{director_url}'>{director_name}</a>"
                directors_list.append(director_name)
        
        directors = ', '.join(directors_list) if directors_list else 'отсутствует'
        
        actors_list = []
        for actor in movie.get('actors', []):
            actor_name = actor.get('name', '') or actor.get('enName', '')
            actor_id = actor.get('id', '')
            
            if actor_name:
                if is_person_search and actor_id and query and query.lower() in actor_name.lower():
                    actor_url = f"https://www.kinopoisk.ru/name/{actor_id}/"
                    actor_name = f"<a href='{actor_url}'>{actor_name}</a>"
                actors_list.append(actor_name)
        
        actors = ', '.join(actors_list) if actors_list else 'отсутствует'
        
        premiere_info = ""
        if is_premiers or movie.get('is_new_release'):
            premiere_russia = movie.get('premiere_russia')
            premiere_world = movie.get('premiere_world')
            await_count = movie.get('await_count', 0)
            
            def format_premiere_date(date_str):
                if not date_str:
                    return 'отсутствует'
                try:
                    if 'T' in date_str:
                        date_part = date_str.split('T')[0]
                        return datetime.strptime(date_part, "%Y-%m-%d").strftime("%d.%m.%Y")
                    else:
                        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")
                except Exception:
                    return 'отсутствует'
            
            premiere_info = (
                f"\n🎉 Премьера РФ: <b>{format_premiere_date(premiere_russia)}</b>\n"
                f"🌎 Премьера Мир: <b>{format_premiere_date(premiere_world)}</b>\n"
                f"👥 Ожидают: <b>{int(await_count) if await_count else 0}</b> чел.\n"
            )
        
        poster_url = movie.get('poster_url', f"https://st.kp.yandex.net/images/film_big/{movie_id}.jpg")
        kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/" if movie_id else "https://www.kinopoisk.ru/"
        
        card = (
            f"🎬 <b>{title}</b> {year_display}\n"
            f"📁 Тип: <b>{type_text}</b>\n"
            f"⭐ Рейтинг Кинопоиска: <b>{rating}</b>\n"
            f"🌍 Страна: <b>{countries}</b>\n"
            f"🎭 Жанр: <b>{genres}</b>\n"
            f"{premiere_info}\n"
            f"📝 <b>Описание:</b>\n<i>{description}</i>\n\n"
            f"🎥 <b>Режиссер:</b> {directors}\n"
            f"👥 <b>Актеры:</b> {actors}\n\n"
            f"🔗 <a href='{kp_url}'>Кинопоиск</a>: {kp_url}"
        )
        
        return card, None
        
    except Exception as e:
        logger.error(f"Ошибка форматирования карточки фильма: {e}")
        return None, None


def format_missing_movie_card(movie_id: int, movie_name: str = None) -> str:
    """
    Создаёт карточку-заглушку для фильма, которого нет в БД
    """
    kp_url = f"https://www.kinopoisk.ru/film/{movie_id}/"
    
    if not movie_name:
        movie_name = f"Фильм (ID: {movie_id})"
    
    card = (
        f"🎬 <b>{movie_name}</b>\n"
        f"📁 Тип: <b>фильм</b>\n"
        f"⭐ Рейтинг Кинопоиска: <b>неизвестен</b>\n"
        f"🌍 Страна: <b>неизвестна</b>\n"
        f"🎭 Жанр: <b>неизвестен</b>\n\n"
        f"📝 <b>Описание:</b>\n"
        f"<i>Этот фильм пока не загружен в мою базу данных. 🐾</i>\n\n"
        f"🔗 <a href='{kp_url}'>Смотреть на Кинопоиске</a>"
    )
    
    return card


def search_movies_with_filters(query, filters=None, count_only=False):
    """Поиск фильмов с фильтрами"""
    all_movies = search_movies_in_db(query, min_rating=0.0, max_rating=10.0)
    
    if not all_movies:
        return (0, False) if count_only else []
    
    filtered_movies = []
    
    for movie in all_movies:
        include = True
        rating = movie.get('rating')
        year = movie.get('year')
        
        if filters:
            if filters.get('rating_range'):
                if filters['rating_range'] == 'new':
                    if rating is not None and rating > 0:
                        include = False
                else:
                    rating_parts = filters['rating_range'].split('-')
                    if len(rating_parts) == 2:
                        min_r = float(rating_parts[0])
                        max_r = float(rating_parts[1])
                        if rating is None or rating < min_r or rating > max_r:
                            include = False
            
            if include and filters.get('decade'):
                if not year:
                    include = False
                elif filters['decade'] == 'pre1980':
                    if year >= 1980:
                        include = False
                elif filters['decade'] == '1980s':
                    if year < 1980 or year >= 1990:
                        include = False
                elif filters['decade'] == '1990s':
                    if year < 1990 or year >= 2000:
                        include = False
                elif filters['decade'] == '2000s':
                    if year < 2000 or year >= 2010:
                        include = False
                elif filters['decade'] == '2010s':
                    if year < 2010 or year >= 2020:
                        include = False
                elif filters['decade'] == '2020s':
                    if year < 2020:
                        include = False
        
        if include:
            filtered_movies.append(movie)
    
    if count_only:
        has_more = (len(filtered_movies) >= 100)
        return (len(filtered_movies), has_more)
    else:
        return filtered_movies

def format_filter_keyboard(query, current_filters=None, total_count=0, has_more=False):
    """Заглушка для Max — клавиатуры с фильтрами пока не поддерживаются"""
    return None

def add_favorite_movie(user_id, movie_id):
    """Добавляет фильм в любимые"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO favorite_movies (user_id, movie_id, added_at)
            VALUES (?, ?, ?)
        ''', (user_id, movie_id, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления в любимые: {e}")
        return False
    finally:
        conn.close()

def remove_favorite_movie(user_id, movie_id):
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

def is_favorite(user_id, movie_id):
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

def get_favorite_movies(user_id, limit=10, offset=0):
    """Получает список любимых фильмов"""
    conn = db.get_opinions_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT fm.movie_id, fm.added_at, m.name, m.year, m.rating
        FROM favorite_movies fm
        JOIN movies m ON fm.movie_id = m.id
        WHERE fm.user_id = ?
        ORDER BY fm.added_at DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    movies = cursor.fetchall()
    conn.close()
    return [{'movie_id': row[0], 'added_at': row[1], 'name': row[2], 'year': row[3], 'rating': row[4]} for row in movies]

def search_movies_by_description(query: str, limit: int = 5) -> list:
    """Ищет фильмы по ключевым словам в описании"""
    conn = db.get_movies_db_connection()
    cursor = conn.cursor()
    
    words = [w.lower() for w in query.split() if len(w) > 3]
    
    if not words:
        conn.close()
        return []
    
    conditions = []
    params = []
    for word in words:
        conditions.append("(LOWER(description) LIKE ? OR LOWER(name) LIKE ?)")
        params.extend([f"%{word}%", f"%{word}%"])
    
    sql = f"""
    SELECT DISTINCT id
    FROM movies
    WHERE {' OR '.join(conditions)}
    ORDER BY rating DESC
    LIMIT ?
    """
    params.append(limit)
    
    cursor.execute(sql, params)
    movie_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return [get_movie_details(movie_id) for movie_id in movie_ids if movie_id]

def search_persons(query: str, limit=20, partial_match=True):
    """Ищет актёров и режиссёров по имени"""
    conn = db.get_movies_db_connection()
    cursor = conn.cursor()
    
    query_clean = query.strip().lower()
    
    if len(query_clean) < 2:
        conn.close()
        return []
    
    logger.info(f"🔍 Поиск персон: запрос='{query}'")
    
    search_pattern = f"%{query_clean}%"
    
    sql = '''
        SELECT id, name, enName, 'actor' as type, photo
        FROM actors 
        WHERE LOWER(name) LIKE ? OR LOWER(enName) LIKE ?
        ORDER BY 
            CASE 
                WHEN LOWER(name) = ? THEN 1
                WHEN LOWER(name) LIKE ? THEN 2
                WHEN LOWER(enName) LIKE ? THEN 3
                ELSE 4
            END
        LIMIT ?
    '''
    
    cursor.execute(sql, [search_pattern, search_pattern, query_clean, f"{query_clean}%", f"{query_clean}%", limit])
    actors = cursor.fetchall()
    
    cursor.execute(sql, [search_pattern, search_pattern, query_clean, f"{query_clean}%", f"{query_clean}%", limit])
    directors = cursor.fetchall()
    
    conn.close()
    
    persons = []
    seen_ids = set()
    
    for person in actors + directors:
        person_id = person[0]
        if person_id in seen_ids:
            continue
        seen_ids.add(person_id)
        
        rus_name = person[1] or ''
        eng_name = person[2] or ''
        person_type = person[3]
        photo = person[4] if len(person) > 4 else None
        
        if rus_name and eng_name:
            display_name = f"{rus_name} ({eng_name})"
        elif rus_name:
            display_name = rus_name
        else:
            display_name = eng_name
        
        persons.append({
            'id': person_id,
            'name': display_name,
            'raw_name': rus_name or eng_name,
            'type': person_type,
            'photo': photo
        })
    
    persons.sort(key=lambda x: 0 if x['type'] == 'actor' else 1)
    
    logger.info(f"🔍 Найдено персон: {len(persons)}")
    return persons[:limit]

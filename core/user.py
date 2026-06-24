# core/user.py — ДОБАВЛЯЕМ В КОНЕЦ ФАЙЛА

# ==================== ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ ====================

def get_user_preferences(user_id: int) -> Dict:
    """
    Собирает предпочтения пользователя для персонализации
    Возвращает словарь с любимыми жанрами, актёрами, режиссёрами
    """
    prefs = {
        'favorite_genres': [],
        'favorite_actors': [],
        'favorite_directors': [],
        'favorite_movies': [],
        'watchlist_movies': []
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
    
    # Топ-3 жанра
    if genre_count:
        sorted_genres = sorted(genre_count.items(), key=lambda x: -x[1])
        prefs['favorite_genres'] = [g for g, _ in sorted_genres[:3] if g]
    
    # 2. Любимые актёры и режиссёры (из любимых фильмов)
    actor_count = {}
    director_count = {}
    for fav in favorites:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            # Актёры
            for actor in movie.get('actors', [])[:5]:
                name = actor.get('name') or actor.get('enName')
                if name:
                    actor_count[name] = actor_count.get(name, 0) + 1
            # Режиссёры
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
    
    # 3. Любимые фильмы (ID и названия)
    prefs['favorite_movies'] = []
    for fav in favorites[:5]:
        movie = movie_module.get_movie_details(fav['movie_id'])
        if movie:
            prefs['favorite_movies'].append({
                'id': fav['movie_id'],
                'name': movie.get('name', ''),
                'year': movie.get('year', '')
            })
    
    # 4. Список "Буду смотреть" (если таблица уже есть)
    try:
        watchlist = get_watchlist(user_id, limit=10)
        prefs['watchlist_movies'] = [item['movie_id'] for item in watchlist]
    except Exception:
        # Таблицы ещё нет — просто пропускаем
        pass
    
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
    
    lines.append("\nСтарайся учитывать эти предпочтения при подборе фильмов, но не ограничивайся только ими — предлагай и новые варианты, которые могут понравиться пользователю.")
    
    return '\n'.join(lines)

# core/db.py
import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'movies.db')
OPINIONS_DB_PATH = os.path.join(DATA_DIR, 'opinions.db')

# ==================== ИНИЦИАЛИЗАЦИЯ БАЗ ДАННЫХ ====================

def get_movies_db_connection():
    """Возвращает соединение с базой данных фильмов"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_opinions_db_connection():
    """Возвращает соединение с базой данных мнений и пользователей"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    conn = sqlite3.connect(OPINIONS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Инициализирует все таблицы баз данных"""
    # База данных фильмов
    conn = get_movies_db_connection()
    cursor = conn.cursor()
    
    # Таблица фильмов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY,
            name TEXT,
            en_name TEXT,
            year INTEGER,
            rating REAL,
            description TEXT,
            movie_type TEXT,
            poster_url TEXT,
            is_new_release INTEGER DEFAULT 0,
            premiere_russia TEXT,
            premiere_world TEXT,
            await_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Таблица жанров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movie_id INTEGER,
            genre TEXT,
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        )
    ''')
    
    # Таблица стран
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movie_id INTEGER,
            country TEXT,
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        )
    ''')
    
    # Таблица актёров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS actors (
            id INTEGER PRIMARY KEY,
            name TEXT,
            enName TEXT,
            photo TEXT
        )
    ''')
    
    # Таблица связи фильмов и актёров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movie_actors (
            movie_id INTEGER,
            actor_id INTEGER,
            FOREIGN KEY (movie_id) REFERENCES movies(id),
            FOREIGN KEY (actor_id) REFERENCES actors(id)
        )
    ''')
    
    # Таблица режиссёров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS directors (
            id INTEGER PRIMARY KEY,
            name TEXT,
            enName TEXT,
            photo TEXT
        )
    ''')
    
    # Таблица связи фильмов и режиссёров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movie_directors (
            movie_id INTEGER,
            director_id INTEGER,
            FOREIGN KEY (movie_id) REFERENCES movies(id),
            FOREIGN KEY (director_id) REFERENCES directors(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
    # База данных мнений и пользователей
    conn = get_opinions_db_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            platform TEXT,
            tariff_name TEXT DEFAULT 'Щенячий азарт',
            tariff_end_date TEXT,
            registered_at TEXT
        )
    ''')
    
    # Таблица статистики пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stat_date TEXT,
            opinion_count INTEGER DEFAULT 0,
            regeneration_count INTEGER DEFAULT 0,
            agent_count INTEGER DEFAULT 0,
            UNIQUE(user_id, stat_date)
        )
    ''')
    
    # Таблица мнений о фильмах
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movie_opinions (
            movie_id INTEGER PRIMARY KEY,
            full_opinion TEXT,
            short_opinion TEXT,
            created_at TEXT
        )
    ''')
    
    # Таблица обратной связи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type INTEGER,
            movie_id INTEGER,
            message TEXT,
            status TEXT DEFAULT 'new',
            admin_comment TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Таблица мнений пользователей о фильмах (для истории)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_movie_opinions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            movie_id INTEGER,
            opinion_text TEXT,
            created_at TEXT,
            UNIQUE(user_id, movie_id)
        )
    ''')
    
    # ==================== НОВЫЕ ТАБЛИЦЫ ====================
    
    # Таблица любимых фильмов (с рейтингом пользователя)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorite_movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            user_rating INTEGER DEFAULT 0,
            review TEXT DEFAULT '',
            UNIQUE(user_id, movie_id)
        )
    ''')
    
    # Таблица списка "Буду смотреть"
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            status TEXT DEFAULT 'planned',
            UNIQUE(user_id, movie_id)
        )
    ''')
    
    # Таблица "Не понравилось"
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS disliked_movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            reason TEXT DEFAULT '',
            UNIQUE(user_id, movie_id)
        )
    ''')
    
    # Таблица истории просмотров (для будущей персонализации)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            watched_at TEXT NOT NULL,
            UNIQUE(user_id, movie_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
    logger.info("✅ Все таблицы инициализированы")


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def clean_text(text: str, for_sql: bool = False) -> str:
    """Очищает текст от специальных символов"""
    if not text:
        return ''
    import re
    text = re.sub(r'[^\w\s\-()\'"]', ' ', text)
    text = ' '.join(text.split())
    if for_sql:
        text = text.replace("'", "''")
    return text

def get_db_version() -> str:
    """Возвращает версию базы данных"""
    conn = get_opinions_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT sqlite_version()")
        version = cursor.fetchone()[0]
        conn.close()
        return version
    except Exception as e:
        logger.error(f"Ошибка получения версии БД: {e}")
        return "unknown"

def backup_db() -> bool:
    """Создаёт резервную копию базы данных"""
    try:
        import shutil
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{DB_PATH}.backup_{timestamp}"
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, backup_path)
            logger.info(f"📦 Резервная копия создана: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"Ошибка создания резервной копии: {e}")
        return False

# core/db.py
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

# ==================== ПУТИ К БАЗАМ ДАННЫХ ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
MOVIES_DB_PATH = os.path.join(DATA_DIR, 'movies.db')
OPINIONS_DB_PATH = os.path.join(DATA_DIR, 'opinions.db')

# ==================== ПОДКЛЮЧЕНИЕ К БАЗАМ ====================
def get_movies_db_connection():
    """Подключение к базе фильмов"""
    conn = sqlite3.connect(MOVIES_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_opinions_db_connection():
    """Подключение к базе мнений и пользователей"""
    conn = sqlite3.connect(OPINIONS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ==================== ОЧИСТКА ТЕКСТА ====================
def clean_text(text: str, for_sql: bool = False) -> str:
    """Очищает текст от лишних символов"""
    if not text:
        return ""
    
    # Удаляем лишние пробелы
    text = ' '.join(text.split())
    
    # Для SQL-запросов экранируем кавычки
    if for_sql:
        text = text.replace("'", "''")
        text = text.replace('"', '""')
    
    return text

def migrate_db():
    """Обновляет схему базы данных до актуальной версии"""
    conn = get_opinions_db_connection()
    cursor = conn.cursor()
    
    # Проверяем, есть ли колонка agent_query_count
    cursor.execute("PRAGMA table_info(user_stats)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'agent_query_count' not in columns:
        logger.info("🔄 Добавляем колонку agent_query_count в user_stats")
        cursor.execute("ALTER TABLE user_stats ADD COLUMN agent_query_count INTEGER DEFAULT 0")
        conn.commit()
        logger.info("✅ Колонка agent_query_count добавлена")
    
    conn.close()

# ==================== ИНИЦИАЛИЗАЦИЯ ТАБЛИЦ ====================
def init_db():
    """Создаёт все необходимые таблицы при первом запуске"""
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
            tariff_end_date TEXT DEFAULT 'бессрочно',
            created_at TEXT
        )
    ''')
    
    # Таблица статистики пользователей (по дням)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER,
            date TEXT,
            opinion_count INTEGER DEFAULT 0,
            regeneration_count INTEGER DEFAULT 0,
            agent_query_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    ''')
    
    # Таблица мнений о фильмах (кэш)
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
            admin_comment TEXT,
            created_at TEXT
        )
    ''')
    
    # Таблица истории мнений пользователя
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_opinions (
            user_id INTEGER,
            movie_id INTEGER,
            created_at TEXT,
            PRIMARY KEY (user_id, movie_id)
        )
    ''')
    
    # ---- НОВЫЕ ТАБЛИЦЫ ДЛЯ СПИСКОВ И КИНОПРОФИЛЯ ----
    
    # Любимые фильмы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorite_movies (
            user_id INTEGER,
            movie_id INTEGER,
            added_at TEXT,
            PRIMARY KEY (user_id, movie_id)
        )
    ''')
    
    # Буду смотреть
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            user_id INTEGER,
            movie_id INTEGER,
            added_at TEXT,
            status TEXT DEFAULT 'planned',
            PRIMARY KEY (user_id, movie_id)
        )
    ''')
    
    # Не понравились
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS disliked_movies (
            user_id INTEGER,
            movie_id INTEGER,
            added_at TEXT,
            reason TEXT,
            PRIMARY KEY (user_id, movie_id)
        )
    ''')
    
    # История запросов пользователя
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            agent_mode TEXT,
            created_at TEXT
        )
    ''')
    
    # Таблица для пользовательских предпочтений (для будущей персонализации)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            favorite_genres TEXT,
            favorite_actors TEXT,
            favorite_directors TEXT,
            preferred_decades TEXT,
            updated_at TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

# Вызываем при первом запуске
init_db()

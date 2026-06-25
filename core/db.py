# core/db.py — обновлённая версия с вызовом миграций

import sqlite3
import logging
import os
from core.migration import check_and_fix_db

logger = logging.getLogger(__name__)

# ==================== ПУТИ К БАЗАМ ДАННЫХ ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
MOVIES_DB_PATH = os.path.join(DATA_DIR, 'movies.db')
OPINIONS_DB_PATH = os.path.join(DATA_DIR, 'opinions.db')


# ==================== ПОДКЛЮЧЕНИЕ К БАЗАМ ====================
def get_movies_db_connection():
    conn = sqlite3.connect(MOVIES_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_opinions_db_connection():
    conn = sqlite3.connect(OPINIONS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== ОЧИСТКА ТЕКСТА ====================
def clean_text(text: str, for_sql: bool = False) -> str:
    if not text:
        return ""
    text = ' '.join(text.split())
    if for_sql:
        text = text.replace("'", "''")
        text = text.replace('"', '""')
    return text


# ==================== ИНИЦИАЛИЗАЦИЯ ====================
def init_db():
    """Создаёт папку data и запускает миграции"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    
    # Запускаем миграции
    check_and_fix_db()
    
    logger.info("✅ База данных инициализирована")

# Вызываем при импорте
init_db()

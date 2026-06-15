# core/max_adapter.py
import logging
import configparser
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.ini')

logger = logging.getLogger(__name__)


def load_config():
    """Загружает конфигурацию как в TG-версии"""
    config = configparser.ConfigParser(interpolation=None)
    config.read(CONFIG_PATH, encoding='utf-8')
    return config


class MaxAdapter:
    def __init__(self):
        self.config = load_config()
        
        # Токен из переменной окружения или конфига (как в TG)
        self.token = os.environ.get('MAX_TOKEN') or self.config['Max']['token']
        
        if not self.token:
            raise ValueError("MAX_TOKEN не найден!")
        
        # Пути к БД (как в TG)
        self.db_path = os.path.join(BASE_DIR, self.config['Data']['db_path'])
        self.movies_db_path = os.path.join(BASE_DIR, self.config['Data']['movies_db_path'])
        self.payments_db_path = os.path.join(BASE_DIR, self.config['Data']['payments_db_path'])
        
        # Инициализация бота
        self.bot = Bot(token=self.token)
        self.dp = Dispatcher()
        self.user_context = {}
        
        self._register_handlers()
        logger.info(f"✅ MaxAdapter инициализирован")
        logger.info(f"   DB: {self.db_path}")
        logger.info(f"   Movies DB: {self.movies_db_path}")

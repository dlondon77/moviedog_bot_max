# moviedog_max.py
import asyncio
import logging
import configparser
from core.max_adapter import MaxAdapter

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler('bot_max.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def main():
    logger.info("🚀 Запуск Max-бота")
    adapter = MaxAdapter()
    await adapter.run()

if __name__ == '__main__':
    asyncio.run(main())

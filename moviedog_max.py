#!/usr/bin/env python
# moviedog_max.py — точка входа для Max

import asyncio
import logging
import os
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.max_adapter import MaxAdapter

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

MAX_TOKEN = os.environ.get("MAX_TOKEN", "")
if not MAX_TOKEN:
    raise ValueError("MAX_TOKEN не задан!")

async def main():
    adapter = MaxAdapter(MAX_TOKEN)
    await adapter.run()

if __name__ == "__main__":
    asyncio.run(main())
